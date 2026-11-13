import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from threading import Lock

import log
from app.helper import DbHelper
from app.message import MessageService
from app.models.model import UserSiteConf
from app.sites import SitesManager
from app.sites.site_schema import SitesschemaCenter
from app.sites.siteuserinfo._base import fetch_site_favicon
from app.utils import StringUtils
from app.utils.commons import singleton

lock = Lock()

# 统计链路需要解析到的文本字段（展示名称, 属性名），未解析到时为 None
SITE_INFO_TEXT_FIELDS = (
    ("用户名", "username"),
    ("用户等级", "user_level"),
    ("加入日期", "join_at"),
)


def _to_float(value, default=0.0) -> float:
    """
    安全转 float

    部分解析器（如 mTorrent 的 shareRate）返回的数值可能是字符串
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _get_missing_fields(site_user_info) -> list[str]:
    """
    检查站点统计结果中未解析到的关键字段

    数值为 0 往往是页面的真实值（无下载量时分享率显示“无限”、未做种时做种数为 0、
    新账号上传/下载为 0 等），不能按 0 直接判定缺失；这里只检查互相矛盾的情况：
    - 上传量、下载量同时为 0：流量数据大概率未解析到
    - 上传量、下载量都不为 0 而分享率为 0：分享率未解析到
    - 做种数不为 0 而做种体积为 0：做种体积未解析到
    """
    missing = []

    # 文本字段：未解析到时为 None 或空串
    for label, attr in SITE_INFO_TEXT_FIELDS:
        value = getattr(site_user_info, attr, None)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(label)

    upload = _to_float(getattr(site_user_info, "upload", 0))
    download = _to_float(getattr(site_user_info, "download", 0))
    ratio = _to_float(getattr(site_user_info, "ratio", 0))
    seeding = _to_float(getattr(site_user_info, "seeding", 0))
    seeding_size = _to_float(getattr(site_user_info, "seeding_size", 0))

    if upload <= 0 and download <= 0:
        missing.append("上传量/下载量")
    elif upload > 0 and download > 0 and ratio <= 0:
        missing.append("分享率")
    if seeding > 0 and seeding_size <= 0:
        missing.append("做种体积")

    return missing


@dataclass
class SiteFavicon:
    """
    站点图标抓取结果

    站点数据解析失败时只更新图标，用该结构传给 DbHelper.update_site_favicon
    """
    site_name: str
    site_url: str
    site_favicon: str


@singleton
class SitesDataStatisticsCenter:
    """
    站点数据统计中心单例
    """
    sites = None
    dbhelper = None
    message = None

    _last_update_time = None
    _sites_data: dict

    _MAX_CONCURRENCY = 10

    def __init__(self):
        self.init_config()

    def init_config(self):
        self.sites = SitesManager()
        self.dbhelper = DbHelper()
        self.message = MessageService()
        # 站点上一次更新时间
        self._last_update_time = None
        # 站点数据
        self._sites_data = {}

    async def __refresh_site_data(self, site_info: UserSiteConf, cached_favicon_sites: set[str]):
        """
        更新单个site 数据信息
        :param site_info: 站点配置
        :param cached_favicon_sites: 已有图标的站点名称，命中时跳过图标抓取
        :return: (解析结果, 失败原因)；成功时失败原因为 None
        """
        site_url = site_info.strict_url
        if not site_url:
            return None, "站点地址为空"

        site_name = site_info.name

        try:
            site_user_info = await SitesschemaCenter().build(site_info)
            if not site_user_info:
                return None, "无法获取站点首页或未匹配到解析模型"

            # 懒更新：已有图标数据时不再重复请求
            site_user_info.skip_favicon = site_name in cached_favicon_sites
            log.debug(f"【Sites】站点 {site_name} 开始以 {site_user_info.site_schema()} 模型解析")
            # 开始解析
            await site_user_info.parse()
            log.debug(f"【Sites】站点 {site_name} 解析完成")

            # 获取不到数据时，仅返回错误信息，不做历史数据更新
            if site_user_info.err_msg:
                log.warn(f'【Sites】 {site_name} 解析出错: {site_user_info.err_msg}')
                return None, site_user_info.err_msg

            # 发送通知，存在未读消息（同步网络发送，放到线程池避免阻塞事件循环）
            unread_msg_notify = site_info.unread_msg_notify
            await asyncio.to_thread(self.__notify_unread_msg, site_name, site_user_info, unread_msg_notify)

            # 做种信息数组转换
            if site_user_info.seeding_info is not None and isinstance(site_user_info.seeding_info, list):
                site_user_info.seeding_info = json.dumps(site_user_info.seeding_info)

            return site_user_info, None

        except Exception as e:
            log.exception(f'【Sites】站点 {site_name} 获取流量数据失败: ')
            return None, f"解析异常: {e!s}"

    def __notify_unread_msg(self, site_name, site_user_info, unread_msg_notify):
        if site_user_info.message_unread <= 0:
            return
        if self._sites_data.get(site_name, {}).get('message_unread') == site_user_info.message_unread:
            return
        if not unread_msg_notify:
            return

        # 解析出内容，则发送内容
        if len(site_user_info.message_unread_contents) > 0:
            for head, date, content in site_user_info.message_unread_contents:
                msg_title = f"【站点 {site_user_info.site_name} 消息】"
                msg_text = f"时间: {date}\n标题: {head}\n内容: \n{content}"
                self.message.send_site_message(title=msg_title, text=msg_text)
        else:
            self.message.send_site_message(
                title=f"站点 {site_user_info.site_name} 收到 {site_user_info.message_unread} 条新消息，请登陆查看")

    @staticmethod
    def __log_result_summary(refresh_sites, site_user_infos, failed_results):
        """
        输出本次统计的最终执行结果：成功/失败站点数、失败原因、未解析到的字段
        """
        log.info(f"【Sites】站点数据统计完成：共 {len(refresh_sites)} 个站点，"
                 f"成功 {len(site_user_infos)} 个，失败 {len(failed_results)} 个")

        for site_name, fail_reason in failed_results:
            log.warn(f"【Sites】站点 {site_name} 统计失败：{fail_reason}")

        for site_user_info in site_user_infos:
            missing_fields = _get_missing_fields(site_user_info)
            if missing_fields:
                log.warn(f"【Sites】站点 {site_user_info.site_name} 以下字段未解析到："
                         f"{'、'.join(missing_fields)}")

    async def __fetch_failed_site_favicons(self, sites: list[UserSiteConf]) -> list[SiteFavicon]:
        """
        站点首页无法解析时（无法访问、Cloudflare 521/522 等）仍单独尝试抓取图标

        :return: 只包含站点图标信息的列表，供 update_site_favicon 使用
        """
        semaphore = asyncio.Semaphore(self._MAX_CONCURRENCY)

        async def _fetch(site_info: UserSiteConf):
            async with semaphore:
                try:
                    favicon = await fetch_site_favicon(
                        site_info.strict_url,
                        site_cookie=site_info.cookie,
                        ua=site_info.ua,
                        proxy=site_info.proxy
                    )
                except Exception as e:
                    log.warn(f"【Sites】{site_info.name} 获取站点图标失败: {e!s}")
                    return None
                if not favicon:
                    return None
                return SiteFavicon(site_info.name, site_info.strict_url, favicon)

        results = await asyncio.gather(*(_fetch(site) for site in sites), return_exceptions=True)
        return [result for result in results if result and not isinstance(result, BaseException)]

    def refresh_site_data_now(self, specify_sites=None):
        """
        强制刷新站点数据

        对外保持同步接口（调用方均为线程：/do 线程池、命令线程、调度器），
        内部刷新链路已异步化，用 asyncio.run 驱动。
        """
        log.info("【Sites】开始执行站点数据统计...")
        try:
            asyncio.run(self.__refresh_all_site_data(force=True, specify_sites=specify_sites))
        except Exception:
            # 命令线程/线程池会吞掉异常，这里必须显式记录，否则统计失败时无任何日志
            log.exception("【Sites】站点数据统计执行失败: ")
            return
        # 刷完发送消息
        string_list = []

        # 增量数据
        incUploads = 0
        incDownloads = 0
        _, _, site, upload, download = self.get_pt_site_statistics_history(2)

        # 按照上传降序排序
        data_list = list(zip(site, upload, download))
        data_list = sorted(data_list, key=lambda x: x[1], reverse=True)

        for data in data_list:
            site = data[0]
            upload = int(data[1])
            download = int(data[2])
            if upload > 0 or download > 0:
                incUploads += int(upload)
                incDownloads += int(download)
                string_list.append(f"【{site}】\n"
                                   f"上传量: {StringUtils.str_filesize(upload)}\n"
                                   f"下载量: {StringUtils.str_filesize(download)}\n"
                                   f"\n————————————")

        if incDownloads or incUploads:
            string_list.insert(0, f"【今日汇总】\n"
                                  f"总上传: {StringUtils.str_filesize(incUploads)}\n"
                                  f"总下载: {StringUtils.str_filesize(incDownloads)}\n"
                                  f"\n————————————")

            self.message.send_user_statistics_message(string_list)
        log.info("【Sites】站点数据统计执行完成")

    async def __refresh_all_site_data(self, force=False, specify_sites=None):
        """
        并发刷新站点下载上传量，默认间隔6小时
        """
        if not self.sites.get_sites():
            return

        with lock:

            if not force \
                    and not specify_sites \
                    and self._last_update_time:
                return

            if specify_sites \
                    and not isinstance(specify_sites, list):
                specify_sites = [specify_sites]

            # 没有指定站点，默认使用全部站点
            if not specify_sites:
                refresh_sites = self.sites.get_sites(statistic=True)
            else:
                refresh_sites = [site for site in self.sites.get_sites(statistic=True) if
                                 site.name in specify_sites]

            if not refresh_sites:
                if specify_sites:
                    log.warn(f"【Sites】指定刷新的站点不存在或未启用站点统计：{'、'.join(specify_sites)}")
                else:
                    log.info("【Sites】没有启用站点统计的站点，跳过站点数据统计")
                return

            # 已有有效图标的站点不再重复抓取（懒更新）
            cached_favicon_sites = {
                favicon.SITE for favicon in self.dbhelper.get_site_favicons()
                if self.dbhelper.is_valid_site_favicon(favicon.FAVICON)
            }

            # 并发刷新：协程并发，限制最大并发数
            semaphore = asyncio.Semaphore(self._MAX_CONCURRENCY)

            async def _refresh(site_info: UserSiteConf):
                async with semaphore:
                    return await self.__refresh_site_data(site_info, cached_favicon_sites)

            results = await asyncio.gather(
                *(_refresh(site) for site in refresh_sites),
                return_exceptions=True
            )
            site_user_infos = []
            failed_results = []
            for site, result in zip(refresh_sites, results):
                if isinstance(result, BaseException):
                    log.error(f"【Sites】刷新站点数据异常: {result!s}")
                    failed_results.append((site.name, f"刷新异常: {result!s}"))
                    continue
                site_user_info, fail_reason = result
                if site_user_info:
                    site_user_infos.append(site_user_info)
                else:
                    failed_results.append((site.name, fail_reason or "解析失败"))

            # 最终执行结果：汇总成功/失败站点与未解析到的字段，便于排查 Cookie 失效、解析模型不适配等问题
            self.__log_result_summary(refresh_sites, site_user_infos, failed_results)

            # 解析失败的站点（无法访问、521/522、解析出错）仍单独尝试抓取图标
            parsed_sites = {site_user_info.site_name for site_user_info in site_user_infos}
            favicon_infos = list(site_user_infos)
            failed_sites = [site for site in refresh_sites
                            if site.name not in parsed_sites and site.name not in cached_favicon_sites]
            if failed_sites:
                favicon_infos += await self.__fetch_failed_site_favicons(failed_sites)

            # 登记历史数据
            self.dbhelper.insert_site_statistics_history(site_user_infos)
            # 实时用户数据
            self.dbhelper.update_site_user_statistics(site_user_infos)
            # 站点图标
            self.dbhelper.update_site_favicon(favicon_infos)
            # 实时做种信息
            self.dbhelper.update_site_seed_info(site_user_infos)

            # 更新时间
            self._last_update_time = datetime.now()

    def get_pt_site_statistics_history(self, days=7, end_day=None):
        """
        获取站点上传下载量
        """
        site_urls = []
        for site in self.sites.get_sites(statistic=True):
            site_url = site.strict_url
            if site_url:
                site_urls.append(site_url)

        return self.dbhelper.get_site_statistics_recent_sites(days=days, end_day=end_day, strict_urls=site_urls)

    def get_site_user_statistics(self, sites=None, encoding="RAW", with_favicon=False,
                                 include_all_sites=False):
        """
        获取站点用户数据
        :param sites: 站点名称
        :param encoding: RAW/DICT
        :param with_favicon: DICT 结果中是否附带站点图标
        :param include_all_sites: 是否包含未启用统计、暂无数据的站点（以站点配置为准）
        :return:
        """
        statistic_sites = self.sites.get_sites() if include_all_sites \
            else self.sites.get_sites(statistic=True)
        if sites:
            statistic_sites = [site for site in statistic_sites if site.name in sites]
        site_urls = [site.strict_url for site in statistic_sites]

        # 查询上限与站点数保持一致，避免默认 100 条把站点截断
        query_num = max(len(site_urls), 1) if include_all_sites else 100
        raw_statistics = self.dbhelper.get_site_user_statistics(num=query_num, strict_urls=site_urls)
        if encoding == "RAW":
            return raw_statistics

        statistics = self.__todict(raw_statistics)
        if include_all_sites:
            statistics = self.__merge_site_statistics(statistic_sites, statistics)
        else:
            # 不带全部站点时按站点配置（优先级）顺序输出
            site_order = {site.strict_url: index for index, site in enumerate(statistic_sites)}
            statistics.sort(key=lambda item: site_order.get(item.get("url"), len(site_order)))
        if with_favicon:
            # 只使用站点图标表里已收录的图标，未收录的不做兜底
            # 历史遗留的远程图标地址无法在导出时内联，同样按未收录处理
            favicons = {
                favicon.SITE: favicon.FAVICON
                for favicon in self.dbhelper.get_site_favicons()
                if self.dbhelper.is_valid_site_favicon(favicon.FAVICON)
            }
            for item in statistics:
                item["favicon"] = favicons.get(item.get("site")) or ""
        return statistics

    def get_pt_site_activity_history(self, site, days=365 * 2):
        """
        查询站点 上传，下载，做种数据
        :param site: 站点名称
        :param days: 最大数据量
        :return:
        """
        site_activities = [["time", "upload", "download", "bonus", "seeding", "seeding_size"]]
        sql_site_activities = self.dbhelper.get_site_statistics_history(site=site, days=days)
        for sql_site_activity in sql_site_activities:
            timestamp = datetime.strptime(sql_site_activity.DATE, '%Y-%m-%d').timestamp() * 1000
            site_activities.append(
                [timestamp,
                 sql_site_activity.UPLOAD,
                 sql_site_activity.DOWNLOAD,
                 sql_site_activity.BONUS,
                 sql_site_activity.SEEDING,
                 sql_site_activity.SEEDING_SIZE])

        return site_activities

    def get_pt_site_seeding_info(self, site):
        """
        查询站点 做种分布信息
        :param site: 站点名称
        :return: seeding_info:[uploader_num, seeding_size]
        """
        site_seeding_info = {"seeding_info": []}
        seeding_info = self.dbhelper.get_site_seeding_info(site=site)
        if not seeding_info:
            return site_seeding_info

        site_seeding_info["seeding_info"] = json.loads(seeding_info[0])
        return site_seeding_info

    def get_pt_site_min_join_date(self, sites=None):
        """
        查询站点加入时间
        """
        statistics = self.get_site_user_statistics(sites=sites, encoding="DICT")
        if not statistics:
            return ""
        dates = []
        for s in statistics:
            if s.get("join_at"):
                try:
                    dates.append(datetime.strptime(s.get("join_at"), '%Y-%m-%d %H:%M:%S'))
                except Exception as err:
                    print(str(err))
        if dates:
            return min(dates).strftime("%Y-%m-%d")
        return ""

    @staticmethod
    def __merge_site_statistics(sites, statistics):
        """
        以站点配置为准整理列表：没有统计数据记录的站点补一条空数据

        :param sites: 站点配置列表（按优先级排序）
        :param statistics: __todict 后的统计结果
        :return: 与站点配置顺序一致的统计列表，含 has_data 标记
        """
        # 统计数据按 URL 与站点配置对应，不用站名：统计表里的站名可能未随站点改名而更新
        stats_by_url = {item["url"]: item for item in statistics if item.get("url")}
        merged = []
        for site in sites:
            item = stats_by_url.get(site.strict_url)
            if item:
                # 展示名以站点配置为准
                item = dict(item, site=site.name, has_data=True)
            else:
                item = {
                    "site": site.name,
                    "username": "",
                    "user_level": "",
                    "join_at": "",
                    "update_at": "",
                    "upload": 0,
                    "download": 0,
                    "ratio": 0,
                    "seeding": 0,
                    "leeching": 0,
                    "seeding_size": 0,
                    "bonus": 0,
                    "url": site.strict_url or "",
                    "msg_unread": 0,
                    "has_data": False,
                }
            merged.append(item)
        return merged

    @staticmethod
    def __todict(raw_statistics):
        statistics = []
        for site in raw_statistics:
            statistics.append({"site": site.SITE,
                               "username": site.USERNAME,
                               "user_level": site.USER_LEVEL,
                               "join_at": site.JOIN_AT,
                               "update_at": site.UPDATE_AT,
                               "upload": site.UPLOAD,
                               "download": site.DOWNLOAD,
                               "ratio": site.RATIO,
                               "seeding": site.SEEDING,
                               "leeching": site.LEECHING,
                               "seeding_size": site.SEEDING_SIZE,
                               "bonus": site.BONUS,
                               "url": site.URL,
                               "msg_unread": site.MSG_UNREAD
                               })
        return statistics

    def update_site_name(self, old_name, name):
        """
        更新站点数据中的站点名称
        """
        self.dbhelper.update_site_user_statistics_site_name(name, old_name)
        self.dbhelper.update_site_seed_info_site_name(name, old_name)
        self.dbhelper.update_site_statistics_site_name(name, old_name)
        self.dbhelper.update_site_favicon_site_name(name, old_name)
        return True
