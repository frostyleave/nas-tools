import datetime
import traceback
from typing import List

import log

from app.conf import SystemConfig
from app.helper import ProgressHelper, DbHelper
from app.indexer.client._base import _IIndexClient
from app.indexer.client import Rarbg, TorrentSpider, TNodeSpider, TorrentLeech, InterfaceSpider, MTorrentSpider
from app.indexer.manager import IndexerManager, IndexerInfo
from app.media.meta.metainfo import MetaInfo
from app.sites import SitesManager
from app.utils import StringUtils
from app.utils.types import SearchType, IndexerType, ProgressKey, SystemConfigKey

from config import Config


class BuiltinIndexer(_IIndexClient):
    # 索引器ID
    client_id = "builtin"
    # 索引器类型
    client_type = IndexerType.BUILTIN
    # 索引器名称
    client_name = IndexerType.BUILTIN.value

    # 私有属性
    _client_config = {}
    _show_more_sites = False
    progress = None
    sites = None
    dbhelper = None

    def __init__(self, config=None):
        super().__init__()
        self._client_config = config or {}
        self.init_config()

    def init_config(self):
        self.sites = SitesManager()
        self.progress = ProgressHelper()
        self.dbhelper = DbHelper()
        self._show_more_sites = Config().get_config("laboratory").get('show_more_sites')

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

    def search(self, order_seq,
               indexer: IndexerInfo,
               key_word,
               filter_args: dict,
               match_media,
               in_from: SearchType) -> List[MetaInfo]:
        """
        根据关键字多线程搜索
        """
        if not indexer or not key_word:
            return None
        # 站点流控
        if self.sites.check_ratelimit(indexer.siteid):
            self.progress.update(ptype=ProgressKey.Search, text=f"{indexer.name} 触发站点流控，跳过 ...")
            return []
        # fix 共用同一个dict时会导致某个站点的更新全局全效
        if filter_args is None:
            filter_args = {}

        # 不在设定搜索范围的站点过滤掉
        if filter_args.get("site") and indexer.name not in filter_args.get("site"):
            return []
        # 搜索条件没有过滤规则时，使用站点的过滤规则
        if not filter_args.get("rule") and indexer.rule:
            filter_args.update({"rule": indexer.rule})
        # 计算耗时
        start_time = datetime.datetime.now()

        log.info(f"【{self.client_name}】开始搜索{indexer.name} ...")
        # 特殊符号处理
        search_word = StringUtils.handler_special_chars(text=key_word, replace_word=" ", allow_space=True)

        # 开始索引
        result_array = []
        try:
            mtype = match_media.type if match_media and match_media.tmdb_info else None

            if indexer.parser == "TNodeSpider":
                error_flag, result_array = TNodeSpider(indexer).search(keyword=search_word)
            elif indexer.parser == "RarBg":
                imdb_id=match_media.imdb_id if match_media else None
                error_flag, result_array = Rarbg(indexer).search(keyword=search_word, imdb_id=imdb_id)
            elif indexer.parser == "TorrentLeech":
                error_flag, result_array = TorrentLeech(indexer).search(keyword=search_word)
            elif indexer.parser == "InterfaceSpider":
                error_flag, result_array = InterfaceSpider(indexer).search(keyword=search_word, mtype=mtype)
            elif indexer.parser == "MTorrentSpider":
                error_flag, result_array = MTorrentSpider(indexer).search(keyword=search_word, mtype=mtype)
            else:
                error_flag, result_array = TorrentSpider(indexer).search(keyword=search_word, mtype=mtype)
        except Exception as err:
            log.error("【%s】%s搜索执行出错: %s - %s" % (self.client_name, indexer.name, str(err), traceback.format_exc()))
            error_flag = True

        # 索引花费的时间
        seconds = round((datetime.datetime.now() - start_time).seconds, 1)
        
        result_count = len(result_array)
        # 没有结果
        if result_count == 0:
            result_info = '搜索失败' if error_flag else '未搜索到数据'
            summary_txt = f"【{self.client_name}】{indexer.name} {result_info}, 用时: {seconds}s"
            log.info(summary_txt)
            # 更新进度
            self.progress.update(ptype=ProgressKey.Search, text=summary_txt)
            return []
        
        # 有搜索结果
        summary_txt = f"【{self.client_name}】{indexer.name} 返回数据：{result_count}, 用时: {seconds}s"
        log.info(summary_txt)
        # 更新进度
        self.progress.update(ptype=ProgressKey.Search, text=summary_txt)
        # 过滤
        return self.filter_search_results(result_array=result_array,
                                              order_seq=order_seq,
                                              indexer=indexer,
                                              filter_args=filter_args,
                                              search_media=match_media,
                                              start_time=start_time)
