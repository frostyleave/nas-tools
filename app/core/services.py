

import os
import signal
import threading

import log
from app.core.jobcenter import JobCenter
from app.core.runtime_state import request_shutdown
from app.core.scheduler import Scheduler
from app.downloader import Downloader
from app.helper import BrowserHelper, ThreadHelper
from app.indexer.manager import IndexerManager
from app.modules.brushtaskv2 import BrushTaskV2 as BrushTask
from app.modules.rsschecker import RssChecker
from app.modules.sync import Sync
from app.modules.torrentremover import TorrentRemover
from app.plugins import PluginManager
from app.sites import SiteConf
from app.utils import zhconv_compat as zhconv

# 重启时等待服务清理的最长时间（秒），超时后直接退出，避免被长任务卡住
RESTART_STOP_TIMEOUT = 10
# 发出退出信号后仍未结束时的强制退出时间（秒）
RESTART_EXIT_TIMEOUT = 25
# 主动重启使用的退出码：非 0 才能让 restart: on-failure 策略也重新拉起容器
RESTART_EXIT_CODE = 1


def _force_exit():
    """
    优雅关闭超时后的强制退出
    """
    log.error(f'【System】优雅关闭超过 {RESTART_EXIT_TIMEOUT} 秒，强制退出')
    os._exit(RESTART_EXIT_CODE)


class ServiceManager:

    # 重启互斥，避免重复请求并发执行清理和退出
    _restart_lock = threading.Lock()
    _restarting = False

    @staticmethod
    def start_service():
        """
        启动服务
        """
        JobCenter()
        ThreadHelper()
        # 加载索引器配置
        IndexerManager()
        # 加载站点配置
        SiteConf()
        # 检测浏览器仿真环境
        BrowserHelper()
        # 启动定时服务
        Scheduler()
        # 启动监控服务
        Sync()
        # 启动刷流服务
        BrushTask()
        # 启动自定义订阅服务
        RssChecker()
        # 启动自动删种服务
        TorrentRemover()
        # 加载插件
        PluginManager()
        # 打印定时任务列表
        JobCenter().print_jobs()

    @staticmethod
    def stop_service():
        """
        关闭服务（逐项兜底，单项失败不影响后续清理）
        """
        steps = (
            ("定时服务", lambda: Scheduler().stop_service()),
            ("目录监控", lambda: Sync().stop_service()),
            ("浏览器仿真与虚拟显示", lambda: BrowserHelper().stop_service()),
            ("刷流服务", lambda: BrushTask().stop_service()),
            ("自定义订阅", lambda: RssChecker().stop_service()),
            ("自动删种", lambda: TorrentRemover().stop_service()),
            ("下载器监控", lambda: Downloader().stop_service()),
            ("插件", lambda: PluginManager().stop_service()),
            ("定时器", lambda: JobCenter().stop_service()),
        )
        for name, func in steps:
            try:
                func()
            except Exception:
                log.exception(f'【System】关闭{name}出错：')

    @staticmethod
    def stop_service_bounded(timeout: int = RESTART_STOP_TIMEOUT):
        """
        在独立线程中关闭服务，超时后不再等待
        """
        stop_thread = threading.Thread(
            target=ServiceManager.stop_service,
            name='stop-service',
            daemon=True,
        )
        stop_thread.start()
        stop_thread.join(timeout=timeout)
        if stop_thread.is_alive():
            log.warn(f'【System】服务清理超过 {timeout} 秒仍未完成，继续关闭')

    @staticmethod
    def is_restarting() -> bool:
        """
        是否正在执行进程重启
        """
        return ServiceManager._restarting

    @staticmethod
    def restart_server():
        """
        停止服务并退出进程，由外部（容器重启策略或进程守护）重新启动
        """
        with ServiceManager._restart_lock:
            if ServiceManager._restarting:
                log.warn('【System】重启已在进行中，忽略重复请求')
                return
            ServiceManager._restarting = True

        # 通知常驻流式响应（如日志 SSE）尽快结束，缩短优雅关闭的等待时间
        request_shutdown()

        # 服务清理可能被长任务阻塞，限时等待后继续退出
        ServiceManager.stop_service_bounded()

        ServiceManager._exit_process()

    @staticmethod
    def _exit_process():
        """
        退出当前进程：先走优雅关闭，超时后强制退出
        """
        if os.name == "nt":
            # Windows 上对 SIGTERM 的 os.kill 等同 TerminateProcess，无法优雅关闭
            log.warn('【System】Windows 环境退出后不会自动拉起，请手动重新启动程序')
            os.kill(os.getpid(), signal.SIGTERM)
            return

        # 兜底定时器：优雅关闭未在限定时间内完成时直接退出
        timer = threading.Timer(RESTART_EXIT_TIMEOUT, _force_exit)
        timer.daemon = True
        timer.start()
        os.kill(os.getpid(), signal.SIGTERM)

    @staticmethod
    def pre_warming_zhconv():
        print("Pre-warming zhconv cache...")
        try:
            # 1. 预热 convert()，使其加载 "zh-hans" 相关的字典
            _ = zhconv.convert("预热", 'zh-hans')
            
            # 2. (重要) 预热 issimp()，使其加载简体字检查相关的字典
            _ = zhconv.issimp("预热")
            
            print("zhconv cache pre-warmed successfully.")
        except Exception as e:
            print(f"Warning: Failed to pre-warm zhconv cache: {e}")
