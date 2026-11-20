import base64
from typing import ClassVar
from urllib.parse import urljoin

import aiohttp

import log as logger
from app.sites.siteuserinfo._base import (
    SITE_BASE_ORDER,
    _is_image_content,
    _ISiteUserInfo,
    resolve_proxy_url,
)
from app.utils import JsonUtils, StringUtils
from app.utils.types import SiteSchema
from config import Config


class YemaUserInfo(_ISiteUserInfo):
    """
    YemaPT 用户信息解析

    站点是 SPA，首页不包含用户数据，所有统计信息都从站点接口获取
    """
    schema = SiteSchema.YemaPT
    order = SITE_BASE_ORDER + 10

    # 用户详情（上传量、下载量、等级、注册时间等）
    _self_detail_api = "api/consumer/fetchSelfDetail"
    # 做种汇总（做种数、做种总大小）
    _seed_info_api = "api/userTorrent/fetchSeedTorrentInfo"
    # 未读消息数量
    _unread_count_api = "api/message/fetchUnreadCounts"
    # 消息列表
    _msg_list_api = "api/message/fetchMsgList"
    # 开放 API 的用户基本信息（API Auth Key 鉴权）
    _openapi_basic_info_api = "openApi/user/fetchBasicInfo.json"

    # 开放 API 的用户信息接口只支持 POST，传空对象占位（值为 None 的字段会被请求层过滤）
    _post_empty_params: ClassVar[dict] = {"_": None}

    # 用户等级名称
    _level_names: ClassVar[dict] = {
        0: "乱民",
        1: "小卒",
        2: "教谕",
        3: "登仕郎",
        4: "修职郎",
        5: "文林郎",
        6: "忠武校尉",
        7: "承信将军",
        8: "武毅将军",
        9: "武节将军",
        10: "显威将军",
        11: "宣武将军"
    }

    # 站点没有 favicon.ico，使用前端登录页展示的站点图标
    _favicon_url = "https://static-c.yemapt.org/icons/icons8-mustang-96.png"

    # 接口均为 POST JSON，接口不校验多余字段，用分页参数占位触发 POST
    _json_headers: ClassVar[dict] = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json"
    }
    _page_params: ClassVar[dict] = {
        "pageParam": {"current": 1, "pageSize": 1}
    }
    _msg_list_params: ClassVar[dict] = {
        "pageParam": {"current": 1, "pageSize": 100}
    }

    def __init__(self, site_name, url, site_cookie, index_html, apikey=None, session=None, ua=None, proxy=None):
        super().__init__(site_name, url, site_cookie, index_html, apikey, session, ua, proxy)

        # 站点未单独配置 UA 时使用全局 UA，基类会把它写入请求头
        self._ua = ua or Config().get_ua()

        # 同时配置 API Auth Key 和 Cookie 时优先使用 API Auth Key
        self._apikey = apikey or ""
        self._use_apikey = bool(self._apikey)
        self._has_cookie = bool(site_cookie)

        # 用户信息优先走开放 API；做种和未读消息没有开放接口，只能使用 Cookie
        self._user_basic_page = self._openapi_basic_info_api if self._use_apikey else self._self_detail_api
        self._user_basic_headers = self._build_api_headers()
        self._torrent_seeding_page = self._seed_info_api if self._has_cookie else None
        self._torrent_seeding_params = dict(self._page_params)
        self._torrent_seeding_headers = dict(self._json_headers)

    @classmethod
    def match(cls, html_text):
        # 首页没有可识别的内容，只能通过站点配置的解析器类型构造
        return False

    async def _parse_favicon(self, html_text):
        """
        首页没有声明图标，也没有 favicon.ico，直接使用前端站点图标
        """
        if self._session is None:
            return
        kwargs = {
            "headers": {"User-Agent": self._ua or Config().get_ua()},
            "timeout": aiohttp.ClientTimeout(total=15)
        }
        proxy_url = resolve_proxy_url(self._proxy)
        if proxy_url:
            kwargs["proxy"] = proxy_url
        try:
            async with self._session.get(self._favicon_url, **kwargs) as res:
                content = await res.read()
            if content and _is_image_content(content):
                self.site_favicon = base64.b64encode(content).decode()
        except (aiohttp.ClientError, TimeoutError) as e:
            logger.warn(f"【Sites】{self.site_name} 获取站点图标失败: {e!s}")

    def _parse_logged_in(self, html_text):
        if self._use_apikey or self._has_cookie:
            return True
        self.err_msg = "未配置站点Cookie或API Auth Key"
        logger.warn(f"【Sites】{self.site_name} 未配置Cookie或API Auth Key，跳过后续操作")
        return False

    def _parse_site_page(self, html_text):
        # 接口解析器不需要额外的页面地址
        self._user_detail_page = ""
        self._user_traffic_page = ""
        self._user_mail_unread_page = None
        self._sys_mail_unread_page = None

    async def visit_base_info(self):
        """
        访问用户详情接口
        """
        # 开放 API 的用户信息接口只支持 POST
        params = dict(self._post_empty_params) if self._use_apikey else None
        return await self._get_page_content(
            url=urljoin(self._base_url, self._user_basic_page),
            params=params,
            headers=self._user_basic_headers
        )

    async def _parse_user_base_info(self, response_text: str):
        response_text, _ = await self.visit_base_info()
        detail = self._load_json(response_text)
        if not detail.get("success"):
            self.err_msg = self._error_message(detail)
            logger.warn(f"【Sites】{self.site_name} 获取用户信息失败: {self.err_msg}")
            return

        user_info = detail.get("data")
        if not isinstance(user_info, dict):
            user_info = {}
        self.userid = user_info.get("id")
        self.username = user_info.get("name")
        self.join_at = StringUtils.unify_datetime_str(user_info.get("registerTime") or "")

        level = user_info.get("level")
        if level is not None:
            self.user_level = self._level_names.get(level) or f"Level {level}"

        # 开放 API 与站内接口都以实际上传/下载量为准，保证两种鉴权方式口径一致
        upload = user_info.get("uploadSize")
        download = user_info.get("downloadSize")
        if upload is None:
            upload = user_info.get("promotionUploadSize")
        if download is None:
            download = user_info.get("promotionDownloadSize")
        self.upload = self._to_int(upload)
        self.download = self._to_int(download)
        self.ratio = round(self.upload / self.download, 3) if self.download > 0 else 0
        self.bonus = user_info.get("bonus") or 0

        # 未读消息没有开放接口，仅在配置了 Cookie 时读取
        if self._has_cookie:
            await self._parse_unread_count()

    async def _parse_unread_count(self):
        """
        从接口读取未读消息数
        """
        if not self._has_cookie:
            return

        response_text, _ = await self._get_page_content(
            url=urljoin(self._base_url, self._unread_count_api),
            params=dict(self._page_params),
            headers=self._json_headers
        )
        result = self._load_json(response_text)
        counts = result.get("data")
        if not isinstance(counts, dict):
            counts = {}
        self.message_unread = self._to_int(counts.get("person")) + self._to_int(counts.get("system"))

    async def _pase_unread_msgs(self):
        """
        解析未读消息，消息接口只支持 POST，不能复用基类的 GET 流程
        """
        if not self._has_cookie or self.message_unread <= 0:
            return

        response_text, _ = await self._get_page_content(
            url=urljoin(self._base_url, self._msg_list_api),
            params=dict(self._msg_list_params),
            headers=self._json_headers
        )
        result = self._load_json(response_text)
        messages = result.get("data")
        if not isinstance(messages, list):
            return

        for message in messages:
            if str(message.get("status") or "").upper() == "READ":
                continue
            title = message.get("title") or ""
            date = message.get("receiveGmtCreate") or ""
            self.message_unread_contents.append((title, date, title))

    def _parse_user_traffic_info(self, html_text):
        # 流量信息已在用户详情接口中解析
        pass

    def _parse_user_detail_info(self, html_text):
        # 详细信息已在用户详情接口中解析
        pass

    def _parse_user_torrent_seeding_info(self, html_text, multi_page=False):
        """
        接口只返回做种总数和总大小，没有单种分布数据
        """
        seeding_info = self._load_json(html_text)
        if not seeding_info.get("success"):
            return
        data = seeding_info.get("data")
        if not isinstance(data, dict):
            data = {}
        self.seeding = self._to_int(data.get("num"))
        self.seeding_size = self._to_int(data.get("fileSize"))

    def _parse_message_unread_links(self, html_text, msg_links):
        # 未读消息在 _pase_unread_msgs 中直接解析
        return

    def _parse_message_content(self, html_text):
        pass

    def _build_api_headers(self) -> dict:
        """
        开放 API 请求头，API Auth Key 直接放在 Authorization 中
        """
        headers = dict(self._json_headers)
        if self._use_apikey:
            headers["Authorization"] = self._apikey
        return headers

    def _error_message(self, detail: dict) -> str:
        """
        根据接口错误码生成用户可读的错误信息
        """
        error_code = detail.get("errorCode")
        if self._use_apikey:
            messages = {
                400: "API Auth Key无效或已过期",
                403: "API Auth Key无效或已删除",
                1402: "需要先完成邮箱验证"
            }
            return messages.get(error_code) or detail.get("errorMessage") or "获取用户信息失败"
        if error_code in (400, 401):
            return "Cookie已失效"
        return detail.get("errorMessage") or "获取用户信息失败"

    @staticmethod
    def _load_json(text) -> dict:
        """
        解析接口响应，只接受 JSON 对象
        """
        result = JsonUtils.loads(text, default=None, silent=True)
        return result if isinstance(result, dict) else {}

    @staticmethod
    def _to_int(value) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0
