import os
from collections.abc import Mapping

from alembic.command import upgrade as alembic_upgrade
from alembic.config import Config as AlembicConfig

import log
from app.db.main_db import MainDb
from app.db.media_db import MediaDb
from app.utils.password_hash import generate_password_hash, normalize_password_hash
from app.utils.string_utils import StringUtils
from config import Config


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

    # API密钥迁移：确保系统默认密钥 SYS_DEFAULT 存在，配置文件不再保存密钥
    try:
        from app.core.security_center import SecurityCenter
        if SecurityCenter().ensure_default_api_key(_config):
            overwrite_cofig = True
    except Exception as e:
        log.exception(f"【Config】API密钥初始化失败：{e!s}")

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


# 日志输出相关配置项，变化后需要重建日志处理器
_LOG_CONFIG_KEYS = {"app.loglevel", "app.logtype", "app.logpath", "app.logserver"}


def diff_config(old_cfg, new_cfg, prefix=""):
    """
    递归比对配置，返回发生变化的配置项（点号路径集合）

    :param old_cfg: 变更前的配置
    :param new_cfg: 变更后的配置
    :param prefix: 当前比对节点的路径前缀
    """
    changed = set()
    if isinstance(old_cfg, Mapping) and isinstance(new_cfg, Mapping):
        for key in set(old_cfg.keys()) | set(new_cfg.keys()):
            path = f"{prefix}.{key}" if prefix else str(key)
            changed |= diff_config(old_cfg.get(key), new_cfg.get(key), path)
    elif old_cfg != new_cfg:
        changed.add(prefix)
    return changed


def _get_config_handlers():
    """
    配置项与重载动作的映射（按需重载，顺序即执行顺序）

    只列出会缓存 config.yaml 配置的服务/任务；其余均在使用时实时读取配置。
    依赖写法：
    - 精确配置项：media.category
    - 整个节点：security（匹配 security 下任意配置项变更）
    - 通配：media.transfer.*（匹配该前缀下的配置项）
    """
    # 延迟导入，避免启动阶段产生循环依赖
    from app.core.scheduler import Scheduler
    from app.core.security_center import SecurityCenter
    from app.helper.meta_helper import MetaHelper
    from app.media.category import Category
    from app.media.media import MediaService
    from app.mediaserver.media_server import MediaServer
    from app.modules.filetransfer import FileTransfer

    return [
        ("日志", _LOG_CONFIG_KEYS, lambda *_: log.setup_logging()),
        # 二级分类在文件转移初始化前加载
        ("Category", {"media.category"}, lambda *_: Category().init_config()),
        ("MediaService", {
            "media.tmdb_language",
            "laboratory.search_keyword",
            "laboratory.search_tmdbweb",
        }, lambda *_: MediaService().init_config()),
        ("FileTransfer", {
            "media.category",
            "media.movie_path",
            "media.tv_path",
            "media.anime_path",
            "media.unknown_path",
            "media.min_filesize",
            "media.ignored_paths",
            "media.ignored_files",
            "media.filesize_cover",
            "media.movie_name_format",
            "media.tv_name_format",
            "media.nfo_poster",
            "pt.rmt_mode",
        }, lambda *_: FileTransfer().init_config()),
        ("MediaServer", {"media.media_server", "emby", "jellyfin", "plex"},
         lambda *_: MediaServer().init_config()),
        ("SecurityCenter", {"security"}, lambda *_: SecurityCenter().init_config()),
        ("MetaHelper", {"laboratory.tmdb_cache_expire"},
         lambda *_: MetaHelper().init_config()),
        # 定时任务精确到单个 job，避免无关任务被重建
        ("Scheduler", {
            "media.mediasync_interval",
            "pt.ptrefresh_date_cron",
            "pt.pt_check_interval",
            "pt.search_rss_interval",
        }, lambda keys: Scheduler().reload_jobs(keys)),
    ]


def _match_config_keys(dependencies, changed_keys):
    """
    判断变更项是否命中服务依赖的配置项
    """
    for dep in dependencies:
        # 通配依赖：media.transfer.*
        if dep.endswith(".*"):
            prefix = dep[:-1]
            if any(key.startswith(prefix) or key == dep[:-2] for key in changed_keys):
                return True
            continue
        # 精确配置项
        if dep in changed_keys:
            return True
        # 整个节点依赖；节点被整体替换/删除时也视为命中
        if "." not in dep:
            if any(key.split(".")[0] == dep for key in changed_keys):
                return True
        elif dep.split(".")[0] in changed_keys:
            return True
    return False


def reload_config(changed_keys):
    """
    按配置变更项执行受影响的重载动作

    :param changed_keys: 发生变化的配置项点号路径集合，由 diff_config 生成
    :return: 已重新加载的服务/任务名称列表
    """
    changed_keys = set(changed_keys or [])
    if not changed_keys:
        return []

    try:
        handlers = _get_config_handlers()
    except Exception:
        log.exception("【Config】加载配置依赖关系失败：")
        return []

    reloaded = []
    for name, dependencies, handler in handlers:
        if not _match_config_keys(dependencies, changed_keys):
            continue
        try:
            handler(changed_keys)
            reloaded.append(name)
        except Exception:
            log.exception(f"【Config】{name} 重新加载配置失败：")

    if reloaded:
        log.info(f"【Config】配置已更新，已重新加载：{'、'.join(reloaded)}")
    return reloaded
