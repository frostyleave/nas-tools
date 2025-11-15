
import asyncio
import tracemalloc

from fastapi import FastAPI
from fastapi.concurrency import asynccontextmanager

import log
from log import set_event_loop_for_logging

from app.task_manager import start_task_processor, stop_task_processor

from initializer import start_config_monitor, stop_config_monitor
from web.action import WebAction


@asynccontextmanager
async def lifespan(app: FastAPI):
    
    try:

        log.info('服务启动中...')
        WebAction.start_service()
        WebAction.pre_warming_zhconv()
        
        log.info('开启配置文件监控...')
        start_config_monitor()

        # 开始内存监控
        tracemalloc.start(25)

        # 注入事件循环
        try:
            loop = asyncio.get_running_loop()
            set_event_loop_for_logging(loop)
        except RuntimeError as e:
            log.error(f"Could not capture event loop for SSE logging: {e}")

        start_task_processor()

        log.info("✅ FastAPI 应用启动完成")
        yield
    except Exception as e:
        log.exception('❌ FastAPI 应用应用时异常')
    finally:
        log.info('关闭服务...')
        WebAction.stop_service()

        # 关闭配置文件监控
        log.info('关闭配置文件监控...')
        stop_config_monitor()

        stop_task_processor()

        log.info("🛑 FastAPI 应用已关闭")
