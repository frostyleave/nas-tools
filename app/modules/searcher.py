from typing import List, Tuple

from app.core.task_manager import GlobalTaskManager
from app.helper import DbHelper
from app.media import Media
from app.media.meta.metainfo import MetaInfo
from app.message import Message
from app.indexer import Indexer
from app.utils.commons import singleton
from app.utils.constants import Constants
from app.utils.types import SearchType


@singleton
class Searcher:
    """
    资源搜索器
    """
    media = None
    message = None
    indexer = None
    progress = None
    dbhelper = None

    def __init__(self):
        self.init_config()

    def init_config(self):
        self.media = Media()
        self.message = Message()
        self.dbhelper = DbHelper()
        self.indexer = Indexer()

    def search_torrents(self,
                        key_word: str,
                        filter_args: dict,
                        match_media=None,
                        in_from: SearchType = None,
                        search_theme: str = None,
                        task_id=None,
                        ident_flag:bool=False) -> List[MetaInfo]:
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

        if task_id:
            GlobalTaskManager().update_task(task_id=task_id, progress=1, message="开始搜索 %s ..." % search_theme)

        torrent_list = self.indexer.search_by_keyword(key_word, filter_args, match_media, in_from, task_id)

        # 清空上次结果
        self.delete_all_search_torrents()
        # 排序, 入库
        if torrent_list and (in_from == SearchType.WEB or in_from in self.message.get_search_types()):
            # 排序
            torrent_list = sorted(torrent_list, key=lambda x: x.get_sort_str(), reverse=True)
            # 插入数据库
            self.insert_search_results(media_items=torrent_list, ident_flag=ident_flag, title=search_theme)

        # 结束进度
        if task_id:
            GlobalTaskManager().finish_task(task_id=task_id, message="搜索完成", result=len(torrent_list))

        return torrent_list


    def get_search_result_info_by_id(self, res_id) -> Tuple[MetaInfo, str]:
        """
        根据下载ID获取搜索结果
        :param res_id: 下载ID
        :return: 搜索结果
        """

        if not res_id:
            return None, '搜索结果查询失败, 结果id为空'

        results = self.dbhelper.get_search_result_by_id(res_id)
        if not results:
            return None, '搜索结果查询失败, 请刷新页面后重试'

        # 结果只会有1个
        resource_info = results[0]

        # 搜索结果没有被识别
        if not resource_info.TMDBID or resource_info.TMDBID == '0':
            # 根据名称和描述信息识别资源
            media_info = self.media.get_media_info(title=resource_info.TORRENT_NAME, subtitle=resource_info.DESCRIPTION)
            if not media_info:
                return None, '无法识别该资源'
            
            # 更新tmdb_id
            if media_info.tmdb_id:
                self.dbhelper.update_search_results_date(resource_info.ID, media_info.tmdb_id)
        else:
            # 搜索结果已被识别
            mtype = Constants.MEDIA_TYPE_MAP.get(resource_info.TYPE, None)
            # 查询TMDB详情
            info = self.media.get_tmdb_info(tmdbid=resource_info.TMDBID, mtype=mtype, append_to_response="all")
            if not info:
                return None, '查询TMDB详情失败'
            
            media_info = MetaInfo(f'{resource_info.TITLE} {resource_info.ES_STRING}')
            media_info.year = resource_info.YEAR
            media_info.org_string = resource_info.TORRENT_NAME
            media_info.set_tmdb_info(info)

        # 结果组装
        media_info.set_torrent_info(enclosure=resource_info.ENCLOSURE,
                                    size=resource_info.SIZE,
                                    site=resource_info.SITE,
                                    page_url=resource_info.PAGEURL,
                                    upload_volume_factor=float(resource_info.UPLOAD_VOLUME_FACTOR),
                                    download_volume_factor=float(resource_info.DOWNLOAD_VOLUME_FACTOR))

        return media_info, ''

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