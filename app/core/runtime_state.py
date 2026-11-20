import threading
import time
import uuid

# 当前进程的唯一标识与启动时间，供前端判断服务是否真的完成了重启
BOOT_ID = uuid.uuid4().hex
STARTED_AT = int(time.time())

_shutdown_event = threading.Event()


def request_shutdown() -> None:
    """
    标记进程正在关闭，常驻的流式响应应尽快结束
    """
    _shutdown_event.set()


def is_shutdown_requested() -> bool:
    """
    进程是否正在关闭
    """
    return _shutdown_event.is_set()
