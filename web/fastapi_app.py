import asyncio
import base64
import datetime
import hashlib
import json
import mimetypes
import os.path
import re
import urllib

from math import floor
from pathlib import Path
from threading import Lock
from urllib.parse import unquote

from fastapi import Body, FastAPI, Request, Response, status, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

import log
from app.conf import ModuleConf, SystemConfig
from app.rsschecker import RssChecker
from app.sync import Sync
from app.brushtask import BrushTask
from app.torrentremover import TorrentRemover
from app.downloader import Downloader
from app.filter import Filter
from app.indexer import Indexer
from app.sites import SiteUserInfo
from app.mediaserver import MediaServer
from app.message import Message
from app.sites import Sites
from app.utils import SystemUtils, StringUtils, ExceptionUtils
from app.utils.types import *
from app.helper import SecurityHelper, ThreadHelper
from app.helper.meta_helper import MetaHelper
from app.plugins import EventManager

from config import Config, PT_TRANSFER_INTERVAL, TMDB_API_DOMAINS

from web.action import WebAction
from web.backend.user import User
from web.backend.wallpaper import get_login_wallpaper
from web.backend.web_utils import WebUtils
from web.fastapi_api import api_router

# 配置文件锁
ConfigLock = Lock()

# TMDB API 域名
TMDB_API_DOMAINS = [
    "api.themoviedb.org",
    "api.tmdb.org",
    "tmdb.org"
]

# 配置FastAPI日志
log.setup_fastapi_logging()

# FastAPI App
app = FastAPI(
    title="NAStool API",
    description="NAStool API",
    version="1.0.0",
)

# 自定义会话管理
# 使用固定的密钥，确保会话可以在重启后保持
SESSION_SECRET_KEY = "nastool_session_key_fixed_for_debugging"
SESSION_COOKIE_NAME = "nastool_session"
SESSION_MAX_AGE = 14 * 24 * 60 * 60  # 14天

# 会话管理函数
def get_session_data(request: Request) -> dict:
    """
    从cookie中获取会话数据
    """
    log.debug(f"获取会话数据，请求路径: {request.url.path}")
    log.debug(f"请求cookies: {request.cookies}")

    session_cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_cookie:
        log.debug(f"未找到会话cookie: {SESSION_COOKIE_NAME}")
        return {}

    try:
        # 解析会话数据
        session_data = json.loads(base64.b64decode(session_cookie.encode()).decode())
        log.debug(f"解析会话数据成功: {session_data}")
        return session_data
    except Exception as e:
        log.debug(f"解析会话数据失败: {str(e)}")
        return {}

def set_session_cookie(response: Response, session_data: dict, max_age: int = None):
    """
    设置会话cookie
    """
    if not max_age:
        max_age = SESSION_MAX_AGE

    # 序列化会话数据
    session_cookie = base64.b64encode(json.dumps(session_data).encode()).decode()

    # 设置cookie
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_cookie,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        path="/"
    )

def delete_session_cookie(response: Response):
    """
    删除会话cookie
    """
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")

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

# 模板
templates = Jinja2Templates(directory="web/templates")

# 添加自定义过滤器
# base64模板过滤器
def b64encode(s):
    return base64.b64encode(s.encode()).decode()

# split模板过滤器
def split(string, char, pos):
    return string.split(char)[pos]

# 刷流规则过滤器
def brush_rule_string(rules):
    return WebAction().parse_brush_rule_string(rules)

# 大小格式化过滤器
def str_filesize(size):
    return StringUtils.str_filesize(size, pre=1)

# MD5 HASH过滤器
def md5_hash(text):
    return StringUtils.md5_hash(text)

# 注册过滤器
templates.env.filters["b64encode"] = b64encode
templates.env.filters["split"] = split
templates.env.filters["brush_rule_string"] = brush_rule_string
templates.env.filters["str_filesize"] = str_filesize
templates.env.filters["hash"] = md5_hash

# 静态文件
app.mount("/static", StaticFiles(directory="web/static"), name="static")

# favicon.ico
@app.get("/favicon.ico")
async def favicon():
    """
    网站图标
    """
    from fastapi.responses import FileResponse
    import os
    favicon_path = os.path.join("web", "static", "favicon.ico")
    if os.path.exists(favicon_path):
        return FileResponse(favicon_path)
    else:
        raise HTTPException(status_code=404, detail="Favicon not found")





# 注册API路由
app.include_router(api_router)

# fix Windows registry stuff
mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('text/css', '.css')

# SSE
LoggingSource = ""
LoggingLock = Lock()

# 用户认证依赖
async def get_current_user(request: Request):
    """
    获取当前登录用户，如果未登录则返回None
    """
    # 获取会话数据
    session_data = get_session_data(request)

    # 获取用户ID
    user_id = session_data.get("user_id")
    if user_id is None:
        return None

    # 获取用户信息
    current_user = User().get(user_id)
    return current_user


# 用户认证依赖 - 必须登录
async def get_current_user_required(request: Request):
    """
    获取当前登录用户，如果未登录则返回401错误
    """
    # 获取会话数据
    session_data = get_session_data(request)

    # 获取用户ID
    user_id = session_data.get("user_id")
    if user_id is None:
        # 返回401错误而不是重定向
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户未登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 获取用户信息
    current_user = User().get(user_id)
    if not current_user:
        # 返回401错误而不是重定向
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return current_user


# 登录保护中间件
class LoginRequiredMiddleware(BaseHTTPMiddleware):
    """
    中间件：要求用户登录
    """
    async def dispatch(self, request: Request, call_next):
        # 排除不需要登录的路径
        excluded_paths = ['/', '/logout', '/static', '/do', '/message', '/stream-logging', '/stream-progress',
                         '/open', '/webhook', '/wechat', '/api']

        # 检查路径是否需要登录
        path = request.url.path
        if any(path.startswith(excluded) for excluded in excluded_paths):
            return await call_next(request)

        # 获取会话数据
        session_data = get_session_data(request)

        # 获取用户ID
        user_id = session_data.get("user_id")
        username = session_data.get("username")

        # 特殊处理admin用户
        if username == "admin" and user_id == 0:
            # admin用户特殊处理
            admin_user = User().get_user("admin")
            if admin_user:
                request.state.current_user = admin_user
                return await call_next(request)

        if user_id is None:
            # 重定向到登录页面，特殊处理/web路径
            if path == "/web":
                # 对于/web路径，从referer中提取hash部分
                referer = request.headers.get("referer", "")
                if "#" in referer:
                    hash_part = referer.split("#")[-1]
                    return RedirectResponse(url=f"/?next={hash_part}", status_code=status.HTTP_302_FOUND)
                else:
                    return RedirectResponse(url="/?next=index", status_code=status.HTTP_302_FOUND)
            else:
                return RedirectResponse(url=f"/?next={path.lstrip('/')}", status_code=status.HTTP_302_FOUND)

        # 获取用户信息
        current_user = User().get(user_id)
        if not current_user:
            # 重定向到登录页面，特殊处理/web路径
            if path == "/web":
                # 对于/web路径，从referer中提取hash部分
                referer = request.headers.get("referer", "")
                if "#" in referer:
                    hash_part = referer.split("#")[-1]
                    return RedirectResponse(url=f"/?next={hash_part}", status_code=status.HTTP_302_FOUND)
                else:
                    return RedirectResponse(url="/?next=index", status_code=status.HTTP_302_FOUND)
            else:
                return RedirectResponse(url=f"/?next={path.lstrip('/')}", status_code=status.HTTP_302_FOUND)

        # 将用户信息添加到请求状态中
        request.state.current_user = current_user

        # 继续处理请求
        return await call_next(request)

# 获取当前用户的依赖函数
async def get_current_user_from_request(request: Request):
    """
    从请求状态中获取当前用户
    """
    return getattr(request.state, "current_user", None)

# 添加登录保护中间件
app.add_middleware(LoginRequiredMiddleware)

# 主页面 - 智能登录检查
@app.get("/", response_class=HTMLResponse)
async def index_page(request: Request, next: str = ""):
    """
    主页面处理：智能检查用户认证状态
    - 优先检查会话认证（session cookie）
    - 如果会话有效，直接重定向到主页
    - 如果会话无效，显示登录页面（前端会检查Token认证）
    """

    # 1. 检查会话认证状态
    session_data = get_session_data(request)
    user_id = session_data.get("user_id")
    username = session_data.get("username")

    if user_id and username:
        # 会话认证有效，直接重定向到主页
        log.info(f"检测到有效会话认证，用户: {username}，重定向到主页")
        Config().current_user = username
        MediaServer().init_config()

        # 构建重定向URL
        if next and next not in ['web', 'index', '']:
            redirect_url = f"/web#{next}"
        else:
            redirect_url = "/web#index"

        log.debug(f"重定向到: {redirect_url}")
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

    # 2. 会话认证无效，显示登录页面

    # 获取登录页面背景
    image_code, img_title, img_link = get_login_wallpaper()

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "GoPage": next or "index",  # 默认跳转到index页面
            "image_code": image_code,
            "img_title": img_title,
            "img_link": img_link,
            "err_msg": ""
        }
    )


# 退出登录
@app.get("/logout")
async def logout(request: Request):
    """
    退出登录
    """
    # 创建重定向响应
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

    # 删除会话cookie
    delete_session_cookie(response)

    return response


