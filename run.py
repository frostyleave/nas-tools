import os
import signal
import warnings

import uvicorn
from fastapi import FastAPI

from config import Config
from log import setup_logging

setup_logging()

import log

# 导入FastAPI应用
from main import app
from version import APP_VERSION

warnings.filterwarnings('ignore')

# 运行环境判断
is_windows = os.name == "nt"

if is_windows:
    import mimetypes
    # fix Windows registry stuff
    mimetypes.add_type('application/javascript', '.js')
    mimetypes.add_type('text/css', '.css')


def sigal_handler(num, stack):
    """
    信号处理
    """
    log.warn(f'捕捉到退出信号：{num}, 开始退出...')

    # 退出主进程
    log.info('退出主进程...')
    server.should_exit = True
    os._exit(0)


# 事件绑定
signal.signal(signal.SIGINT, sigal_handler)
signal.signal(signal.SIGTERM, sigal_handler)

# 生成运行配置
def get_run_config(app: FastAPI) -> uvicorn.Config:

    _web_host = '0.0.0.0'
    _web_port = 3000
    _log_level = 'info'

    app_conf = Config().get_config('app')

    if app_conf:
        _web_host = app_conf.get('_web_host', '0.0.0.0')
        _log_level = app_conf.get('loglevel', 'info')

    # 生成配置
    uvicorn_config = uvicorn.Config(app, 
                                    host=_web_host, 
                                    port=_web_port,
                                    reload=False,
                                    log_level=_log_level,
                                    workers=1,
                                    timeout_graceful_shutdown=60)

    return uvicorn_config


def set_git_proxy():

    if is_windows:
        return

    proxy_config = Config().get_proxies()
    if not proxy_config:
        return
    http_proxy = proxy_config.get('http')
    if not http_proxy:
        return
    
    try:
        import subprocess

        # 设置 http.proxy
        result = subprocess.run(
            ['git', 'config', '--global', 'http.proxy', http_proxy],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            log.error(f'❌ 设置Git HTTP代理失败: {result.stderr.strip()}')
            return

        # 设置 https.proxy
        https_proxy = proxy_config.get('https', http_proxy)
        result = subprocess.run(
            ['git', 'config', '--global', 'https.proxy', https_proxy],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            log.error(f'❌ 设置Git HTTPS代理失败: {result.stderr.strip()}')

        log.info('✅ Git 代理已设置')
    except Exception as e:
        log.error(f'❌ 执行git config异常: {e!s}')


def init_system():
    from app.core.initializer import (
        check_config,
        init_admin_user,
        init_data,
        update_config,
    )
    # 配置
    log.debug(f'NAStool 当前版本号：{APP_VERSION}')
    # 数据初始化
    init_data()
    # 升级配置文件
    update_config()
    # 初始化系统管理员账号
    init_admin_user()
    # 检查配置文件
    check_config()
    # 设置git代理
    set_git_proxy()


# uvicorn服务
server_conf = get_run_config(app)
server = uvicorn.Server(server_conf)


# 本地运行
if __name__ == '__main__':

    try:
        
        # 系统初始化
        init_system()

        # 启动服务器
        server.run()

    except Exception as e:
        print(str(e))
        log.exception('启动FastAPI应用时出错')
