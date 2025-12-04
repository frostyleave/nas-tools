import queue
import threading
import uuid

from multiprocessing import Queue
from queue import Empty
from typing import Dict, Any, Optional

import log


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
# 任务“完成”后 5 分钟
TASK_TTL_SECONDS = 300

class TaskStatus:
    """一个辅助类，用于创建任务字典"""
    @staticmethod
    def create(task_id: str):
        return {
            "task_id": task_id,
            "status": "processing",
            "progress": 0,
            "message": "开始执行..."
        }

class GlobalTaskManager:
    
    def create_task(self) -> str:
        """
        同步创建任务
        """
        task_id = str(uuid.uuid4())
        with TASK_STORE_LOCK:
            TASK_STORE[task_id] = TaskStatus.create(task_id)
        return task_id

    def get_task_dict(self, task_id: str) -> dict | None:
        """
        同步获取任务状态 
        """
        if not task_id:
            return None
        with TASK_STORE_LOCK:
            task = TASK_STORE.get(task_id)
            return task.copy() if task else None # 返回拷贝以保证线程安全

    def update_task(self, task_id: str, progress: Optional[int], message: Optional[str], progress_add: int=0, status: str='processing'):
        """
        只是将消息放入队列，*不等待锁*
        """
        try:
            task_info = {
                "task_id": task_id,
                "status": status,
                "progress": progress,
                "progress_add": progress_add,
                "message": message,
            }
            TASK_QUEUE.put(task_info)
        except Exception as e:
            # 极端情况下的错误处理，避免子进程静默失败
            log.exception("Error putting task update to queue: ", e)
            return False
        return True

def _task_cleanup():
    """
    清理所有已完成且超时的任务(在锁的保护下) 
    """
    tasks_to_delete = []
    
    # 这里的迭代必须在锁内
    for task_id, task in TASK_STORE.items():
        task_status = task.get('status')
        if task_status and task_status == 'finish':
            tasks_to_delete.append(task_id)
                
                
    # 这里的删除也必须在锁内
    if tasks_to_delete:
        for task_id in tasks_to_delete:
            TASK_STORE.pop(task_id, None) # 安全删除

def _task_processor_loop():
    """
    这是“消费者”线程的唯一工作。
    它从队列中读取消息，并（加锁）更新共享字典。
    """
    log.info("[Task Processor Thread] 任务处理器已启动...")
    while True:
        try:

            message = TASK_QUEUE.get(timeout=CLEANUP_INTERVAL_SECONDS)

            # 收到“停止”信号
            if not isinstance(message, dict):
                if message == _STOP_EVENT:
                    log.info("[Task Processor Thread] 收到关闭信号，正在退出...")
                    break
                continue
            
            task_id = message.get("task_id")
            status = message.get("status")
            progress = message.get("progress")
            progress_add = message.get("progress_add")
            message_text = message.get("message")
            
            # 使用锁来安全地写入全局字典
            with TASK_STORE_LOCK:
                current_data = TASK_STORE.get(task_id)
                if current_data:
                    if progress and progress > 0:
                        current_data['progress'] = progress
                    elif progress_add:
                        progress = current_data['progress']
                        current_data['progress'] = progress + progress_add
                        
                    if message_text:
                        current_data['message'] = message_text
                    if status:
                        current_data['status'] = status
                else:
                    # 收到更新时任务可能已被清理或尚未创建
                    pass
            
        except Empty:
            # 5. 队列在 CLEANUP_INTERVAL_SECONDS 秒内没有消息
            with TASK_STORE_LOCK:
                _task_cleanup()
        except Exception as e:
            # 必须捕获所有异常，否则处理器线程会崩溃
            log.exception(" [Task Processor Thread] 处理器循环出错: ", e)

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
            log.warning('[Task Manager] 任务队列已满，无法发送停止信号 (非致命错误)')
            
        except Exception as e:
            log.error(f'[Task Manager] 发送停止信号时出错: {e}')
        
        # 2. 等待消费者线程退出
        _PROCESSOR_THREAD.join(timeout=5)
        _PROCESSOR_THREAD = None
