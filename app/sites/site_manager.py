import json
import re

from datetime import datetime
from lxml import etree
from typing import List, Optional, Tuple

import log

from app.helper import SiteHelper, DbHelper
from app.indexer.client.browser import PlaywrightHelper
from app.indexer.manager import BaseIndexer, IndexerManager
from app.message import Message
from app.sites import PtSite, SiteRateLimiter
from app.utils import RequestUtils, SiteUtils
from app.utils.commons import singleton

from config import Config

@singleton
class SitesManager:
    """
    站点数据管理器
    """
    message = None
    dbhelper = None

    _siteByIds : dict[int, PtSite] = {}
    _siteByUrls : dict[str, PtSite] = {}
    _limiters : dict[int, SiteRateLimiter] = {}

    _MAX_CONCURRENCY = 10

    def __init__(self):
        self.init_config()

    def init_config(self):
        self.dbhelper = DbHelper()
        self.message = Message()
        # ID存储站点
        self._siteByIds : dict[int, PtSite] = {}
        # URL存储站点
        self._siteByUrls : dict[str, PtSite] = {}
        # 站点限速器
        self._limiters : dict[int, SiteRateLimiter] = {}
        
        # 站点数据
        config_sites = self.dbhelper.get_config_site()
        for site in config_sites:

            site_strict_url = SiteUtils.get_url_domain(site.SIGNURL or site.RSSURL)
            if not site_strict_url:
                continue

            # 站点属性
            site_note = self.__get_site_note_items(site.NOTE)

            # 站点用途：Q签到、D订阅、S刷流
            site_rssurl = site.RSSURL
            site_signurl = site.SIGNURL
            site_cookie = site.COOKIE
            site_token = site.TOKEN
            site_apikey = site.API_KEY
            site_uses = site.INCLUDE or ''
            uses = []
            if site_uses:
                rss_enable = True if "D" in site_uses and site_rssurl else False
                brush_enable = True if "S" in site_uses and site_rssurl else False
                statistic_enable = True if "T" in site_uses and (site_rssurl or site_signurl) else False
                uses.append("D") if rss_enable else None
                uses.append("S") if brush_enable else None
                uses.append("T") if statistic_enable else None
            else:
                rss_enable = False
                brush_enable = False
                statistic_enable = False

            site_parser = ''
            indexer_id = ''            
            strict_url = SiteUtils.get_base_url(site_signurl or site_rssurl)
            # 解析器
            indexer_base = IndexerManager().get_indexer_base(strict_url)
            if indexer_base:
                site_parser = indexer_base.parser
                indexer_id = indexer_base.id
            
            # 从订阅链接解析passkey
            passkey = ''
            match = re.search(r'passkey=([a-zA-Z0-9]+)', site_rssurl)
            if match:
                passkey = match.group(1)
            
            site_data_dic = {
                "id": site.ID,
                "name": site.NAME,
                "indexer_id": indexer_id,
                "pri": site.PRI or 0,
                "rssurl": site_rssurl,
                "signurl": site_signurl,
                "strict_url": strict_url,
                "parser" : site_parser,
                "cookie": site_cookie,
                "token": site_token,
                "apikey": site_apikey,
                "passkey": passkey,
                
                "rss_enable": rss_enable,
                "brush_enable": brush_enable,
                "statistic_enable": statistic_enable,
                "uses": uses,

                "ua": site_note.get("ua"),
                "rule": site_note.get("rule"),
                "download_setting": site_note.get("download_setting"),

                "parse": True if site_note.get("parse") == "Y" else False,
                "unread_msg_notify": True if site_note.get("message") == "Y" else False,
                "chrome": True if site_note.get("chrome") == "Y" else False,
                "proxy": True if site_note.get("proxy") == "Y" else False,
                "subtitle": True if site_note.get("subtitle") == "Y" else False
            }

            # 限流策略参数
            limit_interval = site_note.get("limit_interval")
            if limit_interval and str(limit_interval).isdigit():
                site_data_dic["limit_interval"] = int(limit_interval)

            limit_count = site_note.get("limit_count")
            if limit_count and str(limit_count).isdigit():
                site_data_dic["limit_count"] = int(limit_count)

            limit_seconds = site_note.get("limit_seconds")
            if limit_seconds and str(limit_seconds).isdigit():
                site_data_dic["limit_seconds"] = int(limit_seconds)           

            # 实例化
            site_info = PtSite.from_datas(site_data_dic)

            # 以ID存储
            self._siteByIds[site.ID] = site_info
            # 以域名存储
            self._siteByUrls[site_strict_url] = site_info

            # 初始化站点限速器
            self._limiters[site.ID] = SiteRateLimiter(
                limit_interval= site_info.limit_interval if site_info.limit_interval and site_info.limit_count else None,
                limit_count = site_info.limit_count if site_info.limit_interval and site_info.limit_count else None,
                limit_seconds = site_info.limit_seconds
            )

    def get_site(self,
                  siteid=None,
                  siteurl=None) -> Optional[PtSite]:
        """
        获取单个站点配置
        """
        if siteid:
            return self._siteByIds.get(int(siteid)) or None
        if siteurl:
            url_domain = SiteUtils.get_url_domain(siteurl)
            return self._siteByUrls.get(url_domain) or None
        return None

    def get_sites(self,
                  siteids=None,
                  rss=False,
                  brush=False,
                  statistic=False) -> List[PtSite]:
        """
        获取站点配置
        """

        ret_sites = []
        for site in self._siteByIds.values():
            if rss and not site.rss_enable:
                continue
            if brush and not site.brush_enable:
                continue
            if statistic and not site.statistic_enable:
                continue
            if siteids and str(site.id) not in siteids:
                continue
            ret_sites.append(site)

        return ret_sites

    def check_ratelimit(self, site_id) -> bool:
        """
        检查站点是否触发流控
        :param site_id: 站点ID
        :return: True为触发了流控, False为未触发
        """
        site_limiter = self._limiters.get(site_id)
        if not site_limiter:
            return False

        state, msg = site_limiter.check_rate_limit()
        if msg:
            log.warn(f"【Sites】站点 {self._siteByIds[site_id].name} {msg}")
        return state

    def get_sites_by_suffix(self, suffix):
        """
        根据url的后缀获取站点配置
        """
        for key in self._siteByUrls:
            # 使用.分割后再将最后两位(顶级域和二级域)拼起来
            key_parts = key.split(".")
            key_end = ".".join(key_parts[-2:])
            # 将拼起来的结果与参数进行对比
            if suffix == key_end:
                return self._siteByUrls[key]
        return {}

    def get_sites_by_name(self, name) -> List[PtSite]:
        """
        根据站点名称获取站点配置
        """
        ret_sites = []
        for site in self._siteByIds.values():
            if site.name == name:
                ret_sites.append(site)
        return ret_sites

    def get_max_site_pri(self) -> int:
        """
        获取最大站点优先级
        """
        if not self._siteByIds:
            return 0
        return max([site.pri for site in self._siteByIds.values()])

    def get_site_dict(self,
                      rss=False,
                      brush=False,
                      statistic=False):
        """
        获取站点字典
        """
        return [
            {
                "id": site.id,
                "name": site.name
            } for site in self.get_sites(
                rss=rss,
                brush=brush,
                statistic=statistic
            )
        ]

    def get_site_names(self,
                       rss=False,
                       brush=False,
                       statistic=False) -> List[str]:
        """
        获取站点名称集合
        """
        return [
            site.name for site in self.get_sites(
                rss=rss,
                brush=brush,
                statistic=statistic
            )
        ]

    def get_site_download_setting(self, site_name=None) -> Optional[str]:
        """
        获取站点下载设置
        """
        if site_name:
            for site in self._siteByIds.values():
                if site.name == site_name:
                    return site.download_setting
        return None

    def test_connection(self, site_id) -> Tuple[bool, str, int]:
        """
        测试站点连通性
        :param site_id: 站点编号
        :return: 是否连通、错误信息、耗时
        """
        site_info = self.get_site(siteid=site_id)
        if not site_info:
            return False, "站点不存在", 0
        
        # todo 
        site_cookie = site_info.cookie
        if not site_cookie:
            return False, "未配置站点Cookie", 0
        
        ua = site_info.ua or Config().get_ua()
        site_url = site_info.strict_url

        # 计时
        start_time = datetime.now()

        # 仿真
        if site_info.chrome:
            proxy=True if site_info.proxy else False
            # 访问主页
            html_text = PlaywrightHelper().get_page_source(url=site_url, ua=ua, cookies=site_cookie, proxy=proxy, headless=False)
            if not html_text:
                return False, "获取站点源码失败", 0
            
            seconds = int((datetime.now() - start_time).microseconds / 1000)
            if SiteHelper.is_logged_in(html_text):
                return True, "连接成功", seconds
            else:
                return False, "Cookie失效", seconds
        
        res = RequestUtils(cookies=site_cookie,
                           ua=ua,
                           proxies=Config().get_proxies() if site_info.proxy else None
                           ).get_res(url=site_url)
        
        seconds = int((datetime.now() - start_time).microseconds / 1000)
        if res and res.status_code == 200:
            if not SiteHelper.is_logged_in(res.text):
                return False, "Cookie失效", seconds
            else:
                return True, "连接成功", seconds
        elif res is not None:
            return False, f"连接失败，状态码：{res.status_code}", seconds
        else:
            return False, "无法打开网站", seconds

    # 解析网站下载链接
    def parse_site_download_url(self, page_url, xpath) -> Optional[str]:
        """
        从站点详情页面中解析中下载链接
        :param page_url: 详情页面地址
        :param xpath: 解析XPATH，同时还包括Cookie、UA和Referer
        """
        if not page_url or not xpath:
            return ""
        cookie, ua, referer, page_source = None, None, None, None
        xpaths = xpath.split("|")
        xpath = xpaths[0]
        if len(xpaths) > 1:
            cookie = xpaths[1]
        if len(xpaths) > 2:
            ua = xpaths[2]
        if len(xpaths) > 3:
            referer = xpaths[3]
        try:
            site_info = self.match_indexer_sites(url=page_url)
            if not site_info.referer:
                referer = None
            proxy = Config().get_proxies() if site_info.proxy else None

            req = RequestUtils(
                ua=ua,
                cookies=cookie,
                referer=referer,
                proxies=proxy
            ).get_res(url=page_url)

            if req and req.status_code == 200:
                if req.text:
                    page_source = req.text
            # xpath解析
            if page_source:
                html = etree.HTML(page_source)
                urls = html.xpath(xpath)
                if urls:
                    return str(urls[0]).strip()
        except Exception as err:
            log.exception('【Sites】解析网站下载链接出错: ', err)
        return None

    def match_indexer_sites(self, url, site_name=None) -> Optional[BaseIndexer]:
        """
        根据url匹配索引站点信息
        """
        indexers = IndexerManager().get_all_indexer_Base()
        if url:
            base_url = SiteUtils.get_base_url(url)            
            sites_info = next(filter(lambda x: x.domain.startswith(base_url), indexers), None)
            if sites_info:
                return sites_info
            
            url_sld = SiteUtils.get_url_sld(url)
            sites_info = next(filter(lambda x: url_sld.startswith(x.id), indexers), None)
            if sites_info:
                return sites_info
            
        if site_name:
            sites_info = next(filter(lambda x: x.name == site_name, indexers), None)
            return sites_info

        return None

    @staticmethod
    def __get_site_note_items(note):
        """
        从note中提取站点信息
        """
        infos = {}
        if note:
            infos = json.loads(note)
        return infos

    def add_site(self, name, site_pri,
                 rssurl=None, signurl=None, cookie=None, token=None, apikey=None, note=None, rss_uses=None):
        """
        添加站点
        """
        ret = self.dbhelper.insert_config_site(name=name,
                                               site_pri=site_pri,
                                               rssurl=rssurl,
                                               signurl=signurl,
                                               cookie=cookie,
                                               token=token,
                                               apikey=apikey,
                                               note=note,
                                               rss_uses=rss_uses)
        self.init_config()
        return ret

    def update_site(self, tid, name, site_pri,
                    rssurl, signurl, cookie, token, apikey, note, rss_uses):
        """
        更新站点
        """
        ret = self.dbhelper.update_config_site(tid=tid,
                                               name=name,
                                               site_pri=site_pri,
                                               rssurl=rssurl,
                                               signurl=signurl,
                                               cookie=cookie,
                                               token=token,
                                               apikey=apikey,
                                               note=note,
                                               rss_uses=rss_uses)
        self.init_config()
        return ret

    def delete_site(self, siteid):
        """
        删除站点
        """
        ret = self.dbhelper.delete_config_site(siteid)
        self.init_config()
        return ret

    def update_site_cookie(self, siteid, cookie, token=None, ua=None):
        """
        更新站点Cookie和UA
        """
        ret = self.dbhelper.update_site_cookie_ua(tid=siteid,
                                                  cookie=cookie,
                                                  token=token,
                                                  ua=ua)
        self.init_config()
        return ret
