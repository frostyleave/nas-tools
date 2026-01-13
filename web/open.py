import json
import re
import tracemalloc
import xml.dom.minidom

from fastapi import APIRouter, Request, Response
from typing import Optional

from app.conf.moduleconf import ModuleConf
from app.helper.security_helper import SecurityHelper
from app.helper import ThreadHelper
from app.job_center import JobCenter
from app.media.meta.metainfo import MetaInfo
from app.mediaserver.media_server import MediaServer
from app.message import Message
from app.plugins.event_manager import EventManager
from app.subscribe import Subscribe
from app.utils.dom_utils import DomUtils
from app.utils.types import EventType, MediaServerType, MediaType, RssType, SearchType

import log

from web.action import WebAction
from web.backend.WXBizMsgCrypt3 import WXBizMsgCrypt
from web.backend.security import auth_required


# 开放接口路由
open_router = APIRouter()

def send_text_response(content: str, status_code: int = 200) -> Response:
    return Response(content=content, status_code=status_code, media_type="text/plain; charset=utf-8")

# 微信回调
@open_router.get("/wechat")
async def wechat(request: Request, appid: Optional[str] = None):

    # 当前在用的交互渠道
    interactive_clients = Message().get_interactive_client(SearchType.WX)
    if not interactive_clients:
        log.info("NAStool没有启用微信交互")
        return send_text_response(content="NAStool没有启用微信交互", status_code=200)

    if appid:
        assign_app = next(filter(lambda x: x.get('config', {}).get('agentid') == appid, interactive_clients), None)
        if not assign_app:
            return send_text_response(content=f"微信应用{appid}没有开启交互", status_code=200)
    else:
        assign_app = interactive_clients[0]

    conf = assign_app.get("config")
    sToken = conf.get("token")
    sEncodingAESKey = conf.get("encodingAESKey")
    sCorpID = conf.get("corpid")
    if not sToken or not sEncodingAESKey or not sCorpID:
        log.info("配置错误")
        return send_text_response(content="配置错误", status_code=200)

    wxcpt = WXBizMsgCrypt(sToken, sEncodingAESKey, sCorpID)
    query = request.query_params
    sVerifyMsgSig = query.get("msg_signature")
    sVerifyTimeStamp = query.get("timestamp")
    sVerifyNonce = query.get("nonce")

    if not sVerifyMsgSig and not sVerifyTimeStamp and not sVerifyNonce:
        return send_text_response(content="NAStool微信交互服务正常！<br>微信回调配置步聚: <br>1、在微信企业应用接收消息设置页面生成Token和EncodingAESKey并填入设置->消息通知->微信对应项，打开微信交互开关。<br>2、保存并重启本工具，保存并重启本工具，保存并重启本工具。<br>3、在微信企业应用接收消息设置页面输入此地址: http(s)://IP:PORT/wechat", status_code=200)

    sVerifyEchoStr = query.get("echostr")
    log.info(f"收到微信验证请求: echostr= {sVerifyEchoStr}")
    ret, sEchoStr = wxcpt.VerifyURL(sVerifyMsgSig, sVerifyTimeStamp, sVerifyNonce, sVerifyEchoStr)
    if ret != 0:
        log.error(f"微信请求验证失败 VerifyURL ret: {str(ret)}")

    return send_text_response(content=sEchoStr, status_code=200)


