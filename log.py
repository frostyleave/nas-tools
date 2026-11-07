import asyncio
import itertools
import logging
import os
import re
import sys
import threading
import time
from collections import deque
from contextvars import ContextVar
from datetime import datetime
from logging.config import dictConfig
from typing import Any
from zoneinfo import ZoneInfo

from config import Config

DEFAULT_TIMEZONE = "Asia/Shanghai"


def _get_log_timezone():
    try:
        return ZoneInfo(Config().get_timezone() or DEFAULT_TIMEZONE)
    except Exception:
        return None


def _format_timestamp(timestamp: float, date_format: str) -> str:
    """
    按应用配置的时区格式化时间，避免进程时区与预期不一致
    """
    timezone = _get_log_timezone()
    if timezone is None:
        return time.strftime(date_format, time.localtime(timestamp))
    return datetime.fromtimestamp(timestamp, timezone).strftime(date_format)


def _tz_converter(timestamp: float):
    timezone = _get_log_timezone()
    if timezone is None:
        return time.localtime(timestamp)
    return datetime.fromtimestamp(timestamp, timezone).timetuple()


# 所有 logging 格式化器（含 uvicorn）统一使用应用时区
logging.Formatter.converter = staticmethod(_tz_converter)

LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5

# --- SSE ---
LOG_BUFFER_SIZE = 100 # 内存中最多保留 100 条日志

# 新的日志缓冲区和广播系统
log_buffer: deque[dict[str, Any]] = deque(maxlen=LOG_BUFFER_SIZE)   # 全局日志缓冲区 (固定大小, 自动丢弃旧日志)
active_sse_queues: list[asyncio.Queue[dict[str, Any]]] = []     # 活跃的 SSE 客户端队列列表 (扇出目标)

# 全局递增的日志序号, 供 SSE 客户端对“历史重放 + 实时广播”去重和排序
_log_seq = itertools.count(1)

# --- 后台任务日志 (按 task_id 归集, 供前端逐步展示某次任务的完整日志) ---
TASK_LOG_MAX_LINES = 5000   # 单个任务最多保留的日志条数
TASK_LOG_MAX_TASKS = 10     # 内存中最多保留的任务日志个数

_task_logs: dict[str, list[dict[str, Any]]] = {}
_current_task_id: ContextVar[str | None] = ContextVar("log_task_id", default=None)

# 初始化为 None, 等待注入
_event_loop: asyncio.AbstractEventLoop | None = None

# 注入事件循环的函数
def set_event_loop_for_logging(loop: asyncio.AbstractEventLoop):
    """
    捕获正在运行的事件循环, 以便 SSEHandler 可以进行线程安全调用
    """
    global _event_loop
    _event_loop = loop
    
    logger = logging.getLogger("app.setup")
    logger.info(f"事件循环已绑定: {loop}")


def bind_task_log(task_id: str):
    """
    把当前线程后续产生的日志归集到指定任务。

    返回的 token 用于 unbind_task_log 解除绑定。
    """
    _task_logs.setdefault(task_id, [])
    # 控制内存占用，丢弃最早的任务日志
    while len(_task_logs) > TASK_LOG_MAX_TASKS:
        _task_logs.pop(next(iter(_task_logs)))
    return _current_task_id.set(task_id)


def unbind_task_log(token):
    """解除任务日志绑定"""
    _current_task_id.reset(token)