# 导航页面
@app.get("/web", response_class=HTMLResponse)
async def web_page(request: Request):
    # 获取当前用户
    session_data = get_session_data(request)
    log.debug(f"导航页面会话数据: {session_data}")

    user_id = session_data.get("user_id")
    log.debug(f"导航页面用户ID: {user_id}, 类型: {type(user_id)}")

    # 特殊处理admin用户
    username = session_data.get("username")
    if username == "admin":
        log.debug("导航页面检测到admin用户，直接通过")
        admin_user = User().get_user("admin")  # 使用get_user方法获取admin用户
        log.debug(f"Admin用户信息: {admin_user}")

        # 创建一个模拟的admin用户对象
        class AdminUser:
            def __init__(self):
                self.id = 0
                self.username = "admin"
                self.pris = "我的媒体库,资源搜索,探索,站点管理,订阅管理,下载管理,媒体整理,服务,系统设置"
                self.search = 1
                self.level = 99
                self.admin = 1

            def get_usermenus(self):
                return Config().menu

            def get_topmenus(self):
                return self.pris.split(',')

        current_user = AdminUser()
    else:
        if not user_id:
            log.debug("导航页面未找到用户ID，重定向到登录页面")
            return RedirectResponse(url="/?next=web", status_code=status.HTTP_302_FOUND)

        current_user = User().get(user_id)
        if not current_user:
            log.debug("导航页面未找到用户信息，重定向到登录页面")
            return RedirectResponse(url="/?next=web", status_code=status.HTTP_302_FOUND)

    # 跳转页面
    next_page = request.query_params.get("next", "")

    # 判断当前的运营环境
    system_flag = SystemUtils.get_system()
    sync_mod = Config().get_config('media').get('default_rmt_mode')
    tmdb_flag = 1 if Config().get_config('app').get('rmt_tmdbkey') else 0
    default_path = Config().get_config('media').get('media_default_path')

    if not sync_mod:
        sync_mod = "link"

    rmt_mode_dict = WebAction().get_rmt_modes()
    restype_dict = ModuleConf.TORRENT_SEARCH_PARAMS.get("restype")
    pix_dict = ModuleConf.TORRENT_SEARCH_PARAMS.get("pix")
    site_favicons = Sites().get_site_favicon()
    indexers = Indexer().get_indexers()
    search_source = "douban" if Config().get_config("laboratory").get("use_douban_titles") else "tmdb"
    custom_script_cfg = SystemConfig().get(SystemConfigKey.CustomScript)
    menus = WebAction().get_user_menus(current_user=current_user).get("menus") or []
    commands = WebAction().get_commands()

    return templates.TemplateResponse(
        "navigation.html",
        {
            "request": request,
            "GoPage": next_page,
            "CurrentUser": current_user,
            "SystemFlag": system_flag.value,
            "TMDBFlag": tmdb_flag,
            "AppVersion": WebUtils.get_current_version(),
            "RestypeDict": restype_dict,
            "PixDict": pix_dict,
            "SyncMod": sync_mod,
            "SiteFavicons": site_favicons,
            "RmtModeDict": rmt_mode_dict,
            "Indexers": indexers,
            "SearchSource": search_source,
            "CustomScriptCfg": custom_script_cfg,
            "DefaultPath": default_path,
            "Menus": menus,
            "Commands": commands
        }
    )


# 基础设置页面
@app.get("/basic", response_class=HTMLResponse)
async def basic(request: Request, current_user: User = Depends(get_current_user_required)):
    proxy = Config().get_config('app').get("proxies", {}).get("http")
    if proxy:
        proxy = proxy.replace("http://", "")
    RmtModeDict = WebAction().get_rmt_modes()
    CustomScriptCfg = SystemConfig().get(SystemConfigKey.CustomScript)
    ScraperConf = SystemConfig().get(SystemConfigKey.UserScraperConf) or {}
    return templates.TemplateResponse(
        "setting/basic.html",
        {
            "request": request,
            "Config": Config().get_config(),
            "Proxy": proxy,
            "RmtModeDict": RmtModeDict,
            "CustomScriptCfg": CustomScriptCfg,
            "CurrentUser": current_user,
            "ScraperNfo": ScraperConf.get("scraper_nfo") or {},
            "ScraperPic": ScraperConf.get("scraper_pic") or {},
            "MediaServerConf": ModuleConf.MEDIASERVER_CONF,
            "TmdbDomains": TMDB_API_DOMAINS
        }
    )


# 事件响应
@app.post("/do")
def do(content: dict = Body(...)):
    try:
        cmd = content.get("cmd")
        data = content.get("data") or {}
        log.debug(f"处理/do请求: cmd={cmd}, data={data}")
        return WebAction().action(cmd, data)
    except Exception as e:
        log.exception("处理/do请求出错")  # 修正日志记录方式
        return {"code": -1, "msg": str(e)}

# 事件响应 - GET方法
@app.get("/do")
async def do_get(request: Request):
    try:
        cmd = request.query_params.get("cmd")
        data_str = request.query_params.get("data", "{}")
        data = json.loads(data_str) if data_str else {}
        log.debug(f"处理/do GET请求: cmd={cmd}, data={data}")
        return WebAction().action(cmd, data)
    except Exception as e:
        log.exception("处理/do GET请求出错: ", e)
        return {"code": -1, "msg": str(e)}


# 页面不存在
@app.exception_handler(404)
async def page_not_found(request: Request, exc):
    return templates.TemplateResponse("404.html", {"request": request, "error": exc}, status_code=404)


# 服务错误
@app.exception_handler(500)
async def page_server_error(request: Request, exc):
    return templates.TemplateResponse("500.html", {"request": request, "error": exc}, status_code=500)


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
        cookies = websocket.cookies
        session_cookie = cookies.get(SESSION_COOKIE_NAME)
        if session_cookie:
            try:
                # 解析会话数据
                session_data = json.loads(base64.b64decode(session_cookie.encode()).decode())
                user_id = session_data.get("user_id")
                log.debug(f"[WebSocket-消息]会话用户ID: {user_id}")
            except Exception as e:
                log.exception("[WebSocket-消息]解析会话数据失败: ", e)
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


# 开始页面
@app.get("/index", response_class=HTMLResponse)
async def index(request: Request, current_user: User = Depends(get_current_user_required)):

    # 媒体服务器类型
    MSType = Config().get_config('media').get('media_server')
    # 获取媒体数量
    MediaCounts = WebAction().get_library_mediacount()
    if MediaCounts.get("code") == 0:
        ServerSucess = True
    else:
        ServerSucess = False

    # 获得活动日志
    Activity = WebAction().get_library_playhistory().get("result")

    # 磁盘空间
    LibrarySpaces = WebAction().get_library_spacesize()

    # 媒体库
    Librarys = MediaServer().get_libraries()
    LibrarySyncConf = SystemConfig().get(SystemConfigKey.SyncLibrary) or []

    # 继续观看
    Resumes = MediaServer().get_resume()

    # 最近添加
    Latests = MediaServer().get_latest()

    return templates.TemplateResponse("index.html",
                           {
                               "request": request,
                               "CurrentUser": current_user,
                               "ServerSucess": ServerSucess,
                               "MediaCount": {'MovieCount': MediaCounts.get("Movie"),
                                       'SeriesCount': MediaCounts.get("Series"),
                                       'SongCount': MediaCounts.get("Music"),
                                       "EpisodeCount": MediaCounts.get("Episodes")},
                               "Activitys": Activity,
                               "UserCount": MediaCounts.get("User"),
                               "FreeSpace": LibrarySpaces.get("FreeSpace"),
                               "TotalSpace": LibrarySpaces.get("TotalSpace"),
                               "UsedSapce": LibrarySpaces.get("UsedSapce"),
                               "UsedPercent": LibrarySpaces.get("UsedPercent"),
                               "MediaServerType": MSType,
                               "Librarys": Librarys,
                               "LibrarySyncConf": LibrarySyncConf,
                               "Resumes": Resumes,
                               "Latests": Latests
                           })

# 资源搜索页面
@app.get("/search", response_class=HTMLResponse)
async def search(request: Request, current_user: User = Depends(get_current_user_required)):

    # 权限
    username = current_user.username
    pris = User().get_user(username).get("pris")

    # 结果
    res = WebAction().get_search_result()
    SearchResults = res.get("result")
    Count = res.get("total")

    return templates.TemplateResponse("search.html",
                           {
                               "request": request,
                               "UserPris": str(pris).split(","),
                               "Count": Count,
                               "Results": SearchResults,
                               "SiteDict": Indexer().get_indexer_hash_dict(),
                               "UPCHAR": chr(8593)
                           })

# 电影订阅页面
@app.get("/movie_rss", response_class=HTMLResponse)
async def movie_rss(request: Request, current_user: User = Depends(get_current_user_required)):

    RssItems = WebAction().get_movie_rss_list().get("result")
    RuleGroups = {str(group["id"]): group["name"] for group in Filter().get_rule_groups()}
    DownloadSettings = Downloader().get_download_setting()

    return templates.TemplateResponse("rss/movie_rss.html",
                           {
                               "request": request,
                               "CurrentUser": current_user,
                               "Count": len(RssItems),
                               "RuleGroups": RuleGroups,
                               "DownloadSettings": DownloadSettings,
                               "Items": RssItems,
                               "Type": 'MOV',
                               "TypeName": '电影'
                           })

# 电视剧订阅页面
@app.get("/tv_rss", response_class=HTMLResponse)
async def tv_rss(request: Request, current_user: User = Depends(get_current_user_required)):

    RssItems = WebAction().get_tv_rss_list().get("result")
    RuleGroups = {str(group["id"]): group["name"] for group in Filter().get_rule_groups()}
    DownloadSettings = Downloader().get_download_setting()

    return templates.TemplateResponse("rss/movie_rss.html",
                           {
                               "request": request,
                               "CurrentUser": current_user,
                               "Count": len(RssItems),
                               "RuleGroups": RuleGroups,
                               "DownloadSettings": DownloadSettings,
                               "Items": RssItems,
                               "Type": 'TV',
                               "TypeName": '电视剧'
                           })


# 订阅历史页面
@app.get("/rss_history", response_class=HTMLResponse)
async def rss_history(request: Request, current_user: User = Depends(get_current_user_required), t: str = ""):

    RssHistory = WebAction().get_rss_history({"type": t}).get("result")

    return templates.TemplateResponse("rss/rss_history.html",
                           {
                               "request": request,
                               "CurrentUser": current_user,
                               "Count": len(RssHistory),
                               "Items": RssHistory,
                               "Type": t
                           })


