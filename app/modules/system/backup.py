import os.path
import sqlite3
import shutil
import time

from pathlib import Path

import log

from config import Config

class Backup:

    def backup(self, full_backup=False, bk_path=None):
        """
        @param full_backup  是否完整备份
        @param bk_path     自定义备份路径
        """
        try:
            # 创建备份文件夹
            config_path = Path(Config().get_config_path())
            backup_file = f"bk_{time.strftime('%Y%m%d%H%M%S')}"
            if bk_path:
                backup_path = Path(bk_path) / backup_file
            else:
                backup_path = config_path / "backup_file" / backup_file
            backup_path.mkdir(parents=True)
            # 把现有的相关文件进行copy备份
            shutil.copy(f'{config_path}/config.yaml', backup_path)
            shutil.copy(f'{config_path}/default-category.yaml', backup_path)
            shutil.copy(f'{config_path}/user.db', backup_path)

            # 完整备份不删除表
            if not full_backup:
                conn = sqlite3.connect(f'{backup_path}/user.db')
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
                conn.close()
            zip_file = str(backup_path) + '.zip'
            if os.path.exists(zip_file):
                zip_file = str(backup_path) + '.zip'
            shutil.make_archive(str(backup_path), 'zip', str(backup_path))
            shutil.rmtree(str(backup_path))
            return zip_file
        except Exception as e:
            log.exception("[act]备份 异常:")
            return None
