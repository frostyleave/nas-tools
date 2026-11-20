import shutil
import sqlite3
from pathlib import Path

import log
from app.utils.time_utils import TimeUtils
from config import Config


class Backup:

    @staticmethod
    def _backup_sqlite(src_path, dst_path):
        """
        使用 sqlite3 backup API 生成一致性快照

        直接 copy 运行中的数据库可能截到半写页或缺失 WAL 中的最新数据。
        """
        src_path = Path(src_path)
        if not src_path.exists():
            raise FileNotFoundError(f"数据库文件不存在: {src_path}")
        source = sqlite3.connect(str(src_path))
        try:
            target = sqlite3.connect(str(dst_path))
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()

    def backup(self, full_backup=False, bk_path=None):
        """
        @param full_backup  是否完整备份
        @param bk_path     自定义备份路径
        """
        backup_path = None
        try:
            # 创建备份文件夹
            config_path = Path(Config().get_config_path())
            backup_file = f"bk_{TimeUtils.now_str('%Y%m%d%H%M%S')}"
            if bk_path:
                backup_path = Path(bk_path) / backup_file
            else:
                backup_path = config_path / "backup_file" / backup_file
            backup_path.mkdir(parents=True)
            # 把现有的相关文件进行copy备份
            shutil.copy(f'{config_path}/config.yaml', backup_path)
            shutil.copy(f'{config_path}/default-category.yaml', backup_path)
            # 运行中的 SQLite 使用 backup API，避免拿到损坏的快照
            self._backup_sqlite(config_path / "user.db", backup_path / "user.db")

            # 完整备份不删除表
            if not full_backup:
                conn = sqlite3.connect(f'{backup_path}/user.db')
                try:
                    cursor = conn.cursor()
                    # 执行操作删除不需要备份的表
                    table_list = [
                        'SEARCH_RESULT_INFO',
                        'RSS_TORRENTS',
                        'DOUBAN_MEDIAS',
                        'TRANSFER_HISTORY',
                        'TRANSFER_UNKNOWN',
                        'TRANSFER_BLACKLIST',
                        'SYNC_HISTORY',
                        'DOWNLOAD_HISTORY',
                        'alembic_version'
                    ]
                    for table in table_list:
                        cursor.execute(f"""DROP TABLE IF EXISTS {table};""")
                    conn.commit()
                    cursor.close()
                finally:
                    conn.close()
            zip_file = str(backup_path) + '.zip'
            shutil.make_archive(str(backup_path), 'zip', str(backup_path))
            shutil.rmtree(str(backup_path))
            return zip_file
        except Exception as e:
            log.exception("[act]备份 异常:")
            # 清理失败留下的半成品，避免残留目录/压缩包
            if backup_path and backup_path.exists():
                shutil.rmtree(str(backup_path), ignore_errors=True)
            return None
