import aiohttp

import log
from app.helper import SubmoduleHelper
from app.models.model import UserSiteConf
from app.sites.siteuserinfo._base import _ISiteUserInfo, build_async_session, resolve_proxy_url
from app.sites.siteuserinfo.mTorrent import MTorrentUserInfo
from app.utils.async_request import decode_bytes
from app.utils.commons import mask_value, singleton
from app.utils.types import Spider
from config import Config


@singleton
class SitesschemaCenter:
    """
    站点解析中心单例
    """

    _site_schema : list[_ISiteUserInfo]

    def __init__(self):

        # 加载模块
        self._site_schema = SubmoduleHelper.import_submodules('app.sites.siteuserinfo',
                                                              filter_func=lambda _, 
                                                              obj: hasattr(obj, 'schema'))
        self._site_schema.sort(key=lambda x: x.order)
        log.debug(f"【Sites】加载站点解析: {self._site_schema}")


    async def build(self, site_info: UserSiteConf) -> _ISiteUserInfo:

        site_url = site_info.strict_url
        site_name = site_info.name
        site_cookie = site_info.cookie
        site_appkey = site_info.apikey
        use_proxy = site_info.proxy
        parser = site_info.parser

        ua = site_info.ua
        emulate = site_info.chrome

        # 特定解析器
        if parser and parser == Spider.MTorrentSpider.value:
            return MTorrentUserInfo(site_name, site_url, site_cookie, '', apikey=site_appkey,
                                    session=build_async_session(), proxy=use_proxy)

        if not site_cookie:
            return None

        # Cookie 属于站点凭证，日志中不输出原文
        log.debug(f"【Sites】站点 {site_name} url={site_url} cookie={mask_value(site_cookie)} ua={ua}")

        # 站点流控
        # site_id = site_info.id
        # if site_id != None and self.sites.check_ratelimit(site_id):
        #     return

        # 请求网页（会话已携带站点 Cookie）
        session = build_async_session(site_cookie)
        success = False
        try:
            html_text = await self.__request_site_page(url=site_url, session=session, ua=ua,
                                                       emulate=emulate, proxy=use_proxy)
            if not html_text:
                return None

            # 解析站点类型
            site_schema = self.__build_class(html_text)
            if not site_schema:
                log.error(f"【Sites】站点 {site_name} 无法识别站点类型")
                return None
            builder = site_schema(site_name, site_url, site_cookie, html_text,
                                  session=session, ua=ua, emulate=emulate, proxy=use_proxy)
            success = True
            return builder
        finally:
            # 失败路径不能把会话泄漏出去；成功时会话归解析器持有
            if not success:
                await session.close()

    def __build_class(self, html_text):
        for site_schema in self._site_schema:
            try:
                if site_schema.match(html_text):
                    return site_schema
            except Exception as e:
                log.exception('【Sites】实例化站点解析器出错: ')
        return None
    

    async def __request_site_page(self,
                                  url,
                                  session,
                                  ua=None,
                                  emulate=None,
                                  proxy=False) -> str | None:
        """
        请求站点首页并解码
        """
        headers = {"User-Agent": ua or Config().get_ua()}
        proxy_url = resolve_proxy_url(proxy)

        async def _get(target_url):
            kwargs = {"headers": headers}
            if proxy_url:
                kwargs["proxy"] = proxy_url
            try:
                async with session.get(target_url, **kwargs) as res:
                    return res.status, await res.read(), res.charset
            except (aiohttp.ClientError, TimeoutError) as e:
                log.exception(f"【Sites】请求 {target_url} 异常: {e!s}")
                return None, b"", None

        # 直接请求
        status, content, charset = await _get(url)
        if status is None:
            log.error(f"【Sites】{url} 无法访问")
            return None

        # 状态码异常
        if status != 200:
            log.error(f"【Sites】{url} 访问失败，状态码: {status}")
            return None

        # 正常请求, 开始解析
        html_text = decode_bytes(content, charset)

        # 第一次登录反爬
        if html_text.find("title") == -1:
            i = html_text.find("window.location")
            if i == -1:
                return None
            tmp_url = url + html_text[i:html_text.find(";")] \
                .replace("\"", "").replace("+", "").replace(" ", "").replace("window.location=", "")

            status, content, charset = await _get(tmp_url)
            if status == 200:
                html_text = decode_bytes(content, charset)
                if not html_text:
                    return None
            else:
                log.error(f"【Sites】{url} 被反爬限制: 状态码: {status}")
                return None

        # 兼容假首页情况，假首页通常没有 <link rel="search" 属性
        if '"search"' not in html_text and '"csrf-token"' not in html_text:
            status, content, charset = await _get(url + "/index.php")
            if status == 200:
                html_text = decode_bytes(content, charset)
                if not html_text:
                    return None

        return html_text
