"""
/do 的异步命令入口。

同步命令仍由 app/api/action.py 的 /do 处理；这里只登记已经有异步实现的命令，
避免异步路由里执行阻塞调用。新增命令时在 WebAsyncAction 的 _actions 中注册一个
async 方法即可，请求体与 /do 保持一致：{"cmd": ..., "data": {...}}。
"""

import re
import time
from typing import Annotated

from fastapi import APIRouter, Body, Depends

import log
from app.api.action import WebAction
from app.conf import ModuleConf
from app.core.cmd_handler import CommandHandler
from app.mediaserver import MediaServer
from app.middleware.security import CurrentUser, get_current_user
from app.sites import SitesDataStatisticsCenter, SitesManager
from app.utils import AsyncRequestUtils
from app.utils.commons import mask_sensitive
from app.utils.types import SearchType
from config import Config

# 异步命令路由
action_async_router = APIRouter(dependencies=[Depends(get_current_user)])


@action_async_router.post("/do_async")
async def do_async(content: Annotated[dict, Body(...)], current_user: CurrentUser):
    """
    异步命令入口
    """
    start_time = time.time()
    cmd = content.get("cmd")
    data = content.get("data") or {}
    # 请求体可能包含敏感信息，日志中统一脱敏
    log.debug("处理/do_async请求: cmd={%s}, data={%s}", cmd, mask_sensitive(data))
    try:
        return await WebAsyncAction(current_user).action(cmd, data)
    except Exception as e:
        log.exception(f"处理/do_async请求出错, cmd={cmd}")
        return {"code": -1, "msg": str(e)}
    finally:
        process_time = (time.time() - start_time) * 1000
        log.debug("处理/do_async请求完成: cmd={%s}, 耗时: %.2f ms", cmd, process_time)


