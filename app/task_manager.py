import queue
import threading
import uuid

from typing import Dict, Any, Optional
from app.utils.commons import singleton


# 1. 共享的状态存储（受锁保护）
TASK_STORE: Dict[str, Any] = {}
# 2. 保护 TASK_STORE 的锁 (防止读/写冲突)
TASK_STORE_LOCK: threading.Lock = threading.Lock()
# 3. 线程安全的队列 (生产者/消费者模式)
TASK_QUEUE: queue.Queue = queue.Queue()

# 4. 消费者线程的引用
_PROCESSOR_THREAD: Optional[threading.Thread] = None
# 5. 用于优雅停止的“哨兵”
_STOP_EVENT = object()

CLEANUP_INTERVAL_SECONDS = 60  # 每 60 秒触发一次清理检查
TASK_TTL_SECONDS = 300         # 任务“完成”后 5 分钟 (300 秒)

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

@singleton
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

    def update_task(self, task_id: str, progress: Optional[int], message: Optional[str], progress_add: Optional[int]=None, status: str='processing'):
        """
        只是将消息放入队列，*不等待锁*
        """
        TASK_QUEUE.put((task_id, status, progress, progress_add, message))
        return True

# --- 消费者线程的逻辑 ---

def _cleanup_finished_tasks():
    """
    (在锁的保护下) 清理所有已完成且超时的任务
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
    print(" [Task Processor Thread] 任务处理器已启动...")
    while True:
        try:

            message = TASK_QUEUE.get(timeout=CLEANUP_INTERVAL_SECONDS)

            # 收到“停止”信号
            if message is _STOP_EVENT:
                print(" [Task Processor Thread] 收到关闭信号，正在退出。")
                break
            
            task_id, status, progress, progress_add, message_text = message
            
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
            
            # 标记任务完成
            TASK_QUEUE.task_done()
        except queue.Empty:
            # 5. 队列为空（超时）: 执行清理的最佳时机
            with TASK_STORE_LOCK:
                _cleanup_finished_tasks()
        except Exception as e:
            # 必须捕获所有异常，否则处理器线程会崩溃
            print(f" [Task Processor Thread] 处理器循环出错: {e}")

# --- 公开的启动/停止函数 ---

def start_task_processor():
    """在 FastAPI 启动时调用"""
    global _PROCESSOR_THREAD
    if _PROCESSOR_THREAD is None:
        print(" [Task Manager] 正在启动消费者线程...")
        _PROCESSOR_THREAD = threading.Thread(target=_task_processor_loop, daemon=True)
        _PROCESSOR_THREAD.start()

def stop_task_processor():
    """在 FastAPI 关闭时调用"""
    global _PROCESSOR_THREAD
    if _PROCESSOR_THREAD and _PROCESSOR_THREAD.is_alive():
        print(" [Task Manager] 正在停止消费者线程...")
        TASK_QUEUE.put(_STOP_EVENT) # 发送停止信号
        TASK_QUEUE.join() # 等待队列处理完毕
        _PROCESSOR_THREAD.join(timeout=5) # 等待线程退出
        _PROCESSOR_THREAD = None
        print(" [Task Manager] 消费者线程已停止。")
