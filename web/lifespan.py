
import tracemalloc

from fastapi import FastAPI
from fastapi.concurrency import asynccontextmanager

import log

from initializer import start_config_monitor, stop_config_monitor
from web.action import WebAction


@asynccontextmanager
async def lifespan(app: FastAPI):
    
    try:

        log.info('服务启动中...')
        WebAction.start_service()
        
        log.info('开启配置文件监控...')
        start_config_monitor()

        # 开始内存监控
        tracemalloc.start()

        log.info("✅ FastAPI 应用启动完成")
        yield
    except Exception as e:
        log.exception('❌ FastAPI 应用应用时异常', e)
    finally:
        log.info('关闭服务...')
        WebAction.stop_service()

        # 关闭配置文件监控
        log.info('关闭配置文件监控...')
        stop_config_monitor()

        log.info("🛑 FastAPI 应用已关闭")
