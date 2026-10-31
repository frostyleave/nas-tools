import os
import threading

from sqlalchemy import create_engine, text
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import QueuePool

import log
from app.db.models import Base
from app.utils import PathUtils
from config import Config

lock = threading.Lock()
_Engine = create_engine(
    f"sqlite:///{os.path.join(Config().get_config_path(), 'user.db')}?check_same_thread=False",
    echo=False,
    poolclass=QueuePool,
    pool_pre_ping=True,
    pool_size=100,
    pool_recycle=60 * 10,
    max_overflow=0
)
_Session = scoped_session(sessionmaker(bind=_Engine,
                                       autoflush=True,
                                       autocommit=False,
                                       expire_on_commit=False))


class MainDb:

    @property
    def session(self):
        return _Session()

    def init_db(self):
        with lock:
            Base.metadata.create_all(_Engine)
            self.init_db_version()

    def init_db_version(self):
        """
        初始化数据库版本
        """
        try:
            self.excute("delete from alembic_version where 1")
            self.commit()
        except Exception as err:
            print(str(err))

    def ensure_config_users_level(self):
        """
        兜底升级：确保 CONFIG_USERS 存在 LEVEL 列并回填用户等级。

        create_all 只会创建缺失的表，不会为已有表添加列，因此老版本数据库
        需要通过 SQL 迁移或此处补齐。放在 SQL 初始化之后执行，作为兜底。
        """
        try:
            columns = {
                row[1] for row in
                self.session.execute(text("PRAGMA table_info(CONFIG_USERS)")).fetchall()
            }
            if columns and "LEVEL" not in columns:
                self.excute("ALTER TABLE CONFIG_USERS ADD COLUMN LEVEL INTEGER DEFAULT 1")
                self.excute("UPDATE CONFIG_USERS SET LEVEL = 1 WHERE LEVEL IS NULL")
                self.excute("UPDATE CONFIG_USERS SET LEVEL = 9 WHERE LEVEL = 1 AND PRIS LIKE '%系统设置%'")
                self.commit()
                log.console('数据库升级完成：CONFIG_USERS 新增 LEVEL 列')
        except Exception as e:
            log.error(f'检查 CONFIG_USERS.LEVEL 列失败：{e!s}')
            try:
                self.rollback()
            except Exception as rollback_err:
                log.debug(f'回滚 CONFIG_USERS 升级失败：{rollback_err!s}')

    def init_data(self):
        """
        读取config目录下的sql文件，并初始化到数据库，只处理一次
        """
        config = Config().get_config()
        init_files = Config().get_config("app").get("init_files") or []
        config_dir = Config().get_script_path()
        sql_files = PathUtils.get_dir_level1_files(in_path=config_dir, exts=".sql")
        config_flag = False
        for sql_file in sql_files:
            if os.path.basename(sql_file) not in init_files:
                config_flag = True
                with open(sql_file, "r", encoding="utf-8") as f:
                    sql_list = f.read().split(';\n')
                    for sql in sql_list:
                        try:
                            self.execute_sql_script(sql)
                        except Exception as err:
                            print('SQL执行异常: ' + str(err))
                init_files.append(os.path.basename(sql_file))
        if config_flag:
            config['app']['init_files'] = init_files
            Config().save_config(config)

    def insert(self, data):
        """
        插入数据
        """
        if isinstance(data, list):
            self.session.add_all(data)
        else:
            self.session.add(data)

    def query(self, *obj):
        """
        查询对象
        """
        return self.session.query(*obj)
    
    def execute_sql_script(self, sql: str):
        session = self.session  # scoped_session 返回当前线程的 Session

        try:
            conn = self.session.connection()
            conn.exec_driver_sql(sql)
            session.commit()
        except Exception:
            session.rollback()
            raise

    def excute(self, sql):
        """
        执行SQL语句
        """
        self.session.execute(text(sql))

    def flush(self):
        """
        刷写
        """
        self.session.flush()

    def commit(self):
        """
        提交事务
        """
        self.session.commit()

    def rollback(self):
        """
        回滚事务
        """
        self.session.rollback()


class DbPersist(object):
    """
    数据库持久化装饰器
    """

    def __init__(self, db):
        self.db = db

    def __call__(self, f):
        def persist(*args, **kwargs):
            try:
                ret = f(*args, **kwargs)
                self.db.commit()
                return True if ret is None else ret
            except Exception as e:
                log.critical('[DB]数据库持久化出错: ', exc_info=True)
                self.db.rollback()
                return False

        return persist
