import json
import os
import threading

from cachetools import TTLCache, cached
from sqlalchemy import create_engine, text
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import QueuePool

import log
from app.db.models import MEDIASYNCITEMS, MEDIASYNCSTATISTIC, BaseMedia
from app.utils.time_utils import TimeUtils
from config import Config

lock = threading.Lock()
_Engine = create_engine(
    f"sqlite:///{os.path.join(Config().get_config_path(), 'media.db')}?check_same_thread=False",
    echo=False,
    poolclass=QueuePool,
    pool_pre_ping=True,
    pool_size=100,
    pool_recycle=60 * 10,
    max_overflow=0
)
_Session = scoped_session(sessionmaker(bind=_Engine,
                                       autoflush=True,
                                       autocommit=False))


class MediaDb:

    @property
    def session(self):
        return _Session()

    @staticmethod
    def init_db():
        with lock:
            BaseMedia.metadata.create_all(_Engine)
            MediaDb.ensure_sync_items_columns()

    @staticmethod
    def ensure_sync_items_columns():
        """
        兜底升级：create_all 只建缺失的表，不会为已有表补列，
        老版本 media.db 需要手动补上新增的 DOUBANID 列。
        """
        try:
            with _Engine.begin() as conn:
                columns = {
                    row[1] for row in
                    conn.execute(text("PRAGMA table_info(MEDIASYNC_ITEMS)")).fetchall()
                }
                if columns and "DOUBANID" not in columns:
                    conn.execute(text("ALTER TABLE MEDIASYNC_ITEMS ADD COLUMN DOUBANID TEXT"))
                    log.console("数据库升级完成：MEDIASYNC_ITEMS 新增 DOUBANID 列")
                if columns:
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_MEDIASYNC_ITEMS_DOUBANID "
                                      "ON MEDIASYNC_ITEMS (DOUBANID)"))
        except Exception as e:
            log.error(f"检查 MEDIASYNC_ITEMS.DOUBANID 列失败：{e!s}")

    def insert(self, server_type, iteminfo, seasoninfo):
        if not server_type or not iteminfo:
            return False
        try:
            self.session.query(MEDIASYNCITEMS).filter(MEDIASYNCITEMS.SERVER == server_type,
                                                      MEDIASYNCITEMS.ITEM_ID == iteminfo.get("id")).delete()
            self.session.flush()
            self.session.add(MEDIASYNCITEMS(
                SERVER=server_type,
                LIBRARY=iteminfo.get("library"),
                ITEM_ID=iteminfo.get("id"),
                ITEM_TYPE=iteminfo.get("type"),
                TITLE=iteminfo.get("title"),
                ORGIN_TITLE=iteminfo.get("originalTitle"),
                YEAR=iteminfo.get("year"),
                TMDBID=iteminfo.get("tmdbid"),
                IMDBID=iteminfo.get("imdbid"),
                DOUBANID=iteminfo.get("doubanid"),
                PATH=iteminfo.get("path"),
                JSON=json.dumps(seasoninfo)
            ))
            self.session.commit()
            return True
        except Exception as e:
            log.exception("[Db]insert MEDIASYNC_ITEMS error:")
            self.session.rollback()
        return False

    def empty(self, server_type=None, library=None):
        try:
            if server_type and library:
                self.session.query(MEDIASYNCITEMS).filter(MEDIASYNCITEMS.SERVER == server_type,
                                                          MEDIASYNCITEMS.LIBRARY == library).delete()
            elif server_type:
                self.session.query(MEDIASYNCITEMS).filter(MEDIASYNCITEMS.SERVER == server_type).delete()
            else:
                self.session.query(MEDIASYNCITEMS).delete()
            self.session.commit()
            return True
        except Exception as e:
            log.exception("[Db]empty MEDIASYNC_ITEMS error:")
            self.session.rollback()
        return False

    def statistics(self, server_type, total_count, movie_count, tv_count):
        if not server_type:
            return False
        try:
            self.session.query(MEDIASYNCSTATISTIC).filter(MEDIASYNCSTATISTIC.SERVER == server_type).delete()
            self.session.flush()
            self.session.add(MEDIASYNCSTATISTIC(
                SERVER=server_type,
                TOTAL_COUNT=total_count,
                MOVIE_COUNT=movie_count,
                TV_COUNT=tv_count,
                UPDATE_TIME=TimeUtils.now_str()
            ))
            self.session.commit()
            return True
        except Exception as e:
            log.exception("[Db]MEDIASYNC_STATISTICS CRUD ERROR:")
            self.session.rollback()
        return False

    @cached(cache=TTLCache(maxsize=128, ttl=60))
    def query(self, server_type, title, year, tmdbid, doubanid=None):
        if not server_type:
            return None

        if tmdbid:
            item = self.session.query(MEDIASYNCITEMS).filter(MEDIASYNCITEMS.SERVER == server_type,
                                                             MEDIASYNCITEMS.TMDBID == tmdbid).first()
            if item:
                return item

        if doubanid:
            item = self.session.query(MEDIASYNCITEMS).filter(MEDIASYNCITEMS.SERVER == server_type,
                                                             MEDIASYNCITEMS.DOUBANID == doubanid).first()
            if item:
                return item

        if not title:
            return None
        if year:
            item = self.session.query(MEDIASYNCITEMS).filter(MEDIASYNCITEMS.SERVER == server_type,
                                                             MEDIASYNCITEMS.TITLE == title,
                                                             MEDIASYNCITEMS.YEAR == year).first()
        else:
            item = self.session.query(MEDIASYNCITEMS).filter(MEDIASYNCITEMS.SERVER == server_type,
                                                             MEDIASYNCITEMS.TITLE == title).first()
        if item and tmdbid and (not item.TMDBID or item.TMDBID != str(tmdbid)):
            return None
        if item and doubanid and item.DOUBANID and item.DOUBANID != str(doubanid):
            return None
        return item

    def get_statistics(self, server_type):
        if not server_type:
            return None
        return self.session.query(MEDIASYNCSTATISTIC).filter(MEDIASYNCSTATISTIC.SERVER == server_type).first()
