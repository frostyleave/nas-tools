import asyncio
import hashlib
import json
import os
import re

from urllib.parse import unquote
from pathlib import Path

from fastapi import FastAPI, Request, Depends, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import log

from app.utils.system_utils import SystemUtils
from app.utils.types import *

from config import Config

from web.action import action_router, WebAction
from web.backend.security import get_current_user
from web.backend.user import User
from web.backend.web_utils import WebUtils

from web.auth import auth_router
from web.data import data_router
from web.open import open_router
from web.lifespan import lifespan

from version import APP_VERSION

# 配置FastAPI日志
log.setup_fastapi_logging()

# FastAPI App
app = FastAPI(
    title="NAStool",
    lifespan=lifespan,
    version=APP_VERSION,
)

# 启用CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 启用压缩
app.add_middleware(GZipMiddleware, minimum_size=1000)

# 注册路由
app.include_router(open_router)
app.include_router(data_router)
app.include_router(auth_router)
app.include_router(action_router)

# 静态文件
app.mount("/static", StaticFiles(directory="web/static"), name="static")


# 页面不存在
@app.exception_handler(404)
async def page_not_found(request: Request, exc):
    return FileResponse("web/static/404.html", status_code=404)

# 服务错误
@app.exception_handler(500)
async def page_server_error(request: Request, exc):
    return FileResponse("web/static/500.html", status_code=500)

# favicon.ico
@app.get("/favicon.ico")
async def favicon():
    """
    网站图标
    """
    favicon_path = os.path.join("web", "static", "favicon.ico")
    if os.path.exists(favicon_path):
        return FileResponse(favicon_path)
    else:
        raise HTTPException(status_code=404, detail="Favicon not found")


# 禁止搜索引擎
@app.get("/robots.txt")
async def robots():
    """
    禁止搜索引擎
    """
    return FileResponse("robots.txt")


# 主页面
@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    return FileResponse("web/static/index.html")


# 目录事件响应
@app.post("/dirlist")
async def dirlist(request: Request, current_user: User = Depends(get_current_user)):
    """
    目录事件响应
    """
    r = ['<ul class="jqueryFileTree" style="display: none;">']
    try:
        r = ['<ul class="jqueryFileTree" style="display: none;">']
        form = await request.form()
        in_dir = unquote(form.get('dir'))
        ft = form.get("filter")
        if not in_dir or in_dir == "/":
            if SystemUtils.get_system() == OsType.WINDOWS:
                partitions = SystemUtils.get_windows_drives()
                if partitions:
                    dirs = partitions
                else:
                    dirs = [os.path.join("C:/", f) for f in os.listdir("C:/")]
            else:
                dirs = [os.path.join("/", f) for f in os.listdir("/")]
        else:
            d = os.path.normpath(unquote(in_dir))
            if not os.path.isdir(d):
                d = os.path.dirname(d)
            dirs = [os.path.join(d, f) for f in os.listdir(d)]
        for ff in dirs:
            f = os.path.basename(ff)
            if not f:
                f = ff
            if os.path.isdir(ff):
                r.append('<li class="directory collapsed"><a rel="%s/">%s</a></li>' % (
                    ff.replace("\\", "/"), f.replace("\\", "/")))
            else:
                if ft != "HIDE_FILES_FILTER":
                    e = os.path.splitext(f)[1][1:]
                    r.append('<li class="file ext_%s"><a rel="%s">%s</a></li>' % (
                        e, ff.replace("\\", "/"), f.replace("\\", "/")))
        r.append('</ul>')
    except Exception as e:
        log.exception('[App]加载路径失败: ', e)
        r.append('加载路径失败: %s' % str(e))
    r.append('</ul>')
    return Response(content=''.join(r), media_type="text/html")


# 备份配置文件
@app.post("/backup")
async def backup(request: Request, current_user: User = Depends(get_current_user)):
    """
    备份用户设置文件
    :return: 备份文件.zip_file
    """
    zip_file = WebAction(current_user).backup()
    if not zip_file:
        return Response(content="创建备份失败", status_code=400)
    return FileResponse(zip_file)


# 上传文件到服务器
@app.post("/upload")
async def upload(request: Request, current_user: User = Depends(get_current_user)):
    """
    上传文件到服务器
    """
    try:
        form = await request.form()
        files = form.get('file')
        temp_path = Config().get_temp_path()
        if not os.path.exists(temp_path):
            os.makedirs(temp_path)
        file_path = Path(temp_path) / files.filename

        # 保存文件
        with open(file_path, "wb") as f:
            content = await files.read()
            f.write(content)

        return {"code": 0, "filepath": str(file_path)}
    except Exception as e:
        log.exception('[App]文件上传失败: ', e)
        return {"code": 1, "msg": str(e), "filepath": ""}


# 图片中转服务
@app.get("/img")
async def img(request: Request, url: str, current_user: User = Depends(get_current_user)):
    """
    图片中转服务
    """
    if not url:
        return Response(content="参数错误", status_code=400)

    # 计算Etag
    etag = hashlib.sha256(url.encode('utf-8')).hexdigest()

    # 检查协商缓存
    if_none_match = request.headers.get('If-None-Match')
    if if_none_match and if_none_match == etag:
        return Response(content='', status_code=304)

    # 获取图片数据
    response = Response(
        content=WebUtils.request_cache(url),
        media_type='image/jpeg'
    )
    response.headers['Cache-Control'] = 'max-age=604800'
    response.headers['Etag'] = etag
    return response


# WebSocket连接 - 消息中心
@app.websocket("/message")
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
@app.get("/stream-logging")
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
@app.get("/stream-progress")
async def stream_progress(request: Request, type: str = ""):
    """
    进度SSE
    """
    print(f"[SSE-进度]开始连接，进度类型: {type}")

    async def event_generator():
        try:
            while True:                
                # 获取进度
                detail = WebAction().refresh_process({"type": type})
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

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers={ "Content-Encoding": "identity" })
