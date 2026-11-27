import asyncio

import log as logger
from app.indexer.client._speedapp import (
    SpeedAppApiClient,
    SpeedAppTokenProvider,
    class_name,
    integer,
    local_time,
    number,
    speedapp_base_url,
)
from app.sites.siteuserinfo._base import SITE_BASE_ORDER, _ISiteUserInfo
from app.utils.types import SiteSchema
from config import Config


class SpeedAppUserInfo(_ISiteUserInfo):
    """
    SpeedApp 用户信息解析

    站点网页是单页应用，统计信息从 /api/me 获取；认证优先使用个人 API Token，
    未配置时用 Cookie 换取访问令牌。
    """

    schema = SiteSchema.SpeedApp
    order = SITE_BASE_ORDER + 30
    request_mode = "apikey"

    def __init__(self, site_name, url, site_cookie, index_html, apikey=None, session=None, ua=None, proxy=None):
        super().__init__(site_name, url, site_cookie, index_html, apikey, session, ua, proxy)

        self._ua = ua or Config().get_ua()
        self._apikey = str(apikey or "").strip()
        base_url = speedapp_base_url(self.site_url)
        proxies = Config().get_proxies() if proxy else None
        provider = SpeedAppTokenProvider(
            base_url,
            cookie=self._site_cookie,
            apikey=self._apikey,
            ua=self._ua,
            proxy=proxies,
            timeout=20
        )
        self._api = SpeedAppApiClient(
            provider,
            base_url,
            ua=self._ua,
            proxy=proxies,
            timeout=20
        )

    @classmethod
    def match(cls, html_text):
        # 首页没有可识别的内容，只能通过站点配置的解析器类型构造
        return False

    def _parse_logged_in(self, html_text):
        if self._site_cookie or self._apikey:
            return True
        self.err_msg = "未配置 SpeedApp Cookie 或个人 API Token"
        logger.warn(f"【Sites】{self.site_name} 未配置 Cookie 或个人 API Token，跳过后续操作")
        return False

    def _parse_site_page(self, html_text):
        # 统计接口已提供全部数据，不再读取任何网页
        self._user_detail_page = None
        self._user_traffic_page = None
        self._torrent_seeding_page = None
        self._user_mail_unread_page = None
        self._sys_mail_unread_page = None

    async def visit_base_info(self):
        """
        访问账号接口
        """
        return await asyncio.to_thread(self._api.get_json, "/api/me")

    async def test_connection(self) -> tuple[bool, str]:
        """
        使用账号接口验证 Cookie 或个人 API Token
        """
        if not self._site_cookie and not self._apikey:
            return False, "未配置 SpeedApp Cookie 或个人 API Token"

        payload, error = await self.visit_base_info()
        if error:
            return False, error
        try:
            self.__read_stats(payload)
        except (TypeError, ValueError) as err:
            return False, str(err)
        return True, "连接成功"

    async def _parse_user_base_info(self, html_text):
        payload, error = await self.visit_base_info()
        if error:
            self.err_msg = error
            logger.warn(f"【Sites】{self.site_name} 获取用户信息失败: {self.err_msg}")
            return
        try:
            stats = self.__read_stats(payload)
        except (TypeError, ValueError) as err:
            self.err_msg = str(err)
            logger.warn(f"【Sites】{self.site_name} 获取用户信息失败: {self.err_msg}")
            return

        for name, value in stats.items():
            setattr(self, name, value)
        self.traffic_parsed = True

    def __read_stats(self, payload) -> dict:
        """
        校验并读取账号统计
        """
        if not isinstance(payload, dict):
            raise TypeError("SpeedApp API 响应结构无效")

        user_id = integer(payload.get("id"), minimum=1)
        username = payload.get("username")
        if not isinstance(username, str) or not username.strip():
            raise ValueError("SpeedApp 用户名无效")

        join_at = local_time(payload.get("created_at"))
        if not join_at:
            raise ValueError("SpeedApp 注册时间无效")

        user_level = class_name(payload.get("class"))
        if not user_level:
            raise ValueError("SpeedApp 用户等级无效")

        return {
            "userid": user_id,
            "username": username.strip(),
            "join_at": join_at,
            "user_level": user_level,
            "upload": integer(payload.get("uploaded") or 0),
            "download": integer(payload.get("downloaded") or 0),
            "ratio": number(payload.get("ratio") or 0),
            "bonus": number(payload.get("credits") or 0),
            "seeding": integer(payload.get("seeding_count") or 0),
            "seeding_size": integer(payload.get("seeding_size") or 0),
            "leeching": 0,
            "completed": 0,
            "uploaded": 0,
            "message_unread": integer(payload.get("unread_private_message_count") or 0)
            + integer(payload.get("unread_notification_count") or 0)
        }

    def _parse_user_traffic_info(self, html_text):
        # 流量已由账号接口提供
        pass

    def _parse_user_detail_info(self, html_text):
        # 等级、注册时间和魔力值已由账号接口提供
        pass

    def _parse_user_torrent_seeding_info(self, html_text, multi_page=False):
        # 做种数量和体积已由账号接口提供，不读取做种分页
        return None

    def _parse_message_unread_links(self, html_text, msg_links):
        # 只保留未读数量，不读取站内信正文
        return None

    def _parse_message_content(self, html_text):
        return None, None, None
