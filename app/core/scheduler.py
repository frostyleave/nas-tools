import datetime

from apscheduler.schedulers.background import BackgroundScheduler

import log

from app.helper import MetaHelper
from app.mediaserver import MediaServer
from app.modules.rss import Rss
from app.core.jobcenter import JobCenter
from app.modules.wallpaper import get_login_wallpaper
from app.sites import SitesDataStatisticsCenter
from app.modules.subscribe import Subscribe
from app.modules.sync import Sync
from app.utils import SchedulerUtils
from app.utils.commons import singleton

from config import Config

# TMDB信息缓存定时保存时间
METAINFO_SAVE_INTERVAL = 600
# SYNC目录同步聚合转移时间
SYNC_TRANSFER_INTERVAL = 60
# RSS队列中处理时间间隔
RSS_CHECK_INTERVAL = 300
# 刷新订阅TMDB数据的时间间隔（小时）
RSS_REFRESH_TMDB_INTERVAL = 6
# 刷流删除的检查时间间隔
BRUSH_REMOVE_TORRENTS_INTERVAL = 300
# 定时清除未识别的缓存时间间隔（小时）
META_DELETE_UNKNOWN_INTERVAL = 12
# 定时刷新壁纸的间隔（小时）
REFRESH_WALLPAPER_INTERVAL = 1

@singleton
class Scheduler:

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
        
        if self._pt_config:
            # 数据统计
            ptrefresh_date_cron = self._pt_config.get("ptrefresh_date_cron")
            if ptrefresh_date_cron:
                SchedulerUtils.add_job(
                    scheduler=self.get_scheduler(),
                    func=SitesDataStatisticsCenter().refresh_site_data_now,
                    func_desc="数据统计",
                    cron=str(ptrefresh_date_cron)
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
                    self.get_scheduler().add_job(
                        Rss().rssdownload, "interval", seconds=pt_check_interval, name='RSS订阅'
                    )

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
                    self.get_scheduler().add_job(
                        Subscribe().subscribe_search_all,
                        "interval",
                        hours=search_rss_interval, 
                        name='订阅定时搜索'
                    )

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
                    self.get_scheduler().add_job(
                        MediaServer().sync_mediaserver,
                        "interval",
                        hours=mediasync_interval,
                        name='媒体库同步'
                    )

        # 元数据定时保存
        self.get_scheduler().add_job(
            MetaHelper().save_meta_data, 
            "interval", 
            seconds=METAINFO_SAVE_INTERVAL, 
            name='元数据定时保存'
        )

        # 定时把队列中的监控文件转移走
        self.get_scheduler().add_job(
            Sync().transfer_mon_files, 
            "interval", 
            seconds=SYNC_TRANSFER_INTERVAL, 
            name='批量转移文件'
        )

        # RSS队列中搜索
        self.get_scheduler().add_job(
            Subscribe().subscribe_search, 
            "interval", 
            seconds=RSS_CHECK_INTERVAL, 
            name='RSS订阅队列'
        )

        # 豆瓣RSS转TMDB，定时更新TMDB数据
        self.get_scheduler().add_job(
            Subscribe().refresh_rss_metainfo,
            "interval",
            hours=RSS_REFRESH_TMDB_INTERVAL,
            name='RSS订阅队列'
        )

        # 定时清除未识别的缓存
        self.get_scheduler().add_job(
            MetaHelper().delete_unknown_meta,
            "interval",
            hours=META_DELETE_UNKNOWN_INTERVAL,
            name='清理未识别缓存'
        )

        # 定时刷新壁纸
        self.get_scheduler().add_job(
            get_login_wallpaper,
            "interval",
            hours=REFRESH_WALLPAPER_INTERVAL,
            next_run_time=datetime.datetime.now(),
            name='定时刷新壁纸'
        )

    def get_scheduler(self) -> BackgroundScheduler:
        """获取任务管理器"""
        return JobCenter().get_sys_scheduler()
    
    def stop_service(self):
        """
        停止定时服务
        """
        pass