def get_task_logs(task_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
    """
    获取某个任务产生的日志

    :param task_id: 任务ID
    :param after_seq: 只返回序号大于该值的日志（增量读取，避免每次全量复制）
    """
    task_logs = _task_logs.get(task_id, [])
    if after_seq <= 0:
        return list(task_logs)
    # 日志按序号递增排列，从尾部回退定位即可，通常只需复制少量新日志
    index = len(task_logs)
    while index > 0 and task_logs[index - 1].get("seq", 0) > after_seq:
        index -= 1
    return list(task_logs[index:])


def get_last_task_seq(task_id: str) -> int:
    """获取某个任务最后一条日志的序号"""
    task_logs = _task_logs.get(task_id)
    return task_logs[-1].get("seq", 0) if task_logs else 0


# 广播函数 (将在事件循环中运行)
def broadcast_log(log_data: dict[str, Any]):
    """
    将日志数据放入所有活跃的 SSE 队列中。
    此函数必须在主事件循环中被调用。
    """
    broadcast_logs([log_data])


def broadcast_logs(records: list[dict[str, Any]]):
    """
    将一批日志按顺序放入所有活跃的 SSE 队列中。
    此函数必须在主事件循环中被调用。
    """
    if not records:
        return
    # 遍历列表的副本, 以防止在迭代时列表被修改
    for q in list(active_sse_queues):
        for log_data in records:
            try:
                q.put_nowait(log_data)
            except asyncio.QueueFull:
                # 客户端的队列满了 (例如客户端处理缓慢或断开)
                # 我们可以选择在这里移除该队列, 但目前先忽略
                break
            except Exception:
                # 其他异常, 例如队列已关闭
                break


# 日志广播缓冲：同一轮事件循环内的多条日志合并为一次回调
_pending_broadcast: list[dict[str, Any]] = []
_pending_lock = threading.Lock()
_flush_scheduled = False


def _flush_pending_broadcast():
    """事件循环中执行：取出缓冲的日志并批量广播"""
    global _pending_broadcast, _flush_scheduled
    with _pending_lock:
        records = _pending_broadcast
        _pending_broadcast = []
        _flush_scheduled = False
    broadcast_logs(records)


def _schedule_broadcast(log_data: dict[str, Any]):
    """
    把日志放入待广播缓冲，并保证同一轮事件循环只调度一次回调
    （emit 可能来自任意线程，因此用锁保护）
    """
    global _flush_scheduled
    with _pending_lock:
        _pending_broadcast.append(log_data)
        if _flush_scheduled:
            return
        _flush_scheduled = True
    try:
        _event_loop.call_soon_threadsafe(_flush_pending_broadcast)
    except RuntimeError:
        # 事件循环已关闭，清掉缓冲并允许下次重新调度
        with _pending_lock:
            _pending_broadcast.clear()
            _flush_scheduled = False

# SSE 日志处理器
class SSEHandler(logging.Handler):
    """
    一个自定义的 logging handler, 它将日志记录放入 asyncio.Queue。
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def emit(self, record: logging.LogRecord):
        """
        当日志事件被触发时，此方法被 (同步) 调用。
        """

        try:
            text = record.getMessage()
            if text.startswith("【"):
                source = re.findall(r"(?<=【).*?(?=】)", text)[0]
                text = text.replace(f"【{source}】", "")
            else:
                source = "System"

            seq = next(_log_seq)
            log_data = {
                "seq": seq,
                "text": text,
                "source": source,
                "time": _format_timestamp(record.created, '%H:%M:%S'),
                "level": record.levelname,
            }

            # 1.1 如果当前线程绑定了后台任务，同时归集到该任务的日志中
            task_id = _current_task_id.get()
            if task_id:
                log_data["task_id"] = task_id
                task_logs = _task_logs.setdefault(task_id, [])
                task_logs.append(log_data)
                if len(task_logs) > TASK_LOG_MAX_LINES:
                    del task_logs[:len(task_logs) - TASK_LOG_MAX_LINES]

            # 2. 存入全局缓冲区
            log_buffer.append(log_data)

            # 3. 触发广播 (线程安全地调用事件循环，同一轮日志合并成一批)
            if _event_loop:
                _schedule_broadcast(log_data)

        except asyncio.QueueFull:
            # 如果队列满了，丢弃这条日志
            pass
        except Exception:
            # 处理其他可能的错误 (例如队列被关闭)
            self.handleError(record)


# --- 日志配置字典 ---

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "()": "uvicorn.logging.DefaultFormatter",
            "format": "%(levelprefix)s %(asctime)s | %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
            "use_colors": True,
        },
        "access": {
            "()": "uvicorn.logging.AccessFormatter",
            "format": "%(levelprefix)s %(asctime)s | %(client_addr)s - \"%(request_line)s\" %(status_code)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
            "use_colors": True,
        },
        "file_default": {
            "()": "uvicorn.logging.DefaultFormatter",
            "format": "%(levelprefix)s %(asctime)s | %(message)s (%(filename)s:%(lineno)d)",
            "datefmt": "%Y-%m-%d %H:%M:%S",
            "use_colors": False,
        },
         "file_access": {
            "()": "uvicorn.logging.AccessFormatter",
            "format": "%(levelprefix)s %(asctime)s | %(client_addr)s - \"%(request_line)s\" %(status_code)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
            "use_colors": False,
        },
         "syslog_formatter": {
            "()": "uvicorn.logging.DefaultFormatter",
            "format": "%(filename)s: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
            "use_colors": False,
        },
        "sse_formatter": {
            "()": "uvicorn.logging.DefaultFormatter",
            "format": "%(levelprefix)s %(asctime)s | %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
            "use_colors": False,
        },
        "console_default": {
            "()": "uvicorn.logging.DefaultFormatter",
            "format": "%(levelprefix)s [%(thread)d] %(asctime)s | %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
            "use_colors": True,
        },
    },
    "handlers": {
        "console_access": {
            "class": "logging.StreamHandler",
            "formatter": "access",
            "stream": sys.stdout,
            "level": "INFO",
        },
        "null_handler": {
            "class": "logging.NullHandler",
        },
    },
    "loggers": {
        "uvicorn": {
            "handlers": ["null_handler"],
            "propagate": False,
        },
        # 屏蔽 httpx 日志
        "httpx": {
            "handlers": ["null_handler"],
            "propagate": False,
        },
        # 屏蔽 httpcore 日志(httpx 的底层，有时也会打印)
        "httpcore": {
            "handlers": ["null_handler"],
            "propagate": False,
        },
        # Uvicorn 访问日志
        "uvicorn.access": {
            "level": "INFO",
            "handlers": ["console_access"],
            "propagate": False,
        },
        "apscheduler": {
            "handlers": ["null_handler"],
            "propagate": False,
        },
        "alembic": {
            "handlers": ["null_handler"],
            "propagate": False,
        },
        "sqlalchemy": { # 顺便也把 sqlalchemy 屏蔽了
            "handlers": ["null_handler"],
            "propagate": False,
        },
    },
}

# --- 公共函数 ---

def setup_logging():
    """
    应用日志配置
    """

    config = Config()
    loglevel = (config.get_config('app').get('loglevel') or "info").upper()

    logger_handlers = ["console_default", "sse_handler"]

    handler_conf = LOGGING_CONFIG.get('handlers')
    handler_conf['console_default'] = {
        "class": "logging.StreamHandler",
        "formatter": "console_default",
        "stream": sys.stdout,
        "level": loglevel,
    }
    handler_conf['sse_handler'] = {
        "class": "log.SSEHandler",
        "formatter": "sse_formatter",
        "level": loglevel,
    }

    logtype = config.get_config('app').get('logtype') or "console"
    if logtype == 'file':
        # 保存到文件
        logpath = os.environ.get('NASTOOL_LOG') or config.get_config('app').get('logpath') or ""
        if logpath:
            if not os.path.exists(logpath):
                os.makedirs(logpath)
                
            logger_handlers.append('file_default')
            handler_conf['file_default'] = {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "file_default",
                "filename": os.path.join(logpath, "app.log"),
                "maxBytes": LOG_MAX_BYTES,
                "backupCount": LOG_BACKUP_COUNT,
                "encoding": "utf-8",
                "level": loglevel,
            }
    elif logtype == "server":
        # 保存到群晖日志中心
        logserver = config.get_config('app').get('logserver', '').split(':')
        if logserver:
            logip = logserver[0]
            if len(logserver) > 1:
                logport = int(logserver[1] or '514')
            else:
                logport = 514
            logger_handlers.append('synology_syslog')
            handler_conf["synology_syslog"] = {
                "class": "logging.handlers.SysLogHandler",
                "address": (logip, logport),
                "formatter": "syslog_formatter",
                "level": loglevel,
            }

    loggers = LOGGING_CONFIG.get('loggers')
    loggers['root'] = {
        "level": loglevel,
        "handlers": logger_handlers,
        "propagate": False,
    }

    dictConfig(LOGGING_CONFIG)
    
    logger = logging.getLogger("log.setup")
    logger.info(f"Logging configured. Log level: {loglevel}")
    logger.info(f"Application logs writing to: {logtype}")


_logger = logging.getLogger("app")

console = _logger.info
debug = _logger.debug
info = _logger.info
warn = _logger.warning
error = _logger.error
critical = _logger.critical
exception = _logger.exception

log = _logger.log