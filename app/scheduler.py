import datetime
import pytz

from typing import Optional
from apscheduler.schedulers.background import BackgroundScheduler

import log

from app.helper import MetaHelper
from app.mediaserver import MediaServer
from app.rss import Rss
from app.job_center import JobCenter
from app.sites import SitesDataStatisticsCenter
from app.subscribe import Subscribe
from app.sync import Sync
from app.utils import SchedulerUtils
from app.utils.commons import singleton

from config import (
    METAINFO_SAVE_INTERVAL,
    SYNC_TRANSFER_INTERVAL,
    RSS_CHECK_INTERVAL,
    RSS_REFRESH_TMDB_INTERVAL,
    META_DELETE_UNKNOWN_INTERVAL,
    REFRESH_WALLPAPER_INTERVAL,
    Config,
)

from web.backend.wallpaper import get_login_wallpaper


@singleton
class Scheduler:

    _scheduler : Optional[BackgroundScheduler] = None
    _pt_config = None
    _media_config = None

    def __init__(self):
        self.init_config()

    def init_config(self):
        self._pt_config = Config().get_config("pt")
        self._media_config = Config().get_config("media")
        self.stop_service()
        self.run_service()

    def run_service(self):
        """
        读取配置，启动定时服务
        """
        self._scheduler = JobCenter().get_scheduler()
        if not self._scheduler:
            return
        
        if self._pt_config:
            # 数据统计
            ptrefresh_date_cron = self._pt_config.get("ptrefresh_date_cron")
            if ptrefresh_date_cron:
                tz = pytz.timezone(Config().get_timezone())
                SchedulerUtils.add_job(
                    scheduler=self._scheduler,
                    func=SitesDataStatisticsCenter().refresh_site_data_now,
                    func_desc="数据统计",
                    cron=str(ptrefresh_date_cron),
                    next_run_time=datetime.datetime.now(tz)
                    + datetime.timedelta(minutes=1),
                )

            # RSS下载器
            pt_check_interval = self._pt_config.get("pt_check_interval")
            if pt_check_interval:
                if isinstance(pt_check_interval, str) and pt_check_interval.isdigit():
                    pt_check_interval = int(pt_check_interval)
                else:
                    try:
                        pt_check_interval = round(float(pt_check_interval))
                    except Exception as e:
                        log.error("RSS订阅周期 配置格式错误：%s" % str(e))
                        pt_check_interval = 0
                if pt_check_interval:
                    if pt_check_interval < 300:
                        pt_check_interval = 300
                    self._scheduler.add_job(
                        Rss().rssdownload, "interval", seconds=pt_check_interval
                    )
                    log.info("RSS订阅服务启动")

            # RSS订阅定时搜索
            search_rss_interval = self._pt_config.get("search_rss_interval")
            if search_rss_interval:
                if (
                    isinstance(search_rss_interval, str)
                    and search_rss_interval.isdigit()
                ):
                    search_rss_interval = int(search_rss_interval)
                else:
                    try:
                        search_rss_interval = round(float(search_rss_interval))
                    except Exception as e:
                        log.error("订阅定时搜索周期 配置格式错误：%s" % str(e))
                        search_rss_interval = 0
                if search_rss_interval:
                    if search_rss_interval < 3:
                        search_rss_interval = 3
                    self._scheduler.add_job(
                        Subscribe().subscribe_search_all,
                        "interval",
                        hours=search_rss_interval,
                    )
                    log.info("订阅定时搜索服务启动")

        # 媒体库同步
        if self._media_config:
            mediasync_interval = self._media_config.get("mediasync_interval")
            if mediasync_interval:
                if isinstance(mediasync_interval, str):
                    if mediasync_interval.isdigit():
                        mediasync_interval = int(mediasync_interval)
                    else:
                        try:
                            mediasync_interval = round(float(mediasync_interval))
                        except Exception as e:
                            log.info("媒体库数据同步服务启动失败：%s" % str(e))
                            mediasync_interval = 0
                if mediasync_interval:
                    self._scheduler.add_job(
                        MediaServer().sync_mediaserver,
                        "interval",
                        hours=mediasync_interval,
                    )
                    log.info("媒体库同步服务启动")

        # 元数据定时保存
        self._scheduler.add_job(
            MetaHelper().save_meta_data, "interval", seconds=METAINFO_SAVE_INTERVAL
        )

        # 定时把队列中的监控文件转移走
        self._scheduler.add_job(
            Sync().transfer_mon_files, "interval", seconds=SYNC_TRANSFER_INTERVAL
        )

        # RSS队列中搜索
        self._scheduler.add_job(
            Subscribe().subscribe_search, "interval", seconds=RSS_CHECK_INTERVAL
        )

        # 豆瓣RSS转TMDB，定时更新TMDB数据
        self._scheduler.add_job(
            Subscribe().refresh_rss_metainfo,
            "interval",
            hours=RSS_REFRESH_TMDB_INTERVAL,
        )

        # 定时清除未识别的缓存
        self._scheduler.add_job(
            MetaHelper().delete_unknown_meta,
            "interval",
            hours=META_DELETE_UNKNOWN_INTERVAL,
        )

        # 定时刷新壁纸
        self._scheduler.add_job(
            get_login_wallpaper,
            "interval",
            hours=REFRESH_WALLPAPER_INTERVAL,
            next_run_time=datetime.datetime.now(),
        )

    def stop_service(self):
        """
        停止定时服务
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
        except Exception as e:
            log.exception('[Sys]停止定时服务出错: ', e)
