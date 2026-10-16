"""
文件转移管理模块

负责监控下载完成的文件并将其转移到媒体库目录。
从 Downloader 类中提取，遵循单一职责原则。
"""

import re
from threading import Lock
from typing import Optional, TYPE_CHECKING

from apscheduler.job import Job
from apscheduler.schedulers.background import BackgroundScheduler

import log

from app.conf import ModuleConf
from app.downloader.config import PT_TAG, PT_TRANSFER_INTERVAL
from app.utils.constants import Constants
from app.utils.types import MediaType, RmtMode
from app.core.jobcenter import JobCenter

if TYPE_CHECKING:
    from app.downloader.downloader import Downloader


transfer_lock = Lock()


class TransferManager:
    """
    下载文件转移管理器

    负责定时轮询监控下载器，将完成的下载文件转移到媒体库。
    """

    def __init__(self, downloader: 'Downloader'):
        self._downloader = downloader
        self._transfer_job: Optional[Job] = None

    @property
    def transfer_job(self) -> Optional[Job]:
        return self._transfer_job

    def start_service(self):
        """启动转移任务调度"""
        self.stop_service()
        if not self._downloader.monitor_downloader_ids:
            return
        self._transfer_job = self._get_scheduler().add_job(
            func=self.transfer,
            trigger='interval',
            seconds=PT_TRANSFER_INTERVAL,
            name='下载文件转移'
        )

    def stop_service(self):
        """停止服务"""
        if self._transfer_job:
            try:
                self._get_scheduler().remove_job(self._transfer_job.id)
            except Exception:
                log.exception('【Downloader】定时转移任务移除失败: ')

    def transfer(self, downloader_id=None):
        """
        转移下载完成的文件, 进行文件识别重命名到媒体库目录
        """
        downloader_ids = [downloader_id] if downloader_id \
            else self._downloader._config.monitor_downloader_ids

        for downloader_id in downloader_ids:
            with transfer_lock:
                download_client = self._downloader._get_client(downloader_id)
                if not download_client:
                    log.warn(f"【Downloader】下载器id = {downloader_id} 无效")
                    continue

                downloader_conf = self._downloader.get_downloader_conf(downloader_id)
                downloader_name = downloader_conf.name
                filter_tag = PT_TAG if downloader_conf.only_nastool else None
                match_path = downloader_conf.match_path
                rmt_mode = ModuleConf.RMT_MODES.get(downloader_conf.rmt_mode)

                trans_tasks = download_client.get_transfer_task(tag=filter_tag, match_path=match_path)
                if not trans_tasks:
                    log.debug(f"【Downloader】下载器 {downloader_name} 没有可以进行转移的任务")
                    continue

                log.info(f"【Downloader】下载器 {downloader_name} 开始转移下载文件...")
                for task in trans_tasks:
                    media_type = None
                    tmdb_info = None
                    season = None
                    download_info = self._downloader.get_download_history_by_downloader(
                        downloader=downloader_id, download_id=task.get("id"))
                    if download_info:
                        media_type = MediaType.MOVIE if download_info.TYPE in Constants.MOVIE_TYPES else MediaType.TV
                        tmdb_info = self._downloader.media.get_tmdb_info(mtype=media_type, tmdbid=download_info.TMDBID)
                        if download_info.SE:
                            m = re.search(r'S(\d+)', download_info.SE)
                            season = m.group(1) if m else None

                    done_flag, done_msg = self._downloader.filetransfer.transfer_media(
                        in_from=self._downloader._config.downloader_enum[str(downloader_id)],
                        in_path=task.get("path"),
                        rmt_mode=rmt_mode,
                        media_type=media_type,
                        tmdb_info=tmdb_info,
                        season=season)

                    if not done_flag:
                        log.warn(f"【Downloader】下载器 {downloader_name} 任务%s 转移失败: %s" % (task.get("path"), done_msg))
                        download_client.set_torrents_status(ids=task.get("id"), tags=task.get("tags"))
                    else:
                        if rmt_mode in [RmtMode.MOVE, RmtMode.RCLONE, RmtMode.MINIO]:
                            log.warn(f"【Downloader】下载器 {downloader_name} 移动模式下删除种子文件: %s" % task.get("id"))
                            download_client.delete_torrents(delete_file=True, ids=task.get("id"))
                        else:
                            download_client.set_torrents_status(ids=task.get("id"), tags=task.get("tags"))
                log.info(f"【Downloader】下载器 {downloader_name} 下载文件转移结束")

    @staticmethod
    def _get_scheduler() -> BackgroundScheduler:
        """获取任务管理器"""
        return JobCenter().get_sys_scheduler()
