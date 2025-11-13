from collections import deque
import logging
import re
import sys
import os
import asyncio

from logging.config import dictConfig

import time
from typing import Any, Deque, Dict, List

from config import Config

LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5

# --- SSE ---
LOG_BUFFER_SIZE = 100 # 内存中最多保留 100 条日志

# 新的日志缓冲区和广播系统
log_buffer: Deque[Dict[str, Any]] = deque(maxlen=LOG_BUFFER_SIZE)   # 全局日志缓冲区 (固定大小, 自动丢弃旧日志)
active_sse_queues: List[asyncio.Queue[Dict[str, Any]]] = []     # 活跃的 SSE 客户端队列列表 (扇出目标)

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


# 广播函数 (将在事件循环中运行)
def broadcast_log(log_data: Dict[str, Any]):
    """
    将日志数据放入所有活跃的 SSE 队列中。
    此函数必须在主事件循环中被调用。
    """
    # 遍历列表的副本, 以防止在迭代时列表被修改
    for q in list(active_sse_queues):
        try:
            q.put_nowait(log_data)
        except asyncio.QueueFull:
            # 客户端的队列满了 (例如客户端处理缓慢或断开)
            # 我们可以选择在这里移除该队列, 但目前先忽略
            pass
        except Exception:
            # 其他异常, 例如队列已关闭
            pass

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

            log_data = {
                "text": text,
                "source": source,
                "time": time.strftime('%H:%M:%S', time.localtime(record.created)),
                "level": record.levelname,
            }

            # 2. 存入全局缓冲区
            log_buffer.append(log_data)

            # 3. 触发广播 (线程安全地调用事件循环)
            if _event_loop:
                _event_loop.call_soon_threadsafe(broadcast_log, log_data)

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
        "formatter": "default",
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
warning = _logger.warning
warn = _logger.warning
error = _logger.error
critical = _logger.critical
exception = _logger.exception

log = _logger.log