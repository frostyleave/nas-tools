import asyncio
import re
from datetime import datetime
from html import unescape

from lxml import etree

import log
from app.conf import SystemConfig
from app.db.models import CONFIGSITE
from app.helper import DbHelper, SiteHelper
from app.indexer.manager import IndexerManager
from app.message import MessageService
from app.models.model import SiteBaseModel, UserSiteConf
from app.sites import SiteRateLimiter
from app.sites.siteuserinfo.mTorrent import MTorrentUserInfo
from app.utils import JsonUtils, RequestUtils, SiteUtils
from app.utils.commons import singleton
from app.utils.types import Spider, SystemConfigKey
from config import Config

# NexusPHP 站点页脚特征
_NEXUSPHP_PATTERN = re.compile(r'powered\s+by\s+nexusphp', re.IGNORECASE)


@singleton
class SitesManager:
    """
    站点数据管理器
    """
    message = None
    dbhelper = None

    _siteByIds : dict[int, UserSiteConf]
    _siteByUrls : dict[str, UserSiteConf]
    _limiters : dict[int, SiteRateLimiter]

    _MAX_CONCURRENCY = 10

    def __init__(self):
        self.init_config()

    def init_config(self):
        self.dbhelper = DbHelper()
        self.message = MessageService()
        # ID存储站点
        self._siteByIds : dict[int, UserSiteConf] = {}
        # URL存储站点
        self._siteByUrls : dict[str, UserSiteConf] = {}
        # 站点限速器
        self._limiters : dict[int, SiteRateLimiter] = {}
        # 站点数据
        config_sites = self.dbhelper.get_config_site()
        # 已启用的索引器（未匹配索引器的站点只有已启用时才使用默认索引器）
        enabled_indexer_ids = list(
            SystemConfig().get(SystemConfigKey.UserIndexerSites) or [])
        indexer_manager = IndexerManager()
        links_changed = False

        for site in config_sites:

            site_strict_url = SiteUtils.get_url_host(site.SIGNURL or site.RSSURL)
            if not site_strict_url:
                continue

            site_data_dic = self.prepra_site_attr(site, enabled_indexer_ids)

            # 实例化
            site_info = UserSiteConf.from_datas(site_data_dic)

            # 以ID存储
            self._siteByIds[site.ID] = site_info
            # 以主机名存储
            self._siteByUrls[site_strict_url] = site_info

            # 站点改为使用默认索引器启用后，地址变更可能重新匹配到具体索引器，
            # 迁移启用记录并清理残留的默认索引器标记
            derived_indexer_id = indexer_manager.build_site_indexer_id(site.ID)
            if derived_indexer_id in enabled_indexer_ids \
                    and site_info.indexer_id != derived_indexer_id:
                enabled_indexer_ids.remove(derived_indexer_id)
                if site_info.indexer_id \
                        and site_info.indexer_id not in enabled_indexer_ids:
                    enabled_indexer_ids.append(site_info.indexer_id)
                links_changed = True

            # 初始化站点限速器
            self._limiters[site.ID] = SiteRateLimiter(
                limit_interval= site_info.limit_interval if site_info.limit_interval and site_info.limit_count else None,
                limit_count = site_info.limit_count if site_info.limit_interval and site_info.limit_count else None,
                limit_seconds = site_info.limit_seconds
            )

        # 清理已删除站点遗留的默认索引器标记，避免站点ID复用后未经校验直接启用
        for indexer_id in list(enabled_indexer_ids):
            if not isinstance(indexer_id, str) \
                    or not indexer_manager.is_base_indexer_id(indexer_id) \
                    or indexer_id == indexer_manager.BASE_INDEXER_ID:
                continue
            try:
                site_id = int(indexer_id.rsplit('@', 1)[-1])
            except ValueError:
                site_id = None
            if site_id not in self._siteByIds:
                enabled_indexer_ids.remove(indexer_id)
                links_changed = True

        if links_changed:
            try:
                SystemConfig().set(key=SystemConfigKey.UserIndexerSites,
                                   value=enabled_indexer_ids)
            except Exception:
                log.exception("【Sites】同步站点索引器启用记录出错: ")

    def refresh_indexer_links(self, missing_only=False):
        """
        重新关联站点与索引器，索引器配置变更后调用
        :param missing_only: 只处理尚未匹配索引器的站点（含使用默认索引器的站点）
        """
        # 已启用的索引器，站点匹配到具体索引器后需要同步启用记录
        enabled_indexer_ids = list(
            SystemConfig().get(SystemConfigKey.UserIndexerSites) or [])
        indexer_manager = IndexerManager()
        links_changed = False

        for site in self._siteByIds.values():
            if missing_only and site.indexer_id \
                    and not indexer_manager.is_base_indexer_id(site.indexer_id):
                continue

            previous_indexer_id = site.indexer_id
            indexer, indexer_id = self.__resolve_site_indexer(
                site.strict_url, site.id, enabled_indexer_ids)
            site.indexer_id = indexer_id
            site.parser = indexer.parser if indexer else ''

            # 站点原先已启用，跟随匹配结果迁移启用记录，避免重新匹配后变回未启用
            if previous_indexer_id and previous_indexer_id != indexer_id \
                    and previous_indexer_id in enabled_indexer_ids:
                enabled_indexer_ids.remove(previous_indexer_id)
                if indexer_id and indexer_id not in enabled_indexer_ids:
                    enabled_indexer_ids.append(indexer_id)
                links_changed = True

        if links_changed:
            SystemConfig().set(key=SystemConfigKey.UserIndexerSites,
                               value=enabled_indexer_ids)

    @staticmethod
    def __resolve_site_indexer(strict_url, site_id,
                               enabled_indexer_ids=None) -> tuple[SiteBaseModel | None, str]:
        """
        匹配站点索引器；匹配不到时，已启用的站点使用基础索引配置兜底
        :param strict_url: 站点地址
        :param site_id: 站点ID
        :param enabled_indexer_ids: 已启用的索引器ID，为空时实时读取
        :return: 索引器配置、站点关联的索引ID
        """
        indexer_manager = IndexerManager()
        indexer = indexer_manager.get_indexer_base(strict_url)
        if indexer:
            return indexer, indexer.id

        base_indexer = indexer_manager.get_base_indexer()
        if not base_indexer:
            return None, ''

        if enabled_indexer_ids is None:
            enabled_indexer_ids = SystemConfig().get(SystemConfigKey.UserIndexerSites) or []

        # 基础配置为通用模板，按站点派生独立ID，保证站点的启停互不影响
        indexer_id = indexer_manager.build_site_indexer_id(site_id)
        # 未启用且匹配不到索引器的站点不分配默认索引器，启用前需校验站点架构
        if indexer_id not in enabled_indexer_ids:
            return None, ''
        return base_indexer, indexer_id

    def prepra_site_attr(self, site:CONFIGSITE, enabled_indexer_ids=None):

        try:

            # 站点属性
            site_rssurl = site.RSSURL or ''
            site_signurl = site.SIGNURL
            site_cookie = site.COOKIE
            site_token = site.TOKEN
            site_apikey = site.API_KEY
            # 站点用途：Q签到、D订阅、S刷流
            site_note = self.__get_site_note_items(site.NOTE)
            site_uses = site.INCLUDE or ''
            uses = []
            if site_uses:
                rss_enable = bool("D" in site_uses and site_rssurl)
                brush_enable = bool("S" in site_uses and site_rssurl)
                statistic_enable = bool("T" in site_uses and (site_rssurl or site_signurl))
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
                # 解析器（匹配不到时取基础索引配置兜底）
            indexer_base, indexer_id = self.__resolve_site_indexer(
                strict_url, site.ID, enabled_indexer_ids)
            if indexer_base:
                site_parser = indexer_base.parser
                
            # 从订阅链接解析passkey
            passkey = ''
            if site_rssurl:
                match = re.search(r'passkey=([a-zA-Z0-9]+)', site_rssurl)
                if match:
                    passkey = match.group(1)
                
            site_data_dic = {
                    "id": site.ID,
                    "name": site.NAME,
                    "pri": site.PRI or 0,
                    "signurl": site_signurl,
                    "strict_url": strict_url,
                    "rssurl": site_rssurl,
                    "indexer_id": indexer_id,
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
                    "source_type": site_note.get("source_type").split(',') if site_note.get("source_type") else [],
                    "parse_detail": site_note.get("parse") == "Y",
                    "unread_msg_notify": site_note.get("message") == "Y",
                    "chrome": site_note.get("chrome") == "Y",
                    "proxy": site_note.get("proxy") == "Y",
                    "subtitle": site_note.get("subtitle") == "Y"
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

            return site_data_dic
        
        except Exception as e:
            log.exception(f'【Sites】站点[{site.NAME}]配置解析异常: ')
            return None

    def get_site_statistic_sites(self) -> list[dict]:
        """
        获取所有站点及其数据统计开关状态
        """
        return [
            {
                "id": site.id,
                "name": site.name,
                "statistic": site.statistic_enable
            }
            for site in self.get_sites()
        ]

    def save_site_statistic_sites(self, settings: dict):
        """
        保存站点数据统计开关
        :param settings: {站点ID: 是否启用}
        """
        for site_id, enabled in (settings or {}).items():
            try:
                site_id = int(site_id)
            except (TypeError, ValueError):
                continue

            enabled = bool(enabled)

            cft_sites = self.dbhelper.get_site_by_id(site_id)
            if not cft_sites:
                continue

            # 站点用途标记（D订阅/S刷流/T数据统计），仅增删 T
            include = cft_sites[0].INCLUDE or ""
            has_statistic = "T" in include
            if enabled and not has_statistic:
                include += "T"
            elif not enabled and has_statistic:
                include = include.replace("T", "")

            self.dbhelper.update_config_site_include(site_id, include)

            # 就地同步内存中的站点配置，不全量 init_config（那会重建限速器等运行时状态）
            site_info = self._siteByIds.get(site_id)
            if not site_info:
                continue
            if enabled and "T" not in site_info.uses:
                site_info.uses.append("T")
            elif not enabled and "T" in site_info.uses:
                site_info.uses.remove("T")
            # 与 prepra_site_attr 保持一致：只有同时配置了 RSS/签到地址的站点才算启用统计
            site_info.statistic_enable = enabled and bool(site_info.rssurl or site_info.signurl)

        return True

    def get_site(self, siteid=None, siteurl=None) -> UserSiteConf | None:
        """
        获取单个站点配置
        """
        if siteid:
            return self._siteByIds.get(int(siteid)) or None
        if siteurl:
            return self.__get_site_by_url(siteurl)
        return None

    def __get_site_by_url(self, url) -> UserSiteConf | None:
        """
        根据地址查找站点配置
        按主机名精确匹配（忽略协议、端口和 www. 前缀）
        """
        host = SiteUtils.get_url_host(url)
        if not host:
            return None
        return self._siteByUrls.get(host) or None

    def get_sites(self,
                  siteids=None,
                  rss=False,
                  brush=False,
                  statistic=False) -> list[UserSiteConf]:
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

    def get_sites_by_suffix(self, suffix) -> UserSiteConf | None:
        """
        根据域名后缀获取站点配置（用于 CookieCloud 等只能提供主域名的场景）
        """
        site_info = self.__get_site_by_url(suffix)
        if site_info:
            return site_info
        suffix_domain = SiteUtils.get_url_domain(suffix)
        if not suffix_domain:
            return None
        for site in self._siteByIds.values():
            site_url = site.strict_url or site.signurl or site.rssurl
            if SiteUtils.get_url_domain(site_url) == suffix_domain:
                return site
        return None

    def get_sites_by_name(self, name) -> list[UserSiteConf]:
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
                       statistic=False) -> list[str]:
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

    def get_site_download_setting(self, site_name=None) -> str | None:
        """
        获取站点下载设置
        """
        if not site_name:
            return None
        # PT站点
        for site in self._siteByIds.values():
            if site.name == site_name:
                return site.download_setting
        # 公共站点
        indexer_base = IndexerManager().get_public_indexer_base_by_name(site_name)
        if indexer_base and indexer_base.extra:
            return indexer_base.extra.get('downloader', None)
        return None

    def verify_default_indexer(self, site_id) -> tuple[bool, str, str]:
        """
        校验站点是否可使用默认索引器
        使用站点对接信息请求签到页，确认站点为 NexusPHP 架构后才允许使用默认索引器
        :param site_id: 站点编号
        :return: 是否通过校验、失败提示、校验通过后的索引ID
        """
        site = self.get_site(siteid=site_id)
        if not site:
            return False, '站点不存在', ''

        # 已匹配索引器的站点无需校验
        if site.indexer_id:
            return True, '', site.indexer_id

        indexer_manager = IndexerManager()
        base_indexer = indexer_manager.get_base_indexer()
        if not base_indexer:
            return False, '默认索引器不存在，请先新增索引器', ''

        check_url = site.signurl or site.strict_url
        if not check_url:
            return False, '站点未配置签到地址，无法校验站点架构', ''

        try:
            res = RequestUtils(
                cookies=site.cookie,
                ua=site.ua or Config().get_ua(),
                proxies=Config().get_proxies() if site.proxy else None
            ).get_res(url=check_url)
        except Exception:
            log.exception(f'【Sites】站点 {site.name} 签到页访问异常: ')
            res = None

        if not res or res.status_code != 200:
            log.warn(f'【Sites】站点 {site.name} 签到页无法访问，禁止使用默认索引器')
            return False, '站点域名无法匹配预设的站点信息，无法执行搜索', ''

        res.encoding = res.apparent_encoding
        # 去掉标签并还原实体，兼容页脚中的链接、换行等写法
        page_text = unescape(re.sub(r'<[^>]+>', ' ', res.text or ''))
        if not _NEXUSPHP_PATTERN.search(page_text):
            log.warn(f'【Sites】站点 {site.name} 非 NexusPHP 架构，禁止使用默认索引器')
            return False, '站点域名无法匹配预设的站点信息，无法执行搜索', ''

        log.info(f'【Sites】站点 {site.name} 确认为 NexusPHP 架构，可使用默认索引器')
        return True, '', indexer_manager.build_site_indexer_id(site.id)

    def attach_default_indexer(self, site_id) -> str:
        """
        将站点关联到默认索引器（启用记录写入成功后调用）
        :param site_id: 站点编号
        :return: 站点索引ID
        """
        site = self.get_site(siteid=site_id)
        indexer_manager = IndexerManager()
        base_indexer = indexer_manager.get_base_indexer()
        if not site or not base_indexer:
            return ''
        site.indexer_id = indexer_manager.build_site_indexer_id(site.id)
        site.parser = base_indexer.parser or ''
        return site.indexer_id

    def test_connection(self, site_id) -> tuple[bool, str, int]:
        """
        测试站点连通性
        :param site_id: 站点编号
        :return: 是否连通、错误信息、耗时
        """
        try:
            site_info = self.get_site(siteid=site_id)
            if not site_info:
                return False, "站点不存在", 0

            if site_info.parser and site_info.parser == Spider.MTorrentSpider.value:
                return self._test_mteam_connection(site_info)
            
            return self.__test_connection_basic(site_info)
            
        except Exception as e:
            log.exception('【Sites】测试站点连通性异常: ')
            return False, "测试站点连通性异常", 0

    def _test_mteam_connection(self, site_info: UserSiteConf):

        url = site_info.strict_url
        site_name = site_info.name
        site_cookie = site_info.cookie
        site_appkey = site_info.apikey
        proxy = site_info.proxy

        # 计时
        start_time = datetime.now()

        mteam_proxy = MTorrentUserInfo(site_name, url, site_cookie, '', apikey=site_appkey, proxy=proxy)
        response_text, status_code = asyncio.run(mteam_proxy.visit_base_info())

        # 计算耗时
        seconds = int((datetime.now() - start_time).microseconds / 1000)

        if response_text and status_code == 200:
            detail = JsonUtils.loads(response_text)
            if not detail or detail.get("code") != "0":
                return False, "apikey失效", seconds
            return True, "连接成功", seconds

        if status_code:
            return False, f"连接失败，状态码：{status_code}", seconds

        return False, "无法打开网站", seconds

    def __test_connection_basic(self, site_info: UserSiteConf):
            
        site_cookie = site_info.cookie
        if not site_cookie:
            return False, "未配置站点Cookie", 0
        
        ua = site_info.ua or Config().get_ua()
        site_url = site_info.strict_url

        # 计时
        start_time = datetime.now()
        
        res = RequestUtils(cookies=site_cookie,
                           ua=ua,
                           proxies=Config().get_proxies() if site_info.proxy else None
                           ).get_res(url=site_url)
        
        seconds = int((datetime.now() - start_time).microseconds / 1000)

        if res and res.status_code == 200:
            if not SiteHelper.is_logged_in(res.text):
                return False, "Cookie失效", seconds
            return True, "连接成功", seconds

        if res:
            return False, f"连接失败，状态码：{res.status_code}", seconds

        return False, "无法打开网站", seconds


    # 解析网站下载链接
    def parse_site_download_url(self, page_url, xpath) -> str | None:
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
            # 索引配置匹配不到时会兜底到基础索引配置，代理开关以站点配置为准
            indexer_info = self.match_indexer_sites(url=page_url)
            indexer_extra = (indexer_info.get('extra') or {}) if indexer_info else {}
            site_conf = self.get_site(siteurl=page_url)
            use_proxy = bool(site_conf and site_conf.proxy) or bool(indexer_extra.get('proxy'))
            proxy = Config().get_proxies() if use_proxy else None

            req = RequestUtils(
                ua=ua,
                cookies=cookie,
                referer=referer,
                proxies=proxy
            ).get_res(url=page_url)

            if req and req.status_code == 200 and req.text:
                page_source = req.text
            # xpath解析
            if page_source:
                html = etree.HTML(page_source)
                urls = html.xpath(xpath)
                if urls:
                    return str(urls[0]).strip()
        except Exception as err:
            log.exception('【Sites】解析网站下载链接出错: ')
        return None

    def match_indexer_sites(self, url, site_name=None) -> SiteBaseModel | None:
        """
        根据url匹配索引站点信息，匹配不到时取基础索引配置兜底
        """
        indexers = IndexerManager().get_all_indexer_base()
        if url:
            sites_info = IndexerManager().get_indexer_base(url, public=True)
            if sites_info:
                return sites_info

        if site_name:
            sites_info = next(filter(lambda x: x.name == site_name, indexers), None)
            if sites_info:
                return sites_info

        return IndexerManager().get_base_indexer()

    def __get_site_note_items(self, note):
        """
        从note中提取站点信息
        """
        return JsonUtils.loads(note, default={})

    def add_site(self, name, site_pri,
                 rssurl='', signurl='', cookie='', token='', apikey='', note='', rss_uses=''):
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
        # 记录更新前的地址与启用状态：地址变更后需要重新匹配索引器并校验
        old_site = self.get_site(siteid=tid)
        old_indexer_id = old_site.indexer_id if old_site else ''
        enabled_indexer_ids = SystemConfig().get(
            SystemConfigKey.UserIndexerSites) or []
        was_enabled = bool(old_indexer_id) and old_indexer_id in enabled_indexer_ids
        old_host = SiteUtils.get_url_host(old_site.strict_url) if old_site else ''
        new_host = SiteUtils.get_url_host(signurl or rssurl)

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

        if ret and old_site and old_host != new_host:
            self.__recheck_site_indexer(tid, old_indexer_id, was_enabled)
        return ret

    def __recheck_site_indexer(self, site_id, old_indexer_id, was_enabled):
        """
        站点地址变更后重新匹配索引器
        匹配不到索引器时，原本已启用的站点需按新地址重新校验 NexusPHP 架构
        """
        site = self.get_site(siteid=site_id)
        if not site:
            return

        indexer_manager = IndexerManager()
        # 新地址匹配到具体索引器：保持启用状态（启用记录跟随新的索引器）
        if site.indexer_id and not indexer_manager.is_base_indexer_id(site.indexer_id):
            if was_enabled and old_indexer_id != site.indexer_id:
                self.__migrate_enabled_indexer(old_indexer_id, site.indexer_id)
            return

        # 新地址匹配不到索引器：先解除默认索引器关联，强制按新地址重新校验
        if indexer_manager.is_base_indexer_id(site.indexer_id):
            self.__migrate_enabled_indexer(site.indexer_id, '')
            site.indexer_id = ''
            site.parser = ''

        # 原本未启用的站点保持未启用，待用户手动启用时再校验
        if not was_enabled:
            return

        success, _, indexer_id = self.verify_default_indexer(site_id)
        if not success:
            log.warn(f'【Sites】站点 {site.name} 地址变更后校验未通过，已停止使用默认索引器')
            return

        self.__migrate_enabled_indexer('', indexer_id)
        self.attach_default_indexer(site_id)

    @staticmethod
    def __migrate_enabled_indexer(old_indexer_id, new_indexer_id):
        """
        启用记录中把旧索引器替换为新索引器，new 为空表示仅移除旧记录
        """
        enabled_indexer_ids = list(SystemConfig().get(
            SystemConfigKey.UserIndexerSites) or [])
        changed = False
        if old_indexer_id and old_indexer_id in enabled_indexer_ids:
            enabled_indexer_ids.remove(old_indexer_id)
            changed = True
        if new_indexer_id and new_indexer_id not in enabled_indexer_ids:
            enabled_indexer_ids.append(new_indexer_id)
            changed = True
        if changed:
            SystemConfig().set(key=SystemConfigKey.UserIndexerSites,
                               value=enabled_indexer_ids)

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
