import copy
import datetime
import multiprocessing

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from typing import List, Optional

import log

from app.indexer.client.builtin import BuiltinIndexer
from app.indexer.manager import IndexerInfo
from app.media import Media
from app.media.meta._base import MetaBase
from app.media.meta.metainfo import MetaInfo
from app.utils import StringUtils
from app.utils.commons import singleton
from app.utils.types import SearchType
from app.task_manager import GlobalTaskManager

from config import INDEXER_CATEGORY


@singleton
class Indexer(object):

    _client = None
    _client_type = None

    def __init__(self):
        self.init_config()

    def init_config(self):
        self._client = BuiltinIndexer()
        self._client_type = self._client.get_type()

    def get_indexers(self, check=False, filter_limit=False):
        """
        获取当前索引器的索引站点
        """
        if not self._client:
            return []
        return self._client.get_indexers(check=check, filter_limit=filter_limit)

    def get_user_indexer_dict(self):
        """
        获取用户已经选择的索引器字典
        """
        return [
            {
                "id": index.id,
                "name": index.name
            } for index in self.get_indexers(check=True)
        ]

    def get_indexer_hash_dict(self):
        """
        获取全部的索引器Hash字典
        """
        IndexerDict = {}
        for item in self.get_indexers() or []:
            IndexerDict[StringUtils.md5_hash(item.name)] = {
                "id": item.id,
                "name": item.name,
                "public": item.public,
                "builtin": item.builtin
            }
        return IndexerDict

    def get_user_indexer_names(self):
        """
        获取当前用户选中的索引器的索引站点名称
        """
        return [indexer.name for indexer in self.get_indexers(check=True)]

    def list_resources(self, index_id, page=0, keyword=None):
        """
        获取内置索引器的资源列表
        :param index_id: 内置站点ID
        :param page: 页码
        :param keyword: 搜索关键字
        """
        return self._client.list(index_id=index_id, page=page, keyword=keyword)

    def get_client(self):
        """
        获取当前索引器
        """
        return self._client

    def search_by_keyword(self,
                          key_word: str,
                          filter_args: dict,
                          match_media: Optional[MetaBase]=None,
                          in_from: Optional[SearchType]=None,
                          task_id=None) -> List[MetaInfo]:
        """
        根据关键字调用 Index API 搜索
        :param key_word: 搜索的关键字，不能为空
        :param filter_args: 过滤条件，对应属性为空则不过滤，{"season":季, "episode":集, "year":年, "type":类型, "site":站点,
                            "":, "restype":质量, "pix":分辨率, "sp_state":促销状态, "key":其它关键字}
                            sp_state: 为UL DL，* 代表不关心，
        :param match_media: 需要匹配的媒体信息
        :param in_from: 搜索渠道
        :return: 命中的资源媒体信息列表
        """
        if not key_word:
            return []

        search_indexers = self.get_indexers(check=True, filter_limit=True)
        if not search_indexers:
            log.error("没有配置索引器，无法搜索！")
            return []

        if filter_args is None:
            filter_args = {}

        if filter_args.get('site'):
            filter_sites = filter_args.get('site')
            search_indexers = list(filter(lambda x: x.name in filter_sites, search_indexers))            
        elif match_media and match_media.type and match_media.type.name in INDEXER_CATEGORY:
            search_indexers = list(filter(lambda x: not x.source_type or match_media.type.name in x.source_type, search_indexers))

        if not search_indexers:
            log.warn("没有配置符合条件的索引器，无法搜索！")
            return []
        
        ret_array = []

        # 计算耗时
        start_time = datetime.datetime.now()
        if filter_args and filter_args.get("site"):
            log_info = f"【{self._client_type.value}】开始搜索 %s, 站点: %s ..." % (key_word, filter_args.get("site"))
            log.info(log_info)
            self.update_process(task_id=task_id, process_val=5, text=log_info)
        else:
            log_info = f"【{self._client_type.value}】开始并行搜索 {key_word} ..."
            log.info(log_info)
            self.update_process(task_id=task_id, process_val=5, text=log_info)

        cpu_cores = max(1, multiprocessing.cpu_count() - 2)
        process_count = min(cpu_cores, len(search_indexers))

        # 设置进度参数
        self._client.set_step_fator(int(30 / len(search_indexers)))

        # 1. 将索引器列表切分为子列表
        indexer_chunks = list(self._chunk_list(search_indexers, process_count))

        ret_array = []
        # 2. 提交任务给进程池
        with ProcessPoolExecutor(max_workers=process_count) as executor:
            all_tasks = []
            for chunk in indexer_chunks:
                if not chunk: 
                    continue                
                task = executor.submit(exec_search_by_threads, self._client, chunk, key_word, filter_args, match_media, in_from, task_id)
                all_tasks.append(task)

            for future in as_completed(all_tasks):
                try:
                    result_list = future.result() 
                    if result_list:
                        ret_array.extend(result_list)
                except Exception as e:
                    log.exception("【Indexer】搜索进程结果处理失败", e)
        
        # 计算耗时
        end_time = datetime.datetime.now()
        summary_txt = f'所有站点搜索完成，有效资源数：{len(ret_array)} , 总耗时 {(end_time - start_time).seconds} 秒'
        if SearchType.WEB == in_from:
            self.update_process(task_id=task_id, process_val=100, text=summary_txt)
            
        log.info(f"【{self._client_type.value}】{summary_txt}")

        return ret_array
    
    def update_process(self, task_id:Optional[str], process_val:int, text:Optional[str]=None):
        """
        进度更新
        """
        if task_id:
            GlobalTaskManager().update_task(task_id, progress=process_val, message=text)
            return

    def _chunk_list(self, data_list, chunks):
        """
        将列表 data_list 尽可能平均分成 chunks 份
        """
        k, m = divmod(len(data_list), chunks)
        return (data_list[i * k + min(i, m):(i + 1) * k + min(i + 1, m)] for i in range(chunks))
    