@open_router.post("/wechat")
@auth_required
async def wechat_post(request: Request):

    try:

        req_bytes = await request.body()
        req_xml = req_bytes.decode("utf-8")
        log.debug(f"收到微信请求: {req_xml}")

        # 已启用的交互渠道
        interactive_clients = Message().get_interactive_client(SearchType.WX)
        if not interactive_clients:
            log.info("NAStool没有启用微信交互")
            return send_text_response(content="", status_code=200)
        
        match = re.search(r"<AgentID><!\[CDATA\[(.*?)\]\]></AgentID>", req_xml)
        appid = match.group(1) if match else None
        if not appid:
            log.warn("消息中没有包含AgentID")
            return send_text_response(content="", status_code=200)

        agent_client = next(filter(lambda x: x.get('config', {}).get('agentid') == appid, interactive_clients), None)
        if not agent_client:
            log.warn(f"微信应用{appid}没有开启交互")
            return send_text_response(content="", status_code=200)
        
        conf = agent_client.get("config")
        sToken = conf.get("token")
        sEncodingAESKey = conf.get("encodingAESKey")
        sCorpID = conf.get("corpid")
        if not sToken or not sEncodingAESKey or not sCorpID:
            log.warn("配置错误")
            return send_text_response(content="", status_code=200)

        wxcpt = WXBizMsgCrypt(sToken, sEncodingAESKey, sCorpID)
        query = request.query_params
        sVerifyMsgSig = query.get("msg_signature")
        sVerifyTimeStamp = query.get("timestamp")
        sVerifyNonce = query.get("nonce")

        ret, sMsg = wxcpt.DecryptMsg(req_bytes, sVerifyMsgSig, sVerifyTimeStamp, sVerifyNonce)
        if ret != 0:
            log.error(f"解密微信消息失败 DecryptMsg ret = {str(ret)}")
            return Response(content="ok", status_code=200)

        # 解析XML
        dom_tree = xml.dom.minidom.parseString(sMsg.decode("UTF-8"))
        root_node = dom_tree.documentElement

        msg_type = DomUtils.tag_value(root_node, "MsgType")
        event = DomUtils.tag_value(root_node, "Event")
        user_id = DomUtils.tag_value(root_node, "FromUserName")

        if not msg_type or not user_id:
            log.info("收到微信心跳报文...")
            return Response(content="ok", status_code=200)

        content = ""
        if msg_type == "event" and event == "click":
            if conf.get("adminUser") and not any(
                user_id == admin_user for admin_user in str(conf.get("adminUser")).split(";")
            ):
                Message().send_channel_msg(channel=SearchType.WX, title="用户无权限执行菜单命令", user_id=user_id)
                return Response(content="", status_code=200)

            event_key = DomUtils.tag_value(root_node, "EventKey")
            if event_key:
                log.info("点击菜单: %s", event_key)
                keys = event_key.split('#')
                if len(keys) > 2:
                    content = ModuleConf.WECHAT_MENU.get(keys[2])

        elif msg_type == "text":
            content = DomUtils.tag_value(root_node, "Content", default="")

        if content:
            log.info(f"收到微信消息: userid={user_id}, text={content}")
            WebAction().handle_message_job(
                msg=content,
                in_from=SearchType.WX,
                user_id=user_id,
                user_name=user_id,
                client_id = str(agent_client.get("id"))
            )

        return Response(content=content, status_code=200)

    except Exception as err:
        log.exception('微信消息处理发生错误: ')
        return Response(content="ok", status_code=200)
    
# 微信发送消息
@open_router.post("/sendwechat")
@auth_required
async def sendwechat(request: Request, appid: Optional[str] = None):
    
    if not SecurityHelper().check_mediaserver_ip(request.client.host):
        log.warn(f"非法IP地址的媒体服务器消息通知: {request.client.host}")
        return Response(content="不允许的IP地址请求", status_code=403)

    interactive_clients = Message().get_interactive_client(SearchType.WX)
    if not interactive_clients:
        return Response(content="NAStool没有启用微信交互", status_code=200)

    if appid:
        assign_app = next(filter(lambda x: x.get('config', {}).get('agentid') == appid, interactive_clients), None)
        if not assign_app:
            return send_text_response(content=f"微信应用{appid}没有开启交互", status_code=200)
    else:
        assign_app = interactive_clients[0]

    req_json = await request.json()
    title = req_json.get("title")
    if not title:
        return Response(content="请设置消息标题", status_code=200)

    message = req_json.get("message")
    if not message:
        return Response(content="请填写消息内容", status_code=200)

    Message().send_custom_message(
        clients=[str(assign_app.get("id"))],
        title=title,
        text=message,
        image=req_json.get("image")
    )
    return Response(content="ok", status_code=200)


# Plex Webhook
@open_router.post("/plex")
@auth_required
async def plex_webhook(request: Request):
    if not SecurityHelper().check_mediaserver_ip(request.client.host):
        log.warn(f"非法IP地址的媒体服务器消息通知: {request.client.host}")
        return Response(content="不允许的IP地址请求", status_code=403)

    form = await request.form()
    request_json = json.loads(form.get("payload", "{}"))
    log.debug("收到Plex Webhook报文: %s", request_json)

    event_match = request_json.get("event") in ["media.play", "media.stop", "library.new"]
    type_match = request_json.get("Metadata", {}).get("type") in ["movie", "episode", "show"]
    is_live = request_json.get("Metadata", {}).get("live") == "1"

    if event_match and type_match and not is_live:
        ThreadHelper().start_thread(MediaServer().webhook_message_handler,
                                    (request_json, MediaServerType.PLEX))
        EventManager().send_event(EventType.PlexWebhook, request_json)
    return Response(content="Ok", status_code=200)


