from concurrent.futures import ThreadPoolExecutor

from app.utils.commons import singleton


@singleton
class _ThreadHelper:

    common_executor = None

    def __init__(self):
        self.common_executor = ThreadPoolExecutor(max_workers=5)

    def start_thread(self, func, kwargs):
        self.common_executor.submit(func, *kwargs)


thread_helper = _ThreadHelper()