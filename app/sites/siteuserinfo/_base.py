import base64
import inspect
import json
import re
from abc import ABCMeta, abstractmethod
from urllib.parse import urljoin, urlsplit

import aiohttp
from lxml import etree

import log
from app.helper import SiteHelper
from app.utils.async_request import decode_bytes
from app.utils.http_utils import RequestUtils
from app.utils.types import SiteSchema
from config import Config

SITE_BASE_ORDER = 1000


def resolve_proxy_url(use_proxy: bool) -> str | None:
    """
    获取站点抓取使用的代理地址
    """
    if not use_proxy:
        return None
    proxies = Config().get_proxies() or {}
    return proxies.get("https") or proxies.get("http")


def build_async_session(site_cookie: str | None = None) -> aiohttp.ClientSession:
    """
    创建站点级异步会话：携带站点 Cookie、复用连接、保留 Set-Cookie

    站点抓取统一使用 aiohttp：部分 Cloudflare 站点会按客户端 TLS 指纹拦截，
    httpx 等客户端即使 Cookie/UA 正确也会被 403 挑战（cf-mitigated: challenge）。

    会话只能在创建它的事件循环内使用和关闭；站点刷新通过 asyncio.run 在线程中
    新建事件循环，因此不能复用启动时创建的全局会话。
    """
    kwargs = {
        "connector": aiohttp.TCPConnector(ssl=False),
        "timeout": aiohttp.ClientTimeout(total=60),
    }
    if site_cookie:
        kwargs["cookies"] = RequestUtils.cookie_parse(site_cookie)
    return aiohttp.ClientSession(**kwargs)


def _is_image_content(content: bytes) -> bool:
    """
    判断响应内容是否为图片（ico/png/gif/jpeg/webp/svg/bmp）
    """
    head = content[:200].lstrip()
    return (content.startswith((b"\x00\x00\x01\x00", b"\x00\x00\x02\x00", b"\x89PNG",
                                b"GIF8", b"\xff\xd8\xff", b"BM"))
            or (content.startswith(b"RIFF") and content[8:12] == b"WEBP")
            or b"<svg" in head)


def _favicon_urls(site_url: str, html_text: str = "") -> list[str]:
    """
    生成候选图标地址：优先页面声明的图标，最后回退到站点根目录的 favicon.ico
    """
    urls: list[str] = []
    html = etree.HTML(html_text) if html_text else None
    if html is not None:
        for href in html.xpath('//head/link[contains(@rel, "icon")]/@href'):
            # 图标地址相对站点首页解析（部分解析器的 _base_url 是接口域名）
            favicon_url = urljoin(site_url, href)
            if favicon_url not in urls:
                urls.append(favicon_url)

    split_url = urlsplit(site_url)
    default_url = f"{split_url.scheme}://{split_url.netloc}/favicon.ico"
    if default_url not in urls:
        urls.append(default_url)
    return urls


async def fetch_site_favicon(site_url: str,
                             html_text: str = "",
                             site_cookie: str | None = None,
                             ua: str | None = None,
                             proxy: bool = False,
                             session: aiohttp.ClientSession | None = None) -> str:
    """
    抓取站点图标，返回 base64 编码的图片内容；获取失败返回空串

    - 图标地址优先使用页面里的 <link rel="icon">，获取失败时回退到 /favicon.ico
    - 只要响应内容确实是图片就接受，不校验状态码：部分站点（如 Cloudflare
      521/522 状态下）仍会在异常响应中返回图标内容
    """
    if not site_url:
        return ""

    kwargs = {
        # 图标只是展示用途，使用较短的超时，避免拖慢站点数据刷新
        "timeout": aiohttp.ClientTimeout(total=15),
        "headers": {"User-Agent": ua or Config().get_ua()},
    }
    proxy_url = resolve_proxy_url(proxy)
    if proxy_url:
        kwargs["proxy"] = proxy_url

    async def _fetch(active_session: aiohttp.ClientSession) -> str:
        for favicon_url in _favicon_urls(site_url, html_text):
            try:
                async with active_session.get(favicon_url, **kwargs) as res:
                    content = await res.read()
            except (aiohttp.ClientError, TimeoutError) as e:
                log.warn(f"【Sites】获取站点图标失败 {favicon_url}: {e!s}")
                continue
            # 部分站点未登录时会把登录页当图标返回，需要校验内容确实是图片
            if content and _is_image_content(content):
                return base64.b64encode(content).decode()
        return ""

    if session is not None:
        return await _fetch(session)
    # 没有可用会话时在当前事件循环内临时创建，避免复用绑定在其它事件循环上的全局客户端
    async with build_async_session(site_cookie) as local_session:
        return await _fetch(local_session)