# Jellyfin Webhook
@open_router.post("/jellyfin")
@auth_required
async def jellyfin_webhook(request: Request):
    if not SecurityHelper().check_mediaserver_ip(request.client.host):
        log.warn(f"非法IP地址的媒体服务器消息通知: {request.client.host}")
        return Response(content="不允许的IP地址请求", status_code=403)

    request_json = await request.json()
    log.debug("收到Jellyfin Webhook报文: %s", request_json)

    ThreadHelper().start_thread(MediaServer().webhook_message_handler,
                                (request_json, MediaServerType.JELLYFIN))
    EventManager().send_event(EventType.JellyfinWebhook, request_json)
    return Response(content="Ok", status_code=200)


# Emby Webhook
@open_router.api_route("/emby", methods=["GET", "POST"])
@auth_required
async def emby_webhook(request: Request):
    if not SecurityHelper().check_mediaserver_ip(request.client.host):
        log.warn(f"非法IP地址的媒体服务器消息通知: {request.client.host}")
        return Response(content="不允许的IP地址请求", status_code=403)

    if request.method == "POST":
        form = await request.form()
        log.debug("Emby Webhook data: %s", form.get("data", {}))
        request_json = json.loads(form.get("data", "{}"))
    else:
        query = dict(request.query_params)
        log.debug("Emby Webhook data: %s", query)
        request_json = query

    log.debug("收到Emby Webhook报文: %s", request_json)
    ThreadHelper().start_thread(MediaServer().webhook_message_handler,
                                (request_json, MediaServerType.EMBY))
    EventManager().send_event(EventType.EmbyWebhook, request_json)
    return Response(content="Ok", status_code=200)


# Telegram消息响应
@open_router.post("/telegram")
@auth_required
async def telegram(request: Request):
    interactive_clients = Message().get_interactive_client(SearchType.TG)
    if not interactive_clients:
        return Response(content="NAStool未启用Telegram交互", status_code=200)
    
    interactive_client = interactive_clients[0]

    msg_json = await request.json()
    if not SecurityHelper().check_telegram_ip(request.client.host):
        log.error("收到来自 %s 的非法Telegram消息: %s", request.client.host, msg_json)
        return Response(content="不允许的IP地址请求", status_code=403)

    if msg_json:
        message = msg_json.get("message", {})
        text = message.get("text")
        user_id = message.get("from", {}).get("id")
        user_name = message.get("from", {}).get("username")

        if text:
            log.info(f"收到Telegram消息: userid={user_id}, username={user_name}, text={text}")
            if text.startswith("/"):
                if str(user_id) not in interactive_client.get("client").get_admin():
                    Message().send_channel_msg(channel=SearchType.TG,
                                               title="只有管理员才有权限执行此命令",
                                               user_id=user_id)
                    return Response(content="只有管理员才有权限执行此命令", status_code=200)
            else:
                if str(user_id) not in interactive_client.get("client").get_users():
                    Message().send_channel_msg(channel=SearchType.TG,
                                               title="你不在用户白名单中，无法使用此机器人",
                                               user_id=user_id)
                    return Response(content="你不在用户白名单中，无法使用此机器人", status_code=200)

            WebAction().handle_message_job(msg=text,
                                           in_from=SearchType.TG,
                                           user_id=user_id,
                                           user_name=user_name)
    return Response(content="Ok", status_code=200)


# Synology Chat消息响应
@open_router.post("/synology")
@auth_required
async def synology(request: Request):
    interactive_clients = Message().get_interactive_client(SearchType.SYNOLOGY)
    if not interactive_clients:
        return Response(content="NAStool未启用Synology Chat交互", status_code=200)
    
    interactive_client = interactive_clients[0]

    form = await request.form()
    if not SecurityHelper().check_synology_ip(request.client.host):
        log.error("收到来自 %s 的非法Synology Chat消息: %s", request.client.host, form)
        return Response(content="不允许的IP地址请求", status_code=403)

    if form:
        token = form.get("token")
        if not interactive_client.get("client").check_token(token):
            log.error("收到来自 %s 的非法Synology Chat消息: token校验不通过！", request.client.host)
            return Response(content="token校验不通过", status_code=403)

        text = form.get("text")
        user_id = int(form.get("user_id"))
        user_name = form.get("username")

        if text:
            log.info(f"收到Synology Chat消息: userid={user_id}, username={user_name}, text={text}")
            WebAction().handle_message_job(msg=text,
                                           in_from=SearchType.SYNOLOGY,
                                           user_id=user_id,
                                           user_name=user_name)
    return Response(content="Ok", status_code=200)


