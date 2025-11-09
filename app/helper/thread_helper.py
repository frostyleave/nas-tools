from concurrent.futures import Future, ThreadPoolExecutor

from app.utils.commons import singleton


@singleton
class _ThreadHelper:

    common_executor = None
    search_executor = None

    def __init__(self):
        self.common_executor = ThreadPoolExecutor(max_workers=5)
        self.search_executor = ThreadPoolExecutor(max_workers=8)

    def start_thread(self, func, kwargs):
        self.common_executor.submit(func, *kwargs)

    def submit_search(self, func, *args, **kwargs) -> Future:
        """
        提交一个任务到共享线程池。
        """
        if self.search_executor is None:
            raise RuntimeError("ThreadHelper's executor is not initialized. Call setup() first.")
        
        return self.search_executor.submit(func, *args, **kwargs)


thread_helper = _ThreadHelper()