class WebAsyncAction:
    """
    /do_async 的命令分发器，只承载异步实现
    """

    def __init__(self, current_user=None):
        self._current_user = current_user
        self._actions = {
            "get_activity_log": self.__get_activity_log,
            "test_mediaserver": self.__test_mediaserver,
            "test_site": self.__test_site,
            "net_test": self.__net_test,
            "pt_depiler_version": self.__pt_depiler_version,
            "refresh_pt_statistics": self.__refresh_pt_statistics,
        }

    async def action(self, cmd, data):
        """
        执行异步命令
        """
        func = self._actions.get(cmd)
        if not func:
            return {"code": -1, "msg": "无效请求！"}
        return await func(data)

    async def __get_activity_log(self, data):
        """
        首页播放记录
        """
        return {"code": 0, "activitys": await MediaServer().get_activity_log_async(30)}

    async def __test_mediaserver(self, data):
        """
        测试媒体服务器连通性
        """
        server_type = (data or {}).get("type")
        if not server_type or server_type not in ModuleConf.MEDIASERVER_CONF:
            return {"code": 1, "msg": "不支持的媒体服务器类型"}

        ret = await MediaServer().test_connection_async(server_type)
        return {"code": 0 if ret else 1}

    async def __test_site(self, data):
        """
        测试站点连通性
        """
        flag, msg, times = await SitesManager().test_connection_async((data or {}).get("id"))
        code = 0 if flag else -1
        return {"code": code, "msg": msg, "time": times}

    async def __net_test(self, data):
        """
        网络连通性测试
        """
        target = data
        if target == "image.tmdb.org":
            target = target + "/t/p/w500/wwemzKWzjKYJFfCeiB57q3r4Bcm.png"
        if target == "qyapi.weixin.qq.com":
            target = target + "/cgi-bin/message/send"
        target = "https://" + target
        start_time = time.perf_counter()
        if target.find("themoviedb") != -1 \
                or target.find("telegram") != -1 \
                or target.find("fanart") != -1 \
                or target.find("tmdb") != -1:
            res = await AsyncRequestUtils(proxies=Config().get_proxies(),
                                          timeout=5).get_res(target)
        else:
            res = await AsyncRequestUtils(timeout=5).get_res(target)
        seconds = int((time.perf_counter() - start_time) * 1000)
        return {"res": bool(res and res.ok), "time": f"{seconds} 毫秒"}

    async def __pt_depiler_version(self, data=None):
        """
        获取 PT Depiler 最新版本号（标签+提交号）
        """
        # 与同步命令共用进程级缓存
        cache = WebAction._pt_depiler_version_cache
        ttl = WebAction._PT_DEPILER_VERSION_TTL
        now = time.time()
        if now >= cache["expire"]:
            cache["version"] = await self.__fetch_pt_depiler_version_async()
            cache["expire"] = now + ttl

        if not cache["version"]:
            return {"code": -1, "msg": "fail to fetch PT Depiler release version "}
        return {"code": 0, "msg": "success", "data": {"version": cache["version"]}}

    @staticmethod
    async def __fetch_pt_depiler_version_async():
        """
        获取版本号+提交号
        """
        proxies = Config().get_proxies()
        api_headers = {"Accept": "application/vnd.github+json"}
        tag = None
        commit = None

        # 优先 GitHub API：releases/latest 取标签，commits/{tag} 取提交号
        res = await AsyncRequestUtils(headers=api_headers, proxies=proxies).get_res(
            "https://api.github.com/repos/pt-plugins/PT-depiler/releases/latest")
        if res is not None and res.status_code == 200:
            try:
                tag = str(res.json().get("tag_name") or "").strip() or None
            except Exception:
                tag = None

        if tag:
            res = await AsyncRequestUtils(headers=api_headers, proxies=proxies).get_res(
                f"https://api.github.com/repos/pt-plugins/PT-depiler/commits/{tag}")
            if res is not None and res.status_code == 200:
                try:
                    commit = str(res.json().get("sha") or "").strip() or None
                except Exception:
                    commit = None

        # API 被限流时，从 releases/latest 跳转后的标签页解析标签与提交号
        if not tag or not commit:
            res = await AsyncRequestUtils(proxies=proxies).get_res(
                "https://github.com/pt-plugins/PT-depiler/releases/latest")
            if res is not None and res.status_code == 200:
                if not tag:
                    matched = re.search(r"/releases/tag/([^/?#]+)", res.url)
                    tag = matched.group(1) if matched else None
                if tag and not commit:
                    matched = re.search(r"/commit/([0-9a-f]{7,40})", res.text)
                    commit = matched.group(1) if matched else None

        if not tag:
            return None
        return f"{tag}+{commit[:7]}" if commit else tag

    async def __refresh_pt_statistics(self, data):
        """
        刷新站点数据
        """
        if not self._current_user:
            return {"code": 1, "msg": "未登录"}

        site_name = (data or {}).get('site')
        if site_name:
            result = await SitesDataStatisticsCenter().refresh_site_data_now_async(specify_site=site_name)
            if not result:
                return {"code": 1, "msg": "刷新失败，请查看日志"}

            site_results = result.get("sites") or []
            if not site_results:
                return {"code": 1, "msg": result.get("msg") or "站点不存在或未启用站点统计"}

            failed = [item for item in site_results if not item.get("success")]
            if failed:
                return {
                    "code": 1,
                    "msg": "；".join(f"【{item['site']}】刷新失败：{item.get('msg') or '解析失败'}"
                                    for item in failed)
                }

            missing = [item for item in site_results if item.get("missing")]
            if missing:
                # 刷新成功但有字段未解析到，交给前端提示
                return {
                    "code": 0,
                    "msg": "刷新完成，但" + "；".join(
                        f"【{item['site']}】以下字段未解析到：{'、'.join(item['missing'])}"
                        for item in missing),
                    "missing": missing
                }

            return {"code": 0, "msg": "刷新完成", "result": site_results}

        # 全部站点刷新耗时较长，仍走后台任务
        CommandHandler().handle_message_job("/sta",
                                            in_from=SearchType.WEB,
                                            user_id=self._current_user.id,
                                            user_name=self._current_user.username)
        return {"code": 0, "msg": "已提交"}
