# author: https://github.com/jxxghp/MoviePilot/blob/v3/app/modules/indexer/parser/colapt.py
import log as logger
from app.indexer.client._colapt import (
    KEY_REQUIRED,
    decimal,
    integer,
    local_time,
    response_data,
)
from app.sites.siteuserinfo._base import SITE_BASE_ORDER, _ISiteUserInfo
from app.utils import JsonUtils, SiteUtils
from app.utils.types import SiteSchema
from config import Config


class ColaPTUserInfo(_ISiteUserInfo):
    """
    可乐开放 API 用户数据解析器
    """

    schema = SiteSchema.ColaPT
    order = SITE_BASE_ORDER + 20
    request_mode = "apikey"

    def __init__(self, site_name, url, site_cookie, index_html, apikey=None, session=None, ua=None, proxy=None):
        super().__init__(site_name, url, site_cookie, index_html, apikey, session, ua, proxy)

        self._ua = ua or Config().get_ua()
        self._apikey = str(apikey or "").strip()
        self._api_url = f"{SiteUtils.get_base_url(self.site_url)}/api/v1"
        self._addition_headers = {
            "X-API-Key": self._apikey,
            "Accept": "application/json",
            "User-Agent": self._ua,
        }

    @classmethod
    def match(cls, html_text):
        # 首页没有可识别的内容，只能通过站点配置的解析器类型构造
        return False

    def _parse_logged_in(self, html_text):
        if self._apikey:
            return True
        self.err_msg = KEY_REQUIRED
        logger.warn(f"【Sites】{self.site_name} 未配置ColaPT API Key，跳过后续操作")
        return False

    async def visit_base_info(self):
        """
        访问会员数据接口
        """
        return await self._get_page_content(
            url=f"{self._api_url.rstrip('/')}/me/stats",
            headers={"User-Agent": self._ua}
        )

    def _parse_site_page(self, html_text):
        # 会员数据接口已提供全部统计，不再读取任何网页
        self._user_detail_page = None
        self._user_traffic_page = None
        self._torrent_seeding_page = None
        self._user_mail_unread_page = None
        self._sys_mail_unread_page = None

    async def _parse_user_base_info(self, html_text):
        """
        完整校验后才发布用户 ID，避免把错误响应保存为有效统计
        """
        response_text, status_code = await self.visit_base_info()
        data = JsonUtils.loads(response_text, default=None, silent=True)

        if status_code == -1:
            self.err_msg = "ColaPT API Key 已失效或无效"
            logger.warn(f"【Sites】{self.site_name} 获取用户数据失败：{self.err_msg}")
            return

        if not isinstance(data, dict):
            self.err_msg = "ColaPT API 响应结构无效"
            logger.warn(f"【Sites】{self.site_name} 获取用户数据失败：{self.err_msg}")
            return

        try:
            response_data(status_code, data, self._apikey)
            self.__apply_stats(data)
        except (TypeError, ValueError) as err:
            self.err_msg = str(err)
            logger.warn(f"【Sites】{self.site_name} 获取用户数据失败：{self.err_msg}")

    def __apply_stats(self, data: dict):
        """
        一次投影会员数据，字节、瓶盖和人数校验完毕后才公开身份

        身份取 user.id / user.username，注册时间取 joined_at；流量取计费口径
        （billed_*），与站点分享率一致；分享率为 null 表示没有计费下载量。
        """
        user = data.get("user")
        if not isinstance(user, dict):
            raise TypeError("ColaPT API 用户身份无效")

        user_id = integer(user.get("id"), minimum=1)
        username = user.get("username")
        if not isinstance(username, str) or not username.strip():
            raise ValueError("ColaPT API 用户名无效")

        join_at = local_time(data.get("joined_at"))
        if join_at is None:
            raise ValueError("ColaPT API 时间字段无效")

        class_name = data.get("class_name")
        if not isinstance(class_name, (str, type(None))):
            raise TypeError("ColaPT API 用户等级无效")

        ratio = data.get("ratio")
        values = {
            "username": username,
            "user_level": class_name,
            "join_at": join_at,
            "upload": integer(data.get("billed_uploaded_bytes")),
            "download": integer(data.get("billed_downloaded_bytes")),
            "ratio": 0 if ratio is None else decimal(ratio),
            "bonus": decimal(data.get("points_balance"), signed=True),
            "seeding": integer(data.get("seeding")),
            "seeding_size": integer(data.get("seeding_bytes") or 0),
            "leeching": integer(data.get("leeching")),
            "completed": integer(data.get("completions")),
            "message_unread": integer(data.get("unread_messages")),
        }
        for name, value in values.items():
            setattr(self, name, value)
        self.userid = user_id

    def _parse_user_traffic_info(self, html_text):
        # 流量已由会员数据接口提供
        pass

    def _parse_user_detail_info(self, html_text):
        # 等级和瓶盖已由会员数据接口提供
        pass

    def _parse_user_torrent_seeding_info(self, html_text, multi_page=False):
        # 做种数量和体积已由会员数据接口提供，不重复请求做种分页
        return None

    def _parse_message_unread_links(self, html_text, msg_links):
        # 只保留未读数量，不额外读取或标记站内信
        return None

    def _parse_message_content(self, html_text):
        # 本次适配只提供未读数量，不自动访问站内信正文
        return None, None, None
