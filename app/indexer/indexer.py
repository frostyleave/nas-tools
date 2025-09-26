import copy
import datetime
import re

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

import log

from app.media.douban import DouBan
from app.media.meta._base import MetaBase
from app.helper import ProgressHelper, SubmoduleHelper, DbHelper
from app.indexer.client.builtin import BuiltinIndexer
from app.media import Media
from app.media.meta.metainfo import MetaInfo
from app.utils import ExceptionUtils, StringUtils
from app.utils.commons import singleton
from app.utils.types import MediaType, SearchType, ProgressKey

from config import INDEXER_CATEGORY


@singleton
class Indexer(object):

    _client = None
    _client_type = None
    progress = None
    dbhelper = None

    def __init__(self):
        self.init_config()

    def init_config(self):
        self.progress = ProgressHelper()
        self.dbhelper = DbHelper()
        self._client = BuiltinIndexer()
        self._client_type = self._client.get_type()

    def get_indexers(self, check=False):
        """
        获取当前索引器的索引站点
        """
        if not self._client:
            return []
        return self._client.get_indexers(check=check)

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
                          key_word: [str, list],
                          filter_args: dict,
                          match_media=None,
                          in_from: SearchType = None) -> List[MetaInfo]:
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

        indexers = self.get_indexers(check=True)
        if not indexers:
            log.error("没有配置索引器，无法搜索！")
            return []

        if filter_args.get('site'):
            sites = filter_args.get('site')
            indexers = list(filter(lambda x: x.name in sites, indexers))            
        elif match_media and match_media.type and match_media.type.name in INDEXER_CATEGORY:
            indexers = list(filter(lambda x: not x.source_type or match_media.type.name in x.source_type, indexers))

        if not indexers:
            log.error("没有配置符合条件的索引器，无法搜索！")
            return []

        # 计算耗时
        start_time = datetime.datetime.now()
        if filter_args and filter_args.get("site"):
            log_info = f"【{self._client_type.value}】开始搜索 %s, 站点: %s ..." % (key_word, filter_args.get("site"))
            log.info(log_info)
            self.progress.update(ptype=ProgressKey.Search, text=log_info)
        else:
            log_info = f"【{self._client_type.value}】开始并行搜索 %s, 线程数: %s ..." % (key_word, len(indexers))
            log.info(log_info)
            self.progress.update(ptype=ProgressKey.Search, text=log_info)

        # 多线程
        executor = ThreadPoolExecutor(max_workers=len(indexers))
        all_task = []
        for indexer in indexers:
            order_seq = 100 - int(indexer.pri)

            # 原始标题检索
            if 'title' == indexer.search_type and key_word:
                _filter_args = copy.deepcopy(filter_args) if filter_args is not None else {}
                task = executor.submit(self._client.search, order_seq, indexer, key_word, _filter_args, match_media, in_from)
                all_task.append(task)

            # 其他搜索类型都需要 match_media 不为空
            if not match_media:
                continue

            # 豆瓣id检索
            if 'douban_id' == indexer.search_type and match_media.douban_id:
                # 剧集信息, 查询特定季的豆瓣id
                douban_ids = self.get_douban_tv_season_id(match_media)
                for db_id in douban_ids:
                    task = executor.submit(self._client.search, order_seq, indexer, db_id, copy.deepcopy(filter_args), match_media, in_from)
                    all_task.append(task)
                        

            # imdb id 检索
            if 'imdb' == indexer.search_type and match_media.imdb_id:
                task = executor.submit(self._client.search, order_seq, indexer, match_media.imdb_id, copy.deepcopy(filter_args), match_media, in_from)
                all_task.append(task)

            # 英文名检索
            if 'en_name' == indexer.search_type or indexer.en_expand:
                en_name = self.get_en_name(match_media)
                if en_name:
                    _filter_args_en = copy.deepcopy(filter_args) if filter_args is not None else {}
                    task = executor.submit(self._client.search, order_seq, indexer, en_name, _filter_args_en, match_media, in_from)
                    all_task.append(task)

        ret_array = []
        finish_count = 0
        for future in as_completed(all_task):
            result = future.result()
            finish_count += 1
            self.progress.update(ptype=ProgressKey.Search,
                                 value=round(100 * (finish_count / len(all_task))))
            if result:
                ret_array = ret_array + result
        # 计算耗时
        end_time = datetime.datetime.now()
        log.info(f"【{self._client_type.value}】所有站点搜索完成，有效资源数：%s，总耗时 %s 秒"
                 % (len(ret_array), (end_time - start_time).seconds))
        self.progress.update(ptype=ProgressKey.Search,
                             text="所有站点搜索完成，有效资源数：%s，总耗时 %s 秒"
                                  % (len(ret_array), (end_time - start_time).seconds),
                             value=100)
        return ret_array

    def get_en_name(self, media_info):
        """
        获取媒体数据的英文名称
        """
        if media_info.original_language == "en":
            return media_info.original_title
        # 获取英文标题
        return Media().get_tmdb_en_title(media_info)
    
    def get_douban_tv_season_id(self, media_info:MetaBase):
        """
        查询剧集信息的豆瓣id
        """
        douban_ids = []
        if not media_info.douban_id:
            return douban_ids
        
        douban_ids.append(media_info.douban_id)

        doubanapi = DouBan()
        try:
            # 剧集类型时，如果只有1季，也不在进行扩展搜索
            info = media_info.tmdb_info
            if info and len(info.seasons) <= 1:
                return douban_ids
            # 计算季数大于0的季
            season_cnt = len(list(filter(lambda t: t.season_number > 0, info.seasons)))
            if season_cnt == 1:
                return douban_ids
            
            # 解析季名称
            season_names = []
            for season_info in info.seasons:
                if season_info.season_number == 0:
                    continue
                season_name = self.convert_numbers_in_string(season_info.name)
                season_names.append(season_name)
            
            # 根据名称查询豆瓣剧集信息
            start = 0
            page_size = 30
            tv_name = media_info.title
            while True:
                search_res = doubanapi.tv_search(tv_name, start, page_size)
                for res_item in search_res:
                    if not doubanapi.is_target_type_match(res_item.get("target_type"), MediaType.TV):
                        continue
                    target_info = res_item.get("target")
                    if not target_info:
                        continue
                    item_title = target_info.get("title")
                    if not item_title:
                        continue

                    res_item_id = target_info.get("id")
                    if res_item_id == media_info.douban_id:
                        continue
                    if item_title == tv_name:
                        douban_ids.append(target_info.get("id"))
                        continue
                    # 移除名称
                    left_part = item_title.replace(tv_name, "", 1).strip()
                    if left_part in season_names:
                        douban_ids.append(target_info.get("id"))
                if len(search_res) == page_size:
                    start += page_size
                else:
                    break
            
        except Exception as err:
            ExceptionUtils.exception_traceback(err)

        return douban_ids

    def int_to_chinese(self, num: int):
        """将 0~9999 范围内的整数转换为中文数字（简单实现）。"""
        digits = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九']
        if num == 0:
            return digits[0]
        
        num_str = str(num)
        length = len(num_str)
        result = ""
        for i, ch in enumerate(num_str):
            digit = int(ch)
            unit = length - i - 1  # 当前位数对应的单位（十、百、千）
            if digit != 0:
                result += digits[digit]
                if unit == 1:
                    result += "十"
                elif unit == 2:
                    result += "百"
                elif unit == 3:
                    result += "千"
            else:
                # 避免连续“零”
                if not result.endswith("零") and i != length - 1:
                    result += "零"
        # 去除末尾可能多余的“零”
        result = result.rstrip("零")
        # 特殊处理：例如 10、11 转换结果为“一十…”，改为“十…”
        if result.startswith("一十"):
            result = result[1:]
        return result

    def convert_numbers_in_string(self, s: str):
        """
        使用正则表达式查找字符串中所有数字（包含其两侧空白字符），
        并替换为转换后的中文数字，同时去掉两侧的空格。
        """
        # 匹配：任意数量空格 + 一段数字 + 任意数量空格
        pattern = re.compile(r'\s*(\d+)\s*')
        
        def repl(match):
            num = int(match.group(1))
            return self.int_to_chinese(num)
        
        return pattern.sub(repl, s)
