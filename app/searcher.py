from typing import List
from app.db.models import SEARCHRESULTINFO
from app.utils.media_utils import MediaUtils
import log
from app.helper import DbHelper
from app.indexer import Indexer
from app.plugins import EventManager
from app.utils.commons import singleton
from config import Config
from app.message import Message
from app.downloader import Downloader
from app.media import Media
from app.media.meta.metainfo import MetaInfo
from app.helper import ProgressHelper
from app.utils.types import SearchType, EventType, ProgressKey


@singleton
class Searcher:
    downloader = None
    media = None
    message = None
    indexer = None
    progress = None
    dbhelper = None
    eventmanager = None

    _search_auto = True

    def __init__(self):
        self.init_config()

    def init_config(self):
        self.downloader = Downloader()
        self.media = Media()
        self.message = Message()
        self.progress = ProgressHelper()
        self.dbhelper = DbHelper()
        self.indexer = Indexer()
        self.eventmanager = EventManager()
        self._search_auto = Config().get_config("pt").get('search_auto', True)

    def search_medias(self,
                      key_word: [str, list],
                      filter_args: dict,
                      match_media=None,
                      in_from: SearchType = None) -> List[MetaInfo]:
        """
        根据关键字调用索引器检查媒体
        :param key_word: 搜索的关键字，不能为空
        :param filter_args: 过滤条件
        :param match_media: 区配的媒体信息
        :param in_from: 搜索渠道
        :return: 命中的资源媒体信息列表
        """
        if not key_word:
            return []
        if not self.indexer:
            return []
        # 触发事件
        self.eventmanager.send_event(EventType.SearchStart, {
            "key_word": key_word,
            "media_info": match_media.to_dict() if match_media else None,
            "filter_args": filter_args,
            "search_type": in_from.value if in_from else None
        })
        return self.indexer.search_by_keyword(key_word, filter_args, match_media, in_from)

    def search_one_media(self, media_info,
                         in_from: SearchType,
                         no_exists: dict,
                         sites: list = None,
                         filters: dict = None,
                         user_name=None):
        """
        只搜索和下载一个资源，用于精确搜索下载，由微信、Telegram或豆瓣调用
        :param media_info: 已识别的媒体信息
        :param in_from: 搜索渠道
        :param no_exists: 缺失的剧集清单
        :param sites: 搜索哪些站点
        :param filters: 过滤条件，为空则不过滤
        :param user_name: 用户名
        :return: 请求的资源是否全部下载完整，如完整则返回媒体信息
                 请求的资源如果是剧集则返回下载后仍然缺失的季集信息
                 搜索到的结果数量
                 下载到的结果数量，如为None则表示未开启自动下载
        """
        if not media_info:
            return None, {}, 0, 0
        # 进度计数重置
        self.progress.start(ProgressKey.Search)
        # 查找的季
        if media_info.begin_season is None:
            search_season = None
        else:
            search_season = media_info.get_season_list()
        # 查找的集
        search_episode = media_info.get_episode_list()
        if search_episode and not search_season:
            search_season = [1]
        # 过滤条件
        filter_args = {"season": search_season,
                       "episode": search_episode,
                       "year": media_info.year,
                       "type": media_info.type,
                       "site": sites,
                       "seeders": True}
        if filters:
            filter_args.update(filters)
        if media_info.keyword:
            # 直接使用搜索词搜索
            search_name = media_info.keyword
        else:
            # 中文名
            if media_info.cn_name:
                search_name = media_info.cn_name
            else:
                search_name = media_info.title

        # 开始搜索
        log.info("【Searcher】开始搜索 %s ..." % search_name)
        media_list = self.search_medias(search_name, filter_args, media_info, in_from)

        if len(media_list) == 0:
            log.info("【Searcher】 未搜索到任何资源")
            return None, no_exists, 0, 0
        else:
            if in_from in self.message.get_search_types():
                # 保存搜索记录
                self.delete_all_search_torrents()
                # 搜索结果排序
                media_list = sorted(media_list, key=lambda x: x.get_sort_str(), reverse=True)
                # 插入数据库
                self.insert_search_results(media_list)
                # 微信未开自动下载时返回
                if not self._search_auto:
                    return None, no_exists, len(media_list), None
            # 择优下载
            download_items, left_medias = self.downloader.batch_download(in_from=in_from,
                                                                         media_list=media_list,
                                                                         need_tvs=no_exists,
                                                                         user_name=user_name)
            # 统计下载情况，下全了返回True，没下全返回False
            if not download_items:
                log.info("【Searcher】%s 未下载到资源" % media_info.title)
                return None, left_medias, len(media_list), 0
            else:
                log.info("【Searcher】实际下载了 %s 个资源" % len(download_items))
                # 还有剩下的缺失，说明没下完，返回False
                if left_medias:
                    return None, left_medias, len(media_list), len(download_items)
                # 全部下完了
                else:
                    return download_items[0], no_exists, len(media_list), len(download_items)

    def get_search_result_by_id(self, dl_id) -> List[SEARCHRESULTINFO]:
        """
        根据下载ID获取搜索结果
        :param dl_id: 下载ID
        :return: 搜索结果
        """
        return self.dbhelper.get_search_result_by_id(dl_id)

    def get_search_results(self):
        """
        获取搜索结果
        :return: 搜索结果
        """
        return self.dbhelper.get_search_results()

    def delete_all_search_torrents(self):
        """
        删除所有搜索结果
        """
        self.dbhelper.delete_all_search_torrents()

    def insert_search_results(self, media_items: list, title=None, ident_flag=True):
        """
        插入搜索结果
        :param media_items: 搜索结果
        :param title: 搜索标题
        :param ident_flag: 是否标识
        """
        self.dbhelper.insert_search_results(media_items, title, ident_flag)