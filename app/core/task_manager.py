import queue
import threading
import time
import uuid

from enum import Enum
from multiprocessing import Queue
from queue import Empty
from typing import Dict, Any, Optional

import log

from app.utils.commons import singleton


# 1. 共享的状态存储（受锁保护）
TASK_STORE: Dict[str, Any] = {}
# 2. 保护 TASK_STORE 的锁 (防止读/写冲突)
TASK_STORE_LOCK: threading.Lock = threading.Lock()
# 3. 线程安全的队列 (生产者/消费者模式)
TASK_QUEUE: Queue = Queue()
# 4. 消费者线程的引用
_PROCESSOR_THREAD: Optional[threading.Thread] = None
# 5. 用于优雅停止的“哨兵”
_STOP_EVENT = "STOP"
# 每 60 秒触发一次清理检查
CLEANUP_INTERVAL_SECONDS = 60
# 任务“完成”后保留 5 分钟（供前端轮询结果）
TASK_TTL_SECONDS = 300
# “处理中”任务超过 10 分钟无更新，视为异常中断，允许清理
STALE_TASK_SECONDS = 600

# 内部元数据键前缀，不随 get_task_dict 返回给调用方
_INTERNAL_KEY_PREFIX = '_'


class TaskStatus(Enum):
    """任务状态"""
    PROCESSING = 'processing'
    FINISH = 'finish'


def _new_task(task_id: str) -> dict:
    """新建任务的初始状态字典"""
    return {
        "task_id": task_id,
        "status": TaskStatus.PROCESSING.value,
        "progress": 0,
        "message": "开始执行...",
        # 记录最后更新时间，用于超时清理
        "_updated_at": time.monotonic(),
    }


@singleton
class TaskStore:
    """
    任务进度中心
    """

    def create_task(self) -> str:
        """
        同步创建任务
        """
        task_id = str(uuid.uuid4())
        with TASK_STORE_LOCK:
            TASK_STORE[task_id] = _new_task(task_id)
        return task_id

    def get_task_dict(self, task_id: str) -> dict | None:
        """
        同步获取任务状态
        """
        if not task_id:
            return None
        with TASK_STORE_LOCK:
            task = TASK_STORE.get(task_id)
            if not task:
                return None
            # 返回拷贝以保证线程安全，同时剔除内部元数据键
            return {k: v for k, v in task.items() if not k.startswith(_INTERNAL_KEY_PREFIX)}

    @staticmethod
    def _enqueue(task_id: str,
                 status: str,
                 progress: Optional[int],
                 progress_add: int,
                 message: Optional[str],
                 result: Any = None) -> bool:
        """
        将任务更新消息放入队列，*不等待锁*；
        失败时返回 False，避免子进程静默失败
        """
        try:
            task_info = {
                "task_id": task_id,
                "status": status,
                "progress": progress,
                "progress_add": progress_add,
                "message": message,
                "result": result,
            }
            TASK_QUEUE.put(task_info)
        except Exception as e:
            log.exception("Error putting task update to queue: ", e)
            return False
        return True

    def update_task(self,
                    task_id: str,
                    progress: Optional[int] = None,
                    message: Optional[str] = None,
                    progress_add: int = 0,
                    status: str = TaskStatus.PROCESSING.value):
        """
        只是将消息放入队列，*不等待锁*
        """
        return self._enqueue(task_id, status=status, progress=progress,
                             progress_add=progress_add, message=message)

    def finish_task(self,
                    task_id: str,
                    result: Any = None,
                    message: Optional[str] = None):
        """
        设置任务完成
        """
        return self._enqueue(task_id, status=TaskStatus.FINISH.value,
                             progress=100, progress_add=0,
                             message=message, result=result)


