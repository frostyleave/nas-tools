import datetime
import os

import log

from app.helper import DbHelper
from app.utils.commons import singleton

from config import Config

# 单次最大删除数据量
BATCH_SIZE = 500

# 临时种子文件保留天数
TORRENT_RETENTION_DAYS = 3


@singleton
class HistoryCleanup:
    dbhelper = None

    def __init__(self):
        self.init_config()

    def init_config(self):
        self.dbhelper = DbHelper()

    def stop_service(self):
        """
        停止服务
        """
        pass

    def cleanup_history_tables(self, retention_days=180):
        """
        分批清理所有历史表中的过期记录
        """

        cutoff_datetime = datetime.datetime.now() - datetime.timedelta(days=retention_days)
        cutoff_full = cutoff_datetime.strftime('%Y-%m-%d %H:%M:%S')
        cutoff_date = cutoff_datetime.strftime('%Y-%m-%d')

        tables = [
            (self.dbhelper.get_download_history_ids_before, 'DOWNLOAD_HISTORY'),
            (self.dbhelper.get_plugin_history_ids_before, 'PLUGIN_HISTORY'),
            (self.dbhelper.get_rss_history_ids_before, 'RSS_HISTORY'),
            (self.dbhelper.get_site_statistics_history_ids_before, 'SITE_STATISTICS_HISTORY'),
            (self.dbhelper.get_sync_history_ids_before, 'SYNC_HISTORY'),
            (self.dbhelper.get_transfer_history_ids_before, 'TRANSFER_HISTORY'),
            (self.dbhelper.get_userrss_task_history_ids_before, 'USERRSS_TASK_HISTORY'),
        ]

        total_deleted = 0
        log.info(f"【HistoryCleanup】开始清理历史数据，保留 {retention_days} 天内的记录...")

        for query_func, name in tables:
            table_deleted = 0
            try:
                while True:
                    ids = query_func(cutoff_full if name != 'SITE_STATISTICS_HISTORY' else cutoff_date,
                                     BATCH_SIZE)
                    if not ids:
                        break
                    deleted = self.dbhelper.delete_history_by_ids(name, ids)
                    if deleted:
                        table_deleted += deleted
                        total_deleted += deleted

                if table_deleted:
                    log.info(f"【HistoryCleanup】{name} 清理完成，删除 {table_deleted} 条记录")
                else:
                    log.info(f"【HistoryCleanup】{name} 无需清理")
            except Exception as e:
                log.error(f"【HistoryCleanup】{name} 清理失败: {str(e)}")

        log.info(f"【HistoryCleanup】历史数据清理完成，共删除 {total_deleted} 条记录")

        # 清理临时目录中过期的种子文件
        self.cleanup_temp_torrent_files()

        return total_deleted

    def cleanup_temp_torrent_files(self, retention_days=TORRENT_RETENTION_DAYS):
        """
        清理临时目录中指定天数前的种子文件
        """
        temp_path = Config().get_temp_path()
        if not os.path.exists(temp_path):
            log.info(f"【HistoryCleanup】临时目录不存在，跳过种子文件清理: {temp_path}")
            return 0

        cutoff_time = datetime.datetime.now() - datetime.timedelta(days=retention_days)
        deleted_count = 0
        try:
            for entry in os.scandir(temp_path):
                # 仅清理临时目录根目录下的种子文件
                if not entry.is_file() or not entry.name.endswith('.torrent'):
                    continue
                try:
                    file_mtime = datetime.datetime.fromtimestamp(entry.stat().st_mtime)
                    if file_mtime < cutoff_time:
                        os.remove(entry.path)
                        deleted_count += 1
                        log.debug("【HistoryCleanup】删除过期种子文件: %s", entry.path)
                except Exception as e:
                    log.error("【HistoryCleanup】删除种子文件 %s 失败: %s", entry.name, e)

            if deleted_count:
                log.info(f"【HistoryCleanup】临时种子文件清理完成，删除 {deleted_count} 个过期种子文件")
            else:
                log.info("【HistoryCleanup】临时种子文件无需清理")
        except Exception:
            log.exception("【HistoryCleanup】临时种子文件清理失败")

        return deleted_count
