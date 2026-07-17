

from app.downloader.downloader import Downloader
from app.helper.rss_helper import RssHelper
from app.modules.filetransfer import FileTransfer
from app.modules.rss import Rss
from app.modules.subscribe import Subscribe
from app.modules.sync import Sync
from app.modules.torrentremover import TorrentRemover
from app.sites.site_statistics import SitesDataStatisticsCenter


class CommandRegistry:

    _commands: dict = None

    @classmethod
    def get_commands(cls):
        if cls._commands is None:
            cls._commands = {
                "/ptr": {"func": TorrentRemover().auto_remove_torrents, "desc": "自动删种"},
                "/ptt": {"func": Downloader().transfer, "desc": "下载文件转移"},
                "/rst": {"func": Sync().transfer_sync, "desc": "目录同步"},
                "/rss": {"func": Rss().rssdownload, "desc": "电影/电视剧订阅"},
                "/ssa": {"func": Subscribe().subscribe_search_all, "desc": "订阅搜索"},
                "/tbl": {"func": FileTransfer().truncate_transfer_blacklist, "desc": "清理转移缓存"},
                "/trh": {"func": cls.truncate_rsshistory, "desc": "清理RSS缓存"},
                "/utf": {"func": FileTransfer().re_identification_all, "desc": "重新识别"},
                "/sta": {"func": SitesDataStatisticsCenter().refresh_site_data_now, "desc": "站点数据统计"}
            }
        return cls._commands

    def get(self, cmd: str):
        return self.get_commands().get(cmd)
    
    def list_commands(self):
        return [{"id": cid, "name": c.get("desc")} for cid, c in self.get_commands().items()]

    def truncate_rsshistory(self):
        """
        清空RSS历史记录
        """
        RssHelper().truncate_rss_history()
        Subscribe().truncate_rss_episodes()
        return {"code": 0}