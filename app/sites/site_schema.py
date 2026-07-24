import requests

from typing import List, Optional

import log

from app.helper import SubmoduleHelper
from app.indexer.client.browser import PlaywrightHelper
from app.sites._base import PtSiteConf
from app.sites.siteuserinfo._base import _ISiteUserInfo
from app.sites.siteuserinfo.mTorrent import MTorrentUserInfo
from app.utils.types import Spider
from app.utils.http_utils import RequestUtils
from app.utils.commons import singleton

from config import Config

@singleton
class SitesschemaCenter(object):
    """
    站点解析中心单例
    """

    _site_schema : List[_ISiteUserInfo] = []

    def __init__(self):

        # 加载模块
        self._site_schema = SubmoduleHelper.import_submodules('app.sites.siteuserinfo',
                                                              filter_func=lambda _, 
                                                              obj: hasattr(obj, 'schema'))
        self._site_schema.sort(key=lambda x: x.order)
        log.debug(f"【Sites】加载站点解析: {self._site_schema}")


    def build(self, site_info: PtSiteConf) -> _ISiteUserInfo:

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
            return MTorrentUserInfo(site_name, site_url, site_cookie, '', apikey=site_appkey, proxy=use_proxy)

        if not site_cookie:
            return None
        
        log.debug(f"【Sites】站点 {site_name} url={site_url} site_cookie={site_cookie} ua={ua}")

        # 站点流控
        # site_id = site_info.id
        # if site_id != None and self.sites.check_ratelimit(site_id):
        #     return

        # 请求网页
        session = requests.Session()
        html_text = self.__request_site_page(url=site_url, session=session, site_cookie=site_cookie, ua=ua, emulate=emulate, proxy=use_proxy)
        if not html_text:
            return None

        # 解析站点类型
        site_schema = self.__build_class(html_text)
        if not site_schema:
            log.error("【Sites】站点 %s 无法识别站点类型" % site_name)
            return None
        return site_schema(site_name, site_url, site_cookie, html_text, session=session, ua=ua, emulate=emulate, proxy=use_proxy)


    def __build_class(self, html_text):
        for site_schema in self._site_schema:
            try:
                if site_schema.match(html_text):
                    return site_schema
            except Exception as e:
                log.exception('【Sites】实例化站点解析器出错: ')
        return None
    

    def __request_site_page(self, 
                            url, 
                            session, 
                            site_cookie=None, 
                            ua=None, 
                            emulate=None, 
                            proxy=False) -> Optional[str]:
                            
        # 站点需要仿真
        if emulate:
            html_text = PlaywrightHelper().get_page_source(url=url, ua=ua, cookies=site_cookie, proxy=proxy)
            return html_text
        
        # 直接请求
        proxies = Config().get_proxies() if proxy else None
        res = RequestUtils(cookies=site_cookie,
                           session=session,
                           ua=ua,
                           proxies=proxies
                           ).get_res(url=url)
        
        if res is None:
            log.error(f"【Sites】{url} 无法访问")
            return None
        
        # 状态码异常
        if res.status_code != 200:
            log.error(f"【Sites】{url} 访问失败，状态码: {res.status_code}")
            return None
        
        # 正常请求, 开始解析

        if "charset=utf-8" in res.text or "charset=UTF-8" in res.text or 'charset="utf-8"' in res.text :
            res.encoding = "UTF-8"
        else:
            res.encoding = res.apparent_encoding

        html_text = res.text

        # 第一次登录反爬
        if html_text.find("title") == -1:
            i = html_text.find("window.location")
            if i == -1:
                return None
            tmp_url = url + html_text[i:html_text.find(";")] \
                .replace("\"", "").replace("+", "").replace(" ", "").replace("window.location=", "")
            
            res = RequestUtils(cookies=site_cookie,
                               session=session,
                               ua=ua,
                               proxies=proxies
                               ).get_res(url=tmp_url)
            
            if res and res.status_code == 200:
                if "charset=utf-8" in res.text or "charset=UTF-8" in res.text:
                    res.encoding = "UTF-8"
                else:
                    res.encoding = res.apparent_encoding
                html_text = res.text
                if not html_text:
                    return None
            else:
                log.error(f"【Sites】{url} 被反爬限制: 状态码: {res.status_code}")
                return None

        # 兼容假首页情况，假首页通常没有 <link rel="search" 属性
        if '"search"' not in html_text and '"csrf-token"' not in html_text:
            res = RequestUtils(cookies=site_cookie,
                               session=session,
                               ua=ua,
                               proxies=proxies
                               ).get_res(url=url + "/index.php")
            
            if res and res.status_code == 200:
                if "charset=utf-8" in res.text or "charset=UTF-8" in res.text:
                    res.encoding = "UTF-8"
                else:
                    res.encoding = res.apparent_encoding
                html_text = res.text
                if not html_text:
                    return None
        
        return html_text