def exec_search_by_threads(client_instance: BuiltinIndexer,
                           search_indexers: List[IndexerInfo],
                           search_keywords: str,
                           filter_args: dict,
                           match_media: Optional[MetaBase]=None,
                           in_from: Optional[SearchType]=None,
                           task_id: Optional[str]=None):
    """
    接收一组索引器，使用线程池并发执行
    """
    process_results = []
    all_tasks = []

    def get_media_en_name(media_info: MetaBase):
        if media_info.original_language == "en":
            return media_info.original_title
        return Media().get_tmdb_en_title(media_info)
    
    thread_count = min(len(search_indexers), 20)        
    with ThreadPoolExecutor(max_workers=thread_count) as executor:
        # 提交所有线程任务
        for indexer in search_indexers:
            order_seq = 100 - int(indexer.pri)
            # 原始标题检索
            if 'title' == indexer.search_type and search_keywords:
                task = executor.submit(client_instance.search, order_seq, indexer, search_keywords, copy.deepcopy(filter_args), match_media, in_from, task_id)
                all_tasks.append(task)
            # 其他搜索类型都需要 match_media 不为空
            if not match_media:
                continue
            # 豆瓣id检索
            if 'douban_id' == indexer.search_type and match_media.douban_id:
                # 剧集信息, 查询特定季的豆瓣id
                task = executor.submit(client_instance.search, order_seq, indexer, match_media.douban_id, copy.deepcopy(filter_args), match_media, in_from, task_id)
                all_tasks.append(task)
            # imdb id 检索
            if 'imdb' == indexer.search_type and match_media.imdb_id:
                task = executor.submit(client_instance.search, order_seq, indexer, match_media.imdb_id, copy.deepcopy(filter_args), match_media, in_from, task_id)
                all_tasks.append(task)
            # 英文名检索
            if 'en_name' == indexer.search_type or indexer.en_expand:
                en_name = get_media_en_name(match_media)
                if en_name:
                    task = executor.submit(client_instance.search, order_seq, indexer, en_name, copy.deepcopy(filter_args), match_media, in_from, task_id)
                    all_tasks.append(task)
        
        for future in as_completed(all_tasks):
            try:
                result = future.result()
                if result:
                    process_results.extend(result) # 聚合当前进程内所有线程的结果
            except Exception as e:
                log.error("【Indexer】搜索结果处理失败 %s", str(e))
                
    return process_results