# Slack消息响应
@open_router.post("/slack")
@auth_required
async def slack(request: Request):
    if not SecurityHelper().check_slack_ip(request.client.host):
        log.warn(f"非法IP地址的Slack消息通知: {request.client.host}")
        return Response(content="不允许的IP地址请求", status_code=403)

    interactive_clients = Message().get_interactive_client(SearchType.SLACK)
    if not interactive_clients:
        return Response(content="NAStool未启用Slack交互", status_code=200)
    
    msg_json = await request.json()
    if msg_json:
        if msg_json.get("type") == "message":
            userid = msg_json.get("user")
            text = msg_json.get("text")
            username = msg_json.get("user")
        elif msg_json.get("type") == "block_actions":
            userid = msg_json.get("user", {}).get("id")
            text = msg_json.get("actions")[0].get("value")
            username = msg_json.get("user", {}).get("name")
        elif msg_json.get("type") == "event_callback":
            userid = msg_json.get("event", {}).get("user")
            text = re.sub(r"<@[0-9A-Z]+>", "", msg_json.get("event", {}).get("text"), flags=re.IGNORECASE).strip()
            username = ""
        elif msg_json.get("type") == "shortcut":
            userid = msg_json.get("user", {}).get("id")
            text = msg_json.get("callback_id")
            username = msg_json.get("user", {}).get("username")
        else:
            return Response(content="Error", status_code=400)

        log.info(f"收到Slack消息: userid={userid}, username={username}, text={text}")
        WebAction().handle_message_job(msg=text,
                                       in_from=SearchType.SLACK,
                                       user_id=userid,
                                       user_name=username)
    return Response(content="Ok", status_code=200)


# Jellyseerr Overseerr订阅接口
@open_router.post("/subscribe")
@auth_required
async def subscribe(request: Request):
    req_json = await request.json()
    if not req_json:
        return Response(content="非法请求！", status_code=400)

    notification_type = req_json.get("notification_type")
    if notification_type not in ["MEDIA_APPROVED", "MEDIA_AUTO_APPROVED"]:
        return Response(content="ok", status_code=200)

    subject = req_json.get("subject")
    media_type = MediaType.MOVIE if req_json.get("media", {}).get("media_type") == "movie" else MediaType.TV
    tmdbId = req_json.get("media", {}).get("tmdbId")
    if not media_type or not tmdbId or not subject:
        return Response(content="请求参数不正确！", status_code=500)

    code, msg = 0, "ok"
    meta_info = MetaInfo(title=subject, mtype=media_type)
    user_name = req_json.get("request", {}).get("requestedBy_username")

    if media_type == MediaType.MOVIE:
        code, msg, _ = Subscribe().add_rss_subscribe(
            mtype=media_type,
            name=meta_info.get_name(),
            year=meta_info.year,
            channel=RssType.Auto,
            mediaid=tmdbId,
            in_from=SearchType.API,
            user_name=user_name
        )
    else:
        seasons = []
        for extra in req_json.get("extra", []):
            if extra.get("name") == "Requested Seasons":
                seasons = [int(str(sea).strip()) for sea in extra.get("value").split(", ") if str(sea).isdigit()]
                break
        for season in seasons:
            code, msg, _ = Subscribe().add_rss_subscribe(
                mtype=media_type,
                name=meta_info.get_name(),
                year=meta_info.year,
                channel=RssType.Auto,
                mediaid=tmdbId,
                season=season,
                in_from=SearchType.API,
                user_name=user_name
            )

    if code == 0:
        return Response(content="ok", status_code=200)
    else:
        return Response(content=msg, status_code=500)
    

@open_router.get("/memory")
async def memory_snapshot():
    
    global snapshot1
    snapshot1 = tracemalloc.take_snapshot()
    
    print("--- 内存快照1 已拍摄 ---")
    return {"message": "Memory snapshot 1 taken."}

@open_router.get("/mem_compare")
async def memory_snapshot():
    """
    拍下“快照2”, 并与“快照1”对比, 将结果打印到 Docker 日志。
    """
    global snapshot1
    if not snapshot1:
        return {"error": "Snapshot 1 not taken. Call /debug/mem_snapshot first."}

    print("--- 正在拍摄快照2并对比 ---")
    snapshot2 = tracemalloc.take_snapshot()
    
    # 核心：对比两个快照，按代码行分组
    stats = snapshot2.compare_to(snapshot1, 'traceback')

    print("--- 内存泄漏 TOP 10 (按代码行) ---")
    # 3. (关键) 将结果打印到日志！
    for i, stat in enumerate(stats[:10], 1):
        print(f"#{i}: {stat.size_diff / 1024:.1f} KiB new memory ({stat.count_diff} new objects)")
        # 打印完整的调用链
        for line in stat.traceback.format():
            print(f"  {line}")
        print("-" * 20) # 添加分隔符
        

    return {"message": "Memory comparison complete. Check Docker logs."}

@open_router.get("/jobs")
def get_jobs():
    """
    获取所有已注册的定时任务
    """
    return JobCenter().get_jobs()