# 订阅日历页面
@app.get("/rss_calendar", response_class=HTMLResponse)
async def rss_calendar(request: Request, current_user: User = Depends(get_current_user_required)):

    Today = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d')
    # 电影订阅
    RssMovieItems = WebAction().get_movie_rss_items().get("result")
    # 电视剧订阅
    RssTvItems = WebAction().get_tv_rss_items().get("result")

    return templates.TemplateResponse("rss/rss_calendar.html",
                           {
                               "request": request,
                               "CurrentUser": current_user,
                               "Today": Today,
                               "RssMovieItems": RssMovieItems,
                               "RssTvItems": RssTvItems
                           })


# 索引站点页面
@app.get("/indexer", response_class=HTMLResponse)
async def indexer(request: Request, current_user: User = Depends(get_current_user_required)):

    indexers = Indexer().get_indexers(check=False)
    indexer_sites = SystemConfig().get(SystemConfigKey.UserIndexerSites)
    if not indexer_sites:
        indexer_sites = []

    SearchTypes = { "title":'关键字', "en_name":'英文名', "douban_id":'豆瓣id', "imdb":'imdb id' }

    public_indexers = []
    check_sites = []
    for site in indexers:
        checked = site.id in indexer_sites
        if checked:
            check_sites.append(site.id)
        if site.public:
            site_info = {
                "id": site.id,
                "name": site.name,
                "domain": site.domain,
                "render": site.render,
                "source_type": site.source_type,
                "search_type": SearchTypes.get(site.search_type, '关键字'),
                "downloader": site.downloader,
                "public": site.public,
                "proxy": site.proxy,
                "en_expand": site.en_expand,
                "checked": checked
            }
            public_indexers.append(site_info)

    DownloadSettings = {did: attr["name"] for did, attr in Downloader().get_download_setting().items()}
    SourceTypes = { "MOVIE":'电影', "TV":'剧集', "ANIME":'动漫' }

    return templates.TemplateResponse("site/indexer.html",
                           {
                               "request": request,
                               "CurrentUser": current_user,
                               "Config": Config().get_config(),
                               "IsPublic": 1,
                               "Indexers": public_indexers,
                               "DownloadSettings": DownloadSettings,
                               "CheckSites": check_sites,
                               "SourceTypes": SourceTypes
                           })


# PT索引站点页面
@app.get("/ptindexer", response_class=HTMLResponse)
async def ptindexer(request: Request, current_user: User = Depends(get_current_user_required)):

    indexers = Indexer().get_indexers(check=False)
    indexer_sites = SystemConfig().get(SystemConfigKey.UserIndexerSites)
    if not indexer_sites:
        indexer_sites = []

    SearchTypes = { "title":'关键字', "en_name":'英文名', "douban_id":'豆瓣id', "imdb":'imdb id' }

    private_indexers = []
    check_sites = []
    for site in indexers:
        checked = site.id in indexer_sites
        if checked:
            check_sites.append(site.id)
        if site.public:
            continue
        site_info = {
            "id": site.id,
            "name": site.name,
            "domain": site.domain,
            "render": site.render,
            "source_type": site.source_type,
            "search_type": SearchTypes.get(site.search_type, '关键字'),
            "downloader": site.downloader,
            "public": site.public,
            "proxy": site.proxy,
            "en_expand": site.en_expand,
            "checked": checked
        }
        private_indexers.append(site_info)

    DownloadSettings = {did: attr["name"] for did, attr in Downloader().get_download_setting().items()}
    SourceTypes = { "MOVIE":'电影', "TV":'剧集', "ANIME":'动漫' }

    return templates.TemplateResponse("site/indexer.html",
                           {
                               "request": request,
                               "CurrentUser": current_user,
                               "Config": Config().get_config(),
                               "IsPublic": 0,
                               "Indexers": private_indexers,
                               "DownloadSettings": DownloadSettings,
                               "CheckSites": check_sites,
                               "SourceTypes": SourceTypes,
                               "SearchTypes": SearchTypes
                           })

# 站点维护页面
@app.get("/site", response_class=HTMLResponse, response_model=None)
async def sites_page(request: Request, current_user = Depends(get_current_user_from_request)):
    cfg_sites = Sites().get_sites()
    rule_groups = {str(group["id"]): group["name"] for group in Filter().get_rule_groups()}
    download_settings = {did: attr["name"] for did, attr in Downloader().get_download_setting().items()}
    cookie_cloud_cfg = SystemConfig().get(SystemConfigKey.CookieCloud)
    cookie_user_info_cfg = SystemConfig().get(SystemConfigKey.CookieUserInfo)

    return templates.TemplateResponse(
        "site/site.html",
        {
            "request": request,
            "Sites": cfg_sites,
            "RuleGroups": rule_groups,
            "DownloadSettings": download_settings,
            "ChromeOk": True,
            "CookieCloudCfg": cookie_cloud_cfg,
            "CookieUserInfoCfg": cookie_user_info_cfg,
            "CurrentUser": current_user
        }
    )


# 站点资源页面
@app.get("/sitelist", response_class=HTMLResponse, response_model=None)
async def sitelist_page(request: Request, current_user = Depends(get_current_user_from_request)):
    indexer_sites = Indexer().get_indexers(check=False)

    return templates.TemplateResponse(
        "site/sitelist.html",
        {
            "request": request,
            "Sites": indexer_sites,
            "Count": len(indexer_sites),
            "CurrentUser": current_user
        }
    )


# 站点资源页面
@app.get("/resources", response_class=HTMLResponse, response_model=None)
async def resources(request: Request, current_user = Depends(get_current_user_from_request), site: str = "", title: str = "", page: int = 0, keyword: str = ""):
    Results = WebAction().list_site_resources({
        "id": site,
        "page": page,
        "keyword": keyword
    }).get("data") or []

    return templates.TemplateResponse("site/resources.html",
                           {
                               "request": request,
                               "SiteId": site,
                               "Title": title,
                               "Results": Results,
                               "Count": len(Results),
                               "KeyWord": keyword,
                               "CurrentPage": int(page),
                               "TotalPage": int(page) + 1,
                               "CurrentUser": current_user
                           })


# 媒体库页面
@app.get("/library", response_class=HTMLResponse, response_model=None)
async def library(request: Request, current_user = Depends(get_current_user_from_request)):
    return templates.TemplateResponse("setting/library.html",
                           {
                               "request": request,
                               "Config": Config().get_config(),
                               "MediaServerConf": ModuleConf.MEDIASERVER_CONF,
                               "CurrentUser": current_user
                           })


# 通知消息页面
@app.get("/notification", response_class=HTMLResponse, response_model=None)
async def notification(request: Request, current_user = Depends(get_current_user_from_request)):
    MessageClients = Message().get_message_client_info()
    Channels = ModuleConf.MESSAGE_CONF.get("client")
    Switchs = ModuleConf.MESSAGE_CONF.get("switch")

    return templates.TemplateResponse("setting/notification.html",
                           {
                               "request": request,
                               "Channels": Channels,
                               "Switchs": Switchs,
                               "ClientCount": len(MessageClients),
                               "MessageClients": MessageClients,
                               "CurrentUser": current_user
                           })


# 用户管理页面
@app.get("/users", response_class=HTMLResponse, response_model=None)
async def users(request: Request, current_user = Depends(get_current_user_from_request)):
    Users = WebAction().get_users().get("result")
    TopMenus = WebAction().get_top_menus().get("menus")

    return templates.TemplateResponse("setting/users.html",
                           {
                               "request": request,
                               "Users": Users,
                               "UserCount": len(Users),
                               "TopMenus": TopMenus,
                               "CurrentUser": current_user
                           })


# 过滤规则设置页面
@app.get("/filterrule", response_class=HTMLResponse, response_model=None)
async def filterrule(request: Request, current_user = Depends(get_current_user_from_request)):
    result = WebAction().get_filterrules()

    return templates.TemplateResponse("setting/filterrule.html",
                           {
                               "request": request,
                               "Count": len(result.get("ruleGroups")),
                               "RuleGroups": result.get("ruleGroups"),
                               "Init_RuleGroups": result.get("initRules"),
                               "CurrentUser": current_user
                           })


# 目录同步页面
@app.get("/directorysync", response_class=HTMLResponse, response_model=None)
async def directorysync(request: Request, current_user = Depends(get_current_user_from_request)):
    from app.sync import Sync
    RmtModeDict = WebAction().get_rmt_modes()
    SyncPaths = Sync().get_sync_path_conf()
    return templates.TemplateResponse("setting/directorysync.html",
                           {
                               "request": request,
                               "SyncPaths": SyncPaths,
                               "SyncCount": len(SyncPaths),
                               "RmtModeDict": RmtModeDict,
                               "CurrentUser": current_user
                           })


# 自定义识别词设置页面
@app.get("/customwords", response_class=HTMLResponse, response_model=None)
async def customwords(request: Request, current_user = Depends(get_current_user_from_request)):
    groups = WebAction().get_customwords().get("result")
    return templates.TemplateResponse("setting/customwords.html",
                           {
                               "request": request,
                               "Groups": groups,
                               "GroupsCount": len(groups),
                               "CurrentUser": current_user
                           })


