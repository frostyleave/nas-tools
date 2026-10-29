import asyncio
import json
import re
import threading
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

import log
from app.core.cmd_handler import CommandHandler
from app.core.system_update import run_system_update
from app.core.task_manager import TaskStore
from app.message.message_center import SysMessageCenter
from app.middleware.security import get_current_user
from app.utils.types import SearchType
from log import active_sse_queues, log_buffer

# 流式/实时路由
streaming_router = APIRouter()

# 单条 SSE 事件最多携带的日志条数
LOG_BATCH_SIZE = 200

# SSE 通用响应头:
# - identity: 避免被 GZipMiddleware 压缩后产生缓冲
# - X-Accel-Buffering: 让 nginx 等反代不要缓存, 保证日志实时到达
SSE_HEADERS = {
    "Content-Encoding": "identity",
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


def _sse_event(records: list[dict[str, Any]]) -> str:
    """把一条或多条日志打包成一条 SSE 事件"""
    return f"data: {json.dumps(records, ensure_ascii=False)}\n\n"


def _sse_json_event(payload: dict[str, Any]) -> str:
    """把一个 JSON 对象打包成一条 SSE 事件"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# 系统更新互斥锁，避免并发执行 git pull
_update_lock = threading.Lock()


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
        log.error("[WebSocket-消息]会话获取失败: ")

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
                log.warn(f"[WebSocket-消息]接收消息异常: {e!s}")
                break

            try:

                if msgbody.get("text"):
                    # 发送的消息
                    CommandHandler().handle_message_job(
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
                    system_msg = get_system_message(lst_time=msgbody.get("lst_time"))
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
                log.error("[WebSocket-消息]处理消息失败: ")
                # 检查连接状态，避免在连接已关闭时发送消息
                try:
                    await websocket.send_text(json.dumps({"error": str(e)}))
                except Exception:
                    # 连接已关闭，忽略发送错误
                    break

    except Exception as e:
        log.warn(f"[WebSocket-消息]连接异常: {e!s}")
        # 不要在连接异常时尝试发送消息


# 实时日志SSE
@streaming_router.get("/stream-logging")
async def stream_logging(request: Request, source: str = ""):
    """
    实时日志SSE

    每个事件携带一个日志数组, 客户端一次渲染一批。日志密集时(如 git 更新),
    批量推送/渲染可避免逐条积压, 出现“任务已完成但日志还在滚动”的现象。
    """

    # 创建此客户端专用的队列
    my_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def match(log_data: dict[str, Any]) -> bool:
        return bool(log_data) and (not source or log_data.get("source") == source)

    async def event_generator():
        try:
            # 先注册队列再读取历史: 两者之间产生的日志会进入队列。
            # 与历史重复的部分按 seq 去重, 做到不丢不重。
            active_sse_queues.append(my_queue)

            pending: dict[int, dict[str, Any]] = {}
            for log_data in list(log_buffer):
                if match(log_data):
                    pending[log_data.get("seq")] = log_data
            while True:
                try:
                    log_data = my_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if match(log_data):
                    pending[log_data.get("seq")] = log_data

            history = [pending[k] for k in sorted(pending)]
            for i in range(0, len(history), LOG_BATCH_SIZE):
                yield _sse_event(history[i:i + LOG_BATCH_SIZE])
                # 释放控制权, 防止历史日志过多导致堵塞
                await asyncio.sleep(0)

            while True:
                # 取到一条后, 把队列中已积压的全部取出合并成一批发送
                log_data = await my_queue.get()
                batch = [log_data] if match(log_data) else []
                while len(batch) < LOG_BATCH_SIZE:
                    try:
                        log_data = my_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    if match(log_data):
                        batch.append(log_data)
                if batch:
                    yield _sse_event(batch)
                # 仅让出事件循环, 不做限速
                await asyncio.sleep(0)

        except asyncio.CancelledError:
            log.debug("SSE client disconnected.")
        except Exception as e:
            log.error("[SSE-日志]连接异常: ")
            yield _sse_event([{
                "seq": 0,
                "source": "System",
                "level": "ERROR",
                "time": time.strftime("%H:%M:%S"),
                "text": f"实时日志连接异常: {e!s}",
            }])
        finally:
            log.debug("Removing client queue from active SSE listeners.")
            try:
                active_sse_queues.remove(my_queue)
            except ValueError:
                log.debug("SSE queue was already removed.")

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=SSE_HEADERS)


# 系统更新：以 SSE 流式返回本次更新的日志和最终结果
@streaming_router.post("/stream-update-system", dependencies=[Depends(get_current_user)])
async def stream_update_system(request: Request):
    """
    执行一次系统更新，并把日志和结果以 SSE 的形式流式返回给前端。

    每条 SSE 事件的 data 为一个 JSON 对象：
      {"type": "logs", "records": [...]}
      {"type": "progress", "value": 10, "text": "..."}
      {"type": "done", "result": {...}}

    日志与结果走同一个响应，顺序天然有保证，无需 TaskStore。
    """
    # 同一时间只允许一个更新任务
    if not _update_lock.acquire(blocking=False):
        async def busy_generator():
            yield _sse_json_event({
                "type": "done",
                "result": {"code": -1, "msg": "已有更新任务正在执行，请稍后再试"},
            })

        return StreamingResponse(busy_generator(), media_type="text/event-stream", headers=SSE_HEADERS)

    update_id = uuid.uuid4().hex
    result_holder: dict[str, Any] = {}
    done = threading.Event()
    progress_state = {"value": 0, "text": "准备开始..."}
    progress_lock = threading.Lock()

    def report(value: int, text: str) -> None:
        with progress_lock:
            progress_state["value"] = value
            progress_state["text"] = text

    def worker():
        # 把本次更新的日志归集到 update_id
        token = log.bind_task_log(update_id)
        try:
            try:
                result_holder["result"] = run_system_update(progress_cb=report)
            except Exception as e:
                log.exception("执行系统更新任务出错")
                result_holder["result"] = {
                    "code": 1,
                    "updated": False,
                    "msg": f"更新失败：{e!s}",
                    "output": "",
                }
        finally:
            log.unbind_task_log(token)
            done.set()
            _update_lock.release()

    try:
        threading.Thread(target=worker, daemon=True).start()
    except Exception:
        _update_lock.release()
        raise

    async def event_generator():
        last_seq = 0
        last_progress = None

        def dump(event: dict[str, Any]) -> str:
            return _sse_json_event(event)

        def new_records() -> list[dict[str, Any]]:
            # 按 seq 增量获取，避免日志超出缓存上限后按索引取错
            records = log.get_task_logs(update_id)
            pending = []
            for record in reversed(records):
                if record.get("seq", 0) <= last_seq:
                    break
                pending.append(record)
            pending.reverse()
            return pending

        try:
            while True:
                pending = new_records()
                if pending:
                    last_seq = pending[-1].get("seq", last_seq)
                    yield dump({"type": "logs", "records": pending})

                with progress_lock:
                    current = dict(progress_state)
                if current != last_progress:
                    last_progress = current
                    yield dump({"type": "progress", **current})

                if done.is_set():
                    # 再取一次，确保 done 之前的日志全部发出
                    pending = new_records()
                    if pending:
                        yield dump({"type": "logs", "records": pending})
                    yield dump({"type": "done", "result": result_holder.get("result", {})})
                    break

                if await request.is_disconnected():
                    log.debug("[SSE-更新] 客户端断开连接，任务在后台继续执行")
                    break

                await asyncio.sleep(0.05)

        except asyncio.CancelledError:
            log.debug("[SSE-更新] 连接已取消")
        except Exception as e:
            log.error(f"[SSE-更新] 连接异常: {e!s}")
            yield dump({"type": "done", "result": {"code": -1, "msg": f"更新连接异常：{e!s}"}})

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=SSE_HEADERS)


# 进度SSE
@streaming_router.get("/sse-progress")
async def sse_progress(
    request: Request, 
    task_id: str = Query(..., min_length=5, title="任务ID")
):
    """
    进度SSE
    """    

    async def event_generator():
        try:
            while True:

                if await request.is_disconnected():
                    log.info(f"[SSE-进度] 客户端断开连接: {task_id}")
                    break

                # 获取进度
                task_info = TaskStore().get_task_dict(task_id)
                if not task_info:
                    log.info(f"[SSE-进度] 查询任务: {task_id} 进度信息失败")
                    break

                progress_val = task_info.get('progress', 0)
                status_desc = task_info.get('status')

                detail = {
                    'code': 0,
                    'task_id' : task_id,
                    'value' : progress_val,
                    'status' : status_desc,
                    'text' : task_info.get('message')
                }

                if progress_val >= 100:
                    detail['result'] = task_info.get('result')

                # 发送进度
                yield f"data: {json.dumps(detail)}\n\n"
                
                # 进度完成，结束
                if progress_val >= 100 and status_desc == 'finish':
                    break
                # 等一会
                await asyncio.sleep(0.5)

        except Exception as e:
            log.warn("[SSE-进度]连接异常: ")
            yield f"data: {json.dumps({'code': -1, 'value': 0, 'text': f'进度连接异常: {e!s}'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=SSE_HEADERS)

def get_system_message(lst_time):

    messages = SysMessageCenter().get_system_messages(lst_time=lst_time)
    if messages:
        lst_time = messages[0].get("time")
    return {
        "code": 0,
        "message": messages,
        "lst_time": lst_time
    }