class _ISiteUserInfo(metaclass=ABCMeta):
    # 站点模版
    schema = SiteSchema.NexusPhp
    # 站点解析时判断顺序，值越小越先解析
    order = SITE_BASE_ORDER
    # 请求模式 cookie/apikey
    request_mode = "cookie"
    # 是否跳过图标抓取（已有图标数据时由统计中心置 True，懒更新）
    skip_favicon = False

    def __init__(self, site_name, url, site_cookie, index_html, apikey=None, session=None, ua=None, emulate=False, proxy=None):
        super().__init__()
        # 站点信息
        self.site_name = None
        self.site_url = None
        self.site_favicon = None
        # 用户信息
        self.username = None
        self.userid = None
        # 未读消息
        self.message_unread = 0
        self.message_unread_contents = []

        # 流量信息
        self.upload = 0
        self.download = 0
        self.ratio = 0

        # 种子信息
        self.seeding = 0
        self.leeching = 0
        self.uploaded = 0
        self.completed = 0
        self.incomplete = 0
        self.seeding_size = 0
        self.leeching_size = 0
        self.uploaded_size = 0
        self.completed_size = 0
        self.incomplete_size = 0
        # 做种人数, 种子大小
        self.seeding_info = []

        # 用户详细信息
        self.user_level = None
        self.join_at = None
        self.bonus = 0.0

        # 错误信息
        self.err_msg = None
        self._addition_headers = None

        # 用户基础信息页面
        self._user_basic_page = None
        # 用户基础信息参数
        self._user_basic_params = None
        # 用户基础信息请求头
        self._user_basic_headers = None

        # 站点页面
        self._brief_page = "index.php"
        self._user_detail_page = "userdetails.php?id="
        self._user_traffic_page = "index.php"
        self._torrent_seeding_page = "getusertorrentlistajax.php?userid="
        self._user_mail_unread_page = "messages.php?action=viewmailbox&box=1&unread=yes"
        self._sys_mail_unread_page = "messages.php?action=viewmailbox&box=-2&unread=yes"
        self._torrent_seeding_params = None
        self._torrent_seeding_headers = None

        split_url = urlsplit(url)
        self.site_name = site_name
        self.site_url = url

        self._base_url = f"{split_url.scheme}://{split_url.netloc}"
        self._site_cookie = site_cookie
        self._apikey = apikey
        self._index_html = index_html
        # 站点级异步会话由 SitesschemaCenter.build 创建，用于复用连接与保留 Set-Cookie
        self._session = session
        self._ua = ua

        self.site_favicon = ""

        self._emulate = emulate
        self._proxy = proxy

    def site_schema(self):
        """
        站点解析模型
        :return: 站点解析模型
        """
        return self.schema

    @classmethod
    def match(cls, html_text):
        """
        是否匹配当前解析模型
        :param html_text: 站点首页html
        :return: 是否匹配
        """
        return False

    async def parse(self):
        """
        解析站点信息
        :return:
        """
        try:
            # 懒更新：已有图标数据时不再重复抓取
            if not self.skip_favicon:
                await self._parse_favicon(self._index_html)
            if not self._parse_logged_in(self._index_html):
                return

            await self._maybe_await(self._parse_site_page(self._index_html))

            await self._maybe_await(self._parse_user_base_info(self._index_html))

            await self._pase_unread_msgs()

            if self._user_detail_page:
                detail_page, _ = await self._get_page_content(urljoin(self._base_url, self._user_detail_page))
                await self._maybe_await(self._parse_user_detail_info(detail_page))

            if self._user_traffic_page:
                traffic_page, _ = await self._get_page_content(urljoin(self._base_url, self._user_traffic_page))
                await self._maybe_await(self._parse_user_traffic_info(traffic_page))

            await self._parse_seeding_pages()

            self.seeding_info = json.dumps(self.seeding_info)

        except Exception as e:
            log.exception(f"【Sites】{self.site_name} 解析站点信息出错: {e!s}")
        finally:
            # 关闭连接
            await self.close()

    @staticmethod
    async def _maybe_await(value):
        """
        兼容同步/异步的解析实现，子类可逐步改为 async，无需一次性全部改造
        """
        if inspect.isawaitable(value):
            return await value
        return value

    async def _pase_unread_msgs(self):
        """
        解析所有未读消息标题和内容
        :return:
        """
        unread_msg_links = []
        if self.message_unread > 0:
            links = {self._user_mail_unread_page, self._sys_mail_unread_page}
            for link in links:
                if not link:
                    continue

                msg_links = []
                page_content, _ = await self._get_page_content(urljoin(self._base_url, link))
                next_page = await self._maybe_await(self._parse_message_unread_links(page_content, msg_links))
                while next_page:
                    page_content, _ = await self._get_page_content(urljoin(self._base_url, next_page))
                    next_page = await self._maybe_await(self._parse_message_unread_links(page_content, msg_links))

                unread_msg_links.extend(msg_links)

        for msg_link in unread_msg_links:
            log.debug(f"【Sites】{self.site_name} 信息链接 {msg_link}")
            page_content, _ = await self._get_page_content(urljoin(self._base_url, msg_link))
            head, date, content = await self._maybe_await(self._parse_message_content(page_content))
            log.debug(f"【Sites】{self.site_name} 标题 {head} 时间 {date} 内容 {content}")
            self.message_unread_contents.append((head, date, content))

    async def _parse_seeding_pages(self):

        if self._torrent_seeding_page:
            page_url = urljoin(self._base_url, self._torrent_seeding_page)
            refer_url = urljoin(self._base_url, self._user_detail_page)
            if self._torrent_seeding_headers:
                self._torrent_seeding_headers.update({'Referer' : refer_url})
            else:
                self._torrent_seeding_headers = {'Referer' : refer_url}

            page_conent, _ = await self._get_page_content(page_url, self._torrent_seeding_params, self._torrent_seeding_headers)
            # 第一页
            next_page = await self._maybe_await(self._parse_user_torrent_seeding_info(page_conent))

            # 其他页处理
            while next_page:
                page_conent, _ = await self._get_page_content(urljoin(page_url, next_page),
                                           self._torrent_seeding_params,
                                           self._torrent_seeding_headers)
                next_page = await self._maybe_await(self._parse_user_torrent_seeding_info(page_conent, multi_page=True))

    @staticmethod
    def _prepare_html_text(html_text):
        """
        处理掉HTML中的干扰部分，包括 #数字、xxpx，以及换行符
        """
        # 去掉 #123 这种
        cleaned = re.sub(r"#\d+", "", html_text)
        # 去掉 12px 这种
        cleaned = re.sub(r"\d+px", "", cleaned)
        # 去掉换行、制表符、多余空格
        cleaned = re.sub(r"[\r\n\t]+", "", cleaned)
        return cleaned.strip()

    @abstractmethod
    def _parse_message_unread_links(self, html_text, msg_links):
        """
        获取未阅读消息链接
        :param html_text:
        :return:
        """
        pass

    async def _parse_favicon(self, html_text):
        """
        解析站点 favicon，结果保存在 site_favicon（获取失败不影响站点数据解析）
        :param html_text: 站点首页内容，用于查找图标地址
        :return:
        """
        try:
            self.site_favicon = await fetch_site_favicon(
                self.site_url,
                html_text or "",
                site_cookie=self._site_cookie,
                ua=self._ua,
                proxy=self._proxy,
                session=self._session
            )
        except Exception as e:
            log.warn(f"【Sites】{self.site_name} 获取站点图标失败: {e!s}")

    async def _get_page_content(self, url, params=None, headers=None, with_api_headers=True):
        """
        :param url: 网页地址
        :param params: post参数
        :param headers: 额外的请求头
        :param with_api_headers: 是否携带站点接口专用请求头（如 x-api-key）
        :return:
        """
        req_headers = self._assemble_request_headers(headers, with_api_headers)
        if self._session is not None:
            return await self.__request_page(self._session, url, params, req_headers)

        # 没有可用会话（如直接构造的 mTorrent）时，在当前事件循环内临时创建会话，
        # 避免复用绑定在其它事件循环上的全局客户端
        async with build_async_session(None if self.request_mode == "apikey" else self._site_cookie) as session:
            return await self.__request_page(session, url, params, req_headers)

    async def __request_page(self, session, url, params, req_headers):
        """
        使用指定会话发起请求
        """
        if not req_headers:
            # 未指定请求头时使用默认 UA 与表单 Content-Type
            req_headers = {
                "User-Agent": self._ua or Config().get_ua(),
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            }

        kwargs = {"headers": req_headers}
        proxy = resolve_proxy_url(self._proxy)
        if proxy:
            kwargs["proxy"] = proxy

        try:
            if params:
                # requests 会自动丢弃值为 None 的参数，aiohttp 会序列化成 "None"，这里对齐
                if isinstance(params, dict):
                    params = {key: value for key, value in params.items() if value is not None}
                if req_headers and req_headers.get("Content-Type") == "application/json":
                    ctx = session.post(url, json=params, **kwargs)
                else:
                    ctx = session.post(url, data=params, **kwargs)
            else:
                ctx = session.get(url, **kwargs)

            async with ctx as res:
                status = res.status
                content = await res.read()
                charset = res.charset
        except (aiohttp.ClientError, TimeoutError) as e:
            log.exception(f"【Sites】{self.site_name} 请求 {url} 失败: {e!s}")
            return "", -1

        return self._handle_response(status, content, charset, req_headers)

    def _handle_response(self, status, content, charset, req_headers):
        """
        统一处理响应：状态码校验、JSON/文本解码
        """
        if status not in (200, 500, 403):
            return "", -1

        if req_headers and "application/json" in str(req_headers.get("Accept")):
            try:
                return json.dumps(json.loads(decode_bytes(content, charset))), status
            except (json.JSONDecodeError, ValueError) as e:
                log.exception(f"【Sites】{self.site_name} API响应JSON解析失败: {e}")
                return "", status

        return decode_bytes(content, charset), status

    def _assemble_request_headers(self, headers, with_api_headers=True):
        """
        组装请求头信息
        :param headers: 额外的请求头
        :param with_api_headers: 是否携带站点接口专用请求头
        :return: 请求头信息
        """
        req_headers = None

        if self._ua or headers or (with_api_headers and self._addition_headers):
            if self.request_mode == "apikey":
                req_headers = {}
            else:
                req_headers = {
                    "User-Agent": f"{self._ua}"
                }

            if headers:
                req_headers.update(headers)
            else:
                req_headers.update({
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
                })

            if with_api_headers and self._addition_headers:
                req_headers.update(self._addition_headers)

        return req_headers

    @abstractmethod
    def _parse_site_page(self, html_text):
        """
        解析站点相关信息页面
        :param html_text:
        :return:
        """
        pass

    @abstractmethod
    def _parse_user_base_info(self, html_text):
        """
        解析用户基础信息
        :param html_text:
        :return:
        """
        pass

    def _parse_logged_in(self, html_text):
        """
        解析用户是否已经登陆
        :param html_text:
        :return: True/False
        """
        logged_in = SiteHelper.is_logged_in(html_text)
        if not logged_in:
            self.err_msg = "未检测到已登陆，请检查cookies是否过期"
            log.warn(f"【Sites】{self.site_name} 未登录，跳过后续操作")

        return logged_in

    @abstractmethod
    def _parse_user_traffic_info(self, html_text):
        """
        解析用户的上传，下载，分享率等信息
        :param html_text:
        :return:
        """
        pass

    @abstractmethod
    def _parse_user_torrent_seeding_info(self, html_text, multi_page=False):
        """
        解析用户的做种相关信息
        :param html_text:
        :param multi_page: 是否多页数据
        :return: 下页地址
        """
        pass

    @abstractmethod
    def _parse_user_detail_info(self, html_text):
        """
        解析用户的详细信息
        加入时间/等级/魔力值等
        :param html_text:
        :return:
        """
        pass

    @abstractmethod
    def _parse_message_content(self, html_text):
        """
        解析短消息内容
        :param html_text:
        :return:  head: message, date: time, content: message content
        """
        pass

    async def close(self):
        """
        关闭会话
        """
        if self._session:
            try:
                await self._session.close()
            except Exception as e:
                log.debug(f"【Sites】{self.site_name} 关闭会话失败: {e!s}")
            self._session = None