# 插件页面
@app.get("/plugin", response_class=HTMLResponse, response_model=None)
async def plugin(request: Request, current_user = Depends(get_current_user_from_request)):
    # 下载器
    DefaultDownloader = Downloader().default_downloader_id
    Downloaders = Downloader().get_downloader_conf()
    DownloadersCount = len(Downloaders)
    Categories = {
        x: WebAction().get_categories({
            "type": x
        }).get("category") for x in ["电影", "电视剧", "动漫"]
    }
    RmtModeDict = WebAction().get_rmt_modes()
    # 插件
    # 确保current_user不为None
    if current_user:
        # 直接传递用户级别
        from app.plugins.plugin_manager import PluginManager
        Plugins = PluginManager().get_plugins_conf(current_user.level)
    else:
        # 如果current_user为None，使用默认admin用户级别
        admin_user = User().get_user("admin")
        if admin_user:
            # 直接传递admin用户级别
            from app.plugins.plugin_manager import PluginManager
            Plugins = PluginManager().get_plugins_conf(admin_user.level)
        else:
            # 如果无法获取admin用户，使用最高级别99
            from app.plugins.plugin_manager import PluginManager
            Plugins = PluginManager().get_plugins_conf(99)

    Settings = '\n'.join(SystemConfig().get(SystemConfigKey.ExternalPluginsSource) or [])
    return templates.TemplateResponse("setting/plugin.html",
                           {
                               "request": request,
                               "Config": Config().get_config(),
                               "Downloaders": Downloaders,
                               "DefaultDownloader": DefaultDownloader,
                               "DownloadersCount": DownloadersCount,
                               "Categories": Categories,
                               "RmtModeDict": RmtModeDict,
                               "DownloaderConf": ModuleConf.DOWNLOADER_CONF,
                               "Plugins": Plugins,
                               "Settings": Settings,
                               "PluginCount": len(Plugins),
                               "CurrentUser": current_user
                           })


# 唤起App中转页面
@app.get("/open", response_class=HTMLResponse)
async def open_app(request: Request):
    return templates.TemplateResponse("openapp.html", {"request": request})


# Webhook处理
@app.post("/webhook/{type}")
async def webhook(type: str, request: Request):
    """
    处理Webhook请求
    """
    # 获取请求体
    body = await request.body()
    body_str = body.decode('utf-8') if body else ""

    # 获取请求头
    headers = dict(request.headers)

    # 获取查询参数
    params = dict(request.query_params)

    # 处理Webhook
    result = WebAction().webhook(
        type=type,
        body=body_str,
        headers=headers,
        params=params
    )

    # 处理结果
    if isinstance(result, dict):
        code = result.get("code", 0)
        success = code == 0
        message = result.get("message", "")
        data = result.get("data") or result.get("result")

        return {
            "code": code,
            "success": success,
            "message": message,
            "data": data
        }
    else:
        return {
            "code": -1,
            "success": False,
            "message": "未知错误",
            "data": None
        }


# 微信回调
@app.get("/wechat")
async def wechat_get(request: Request):
    """
    微信回调GET请求
    """
    # 获取查询参数
    params = dict(request.query_params)

    # 处理微信回调
    result = WebAction().wechat(
        params=params,
        body="",
        method="GET"
    )

    # 返回结果
    return Response(content=result, media_type="text/plain")


@app.post("/wechat")
async def wechat_post(request: Request):
    """
    微信回调POST请求
    """
    # 获取请求体
    body = await request.body()
    body_str = body.decode('utf-8') if body else ""

    # 获取查询参数
    params = dict(request.query_params)

    # 处理微信回调
    result = WebAction().wechat(
        params=params,
        body=body_str,
        method="POST"
    )

    # 返回结果
    return Response(content=result, media_type="text/plain")


