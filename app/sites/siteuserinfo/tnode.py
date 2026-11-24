import re
from urllib.parse import urljoin

from app.sites.siteuserinfo._base import SITE_BASE_ORDER, _ISiteUserInfo, build_async_session
from app.utils import JsonUtils, StringUtils
from app.utils.types import SiteSchema


class TNodeSiteUserInfo(_ISiteUserInfo):
    schema = SiteSchema.TNode
    order = SITE_BASE_ORDER + 60

    @classmethod
    def match(cls, html_text):
        return 'Powered By TNode' in html_text

    async def test_connection(self) -> tuple[bool, str]:
        """
        使用用户信息接口验证 Cookie 是否有效

        TNode 站点首页是 SPA 外壳，页面里没有登出/用户面板链接，
        无法通过首页 HTML 判断登录状态，需要请求鉴权接口验证。
        """
        if not self._site_cookie:
            return False, "未配置站点Cookie"

        # 连通性测试可能不传会话，这里临时创建一个并在结束时关闭
        original_session = self._session
        if original_session is None:
            self._session = build_async_session(self._site_cookie)
        try:
            # 首页用于获取 CSRF Token
            index_html, status = await self._get_page_content(self.site_url)
            if not index_html or status != 200:
                return False, "无法打开网站"

            self._parse_site_page(index_html)
            if not self._addition_headers:
                return False, "无法获取站点Token"

            detail_page, status = await self._get_page_content(
                urljoin(self._base_url, self._user_detail_page))
            if status == -1:
                return False, "无法访问站点接口"
            if status != 200:
                return False, "Cookie失效"

            detail = JsonUtils.loads(detail_page, silent=True)
            if not detail or detail.get("status") != 200:
                return False, "Cookie失效"
            return True, "连接成功"
        finally:
            if original_session is None:
                await self._session.close()
                self._session = None
            else:
                self._session = original_session

    def _parse_site_page(self, html_text):
        html_text = self._prepare_html_text(html_text)

        # <meta name="x-csrf-token" content="fd169876a7b4846f3a7a16fcd5cccf8d">
        csrf_token = re.search(r'<meta name="x-csrf-token" content="(.+?)">', html_text)
        if csrf_token:
            self._addition_headers = {'X-CSRF-TOKEN': csrf_token.group(1)}
            self._user_detail_page = "api/user/getMainInfo"
            self._torrent_seeding_page = "api/user/listTorrentActivity?id=&type=seeding&page=1&size=20000"

    def _parse_logged_in(self, html_text):
        """
        判断是否登录成功, 通过判断是否存在用户信息
        暂时跳过检测，待后续优化
        :param html_text:
        :return:
        """
        return True

    def _parse_user_base_info(self, html_text):
        self.username = self.userid

    def _parse_user_traffic_info(self, html_text):
        pass

    def _parse_user_detail_info(self, html_text):
        detail = JsonUtils.loads(html_text)
        if not detail or detail.get("status") != 200:
            return

        user_info = detail.get("data", {})
        self.userid = user_info.get("id")
        self.username = user_info.get("username")
        self.user_level = user_info.get("class", {}).get("name")
        self.join_at = user_info.get("regTime", 0)
        self.join_at = StringUtils.unify_datetime_str(str(self.join_at))

        self.upload = user_info.get("upload")
        self.download = user_info.get("download")
        self.ratio = 0 if self.download <= 0 else round(self.upload / self.download, 3)
        self.bonus = user_info.get("bonus")
        self.traffic_parsed = True

        self.message_unread = user_info.get("unreadAdmin", 0) + user_info.get("unreadInbox", 0) + user_info.get(
            "unreadSystem", 0)

    def _parse_user_torrent_seeding_info(self, html_text, multi_page=False):
        """
        解析用户做种信息
        """
        seeding_info = JsonUtils.loads(html_text)
        if not seeding_info or seeding_info.get("status") != 200:
            return

        torrents = seeding_info.get("data", {}).get("torrents", [])

        page_seeding_size = 0
        page_seeding_info = []
        for torrent in torrents:
            size = torrent.get("size", 0)
            seeders = torrent.get("seeding", 0)

            page_seeding_size += size
            page_seeding_info.append([seeders, size])

        self.seeding += len(torrents)
        self.seeding_size += page_seeding_size
        self.seeding_info.extend(page_seeding_info)

        # 是否存在下页数据
        next_page = None

        return next_page

    def _parse_message_unread_links(self, html_text, msg_links):
        return None

    def _parse_message_content(self, html_text):
        """
        系统信息 api/message/listSystem?page=1&size=20
        收件箱信息 api/message/listInbox?page=1&size=20
        管理员信息 api/message/listAdmin?page=1&size=20
        :param html_text:
        :return:
        """
        return None, None, None
