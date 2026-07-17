

import os
import signal

import zhconv

from app.core.jobcenter import JobCenter
from app.core.scheduler import Scheduler
from app.downloader import Downloader

from app.helper import ThreadHelper, DisplayHelper

from app.indexer.manager import IndexerManager
from app.modules.brushtaskv2 import BrushTaskV2 as BrushTask
from app.modules.rsschecker import RssChecker
from app.modules.sync import Sync
from app.modules.torrentremover import TorrentRemover
from app.plugins import PluginManager
from app.sites import SiteConf

class ServiceManager:

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
        # 启动虚拟显示
        DisplayHelper()
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
        关闭服务
        """
        # 停止定时服务
        Scheduler().stop_service()
        # 停止监控
        Sync().stop_service()
        # 关闭虚拟显示
        DisplayHelper().stop_service()
        # 关闭刷流
        BrushTask().stop_service()
        # 关闭自定义订阅
        RssChecker().stop_service()
        # 关闭自动删种
        TorrentRemover().stop_service()
        # 关闭下载器监控
        Downloader().stop_service()
        # 关闭插件
        PluginManager().stop_service()
        # 清理定时器
        JobCenter().stop_service()

    @staticmethod
    def restart_service():
        """
        重启服务
        """
        ServiceManager.stop_service()
        ServiceManager.start_service()

    @staticmethod
    def restart_server():
        """
        停止进程
        """
        # 关闭服务
        ServiceManager.stop_service()

        # 重启进程
        if os.name == "nt":
            os.kill(os.getpid(), getattr(signal, "SIGKILL", signal.SIGTERM))
            return
        
        if SystemUtils.is_synology():
            os.system(
                "ps -ef | grep -v grep | grep 'python run.py'|awk '{print $2}'|xargs kill -9")
            return

        if SystemUtils.check_process('node'):
            os.system("pm2 restart NAStool")
        else:
            log.info("kill $(pgrep -f 'python3 run.py')")
            os.system("kill $(pgrep -f 'python3 run.py')")
            # os.system("pkill -f 'python3 run.py'")

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