# 排行榜页面
@app.get("/ranking", response_model=None)
async def ranking(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    排行榜页面
    """
    return templates.TemplateResponse(
        "discovery/ranking.html",
        {
            "request": request,
            "DiscoveryType": "RANKING",
            "current_user": current_user
        }
    )


# 电视剧排行榜页面
@app.get("/tv_ranking", response_model=None)
async def tv_ranking(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    电视剧排行榜页面
    """
    return templates.TemplateResponse(
        "discovery/ranking.html",
        {
            "request": request,
            "DiscoveryType": "TV",
            "current_user": current_user
        }
    )


# 用户RSS页面
@app.get("/user_rss", response_model=None)
async def user_rss(request: Request, current_user: User = Depends(get_current_user_from_request)):
    """
    用户RSS页面
    """
    Tasks = RssChecker().get_rsstask_info()
    RssParsers = RssChecker().get_userrss_parser()
    RuleGroups = {str(group["id"]): group["name"] for group in Filter().get_rule_groups()}
    DownloadSettings = {did: attr["name"] for did, attr in Downloader().get_download_setting().items()}
    RestypeDict = ModuleConf.TORRENT_SEARCH_PARAMS.get("restype")
    PixDict = ModuleConf.TORRENT_SEARCH_PARAMS.get("pix")

    return templates.TemplateResponse(
        "rss/user_rss.html",
        {
            "request": request,
            "Tasks": Tasks,
            "Count": len(Tasks),
            "RssParsers": RssParsers,
            "RuleGroups": RuleGroups,
            "RestypeDict": RestypeDict,
            "PixDict": PixDict,
            "DownloadSettings": DownloadSettings,
            "current_user": current_user
        }
    )


# 服务页面
@app.get("/service", response_model=None)
async def service(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    服务页面
    """
    # 所有规则组
    RuleGroups = Filter().get_rule_groups()
    # 所有同步目录
    SyncPaths = Sync().get_sync_path_conf()

    # 获取用户服务（get_current_user_required已经保证current_user不为空）
    Services = current_user.get_services()
    pt = Config().get_config('pt')
    # RSS订阅
    if "rssdownload" in Services:
        pt_check_interval = pt.get('pt_check_interval')
        if str(pt_check_interval).isdigit():
            tim_rssdownload = str(round(int(pt_check_interval) / 60)) + " 分钟"
            rss_state = 'ON'
        else:
            tim_rssdownload = ""
            rss_state = 'OFF'
        Services['rssdownload'].update({
            'time': tim_rssdownload,
            'state': rss_state,
        })

    # RSS搜索
    if "subscribe_search_all" in Services:
        search_rss_interval = pt.get('search_rss_interval')
        if str(search_rss_interval).isdigit():
            if int(search_rss_interval) < 3:
                search_rss_interval = 3
            tim_rsssearch = str(int(search_rss_interval)) + " 小时"
            rss_search_state = 'ON'
        else:
            tim_rsssearch = ""
            rss_search_state = 'OFF'
        Services['subscribe_search_all'].update({
            'time': tim_rsssearch,
            'state': rss_search_state,
        })

    # 下载文件转移
    if "pttransfer" in Services:
        pt_monitor = Downloader().monitor_downloader_ids
        if pt_monitor:
            tim_pttransfer = str(round(PT_TRANSFER_INTERVAL / 60)) + " 分钟"
            sta_pttransfer = 'ON'
        else:
            tim_pttransfer = ""
            sta_pttransfer = 'OFF'
        Services['pttransfer'].update({
            'time': tim_pttransfer,
            'state': sta_pttransfer,
        })

    # 目录同步
    if "sync" in Services:
        if Sync().monitor_sync_path_ids:
            Services['sync'].update({
                'state': 'ON'
            })

    # 系统进程
    if "processes" in Services:
        if not SystemUtils.is_docker() or not SystemUtils.get_all_processes():
            Services.pop('processes')

    return templates.TemplateResponse(
        "service.html",
        {
            "request": request,
            "Count": len(Services),
            "RuleGroups": RuleGroups,
            "SyncPaths": SyncPaths,
            "SchedulerTasks": Services,
            "current_user": current_user
        }
    )


# 正在下载页面
@app.get("/downloading", response_model=None)
async def downloading(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    正在下载页面
    """
    downloader_proxy = Downloader()
    Downloaders = []
    for key, value in downloader_proxy.get_downloader_conf().items():
        if value.get('enabled'):
            Downloaders.append(value)

    did = request.query_params.get('downloaderId')
    if not did:
        did = downloader_proxy.default_downloader_id

    DispTorrents = WebAction().get_downloading(downloader_id=did).get("result")

    return templates.TemplateResponse(
        "download/downloading.html",
        {
            "request": request,
            "DownloaderId": int(did) if did else 0,
            "Downloaders": Downloaders,
            "DownloadCount": len(DispTorrents),
            "Torrents": DispTorrents,
            "current_user": current_user
        }
    )


# 媒体文件管理页面
@app.get("/mediafile", response_model=None)
async def mediafile(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    媒体文件管理页面
    """
    media_default_path = Config().get_config('media').get('media_default_path')
    if media_default_path:
        DirD = media_default_path
    else:
        download_dirs = Downloader().get_download_visit_dirs()
        if download_dirs:
            try:
                DirD = os.path.commonpath(download_dirs).replace("\\", "/")
            except Exception as err:
                log.exception(f'管理目录转换异常: {download_dirs}', err)
                DirD = "/"
        else:
            DirD = "/"
    DirR = request.query_params.get("dir")

    return templates.TemplateResponse(
        "rename/mediafile.html",
        {
            "request": request,
            "Dir": DirR or DirD,
            "current_user": current_user
        }
    )


# 数据统计页面
@app.get("/statistics", response_model=None)
async def statistics(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    数据统计页面
    """
    # 刷新单个site
    refresh_site = request.query_params.getlist("refresh_site")
    # 强制刷新所有
    refresh_force = True if request.query_params.get("refresh_force") else False
    # 总上传下载
    TotalUpload = 0
    TotalDownload = 0
    TotalSeedingSize = 0
    TotalSeeding = 0
    # 站点标签及上传下载
    SiteNames = []
    SiteUploads = []
    SiteDownloads = []
    SiteRatios = []
    SiteErrs = {}
    # 站点上传下载
    SiteData = SiteUserInfo().get_site_data(specify_sites=refresh_site, force=refresh_force)
    if isinstance(SiteData, dict):
        for name, data in SiteData.items():
            if not data:
                continue
            up = data.get("upload", 0)
            dl = data.get("download", 0)
            ratio = data.get("ratio", 0)
            seeding = data.get("seeding", 0)
            seeding_size = data.get("seeding_size", 0)
            err_msg = data.get("err_msg", "")

            SiteErrs.update({name: err_msg})

            if not up and not dl and not ratio:
                continue
            if not str(up).isdigit() or not str(dl).isdigit():
                continue
            if name not in SiteNames:
                SiteNames.append(name)
                TotalUpload += int(up)
                TotalDownload += int(dl)
                TotalSeeding += int(seeding)
                TotalSeedingSize += int(seeding_size)
                SiteUploads.append(int(up))
                SiteDownloads.append(int(dl))
                SiteRatios.append(round(float(ratio), 1))

    # 站点用户数据
    SiteUserStatistics = WebAction().get_site_user_statistics({"encoding": "DICT"}).get("data")

    return templates.TemplateResponse(
        "site/statistics.html",
        {
            "request": request,
            "TotalDownload": TotalDownload,
            "TotalUpload": TotalUpload,
            "TotalSeedingSize": TotalSeedingSize,
            "TotalSeeding": TotalSeeding,
            "SiteDownloads": SiteDownloads,
            "SiteUploads": SiteUploads,
            "SiteRatios": SiteRatios,
            "SiteNames": SiteNames,
            "SiteErr": SiteErrs,
            "SiteUserStatistics": SiteUserStatistics,
            "current_user": current_user
        }
    )


# 刷流任务页面
@app.get("/brushtask", response_model=None)
async def brushtask(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    刷流任务页面
    """
    # 站点列表
    CfgSites = Sites().get_sites(brush=True)
    # 下载器列表
    Downloaders = Downloader().get_downloader_conf_simple()
    # 任务列表
    Tasks = BrushTask().get_brushtask_info()

    return templates.TemplateResponse(
        "site/brushtask.html",
        {
            "request": request,
            "Count": len(Tasks),
            "Sites": CfgSites,
            "Tasks": Tasks,
            "Downloaders": Downloaders,
            "current_user": current_user
        }
    )


# 电影订阅页面
@app.get("/movie_rss", response_model=None)
async def movie_rss(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    电影订阅页面
    """
    RssItems = WebAction().get_movie_rss_list().get("result")
    RuleGroups = {str(group["id"]): group["name"] for group in Filter().get_rule_groups()}
    DownloadSettings = Downloader().get_download_setting()

    return templates.TemplateResponse(
        "rss/movie_rss.html",
        {
            "request": request,
            "Count": len(RssItems),
            "RuleGroups": RuleGroups,
            "DownloadSettings": DownloadSettings,
            "Items": RssItems,
            "Type": 'MOV',
            "TypeName": '电影',
            "current_user": current_user
        }
    )


# 电视剧订阅页面
@app.get("/tv_rss", response_model=None)
async def tv_rss(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    电视剧订阅页面
    """
    RssItems = WebAction().get_tv_rss_list().get("result")
    RuleGroups = {str(group["id"]): group["name"] for group in Filter().get_rule_groups()}
    DownloadSettings = Downloader().get_download_setting()

    return templates.TemplateResponse(
        "rss/movie_rss.html",
        {
            "request": request,
            "Count": len(RssItems),
            "RuleGroups": RuleGroups,
            "DownloadSettings": DownloadSettings,
            "Items": RssItems,
            "Type": 'TV',
            "TypeName": '电视剧',
            "current_user": current_user
        }
    )


# 订阅历史页面
@app.get("/rss_history", response_model=None)
async def rss_history(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    订阅历史页面
    """
    mtype = request.query_params.get("t")
    RssHistory = WebAction().get_rss_history({"type": mtype}).get("result")

    return templates.TemplateResponse(
        "rss/rss_history.html",
        {
            "request": request,
            "Count": len(RssHistory),
            "Items": RssHistory,
            "Type": mtype,
            "current_user": current_user
        }
    )


# 订阅日历页面
@app.get("/rss_calendar", response_model=None)
async def rss_calendar(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    订阅日历页面
    """
    Today = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d')
    # 电影订阅
    RssMovieItems = WebAction().get_movie_rss_items().get("result")
    # 电视剧订阅
    RssTvItems = WebAction().get_tv_rss_items().get("result")

    return templates.TemplateResponse(
        "rss/rss_calendar.html",
        {
            "request": request,
            "Today": Today,
            "RssMovieItems": RssMovieItems,
            "RssTvItems": RssTvItems,
            "current_user": current_user
        }
    )


# RSS解析器页面
@app.get("/rss_parser", response_model=None)
async def rss_parser(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    RSS解析器页面
    """
    RssParsers = RssChecker().get_userrss_parser()

    return templates.TemplateResponse(
        "rss/rss_parser.html",
        {
            "request": request,
            "RssParsers": RssParsers,
            "Count": len(RssParsers),
            "current_user": current_user
        }
    )


# 索引站点页面
@app.get("/indexer", response_model=None)
async def indexer(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    索引站点页面
    """
    indexers = Indexer().get_indexers(check=False)
    indexer_sites = SystemConfig().get(SystemConfigKey.UserIndexerSites)

    SearchTypes = {"title": '关键字', "en_name": '英文名', "douban_id": '豆瓣id', "imdb": 'imdb id'}

    public_indexers = []
    check_sites = []
    for site in indexers:
        checked = site.id in indexer_sites
        if checked:
            check_sites.append(site.id)
        if site.public:
            site_info = {
                "id": site.id,
                "name": site.name,
                "domain": site.domain,
                "render": site.render,
                "source_type": site.source_type,
                "search_type": SearchTypes.get(site.search_type, '关键字'),
                "downloader": site.downloader,
                "public": site.public,
                "proxy": site.proxy,
                "en_expand": site.en_expand,
                "checked": checked
            }
            public_indexers.append(site_info)

    DownloadSettings = {did: attr["name"] for did, attr in Downloader().get_download_setting().items()}
    SourceTypes = {"MOVIE": '电影', "TV": '剧集', "ANIME": '动漫'}

    return templates.TemplateResponse(
        "site/indexer.html",
        {
            "request": request,
            "Config": Config().get_config(),
            "IsPublic": 1,
            "Indexers": public_indexers,
            "DownloadSettings": DownloadSettings,
            "CheckSites": check_sites,
            "SourceTypes": SourceTypes,
            "current_user": current_user
        }
    )


# PT索引站点页面
@app.get("/ptindexer", response_model=None)
async def ptindexer(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    PT索引站点页面
    """
    indexers = Indexer().get_indexers(check=False)
    indexer_sites = SystemConfig().get(SystemConfigKey.UserIndexerSites)

    SearchTypes = {"title": '关键字', "en_name": '英文名', "douban_id": '豆瓣id', "imdb": 'imdb id'}

    private_indexers = []
    check_sites = []
    for site in indexers:
        checked = site.id in indexer_sites
        if checked:
            check_sites.append(site.id)
        if site.public:
            continue
        site_info = {
            "id": site.id,
            "name": site.name,
            "domain": site.domain,
            "render": site.render,
            "source_type": site.source_type,
            "search_type": SearchTypes.get(site.search_type, '关键字'),
            "downloader": site.downloader,
            "public": site.public,
            "proxy": site.proxy,
            "en_expand": site.en_expand,
            "checked": checked
        }
        private_indexers.append(site_info)

    DownloadSettings = {did: attr["name"] for did, attr in Downloader().get_download_setting().items()}
    SourceTypes = {"MOVIE": '电影', "TV": '剧集', "ANIME": '动漫'}

    return templates.TemplateResponse(
        "site/indexer.html",
        {
            "request": request,
            "Config": Config().get_config(),
            "IsPublic": 0,
            "Indexers": private_indexers,
            "DownloadSettings": DownloadSettings,
            "CheckSites": check_sites,
            "SourceTypes": SourceTypes,
            "SearchTypes": SearchTypes,
            "current_user": current_user
        }
    )


# 站点维护页面
@app.get("/site", response_model=None)
async def sites(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    站点维护页面
    """
    CfgSites = Sites().get_sites()
    RuleGroups = {str(group["id"]): group["name"] for group in Filter().get_rule_groups()}
    DownloadSettings = {did: attr["name"] for did, attr in Downloader().get_download_setting().items()}
    CookieCloudCfg = SystemConfig().get(SystemConfigKey.CookieCloud)
    CookieUserInfoCfg = SystemConfig().get(SystemConfigKey.CookieUserInfo)

    return templates.TemplateResponse(
        "site/site.html",
        {
            "request": request,
            "Sites": CfgSites,
            "RuleGroups": RuleGroups,
            "DownloadSettings": DownloadSettings,
            "ChromeOk": True,
            "CookieCloudCfg": CookieCloudCfg,
            "CookieUserInfoCfg": CookieUserInfoCfg,
            "current_user": current_user
        }
    )


# 站点资源页面
@app.get("/sitelist", response_model=None)
async def sitelist(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    站点资源页面
    """
    IndexerSites = Indexer().get_indexers(check=False)

    return templates.TemplateResponse(
        "site/sitelist.html",
        {
            "request": request,
            "Sites": IndexerSites,
            "Count": len(IndexerSites),
            "current_user": current_user
        }
    )


# 站点资源页面
@app.get("/resources", response_model=None)
async def resources(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    站点资源页面
    """
    site_id = request.query_params.get("site")
    site_name = request.query_params.get("title")
    page = request.query_params.get("page") or 0
    keyword = request.query_params.get("keyword")

    Results = WebAction().list_site_resources({
        "id": site_id,
        "page": page,
        "keyword": keyword
    }).get("data") or []

    return templates.TemplateResponse(
        "site/resources.html",
        {
            "request": request,
            "Results": Results,
            "SiteId": site_id,
            "Title": site_name,
            "KeyWord": keyword,
            "TotalCount": len(Results),
            "PageRange": range(0, 10),
            "CurrentPage": int(page),
            "TotalPage": 10,
            "current_user": current_user
        }
    )


# 媒体库页面
@app.get("/library", response_model=None)
async def library(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    媒体库页面
    """
    return templates.TemplateResponse(
        "setting/library.html",
        {
            "request": request,
            "Config": Config().get_config(),
            "MediaServerConf": ModuleConf.MEDIASERVER_CONF,
            "current_user": current_user
        }
    )


# 通知消息页面
@app.get("/notification", response_model=None)
async def notification(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    通知消息页面
    """
    MessageClients = Message().get_message_client_info()
    Channels = ModuleConf.MESSAGE_CONF.get("client")
    Switchs = ModuleConf.MESSAGE_CONF.get("switch")

    return templates.TemplateResponse(
        "setting/notification.html",
        {
            "request": request,
            "Channels": Channels,
            "Switchs": Switchs,
            "ClientCount": len(MessageClients),
            "MessageClients": MessageClients,
            "current_user": current_user
        }
    )


# 用户管理页面
@app.get("/users", response_model=None)
async def users(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    用户管理页面
    """
    Users = WebAction().get_users().get("result")
    TopMenus = WebAction().get_top_menus().get("menus")

    return templates.TemplateResponse(
        "setting/users.html",
        {
            "request": request,
            "Users": Users,
            "UserCount": len(Users),
            "TopMenus": TopMenus,
            "current_user": current_user
        }
    )


# 过滤规则设置页面
@app.get("/filterrule", response_model=None)
async def filterrule(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    过滤规则设置页面
    """
    result = WebAction().get_filterrules()

    return templates.TemplateResponse(
        "setting/filterrule.html",
        {
            "request": request,
            "Count": len(result.get("ruleGroups")),
            "RuleGroups": result.get("ruleGroups"),
            "Init_RuleGroups": result.get("initRules"),
            "current_user": current_user
        }
    )


# 目录事件响应
@app.post("/dirlist")
async def dirlist(request: Request, current_user: User = Depends(get_current_user_required)):
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
            d = os.path.normpath(urllib.parse.unquote(in_dir))
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
        ExceptionUtils.exception_traceback(e)
        r.append('加载路径失败: %s' % str(e))
    r.append('</ul>')
    return Response(content=''.join(r), media_type="text/html")


# 禁止搜索引擎
@app.get("/robots.txt")
async def robots():
    """
    禁止搜索引擎
    """
    return FileResponse("robots.txt")


# 唤起App中转页面
@app.get("/open")
async def open_app(request: Request):
    """
    唤起App中转页面
    """
    return templates.TemplateResponse("openapp.html", {"request": request})


# 备份配置文件
@app.post("/backup")
async def backup(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    备份用户设置文件
    :return: 备份文件.zip_file
    """
    zip_file = WebAction().backup()
    if not zip_file:
        return Response(content="创建备份失败", status_code=400)
    return FileResponse(zip_file)


# 上传文件到服务器
@app.post("/upload")
async def upload(request: Request, current_user: User = Depends(get_current_user_required)):
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
        ExceptionUtils.exception_traceback(e)
        return {"code": 1, "msg": str(e), "filepath": ""}


# 图片中转服务
@app.get("/img")
async def img(request: Request, url: str, current_user: User = Depends(get_current_user_required)):
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


# Plex Webhook
@app.post("/plex")
async def plex_webhook(request: Request):
    """
    Plex Webhook
    """
    if not SecurityHelper().check_mediaserver_ip(request.client.host):
        log.warn(f"非法IP地址的媒体服务器消息通知：{request.client.host}")
        return '不允许的IP地址请求'

    form = await request.form()
    request_json = json.loads(form.get('payload', '{}'))
    log.debug("收到Plex Webhook报文：%s" % str(request_json))

    # 事件类型
    event_match = request_json.get("event") in ["media.play", "media.stop", "library.new"]
    # 媒体类型
    type_match = request_json.get("Metadata", {}).get("type") in ["movie", "episode", "show"]
    # 是否直播
    is_live = request_json.get("Metadata", {}).get("live") == "1"

    # 如果事件类型匹配,媒体类型匹配,不是直播
    if event_match and type_match and not is_live:
        # 发送消息
        ThreadHelper().start_thread(MediaServer().webhook_message_handler,
                                  (request_json, MediaServerType.PLEX))
        # 触发事件
        EventManager().send_event(EventType.PlexWebhook, request_json)

    return 'Ok'


# Jellyfin Webhook
@app.post("/jellyfin")
async def jellyfin_webhook(request: Request):
    """
    Jellyfin Webhook
    """
    if not SecurityHelper().check_mediaserver_ip(request.client.host):
        log.warn(f"非法IP地址的媒体服务器消息通知：{request.client.host}")
        return '不允许的IP地址请求'

    request_json = await request.json()
    log.debug("收到Jellyfin Webhook报文：%s" % str(request_json))

    # 发送消息
    ThreadHelper().start_thread(MediaServer().webhook_message_handler,
                              (request_json, MediaServerType.JELLYFIN))
    # 触发事件
    EventManager().send_event(EventType.JellyfinWebhook, request_json)

    return 'Ok'


# Emby Webhook
@app.route("/emby", methods=['GET', 'POST'])
async def emby_webhook(request: Request):
    """
    Emby Webhook
    """
    if not SecurityHelper().check_mediaserver_ip(request.client.host):
        log.warn(f"非法IP地址的媒体服务器消息通知：{request.client.host}")
        return '不允许的IP地址请求'

    if request.method == 'POST':
        form = await request.form()
        log.debug("Emby Webhook data: %s" % str(form.get('data', {})))
        request_json = json.loads(form.get('data', '{}'))
    else:
        log.debug("Emby Webhook data: %s" % str(dict(request.query_params)))
        request_json = dict(request.query_params)

    log.debug("收到Emby Webhook报文：%s" % str(request_json))

    # 发送消息
    ThreadHelper().start_thread(MediaServer().webhook_message_handler,
                              (request_json, MediaServerType.EMBY))
    # 触发事件
    EventManager().send_event(EventType.EmbyWebhook, request_json)

    return 'Ok'


# 自动删种页面
@app.get("/torrent_remove", response_model=None)
async def torrent_remove(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    自动删种页面
    """
    Downloaders = Downloader().get_downloader_conf_simple()
    TorrentRemoveTasks = TorrentRemover().get_torrent_remove_tasks()

    return templates.TemplateResponse(
        "download/torrent_remove.html",
        {
            "request": request,
            "Downloaders": Downloaders,
            "DownloaderConfig": ModuleConf.TORRENTREMOVER_DICT,
            "Count": len(TorrentRemoveTasks),
            "TorrentRemoveTasks": TorrentRemoveTasks,
            "current_user": current_user
        }
    )


# 首页
@app.get("/index", response_model=None)
async def index(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    首页
    """
    # 媒体服务器类型
    MSType = Config().get_config('media').get('media_server')
    # 获取媒体数量
    MediaCounts = WebAction().get_library_mediacount()
    if MediaCounts.get("code") == 0:
        ServerSucess = True
    else:
        ServerSucess = False

    # 获得活动日志
    Activity = WebAction().get_library_playhistory().get("result")

    # 磁盘空间
    LibrarySpaces = WebAction().get_library_spacesize()

    # 媒体库
    Librarys = MediaServer().get_libraries()
    LibrarySyncConf = SystemConfig().get(SystemConfigKey.SyncLibrary) or []

    # 继续观看
    Resumes = MediaServer().get_resume()

    # 最近添加
    Latests = MediaServer().get_latest()

    # 获取主机名
    host = request.headers.get("host", "")
    curdomainleft = host.split(':')[0] if host else ""

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "ServerSucess": ServerSucess,
            "MediaCount": {
                'MovieCount': MediaCounts.get("Movie"),
                'SeriesCount': MediaCounts.get("Series"),
                'SongCount': MediaCounts.get("Music"),
                "EpisodeCount": MediaCounts.get("Episodes")
            },
            "Activitys": Activity,
            "UserCount": MediaCounts.get("User"),
            "FreeSpace": LibrarySpaces.get("FreeSpace"),
            "TotalSpace": LibrarySpaces.get("TotalSpace"),
            "UsedSapce": LibrarySpaces.get("UsedSapce"),
            "UsedPercent": LibrarySpaces.get("UsedPercent"),
            "MediaServerType": MSType,
            "Librarys": Librarys,
            "LibrarySyncConf": LibrarySyncConf,
            "Resumes": Resumes,
            "Latests": Latests,
            "current_user": current_user,
            "curdomainleft": curdomainleft
        }
    )


# 资源搜索页面
@app.get("/search", response_model=None)
async def search(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    资源搜索页面
    """
    # 权限
    pris = ""
    if current_user:
        pris = current_user.pris

    # 结果
    res = WebAction().get_search_result()
    SearchResults = res.get("result")
    Count = res.get("total")

    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "UserPris": str(pris).split(","),
            "Count": Count,
            "Results": SearchResults,
            "SiteDict": Indexer().get_indexer_hash_dict(),
            "UPCHAR": chr(8593),
            "current_user": current_user
        }
    )


# 近期下载页面
@app.get("/downloaded", response_model=None)
async def downloaded(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    近期下载页面
    """
    CurrentPage = request.query_params.get("page") or 1

    return templates.TemplateResponse(
        "discovery/recommend.html",
        {
            "request": request,
            "Type": 'DOWNLOADED',
            "Title": '近期下载',
            "CurrentPage": CurrentPage,
            "current_user": current_user
        }
    )


# 下载设置页面
@app.get("/download_setting", response_model=None)
async def download_setting(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    下载设置页面
    """
    DefaultDownloadSetting = Downloader().default_download_setting_id
    Downloaders = Downloader().get_downloader_conf_simple()
    DownloadSetting = Downloader().get_download_setting()

    return templates.TemplateResponse(
        "setting/download_setting.html",
        {
            "request": request,
            "DownloadSetting": DownloadSetting,
            "DefaultDownloadSetting": DefaultDownloadSetting,
            "Downloaders": Downloaders,
            "Count": len(DownloadSetting),
            "current_user": current_user
        }
    )


# 插件页面
@app.get("/plugin", response_model=None)
async def plugin(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    插件页面
    """
    # 下载器
    DefaultDownloader = Downloader().default_downloader_id
    Downloaders = Downloader().get_downloader_conf()
    DownloadersCount = len(Downloaders)
    Categories = {
        x: WebAction().get_categories({
            "type": x
        }).get("category") for x in ["电影", "电视剧", "动漫"]
    }
    RmtModeDict = WebAction().get_rmt_modes()
    # 插件
    Plugins = WebAction().get_plugins_conf({"user": current_user}).get("result")
    Settings = '\n'.join(SystemConfig().get(SystemConfigKey.ExternalPluginsSource) or [])

    return templates.TemplateResponse(
        "setting/plugin.html",
        {
            "request": request,
            "Config": Config().get_config(),
            "Downloaders": Downloaders,
            "DefaultDownloader": DefaultDownloader,
            "DownloadersCount": DownloadersCount,
            "Categories": Categories,
            "RmtModeDict": RmtModeDict,
            "DownloaderConf": ModuleConf.DOWNLOADER_CONF,
            "Plugins": Plugins,
            "Settings": Settings,
            "PluginCount": len(Plugins),
            "current_user": current_user
        }
    )


# 推荐页面
@app.get("/recommend", response_model=None)
async def recommend(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    推荐页面
    """
    Type = request.query_params.get("type") or ""
    SubType = request.query_params.get("subtype") or ""
    Title = request.query_params.get("title") or ""
    SubTitle = request.query_params.get("subtitle") or ""
    CurrentPage = request.query_params.get("page") or 1
    Week = request.query_params.get("week") or ""
    TmdbId = request.query_params.get("tmdbid") or ""
    PersonId = request.query_params.get("personid") or ""
    Keyword = request.query_params.get("keyword") or ""
    Source = request.query_params.get("source") or ""
    FilterKey = request.query_params.get("filter") or ""
    Params = json.loads(request.query_params.get("params")) if request.query_params.get("params") else {}

    return templates.TemplateResponse(
        "discovery/recommend.html",
        {
            "request": request,
            "Type": Type,
            "SubType": SubType,
            "Title": Title,
            "CurrentPage": CurrentPage,
            "Week": Week,
            "TmdbId": TmdbId,
            "PersonId": PersonId,
            "SubTitle": SubTitle,
            "Keyword": Keyword,
            "Source": Source,
            "Filter": FilterKey,
            "FilterConf": ModuleConf.DISCOVER_FILTER_CONF.get(FilterKey) if FilterKey else {},
            "Params": Params,
            "current_user": current_user
        }
    )


# 豆瓣电影
@app.get("/douban_movie", response_model=None)
async def douban_movie(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    豆瓣电影页面
    """
    return templates.TemplateResponse(
        "discovery/recommend.html",
        {
            "request": request,
            "Type": "DOUBANTAG",
            "SubType": "MOV",
            "Title": "豆瓣电影",
            "Filter": "douban_movie",
            "FilterConf": ModuleConf.DISCOVER_FILTER_CONF.get('douban_movie'),
            "current_user": current_user
        }
    )


# 豆瓣电视剧
@app.get("/douban_tv", response_model=None)
async def douban_tv(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    豆瓣电视剧页面
    """
    return templates.TemplateResponse(
        "discovery/recommend.html",
        {
            "request": request,
            "Type": "DOUBANTAG",
            "SubType": "TV",
            "Title": "豆瓣剧集",
            "Filter": "douban_tv",
            "FilterConf": ModuleConf.DISCOVER_FILTER_CONF.get('douban_tv'),
            "current_user": current_user
        }
    )


# TMDB电影
@app.get("/tmdb_movie", response_model=None)
async def tmdb_movie(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    TMDB电影页面
    """
    return templates.TemplateResponse(
        "discovery/recommend.html",
        {
            "request": request,
            "Type": "DISCOVER",
            "SubType": "MOV",
            "Title": "TMDB电影",
            "Filter": "tmdb_movie",
            "FilterConf": ModuleConf.DISCOVER_FILTER_CONF.get('tmdb_movie'),
            "current_user": current_user
        }
    )


# TMDB电视剧
@app.get("/tmdb_tv", response_model=None)
async def tmdb_tv(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    TMDB电视剧页面
    """
    return templates.TemplateResponse(
        "discovery/recommend.html",
        {
            "request": request,
            "Type": "DISCOVER",
            "SubType": "TV",
            "Title": "TMDB剧集",
            "Filter": "tmdb_tv",
            "FilterConf": ModuleConf.DISCOVER_FILTER_CONF.get('tmdb_tv'),
            "current_user": current_user
        }
    )


# Bangumi每日放送
@app.get("/bangumi", response_model=None)
async def bangumi(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    Bangumi每日放送页面
    """
    return templates.TemplateResponse(
        "discovery/ranking.html",
        {
            "request": request,
            "DiscoveryType": "BANGUMI",
            "current_user": current_user
        }
    )


# 媒体详情页面
@app.get("/media_detail", response_model=None)
async def media_detail(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    媒体详情页面
    """
    TmdbId = request.query_params.get("id")
    Type = request.query_params.get("type")

    return templates.TemplateResponse(
        "discovery/mediainfo.html",
        {
            "request": request,
            "TmdbId": TmdbId,
            "Type": Type,
            "current_user": current_user
        }
    )


# 演职人员页面
@app.get("/discovery_person", response_model=None)
async def discovery_person(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    演职人员页面
    """
    TmdbId = request.query_params.get("tmdbid")
    Title = request.query_params.get("title")
    SubTitle = request.query_params.get("subtitle")
    Type = request.query_params.get("type")
    Keyword = request.query_params.get("keyword")

    return templates.TemplateResponse(
        "discovery/person.html",
        {
            "request": request,
            "TmdbId": TmdbId,
            "Title": Title,
            "SubTitle": SubTitle,
            "Type": Type,
            "Keyword": Keyword,
            "current_user": current_user
        }
    )


# TMDB缓存页面
@app.get("/tmdbcache", response_model=None)
async def tmdbcache(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    TMDB缓存页面
    """
    page_num = request.query_params.get("pagenum")
    if not page_num:
        page_num = 30
    search_str = request.query_params.get("s")
    if not search_str:
        search_str = ""
    current_page = request.query_params.get("page")
    if not current_page:
        current_page = 1
    else:
        current_page = int(current_page)

    total_count, tmdb_caches = MetaHelper().dump_meta_data(search_str, current_page, page_num)
    total_page = floor(total_count / page_num) + 1
    page_range = WebUtils.get_page_range(current_page=current_page, total_page=total_page)

    return templates.TemplateResponse(
        "rename/tmdbcache.html",
        {
            "request": request,
            "TmdbCaches": tmdb_caches,
            "Search": search_str,
            "CurrentPage": current_page,
            "TotalCount": total_count,
            "TotalPage": total_page,
            "PageRange": page_range,
            "PageNum": page_num,
            "current_user": current_user
        }
    )


# 自定义识别词设置页面
@app.get("/customwords", response_model=None)
async def customwords(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    自定义识别词设置页面
    """
    groups = WebAction().get_customwords().get("result")

    return templates.TemplateResponse(
        "setting/customwords.html",
        {
            "request": request,
            "Groups": groups,
            "GroupsCount": len(groups),
            "current_user": current_user
        }
    )


# 目录同步页面
@app.get("/directorysync", response_model=None)
async def directorysync(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    目录同步页面
    """
    RmtModeDict = WebAction().get_rmt_modes()
    SyncPaths = Sync().get_sync_path_conf()

    return templates.TemplateResponse(
        "setting/directorysync.html",
        {
            "request": request,
            "SyncPaths": SyncPaths,
            "SyncCount": len(SyncPaths),
            "RmtModeDict": RmtModeDict,
            "current_user": current_user
        }
    )


# 系统设置页面
@app.get("/system", response_model=None)
async def system(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    系统设置页面
    """
    SystemConfig = Config().get_config('system') or {}
    CurrentVersion = WebUtils.get_current_version()
    RestartFlag = SystemConfig.get("restart_flag") or ""
    return templates.TemplateResponse(
        "setting/system.html",
        {
            "request": request,
            "Config": Config().get_config(),
            "CurrentVersion": CurrentVersion,
            "RestartFlag": RestartFlag,
            "IndexerStatistics": WebAction().get_indexer_statistics().get("result"),
            "current_user": current_user
        }
    )


# 基础设置页面
@app.get("/basic", response_model=None)
async def basic(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    基础设置页面
    """
    proxy = Config().get_config('app').get("proxies", {}).get("http")
    if proxy:
        proxy = proxy.replace("http://", "")
    RmtModeDict = WebAction().get_rmt_modes()
    CustomScriptCfg = SystemConfig().get(SystemConfigKey.CustomScript)
    ScraperConf = SystemConfig().get(SystemConfigKey.UserScraperConf) or {}
    return templates.TemplateResponse(
        "setting/basic.html",
        {
            "request": request,
            "Config": Config().get_config(),
            "Proxy": proxy,
            "RmtModeDict": RmtModeDict,
            "CustomScriptCfg": CustomScriptCfg,
            "CurrentUser": current_user,
            "ScraperNfo": ScraperConf.get("scraper_nfo") or {},
            "ScraperPic": ScraperConf.get("scraper_pic") or {},
            "MediaServerConf": ModuleConf.MEDIASERVER_CONF,
            "TmdbDomains": TMDB_API_DOMAINS,
            "current_user": current_user
        }
    )


# 实验室页面
@app.get("/laboratory", response_model=None)
async def laboratory(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    实验室页面
    """
    return templates.TemplateResponse(
        "setting/laboratory.html",
        {
            "request": request,
            "Config": Config().get_config(),
            "current_user": current_user
        }
    )


# 进度页面
@app.get("/progress", response_model=None)
async def progress(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    进度页面
    """
    return templates.TemplateResponse(
        "discovery/progress.html",
        {
            "request": request,
            "current_user": current_user
        }
    )


# 流媒体页面
@app.get("/stream", response_model=None)
async def stream(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    流媒体页面
    """
    return templates.TemplateResponse(
        "discovery/stream.html",
        {
            "request": request,
            "current_user": current_user
        }
    )


# 字幕页面
@app.get("/subtitle", response_model=None)
async def subtitle(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    字幕页面
    """
    SubtitleSites = SystemConfig().get(SystemConfigKey.UserSubtitleSites) or []
    return templates.TemplateResponse(
        "discovery/subtitle.html",
        {
            "request": request,
            "SubtitleSites": SubtitleSites,
            "current_user": current_user
        }
    )


# 历史记录页面
@app.get("/history", response_model=None)
async def history(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    历史记录页面
    """
    pagenum = request.query_params.get("pagenum")
    keyword = request.query_params.get("s") or ""
    current_page = request.query_params.get("page")
    Result = WebAction().get_transfer_history({"keyword": keyword, "page": current_page, "pagenum": pagenum})
    PageRange = WebUtils.get_page_range(current_page=Result.get("currentPage"),
                                        total_page=Result.get("totalPage"))

    return templates.TemplateResponse(
        "rename/history.html",
        {
            "request": request,
            "TotalCount": Result.get("total"),
            "Count": len(Result.get("result")),
            "Historys": Result.get("result"),
            "Search": keyword,
            "CurrentPage": Result.get("currentPage"),
            "TotalPage": Result.get("totalPage"),
            "PageRange": PageRange,
            "PageNum": Result.get("currentPage"),
            "current_user": current_user
        }
    )

# 日历接口
@app.get("/ical")
async def ical(request: Request, token: str = ""):
    """
    日历接口
    """
    if not token:
        return Response(content="Invalid token", status_code=403)

    # 获取用户
    user_info = User().get_user_by_apikey(token)
    if not user_info:
        return Response(content="Invalid token", status_code=403)

    # 查询订阅日历
    res_list = []
    # 电视剧订阅
    res_list.extend(WebAction().get_rss_history({"type": "TV"}).get("result"))
    # 电影订阅
    res_list.extend(WebAction().get_rss_history({"type": "MOV"}).get("result"))

    # 生成日历
    calendar_str = WebUtils.generate_ical_str(res_list)

    # 返回日历
    return Response(
        content=calendar_str,
        media_type="text/calendar",
        headers={"Content-Disposition": "attachment; filename=nas-tools.ics"}
    )


# 站点维护页面
@app.get("/site", response_model=None)
async def site(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    站点维护页面
    """
    CfgSites = Sites().get_sites()
    RuleGroups = {str(group["id"]): group["name"] for group in Filter().get_rule_groups()}
    DownloadSettings = {did: attr["name"] for did, attr in Downloader().get_download_setting().items()}
    CookieCloudCfg = SystemConfig().get(SystemConfigKey.CookieCloud)
    CookieUserInfoCfg = SystemConfig().get(SystemConfigKey.CookieUserInfo)

    return templates.TemplateResponse(
        "site/site.html",
        {
            "request": request,
            "Sites": CfgSites,
            "RuleGroups": RuleGroups,
            "DownloadSettings": DownloadSettings,
            "ChromeOk": True,
            "CookieCloudCfg": CookieCloudCfg,
            "CookieUserInfoCfg": CookieUserInfoCfg,
            "current_user": current_user
        }
    )


# 唤起App中转页面
@app.get("/open", response_model=None)
async def open_app(request: Request):
    """
    唤起App中转页面
    """
    return templates.TemplateResponse(
        "openapp.html",
        {
            "request": request
        }
    )


# 退出登录
@app.get("/logout", response_model=None)
async def logout(request: Request):
    """
    退出登录
    """
    # 创建响应
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

    # 清除会话
    response.delete_cookie(key="session")

    return response





# 媒体库页面
@app.get("/library", response_model=None)
async def library(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    媒体库页面
    """
    return templates.TemplateResponse(
        "setting/library.html",
        {
            "request": request,
            "Config": Config().get_config(),
            "MediaServerConf": ModuleConf.MEDIASERVER_CONF,
            "current_user": current_user
        }
    )


# 过滤规则设置页面
@app.get("/filterrule", response_model=None)
async def filterrule(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    过滤规则设置页面
    """
    result = WebAction().get_filterrules()

    return templates.TemplateResponse(
        "setting/filterrule.html",
        {
            "request": request,
            "Count": len(result.get("ruleGroups")),
            "RuleGroups": result.get("ruleGroups"),
            "Init_RuleGroups": result.get("initRules"),
            "current_user": current_user
        }
    )


# 电影订阅页面
@app.get("/movie_rss", response_model=None)
async def movie_rss(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    电影订阅页面
    """
    RssItems = WebAction().get_movie_rss_list().get("result")
    RuleGroups = {str(group["id"]): group["name"] for group in Filter().get_rule_groups()}
    DownloadSettings = Downloader().get_download_setting()

    return templates.TemplateResponse(
        "rss/movie_rss.html",
        {
            "request": request,
            "Count": len(RssItems),
            "RuleGroups": RuleGroups,
            "DownloadSettings": DownloadSettings,
            "Items": RssItems,
            "Type": 'MOV',
            "TypeName": '电影',
            "current_user": current_user
        }
    )


# 电视剧订阅页面
@app.get("/tv_rss", response_model=None)
async def tv_rss(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    电视剧订阅页面
    """
    RssItems = WebAction().get_tv_rss_list().get("result")
    RuleGroups = {str(group["id"]): group["name"] for group in Filter().get_rule_groups()}
    DownloadSettings = Downloader().get_download_setting()

    return templates.TemplateResponse(
        "rss/movie_rss.html",
        {
            "request": request,
            "Count": len(RssItems),
            "RuleGroups": RuleGroups,
            "DownloadSettings": DownloadSettings,
            "Items": RssItems,
            "Type": 'TV',
            "TypeName": '电视剧',
            "current_user": current_user,
            "CurrentUser": current_user
        }
    )


# 订阅历史页面
@app.get("/rss_history", response_model=None)
async def rss_history(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    订阅历史页面
    """
    mtype = request.query_params.get("t")
    RssHistory = WebAction().get_rss_history({"type": mtype}).get("result")

    return templates.TemplateResponse(
        "rss/rss_history.html",
        {
            "request": request,
            "Count": len(RssHistory),
            "Items": RssHistory,
            "Type": mtype,
            "current_user": current_user,
            "CurrentUser": current_user
        }
    )


# 订阅日历页面
@app.get("/rss_calendar", response_model=None)
async def rss_calendar(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    订阅日历页面
    """
    Today = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d')
    # 电影订阅
    RssMovieItems = WebAction().get_movie_rss_items().get("result")
    # 电视剧订阅
    RssTvItems = WebAction().get_tv_rss_items().get("result")

    return templates.TemplateResponse(
        "rss/rss_calendar.html",
        {
            "request": request,
            "Today": Today,
            "RssMovieItems": RssMovieItems,
            "RssTvItems": RssTvItems,
            "current_user": current_user,
            "CurrentUser": current_user
        }
    )


# PT索引站点页面
@app.get("/ptindexer", response_model=None)
async def ptindexer(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    PT索引站点页面
    """
    indexers = Indexer().get_indexers(check=False)
    indexer_sites = SystemConfig().get(SystemConfigKey.UserIndexerSites)

    SearchTypes = {"title": '关键字', "en_name": '英文名', "douban_id": '豆瓣id', "imdb": 'imdb id'}

    # 站点配置
    check_sites = []
    private_indexers = []
    for indexer in indexers:
        if not indexer.get("public"):
            private_indexers.append(indexer)
            if indexer.get("id") in indexer_sites:
                check_sites.append(indexer.get("id"))

    DownloadSettings = {did: attr["name"] for did, attr in Downloader().get_download_setting().items()}
    SourceTypes = {"MOVIE": '电影', "TV": '剧集', "ANIME": '动漫'}

    return templates.TemplateResponse(
        "site/indexer.html",
        {
            "request": request,
            "Config": Config().get_config(),
            "IsPublic": 0,
            "Indexers": private_indexers,
            "DownloadSettings": DownloadSettings,
            "CheckSites": check_sites,
            "SourceTypes": SourceTypes,
            "SearchTypes": SearchTypes,
            "current_user": current_user,
            "CurrentUser": current_user
        }
    )


# 站点资源页面
@app.get("/sitelist", response_model=None)
async def sitelist(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    站点资源页面
    """
    IndexerSites = Indexer().get_indexers(check=False)

    return templates.TemplateResponse(
        "site/sitelist.html",
        {
            "request": request,
            "Sites": IndexerSites,
            "Count": len(IndexerSites),
            "current_user": current_user,
            "CurrentUser": current_user
        }
    )


# 禁止搜索引擎
@app.get("/robots.txt")
async def robots():
    """
    禁止搜索引擎
    """
    return Response(
        content="User-agent: *\nDisallow: /",
        media_type="text/plain"
    )


# 手工识别页面
@app.get("/unidentification", response_model=None)
async def unidentification(request: Request, current_user: User = Depends(get_current_user_required)):
    """
    手工识别页面
    """
    pagenum = request.query_params.get("pagenum")
    keyword = request.query_params.get("s") or ""
    current_page = request.query_params.get("page")
    Result = WebAction().get_unknown_list_by_page({"keyword": keyword, "page": current_page, "pagenum": pagenum})
    PageRange = WebUtils.get_page_range(current_page=Result.get("currentPage"),
                                        total_page=Result.get("totalPage"))

    return templates.TemplateResponse(
        "rename/unidentification.html",
        {
            "request": request,
            "TotalCount": Result.get("total"),
            "Count": len(Result.get("items")),
            "Items": Result.get("items"),
            "Search": keyword,
            "CurrentPage": Result.get("currentPage"),
            "TotalPage": Result.get("totalPage"),
            "PageRange": PageRange,
            "PageNum": Result.get("currentPage"),
            "current_user": current_user,
            "CurrentUser": current_user
        }
    )