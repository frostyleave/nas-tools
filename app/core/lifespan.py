import asyncio
import contextlib

from fastapi import FastAPI

import log
from app.core.services import ServiceManager
from app.core.task_manager import task_processor_start, task_processor_stop
from app.utils.async_request import close_async_client, init_async_client
from app.utils.asyncio_utils import install_connection_reset_filter
from log import set_event_loop_for_logging


def _inject_event_loop() -> None:
    """
    注入当前运行的事件循环
    """
    try:
        loop = asyncio.get_running_loop()
        set_event_loop_for_logging(loop)
        install_connection_reset_filter(loop)
    except RuntimeError as e:
        log.error(f"Could not capture event loop: {e}")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    
    try:

        log.info('服务启动中...')
        ServiceManager.start_service()
        ServiceManager.pre_warming_zhconv()

        # 注入事件循环
        _inject_event_loop()

        # 启动任务管理器
        task_processor_start()

        # 初始化全局异步会话
        init_async_client()

        log.info("✅ FastAPI 应用启动完成")

        yield
    except Exception as e:
        log.critical('❌ FastAPI 应用启动时异常', exc_info=True)
    finally:
        log.info('FastAPI 应用开始关闭...')
        ServiceManager.stop_service()

        # 关闭任务管理器
        task_processor_stop()

        # 关闭全局异步会话
        await close_async_client()

        log.info("🛑 FastAPI 应用已关闭")
