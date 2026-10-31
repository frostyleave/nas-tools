import os
import time

from alembic.command import upgrade as alembic_upgrade
from alembic.config import Config as AlembicConfig
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

import log
from app.db.main_db import MainDb
from app.db.media_db import MediaDb
from app.media import Category
from app.utils.cache_manager import CategoryLoadCache, ConfigLoadCache
from app.utils.commons import INSTANCES
from app.utils.password_hash import generate_password_hash, normalize_password_hash
from app.utils.string_utils import StringUtils
from config import Config

_observer = Observer(timeout=10)

def init_data():

    log.console('开始初始化数据库...')
    MediaDb().init_db()
    MainDb().init_db()
    log.console('数据库初始化完成, 开始初始化数据...')
    MainDb().init_data()
    MainDb().ensure_config_users_level()
    log.console('数据初始化完成')
    
    db_location = os.path.normpath(os.path.join(Config().get_config_path(), 'user.db'))
    script_location = os.path.normpath(os.path.join(Config().get_root_path(), 'scripts'))
    try:
        log.console('开始更新数据库...')
        alembic_cfg = AlembicConfig()
        alembic_cfg.set_main_option('script_location', script_location)
        alembic_cfg.set_main_option('sqlalchemy.url', f"sqlite:///{db_location}")
        alembic_upgrade(alembic_cfg, 'head')
        log.console('数据库更新完成')
    except Exception as e:
        log.console(f'数据库更新失败：{e}')

def check_config():
    """
    检查配置文件，如有错误进行日志输出
    """
    # 检查日志输出
    if Config().get_config('app'):
        logtype = Config().get_config('app').get('logtype')
        if logtype:
            log.info(f"日志输出类型为：{logtype}")
        if logtype == "server":
            logserver = Config().get_config('app').get('logserver')
            if not logserver:
                log.warn("【Config】日志中心地址未配置，无法正常输出日志")
            else:
                log.info(f"日志将上送到服务器：{logserver}")
        elif logtype == "file":
            logpath = Config().get_config('app').get('logpath')
            if not logpath:
                log.warn("【Config】日志文件路径未配置，无法正常输出日志")
            else:
                log.info(f"日志将写入文件：{logpath}")

        # 检查系统管理员账号（以数据库为准）
        try:
            from app.models.user import UserManager
            admin_user = UserManager().get_admin_user()
        except Exception as e:
            admin_user = None
            log.error(f"【Config】查询系统管理员失败：{e!s}")
        if admin_user:
            log.info(f"WEB管理页面用户：{admin_user.username}（系统管理员）")
        else:
            log.warn("【Config】数据库中未找到系统管理员账号，请检查 config.yaml 中的 login_user / login_password")

        log.info("请使用 http://IP:3000 访问管理页面")
    else:
        log.error("【Config】配置文件格式错误，找不到app配置项！")


def init_admin_user():
    """
    确保数据库中存在系统管理员账号（LEVEL=99）。

    仅在 CONFIG_USERS 中没有任何系统管理员时，使用 config.yaml 中的
    login_user / login_password 引导创建；初始化完成后管理员账号以数据库为准，
    并移除配置文件中的 login_password，后续密码通过“修改密码”功能维护。
    通过“基础设置”修改用户名会同步到数据库，直接编辑配置文件不会同步。
    """
    from app.helper import DbHelper
    from app.models.user import LEVEL_SYSADMIN

    dbhelper = DbHelper()
    app_conf = Config().get_config('app') or {}

    if not dbhelper.get_users_by_level(LEVEL_SYSADMIN):
        if not app_conf.get('login_user') or not app_conf.get('login_password'):
            log.warn("【Config】WEB管理用户或密码未设置，将使用默认用户：admin，密码：password")
        login_user = app_conf.get('login_user') or 'admin'
        password_hash = normalize_password_hash(app_conf.get('login_password'))
        default_pris = ",".join(
            menu.get('name') for menu in (Config().menu or []) if menu.get('name')
        )

        if dbhelper.is_user_exists(login_user):
            # 同名用户已存在：只提升为系统管理员，不覆盖其密码
            dbhelper.update_user_level(login_user, LEVEL_SYSADMIN)
            log.warn(f"【Config】数据库中存在同名用户 {login_user}，已将其提升为系统管理员")
        else:
            dbhelper.insert_user(login_user, password_hash, default_pris, LEVEL_SYSADMIN)
            log.info(f"【Config】已根据配置文件创建系统管理员：{login_user}")

        if not dbhelper.get_users_by_level(LEVEL_SYSADMIN):
            # 初始化失败时保留配置中的密码，避免丢失引导凭据
            log.error("【Config】系统管理员初始化失败，保留配置文件中的登录密码")
            return

    # 移除配置文件中的 login_password
    app_conf.pop('login_password', None)


