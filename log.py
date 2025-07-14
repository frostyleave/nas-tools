import logging
import os
import re
import threading
import time
import traceback

from collections import deque
from html import escape
from logging.handlers import RotatingFileHandler

from config import Config

# 禁用uvicorn和fastapi的默认日志
logging.getLogger("uvicorn").propagate = False
logging.getLogger("uvicorn.access").propagate = False
logging.getLogger("fastapi").propagate = False
logging.getLogger("websockets").propagate = False
logging.getLogger("websockets.protocol").propagate = False

lock = threading.Lock()

LOG_QUEUE = deque(maxlen=200)
LOG_INDEX = 0


class Logger:
    logger = None
    __instance = {}
    __config = None

    __loglevels = {
        "info": logging.INFO,
        "debug": logging.DEBUG,
        "error": logging.ERROR
    }

    def __init__(self, module):
        self.logger = logging.getLogger(module)
        self.__config = Config()
        logtype = self.__config.get_config('app').get('logtype') or "console"
        loglevel = self.__config.get_config('app').get('loglevel') or "info"
        self.logger.setLevel(level=self.__loglevels.get(loglevel))
        if logtype == "server":
            logserver = self.__config.get_config('app').get('logserver', '').split(':')
            if logserver:
                logip = logserver[0]
                if len(logserver) > 1:
                    logport = int(logserver[1] or '514')
                else:
                    logport = 514
                log_server_handler = logging.handlers.SysLogHandler((logip, logport),
                                                                    logging.handlers.SysLogHandler.LOG_USER)
                log_server_handler.setFormatter(logging.Formatter('%(filename)s: %(message)s'))
                self.logger.addHandler(log_server_handler)
        elif logtype == "file":
            # 记录日志到文件
            logpath = os.environ.get('NASTOOL_LOG') or self.__config.get_config('app').get('logpath') or ""
            if logpath:
                if not os.path.exists(logpath):
                    os.makedirs(logpath)
                log_file_handler = RotatingFileHandler(filename=os.path.join(logpath, module + ".txt"),
                                                       maxBytes=5 * 1024 * 1024,
                                                       backupCount=3,
                                                       encoding='utf-8')
                log_file_handler.setFormatter(logging.Formatter('%(asctime)s\t%(levelname)s: %(message)s'))
                self.logger.addHandler(log_file_handler)
        # 记录日志到终端
        log_console_handler = logging.StreamHandler()
        log_console_handler.setFormatter(logging.Formatter('%(asctime)s\t%(levelname)s: %(message)s'))
        self.logger.addHandler(log_console_handler)

    @staticmethod
    def get_instance(module):
        if not module:
            module = "run"
        if Logger.__instance.get(module):
            return Logger.__instance.get(module)
        with lock:
            Logger.__instance[module] = Logger(module)
        return Logger.__instance.get(module)


def __append_log_queue(level, text):
    global LOG_INDEX, LOG_QUEUE
    with lock:
        text = escape(text)
        if text.startswith("【"):
            source = re.findall(r"(?<=【).*?(?=】)", text)[0]
            text = text.replace(f"【{source}】", "")
        else:
            source = "System"
        LOG_QUEUE.append({
            "time": time.strftime('%H:%M:%S', time.localtime(time.time())),
            "level": level,
            "source": source,
            "text": text})
        LOG_INDEX += 1


def debug(text, module=None):
    return Logger.get_instance(module).logger.debug(text)


def info(text, module=None):
    __append_log_queue("INFO", text)
    return Logger.get_instance(module).logger.info(text)


def error(text, module=None):
    __append_log_queue("ERROR", text)
    return Logger.get_instance(module).logger.error(text)

def exception(text, e, module=None):
    text = f"{text}\nException: {str(e)}\nCallstack:\n{traceback.format_exc()}\n"
    __append_log_queue("ERROR", text)
    return Logger.get_instance(module).logger.error(text)

def warn(text, module=None):
    __append_log_queue("WARN", text)
    return Logger.get_instance(module).logger.warning(text)


def console(text):
    __append_log_queue("INFO", text)
    print(text)


def setup_fastapi_logging():
    """
    配置FastAPI和Uvicorn的日志系统，使其使用我们的日志配置
    """
    # 获取配置
    config = Config()
    loglevel = config.get_config('app').get('loglevel') or "info"

    # 直接映射日志级别，而不是使用Logger类的私有变量
    log_levels = {
        "info": logging.INFO,
        "debug": logging.DEBUG,
        "error": logging.ERROR
    }
    log_level = log_levels.get(loglevel, logging.INFO)

    # 直接屏蔽uvicorn相关的噪音日志
    loggers_to_configure = {
        "uvicorn": logging.ERROR,           # 只显示错误
        "uvicorn.access": None,             # 完全禁用访问日志
        "uvicorn.error": logging.INFO,      # 保留错误日志器的基本信息
        "fastapi": log_level,               # 保持FastAPI日志
        "websockets": logging.ERROR,        # 只显示WebSocket错误
        "websockets.protocol": logging.ERROR # 只显示协议错误
    }

    for logger_name, level in loggers_to_configure.items():
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()  # 清除现有的处理器

        if level is None:
            # 完全禁用此日志器
            logger.disabled = True
            logger.propagate = False
        else:
            logger.setLevel(level)
            logger.propagate = False

            # 只为非禁用的日志器添加处理器
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter('%(asctime)s\t%(levelname)s: [%(name)s] %(message)s'))
            logger.addHandler(handler)

    print("已屏蔽uvicorn访问日志和WebSocket调试日志")
