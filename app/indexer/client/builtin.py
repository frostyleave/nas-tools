import datetime

from typing import List, Optional, Tuple

import log

from app.conf import SystemConfig
from app.helper import ProgressHelper
from app.indexer.client._base import _IIndexClient
from app.indexer.client import TorrentSpider, TNodeSpider, TorrentLeech, InterfaceSpider, MTorrentSpider
from app.indexer.manager import IndexerManager, IndexerInfo
from app.media.meta.metainfo import MetaInfo
from app.sites import SitesManager
from app.utils import StringUtils
from app.utils.types import MediaType, SearchType, IndexerType, ProgressKey, SystemConfigKey


class BuiltinIndexer(_IIndexClient):

    # 索引器ID
    client_id = "builtin"
    # 索引器类型
    client_type = IndexerType.BUILTIN
    # 索引器名称
    client_name = IndexerType.BUILTIN.value

    @classmethod
    def match(cls, ctype):
        return True if ctype in [cls.client_id, cls.client_type, cls.client_name] else False

    def get_type(self):
        return self.client_type

    def get_status(self):
        """
        检查连通性
        :return: True、False
        """
        return True

    def get_indexers(self, check=True, indexer_id=None, public=True) -> List[IndexerInfo]:

        ret_indexers = []

        # 选中站点配置
        indexer_sites = SystemConfig().get(SystemConfigKey.UserIndexerSites) or []
        _indexer_domains = []

        # PT站点
        for pt_site in SitesManager().get_sites():
            url = pt_site.signurl or pt_site.rssurl
            if not url:
                continue
            render = pt_site.chrome
            indexer_conf = IndexerManager().build_indexer_conf(url=url,
                                                  siteid=pt_site.id,
                                                  cookie=pt_site.cookie,
                                                  token=pt_site.token,
                                                  apikey=pt_site.apikey,
                                                  ua=pt_site.ua,
                                                  name=pt_site.name,
                                                  rule=pt_site.rule,
                                                  pri=pt_site.pri,
                                                  public=False,
                                                  proxy=pt_site.proxy,
                                                  render=render)
            if indexer_conf:
                if indexer_id and indexer_conf.id == indexer_id:
                    return indexer_conf
                if check and (not indexer_sites or indexer_conf.id not in indexer_sites):
                    continue
                if indexer_conf.domain not in _indexer_domains:
                    _indexer_domains.append(indexer_conf.domain)
                    indexer_conf.name = pt_site.name
                    ret_indexers.append(indexer_conf)
        # 公开站点
        for base_item in IndexerManager().get_all_indexer_Base():
            if not base_item.public:
                continue
            if indexer_id and base_item.id == indexer_id:
                conf_data = IndexerManager().prepare_datas(conf_data=base_item)
                return IndexerInfo.from_datas(conf_data)
            
            if check and (not indexer_sites or base_item.id not in indexer_sites):
                continue

            if base_item.domain not in _indexer_domains:
                _indexer_domains.append(base_item.domain)
                conf_data = IndexerManager().prepare_datas(conf_data=base_item)
                ret_indexers.append(IndexerInfo.from_datas(conf_data))
        
        return None if indexer_id else ret_indexers

    def search(self, 
               order_seq,
               indexer: IndexerInfo,
               key_word: str,
               filter_args: dict,
               match_media,
               in_from: SearchType) -> List[MetaInfo]:
        """
        根据关键字搜索资源并过滤
        """
        if not indexer or not key_word:
            return None
        
        if SearchType.WEB == in_from:
            search_progress = ProgressHelper()
        else:
            search_progress = None

        # 站点流控
        sites_manager = SitesManager()
        if sites_manager.check_ratelimit(indexer.siteid):
            if search_progress:
                search_progress.update(ptype=ProgressKey.Search, text=f"{indexer.name} 触发站点流控，跳过 ...")
            return []

        if filter_args is None:
            filter_args = {}

        # 不在设定搜索范围的站点过滤掉
        if filter_args.get("site") and indexer.name not in filter_args.get("site"):
            return []
        
        # 搜索条件没有过滤规则时，使用站点的过滤规则
        if not filter_args.get("rule") and indexer.rule:
            filter_args.update({"rule": indexer.rule})

        log.info(f"【索引器】开始搜索{indexer.name} ...")

        # 特殊符号处理
        search_word = StringUtils.handler_special_chars(text=key_word, replace_word=" ", allow_space=True)
        # 类型
        mtype = match_media.type if match_media and match_media.tmdb_info else None
       
        # 当前时间
        start_time = datetime.datetime.now()

        # 开始索引
        error_flag, result_array = self.search_torrents(indexer, search_word, mtype)

        # 计算耗时
        seconds = round((datetime.datetime.now() - start_time).seconds, 1)
        
        result_count = len(result_array)
        # 没有结果
        if result_count == 0:
            result_info = '搜索失败' if error_flag else '未搜索到数据'
            summary_txt = f"【索引器】{indexer.name} {result_info}, 用时: {seconds}s"
            log.info(summary_txt)
            # 更新进度
            if search_progress:
                search_progress.update(ptype=ProgressKey.Search, text=summary_txt)
            return []
        
        # 有搜索结果
        summary_txt = f"【索引器】{indexer.name} 返回数据：{result_count}, 用时: {seconds}s"
        # 记录日志
        log.info(summary_txt)
        # 更新进度
        if search_progress:
            search_progress.update(ptype=ProgressKey.Search, text=summary_txt)

        # 结果过滤
        return self.filter_search_results(result_array=result_array,
                                          order_seq=order_seq,
                                          indexer=indexer,
                                          filter_args=filter_args,
                                          search_media=match_media,
                                          start_time=start_time)


    def search_torrents(self, indexer: IndexerInfo, search_word: str='', mtype: Optional[MediaType]=None) -> Tuple[bool, list]:
        """
        根据关键字搜索资源
        """
        try:

            if indexer.parser == "TNodeSpider":
                return TNodeSpider(indexer).search(keyword=search_word)
            
            if indexer.parser == "TorrentLeech":
                return TorrentLeech(indexer).search(keyword=search_word)
            
            if indexer.parser == "InterfaceSpider":
                return InterfaceSpider(indexer).search(keyword=search_word, mtype=mtype)
            
            if indexer.parser == "MTorrentSpider":
                return MTorrentSpider(indexer).search(keyword=search_word, mtype=mtype)
            
            return TorrentSpider(indexer).search(keyword=search_word, mtype=mtype)
        
        except Exception as err:
            log.exception(f'【索引器】[{indexer.name}]执行搜索异常: ', err)
            return True, []