def _task_cleanup(now: float):
    """
    清理超时任务（调用方需持有 TASK_STORE_LOCK）：
    - 已“完成”且超过 TASK_TTL_SECONDS 的任务
    - “处理中”且超过 STALE_TASK_SECONDS 无更新的任务（视为异常中断）
    """
    tasks_to_delete = []
    for task_id, task in TASK_STORE.items():
        status = task.get('status')
        updated_at = task.get('_updated_at', 0)
        if status == TaskStatus.FINISH.value:
            if now - updated_at >= TASK_TTL_SECONDS:
                tasks_to_delete.append(task_id)
        elif status == TaskStatus.PROCESSING.value:
            if now - updated_at >= STALE_TASK_SECONDS:
                tasks_to_delete.append(task_id)

    for task_id in tasks_to_delete:
        TASK_STORE.pop(task_id, None)  # 安全删除


def _task_processor_loop():
    """
    这是“消费者”线程的唯一工作。
    它从队列中读取消息，并（加锁）更新共享字典；同时周期性清理超时任务。
    """
    log.info("[Task Processor Thread] 任务处理器已启动...")
    last_cleanup = time.monotonic()

    while True:
        try:
            message = TASK_QUEUE.get(timeout=CLEANUP_INTERVAL_SECONDS)

            # 收到“停止”信号
            if not isinstance(message, dict) and message == _STOP_EVENT:
                log.info("[Task Processor Thread] 收到关闭信号，正在退出...")
                break
        except Empty:
            # 队列在 CLEANUP_INTERVAL_SECONDS 秒内没有消息（正常超时，触发周期清理）
            message = None
        except Exception as e:
            # 必须捕获所有异常，否则处理器线程会崩溃
            log.exception(" [Task Processor Thread] 处理器循环出错: ", e)
            message = None

        # 处理任务更新消息（加锁写入共享字典）
        if isinstance(message, dict):
            with TASK_STORE_LOCK:
                current_data = TASK_STORE.get(message.get("task_id"))
                if current_data:
                    status = message.get("status")
                    progress = message.get("progress")
                    progress_add = message.get("progress_add")
                    message_text = message.get("message")
                    task_result = message.get("result")

                    # 绝对进度（progress > 0）优先，否则按 progress_add 累加
                    if progress and progress > 0:
                        current_data['progress'] = progress
                    elif progress_add:
                        current_data['progress'] = current_data['progress'] + progress_add

                    if message_text:
                        current_data['message'] = message_text
                    if status:
                        current_data['status'] = status
                    if task_result is not None:
                        current_data['result'] = task_result
                    # 记录最后更新时间（用于超时清理）
                    current_data['_updated_at'] = time.monotonic()
                else:
                    # 收到更新时任务可能已被清理或尚未创建
                    pass

        # 周期性清理超时任务（不依赖队列空闲）
        now = time.monotonic()
        if now - last_cleanup >= CLEANUP_INTERVAL_SECONDS:
            with TASK_STORE_LOCK:
                _task_cleanup(now)
            last_cleanup = now

def task_processor_start():
    """
    启动-任务管理器消费线程, 在 FastAPI 启动时调用
    """
    global _PROCESSOR_THREAD
    if _PROCESSOR_THREAD is None:
        log.info('[Task Manager] 正在启动消费者线程...')
        _PROCESSOR_THREAD = threading.Thread(target=_task_processor_loop, daemon=True)
        _PROCESSOR_THREAD.start()

def task_processor_stop():
    """
    停止-任务管理器消费线程, 在 FastAPI 关闭时调用
    """
    global _PROCESSOR_THREAD

    if _PROCESSOR_THREAD and _PROCESSOR_THREAD.is_alive():

        log.info('[Task Manager] 正在停止消费者线程...')

        try:
            # 1. 发送停止信号
            # 使用 put_nowait 防止队列已满导致主进程在关闭时死锁
            # 如果队列满，说明积压严重，直接放弃发送停止信号（线程会在下次循环或强制退出时结束）
            TASK_QUEUE.put_nowait(_STOP_EVENT)
        except queue.Full:
            log.warn('[Task Manager] 任务队列已满，无法发送停止信号 (非致命错误)')

        except Exception as e:
            log.error(f'[Task Manager] 发送停止信号时出错: {e}')

        # 2. 等待消费者线程退出
        _PROCESSOR_THREAD.join(timeout=5)
        _PROCESSOR_THREAD = None
