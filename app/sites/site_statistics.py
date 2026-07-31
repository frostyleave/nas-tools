import json

from datetime import datetime
from multiprocessing.dummy import Pool as ThreadPool
from threading import Lock

import log

from app.helper import DbHelper
from app.message import Message
from app.models.model import UserSiteConf
from app.sites import SitesManager
from app.sites.site_schema import SitesschemaCenter
from app.utils import StringUtils
from app.utils.commons import singleton

lock = Lock()


@singleton
class SitesDataStatisticsCenter(object):
    """
    站点数据统计中心单例
    """
    sites = None
    dbhelper = None
    message = None

    _last_update_time = None
    _sites_data = {}

    _MAX_CONCURRENCY = 10

    def __init__(self):
        self.init_config()

    def init_config(self):
        self.sites = SitesManager()
        self.dbhelper = DbHelper()
        self.message = Message()
        # 站点上一次更新时间
        self._last_update_time = None
        # 站点数据
        self._sites_data = {}

    def __refresh_site_data(self, site_info: UserSiteConf):
        """
        更新单个site 数据信息
        :param site_info:
        :return:
        """
        site_url = site_info.strict_url
        if not site_url:
            return None
        
        site_name = site_info.name

        try:
            site_user_info = SitesschemaCenter().build(site_info)
            if site_user_info:
                log.debug(f"【Sites】站点 {site_name} 开始以 {site_user_info.site_schema()} 模型解析")
                # 开始解析
                site_user_info.parse()
                log.debug(f"【Sites】站点 {site_name} 解析完成")

                # 获取不到数据时，仅返回错误信息，不做历史数据更新
                if site_user_info.err_msg:
                    log.warn(f'【Sites】 {site_name} 解析出错: {site_user_info.err_msg}')
                    return None

                # 发送通知，存在未读消息
                unread_msg_notify = site_info.unread_msg_notify
                self.__notify_unread_msg(site_name, site_user_info, unread_msg_notify)
                
                # 做种信息数组转换
                if site_user_info.seeding_info is not None and isinstance(site_user_info.seeding_info, list):
                    site_user_info.seeding_info = json.dumps(site_user_info.seeding_info)

                return site_user_info

        except Exception as e:
            log.exception(f'【Sites】站点 {site_name} 获取流量数据失败: ')
            return None

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

    def refresh_site_data_now(self, specify_sites=None):
        """
        强制刷新站点数据
        """
        self.__refresh_all_site_data(force=True, specify_sites=specify_sites)
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

    def __refresh_all_site_data(self, force=False, specify_sites=None):
        """
        多线程刷新站点下载上传量，默认间隔6小时
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
                return

            # 并发刷新
            with ThreadPool(min(len(refresh_sites), self._MAX_CONCURRENCY)) as p:
                site_user_infos = list(filter(None, p.map(self.__refresh_site_data, refresh_sites)))
                
            # 登记历史数据
            self.dbhelper.insert_site_statistics_history(site_user_infos)
            # 实时用户数据
            self.dbhelper.update_site_user_statistics(site_user_infos)
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

    def get_site_user_statistics(self, sites=None, encoding="RAW"):
        """
        获取站点用户数据
        :param sites: 站点名称
        :param encoding: RAW/DICT
        :return:
        """
        statistic_sites = self.sites.get_sites(statistic=True)
        if not sites:
            site_urls = [site.strict_url for site in statistic_sites]
        else:
            site_urls = [site.strict_url for site in statistic_sites
                         if site.name in sites]

        raw_statistics = self.dbhelper.get_site_user_statistics(strict_urls=site_urls)
        if encoding == "RAW":
            return raw_statistics

        return self.__todict(raw_statistics)

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
                    pass
        if dates:
            return min(dates).strftime("%Y-%m-%d")
        return ""

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
        return True