def update_config():
    """
    升级配置文件
    """
    _config = Config().get_config()
    overwrite_cofig = False

    # 密码初始化（仅处理配置文件中的明文密码；初始化完成后该配置会被移除）
    login_password = _config.get("app", {}).get("login_password")
    if login_password and not str(login_password).startswith("[hash]"):
        _config['app']['login_password'] = "[hash]{}".format(generate_password_hash(
            login_password))
        overwrite_cofig = True

    # API密钥初始化
    if not _config.get("security", {}).get("api_key"):
        _config['security']['api_key'] = StringUtils.generate_random_str(32)
        overwrite_cofig = True

    # jwt_secret
    if not _config.get("security", {}).get("jwt_secret"):
        _config['security']['jwt_secret'] = StringUtils.generate_random_str(32)
        overwrite_cofig = True

    # 站点数据刷新时间默认配置
    try:
        if "ptrefresh_date_cron" not in _config['pt']:
            _config['pt']['ptrefresh_date_cron'] = '6'
            overwrite_cofig = True
    except Exception as e:
        log.exception("【Config】站点数据刷新时间默认配置 设置异常: ")

    # 重写配置文件
    if overwrite_cofig:
        Config().save_config(_config)


class ConfigMonitor(FileSystemEventHandler):
    """
    配置文件变化响应
    """

    def __init__(self):
        FileSystemEventHandler.__init__(self)

    def on_modified(self, event):
        if event.is_directory:
            return
        src_path = event.src_path
        file_name = os.path.basename(src_path)
        file_head, file_ext = os.path.splitext(os.path.basename(file_name))
        if file_ext != ".yaml":
            return
        # 配置文件10秒内只能加载一次
        if file_name == "config.yaml" and not ConfigLoadCache.get(src_path):
            ConfigLoadCache.set(src_path, True)
            CategoryLoadCache.set("ConfigLoadBlock", True, ConfigLoadCache.ttl)
            log.warn(f"【System】进程 {os.getpid()} 检测到系统配置文件已修改，正在重新加载...")
            time.sleep(1)
            # 重新加载配置
            Config().init_config()
            # 重载singleton服务
            for instance in INSTANCES.values():
                if hasattr(instance, "init_config"):
                    instance.init_config()
        # 正在使用的二级分类策略文件3秒内只能加载一次，配置文件加载时，二级分类策略文件不加载
        elif file_name == os.path.basename(Config().category_path) \
                and not CategoryLoadCache.get(src_path) \
                and not CategoryLoadCache.get("ConfigLoadBlock"):
            CategoryLoadCache.set(src_path, True)
            log.warn(f"【System】进程 {os.getpid()} 检测到二级分类策略 {file_head} 配置文件已修改，正在重新加载...")
            time.sleep(1)
            # 重新加载二级分类策略
            Category().init_config()


def start_config_monitor():
    """
    启动服务
    """
    global _observer
    # 配置文件监听
    _observer.schedule(ConfigMonitor(), path=Config().get_config_path(), recursive=False)
    _observer.daemon = True
    _observer.start()


def stop_config_monitor():
    """
    停止服务
    """
    global _observer
    try:
        if _observer:
            _observer.stop()
            _observer.join()
    except Exception as err:
        print(str(err))
