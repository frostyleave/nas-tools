import os
import time

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

import log
from app.conf import SystemConfig
from app.helper import PluginHelper
from app.media import Category
from app.utils import ConfigLoadCache, CategoryLoadCache, StringUtils
from app.utils.commons import INSTANCES
from app.utils.types import SystemConfigKey
from app.utils.password_hash import generate_password_hash

from config import Config

_observer = Observer(timeout=10)


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

        # 检查WEB端口
        web_port = Config().get_config('app').get('web_port')
        if not web_port:
            log.warn("【Config】WEB服务端口未设置，将使用默认3000端口")

        # 检查登录用户和密码
        login_user = Config().get_config('app').get('login_user')
        login_password = Config().get_config('app').get('login_password')
        if not login_user or not login_password:
            log.warn("【Config】WEB管理用户或密码未设置，将使用默认用户：admin，密码：password")
        else:
            log.info(f"WEB管理页面用户：{str(login_user)}")

        # 检查HTTPS
        ssl_cert = Config().get_config('app').get('ssl_cert')
        ssl_key = Config().get_config('app').get('ssl_key')
        if not ssl_cert or not ssl_key:
            log.info(f"未启用https，请使用 http://IP:{str(web_port)} 访问管理页面")
        else:
            if not os.path.exists(ssl_cert):
                log.warn(f"【Config】ssl_cert文件不存在：{ssl_cert}")
            if not os.path.exists(ssl_key):
                log.warn(f"【Config】ssl_key文件不存在：{ssl_key}")
            log.info(f"已启用https，请使用 https://IP:{str(web_port)} 访问管理页面")
    else:
        log.error("【Config】配置文件格式错误，找不到app配置项！")


def update_config():
    """
    升级配置文件
    """
    _config = Config().get_config()
    overwrite_cofig = False

    # 密码初始化
    login_password = _config.get("app", {}).get("login_password") or "password"
    if login_password and not login_password.startswith("[hash]"):
        _config['app']['login_password'] = "[hash]%s" % generate_password_hash(
            login_password)
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
        log.exception("【Config】站点数据刷新时间默认配置 设置异常: ", e)

    # 存量插件安装情况统计
    try:
        plugin_report_state = SystemConfig().get(SystemConfigKey.UserInstalledPluginsReport)
        installed_plugins = SystemConfig().get(SystemConfigKey.UserInstalledPlugins)
        if not plugin_report_state and installed_plugins:
            ret = PluginHelper().report(installed_plugins)
            if ret:
                SystemConfig().set(SystemConfigKey.UserInstalledPluginsReport, '1')
    except Exception as e:
        log.exception("【Config】存量插件安装情况统计 异常: ", e)

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
