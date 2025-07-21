import datetime
import traceback
from typing import List

import log

from app.conf import SystemConfig
from app.helper import ProgressHelper, DbHelper
from app.indexer.client._base import _IIndexClient
from app.indexer.client import Rarbg, TorrentSpider, TNodeSpider, TorrentLeech, InterfaceSpider, MTorrentSpider
from app.indexer.manager import IndexerManager, IndexerConf
from app.media.meta.metainfo import MetaInfo
from app.sites import Sites
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
        self.sites = Sites()
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

    def get_indexers(self, check=True, indexer_id=None, public=True) -> List[IndexerConf]:

        ret_indexers = []

        # 选中站点配置
        indexer_sites = SystemConfig().get(SystemConfigKey.UserIndexerSites) or []
        _indexer_domains = []

        # 私有站点
        for site in Sites().get_sites():
            url = site.get("signurl") or site.get("rssurl")
            if not url:
                continue
            render = site.get("chrome")
            indexer = IndexerManager().build_indexer_conf(url=url,
                                                  siteid=site.get("id"),
                                                  cookie=site.get("cookie"),
                                                  token=site.get("token"),
                                                  apikey=site.get("apikey"),
                                                  ua=site.get("ua"),
                                                  name=site.get("name"),
                                                  rule=site.get("rule"),
                                                  pri=site.get('pri'),
                                                  public=False,
                                                  proxy=site.get("proxy"),
                                                  render=render)
            if indexer:
                if indexer_id and indexer.id == indexer_id:
                    return indexer
                if check and (not indexer_sites or indexer.id not in indexer_sites):
                    continue
                if indexer.domain not in _indexer_domains:
                    _indexer_domains.append(indexer.domain)
                    indexer.name = site.get("name")
                    ret_indexers.append(indexer)
        # 公开站点
        for indexer in IndexerManager().get_all_indexers():
            if not indexer.get("public"):
                continue
            if indexer_id and indexer.get("id") == indexer_id:
                return IndexerConf(datas=indexer)
            if check and (not indexer_sites or indexer.get("id") not in indexer_sites):
                continue
            if indexer.get("domain") not in _indexer_domains:
                _indexer_domains.append(indexer.get("domain"))
                ret_indexers.append(IndexerConf(datas=indexer))
        
        return None if indexer_id else ret_indexers

    def search(self, order_seq,
               indexer: IndexerConf,
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

        log.info(f"【{self.client_name}】开始搜索Indexer：{indexer.name} ...")
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
                error_flag, result_array = TorrentSpider(indexer).search_torrents(keyword=search_word, mtype=mtype)
        except Exception as err:
            log.error("【%s】%s搜索执行出错: %s - %s" % (self.client_name, indexer.name, str(err), traceback.format_exc()))
            error_flag = True

        # 索引花费的时间
        seconds = round((datetime.datetime.now() - start_time).seconds, 1)
        # 索引统计
        self.dbhelper.insert_indexer_statistics(indexer=indexer.name,
                                                itype=self.client_id,
                                                seconds=seconds,
                                                result='N' if error_flag else 'Y')
        # 返回结果
        if len(result_array) == 0:
            log.warn(f"【{self.client_name}】{indexer.name} 未搜索到数据")
            # 更新进度
            self.progress.update(ptype=ProgressKey.Search, text=f"{indexer.name} 未搜索到数据")
            return []
        else:
            log.warn(f"【{self.client_name}】{indexer.name} 返回数据：{len(result_array)}")
            # 更新进度
            self.progress.update(ptype=ProgressKey.Search, text=f"{indexer.name} 返回 {len(result_array)} 条数据")
            # 过滤
            return self.filter_search_results(result_array=result_array,
                                              order_seq=order_seq,
                                              indexer=indexer,
                                              filter_args=filter_args,
                                              search_media=match_media,
                                              start_time=start_time)
