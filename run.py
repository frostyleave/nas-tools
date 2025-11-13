import logging
import multiprocessing
import os
import signal
import sys
import warnings
import uvicorn

from fastapi import FastAPI

from config import Config

from log import setup_logging
setup_logging()

import log

from app.db import init_db, update_db, init_data
from initializer import update_config, check_config

# 导入FastAPI应用
from web.app import app
from version import APP_VERSION

warnings.filterwarnings('ignore')

# 运行环境判断
is_windows = os.name == "nt"
is_executable = getattr(sys, 'frozen', False)
is_windows_exe = is_executable and is_windows

if is_windows:
    import mimetypes
    # fix Windows registry stuff
    mimetypes.add_type('application/javascript', '.js')
    mimetypes.add_type('text/css', '.css')

if is_windows_exe:
    # 托盘相关库
    import threading
    from package.trayicon import TrayIcon, NullWriter

if is_executable:
    # 可执行文件初始化环境变量
    config_path = os.path.join(os.path.dirname(sys.executable), "config").replace("\\", "/")
    os.environ["NASTOOL_CONFIG"] = os.path.join(config_path, "config.yaml").replace("\\", "/")
    os.environ["NASTOOL_LOG"] = os.path.join(config_path, "logs").replace("\\", "/")
    try:
        if not os.path.exists(config_path):
            os.makedirs(config_path)
    except Exception as err:
        print(str(err))


def sigal_handler(num, stack):
    """
    信号处理
    """
    log.warn('捕捉到退出信号：%s, 开始退出...' % num)

    # 退出主进程
    log.info('退出主进程...')
    server.should_exit = True
    os._exit(0)


# 事件绑定
signal.signal(signal.SIGINT, sigal_handler)
signal.signal(signal.SIGTERM, sigal_handler)

# 生成运行配置
def get_run_config(app: FastAPI) -> uvicorn.Config:

    _web_host = "0.0.0.0"
    _web_port = 3000
    _log_level = 'info'

    app_conf = Config().get_config('app')

    if app_conf:
        _web_port_conf = app_conf.get('web_port', '')
        _web_port = int(_web_port_conf) if str(_web_port_conf).isdigit() else 3000
        _log_level = app_conf.get('loglevel', 'info')

    cpu_count = multiprocessing.cpu_count()
    # 生成配置
    uvicorn_config = uvicorn.Config(app, 
                                    host=_web_host, 
                                    port=_web_port,
                                    reload=False,
                                    log_level=_log_level,
                                    workers=cpu_count,
                                    timeout_graceful_shutdown=60)

    return uvicorn_config


def init_system():
    # 配置
    log.debug('NAStool 当前版本号：%s' % APP_VERSION)
    # 数据库初始化
    init_db()
    # 数据库更新
    update_db()
    # 数据初始化
    init_data()
    # 升级配置文件
    update_config()
    # 检查配置文件
    check_config()


# uvicorn服务
server_conf = get_run_config(app)
server = uvicorn.Server(server_conf)


# 本地运行
if __name__ == '__main__':
   
    # Windows启动托盘
    if is_windows_exe:
        homepage = Config().get_config('app').get('domain')
        if not homepage:
            homepage = "http://localhost:%s" % str(Config().get_config('app').get('web_port'))
            
        log_path = os.environ.get("NASTOOL_LOG")

        sys.stdout = NullWriter()
        sys.stderr = NullWriter()

        def traystart():
            TrayIcon(homepage, log_path)

        if len(os.popen("tasklist| findstr %s" % os.path.basename(sys.executable), 'r').read().splitlines()) <= 2:
            p1 = threading.Thread(target=traystart, daemon=True)
            p1.start()

    try:
        
        # 系统初始化
        init_system()

        # 启动服务器
        server.run()

    except Exception as e:
        print(str(e))
        log.exception('启动FastAPI应用时出错')
