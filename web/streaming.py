import asyncio
import json
import re

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

import log

from web.action import WebAction
from web.backend.security import get_current_user
from app.utils.types import *

# 流式/实时路由
streaming_router = APIRouter()


# WebSocket连接 - 消息中心
@streaming_router.websocket("/message")
async def message_handler(websocket: WebSocket):
    """
    消息中心WebSocket
    """
    await websocket.accept()

    # 获取当前用户
    user_id = None
    try:
        # 尝试从cookie中获取会话数据
        user_info = await get_current_user(websocket)
        if user_info:
            user_id = user_info.id
            log.debug(f"[WebSocket-消息]会话用户ID: {user_id}")
    except Exception as e:
        log.exception("[WebSocket-消息]会话获取失败: ", e)

    try:
        while True:
            try:
                data = await websocket.receive_text()
                if not data:
                    continue

                try:
                    msgbody = json.loads(data)
                except Exception as err:
                    log.warn("[WebSocket-消息]连接出错: " + str(err))
                    continue
            except WebSocketDisconnect:
                # WebSocket正常断开，直接退出循环
                log.debug("[WebSocket-消息]连接正常断开")
                break
            except Exception as e:
                # 其他异常，记录日志并退出
                log.warn(f"[WebSocket-消息]接收消息异常: {str(e)}")
                break

            try:

                if msgbody.get("text"):
                    # 发送的消息
                    WebAction().handle_message_job(
                        msg=msgbody.get("text"),
                        in_from=SearchType.WEB,
                        user_id=user_id or "anonymous",
                        user_name=user_id or "anonymous"
                    )
                    try:
                        await websocket.send_text(json.dumps({}))
                    except Exception:
                        # 连接已关闭
                        break
                else:
                    # 拉取消息
                    system_msg = WebAction().get_system_message(lst_time=msgbody.get("lst_time"))
                    messages = system_msg.get("message")
                    lst_time = system_msg.get("lst_time")
                    ret_messages = []

                    for message in list(reversed(messages)):
                        content = re.sub(
                            r"#+",
                            "<br>",
                            re.sub(
                                r"<[^>]+>",
                                "",
                                re.sub(r"<br/?>", "####", message.get("content"), flags=re.IGNORECASE)
                            )
                        )
                        ret_messages.append({
                            "level": "bg-red" if message.get("level") == "ERROR" else "",
                            "title": message.get("title"),
                            "content": content,
                            "time": message.get("time")
                        })

                    try:
                        await websocket.send_text(json.dumps({
                            "lst_time": lst_time,
                            "message": ret_messages
                        }))
                    except Exception:
                        # 连接已关闭
                        break
            except Exception as e:
                log.exception("[WebSocket-消息]处理消息失败: ", e)
                # 检查连接状态，避免在连接已关闭时发送消息
                try:
                    await websocket.send_text(json.dumps({"error": str(e)}))
                except Exception:
                    # 连接已关闭，忽略发送错误
                    break

    except Exception as e:
        log.warn(f"[WebSocket-消息]连接异常: {str(e)}")
        # 不要在连接异常时尝试发送消息


# 实时日志SSE
@streaming_router.get("/stream-logging")
async def stream_logging(request: Request, source: str = ""):
    """
    实时日志SSE
    """
    # 全局变量，用于跟踪日志源和索引
    logging_source = source

    # 重置日志索引
    log.LOG_INDEX = len(log.LOG_QUEUE)

    async def event_generator():
        nonlocal logging_source
        try:
            while True:
                try:
                    # 获取新日志
                    logs = []
                    if log.LOG_INDEX > 0:
                        logs = list(log.LOG_QUEUE)[-log.LOG_INDEX:]
                        log.LOG_INDEX = 0
                        if logging_source:
                            logs = [lg for lg in logs if lg.get("source") == logging_source]

                    # 发送日志
                    yield f"data: {json.dumps(logs)}\n\n"
                    # 等待一段时间
                    await asyncio.sleep(1)

                except Exception as e:
                    log.exception("[SSE-日志]处理失败: ", e)
                    await asyncio.sleep(1)

        except Exception as e:
            log.exception("[SSE-日志]连接异常: ", e)
            yield f"data: {json.dumps({'code': -1, 'value': 0, 'text': f'实时日志连接异常: {str(e)}'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers={ "Content-Encoding": "identity" })


# 进度SSE
@streaming_router.get("/stream-progress")
async def stream_progress(request: Request, type: str = ""):
    """
    进度SSE
    """

    web_action = WebAction()

    async def event_generator():
        try:
            while True:                
                # 获取进度
                detail = web_action.refresh_process({"type": type})
                # 发送进度
                yield f"data: {json.dumps(detail)}\n\n"
                # 进度完成，结束
                if detail['value'] >= 100:
                    break
                # 等待一段时间
                await asyncio.sleep(0.5)
        except Exception as e:
            log.exception("[SSE-进度]连接异常: ", e)
            yield f"data: {json.dumps({'code': -1, 'value': 0, 'text': f'进度连接异常: {str(e)}'})}\n\n"

    # 初始化进度
    web_action.init_process({"type": type})
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers={ "Content-Encoding": "identity" })
