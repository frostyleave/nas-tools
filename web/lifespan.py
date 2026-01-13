import asyncio
import contextlib

from fastapi import FastAPI

import log
from log import set_event_loop_for_logging

from app.task_manager import task_processor_start, task_processor_stop
from app.utils.async_request import AsyncRequestUtils

from initializer import start_config_monitor, stop_config_monitor
from web.action import WebAction


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    
    try:

        log.info('服务启动中...')
        WebAction.start_service()
        WebAction.pre_warming_zhconv()
        
        log.info('开启配置文件监控...')
        start_config_monitor()

        # 注入事件循环
        try:
            loop = asyncio.get_running_loop()
            set_event_loop_for_logging(loop)
            
        except RuntimeError as e:
            log.error(f"Could not capture event loop for SSE logging: {e}")

        # 启动任务管理器
        task_processor_start()

        # 初始化客户端
        AsyncRequestUtils.init_client()

        log.info("✅ FastAPI 应用启动完成")

        yield
    except Exception as e:
        log.exception('❌ FastAPI 应用启动时异常')
    finally:
        log.info('FastAPI 应用开始关闭...')
        WebAction.stop_service()

        # 关闭配置文件监控
        log.info('关闭配置文件监控...')
        stop_config_monitor()

        # 关闭任务管理器
        task_processor_stop()

        # 关闭client_session
        AsyncRequestUtils.close_client()

        log.info("🛑 FastAPI 应用已关闭")
