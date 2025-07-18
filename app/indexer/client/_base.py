import regex as re
import datetime
from abc import ABCMeta, abstractmethod
from typing import List

import log
from app.filter import Filter
from app.helper import ProgressHelper
from app.media import Media
from app.media.meta import MetaInfo
from app.utils import StringUtils
from app.utils.types import MediaType, SearchType, ProgressKey
from config import SPLIT_CHARS


class _IIndexClient(metaclass=ABCMeta):
    # 索引器ID
    client_id = ""
    # 索引器类型
    client_type = ""
    # 索引器名称
    client_name = "Indexer"

    media = None
    progress = None
    filter = None

    def __init__(self):
        self.media = Media()
        self.filter = Filter()
        self.progress = ProgressHelper()

    @abstractmethod
    def match(self, ctype):
        """
        匹配实例
        """
        pass

    @abstractmethod
    def get_status(self):
        """
        检查连通性
        """
        pass

    @abstractmethod
    def get_type(self):
        """
        获取类型
        """
        pass

    @abstractmethod
    def get_indexers(self):
        """
        :return:  indexer 信息 [(indexerId, indexerName, url)]
        """
        pass

    @abstractmethod
    def search(self, order_seq,
               indexer,
               key_word,
               filter_args: dict,
               match_media,
               in_from: SearchType):
        """
        根据关键字多线程搜索
        """
        pass

    def filter_search_results(self, result_array: list,
                              order_seq,
                              indexer,
                              filter_args: dict,
                              search_media,
                              start_time) -> List[MetaInfo]:
        """
        从搜索结果中匹配符合资源条件的记录
        """
        ret_array = []
        index_sucess = 0
        index_rule_fail = 0
        index_match_fail = 0
        index_error = 0

        for item in result_array:
            # 名称
            torrent_name = item.get('title')
            if not torrent_name:
                index_error += 1
                continue

            seeders = item.get('seeders')
            # 全匹配模式下，非公开站点，过滤掉做种数为0的
            if filter_args.get("seeders") and not indexer.public and str(seeders) == "0":
                log.info(f"【{self.client_name}】{torrent_name} 做种数为0")
                index_rule_fail += 1
                continue

            enclosure = item.get('enclosure')
            size = item.get('size')

            peers = item.get('peers')
            page_url = item.get('page_url')
            uploadvolumefactor = round(float(item.get('uploadvolumefactor')), 1) if item.get(
                'uploadvolumefactor') is not None else 1.0
            downloadvolumefactor = round(float(item.get('downloadvolumefactor')), 1) if item.get(
                'downloadvolumefactor') is not None else 1.0

            imdbid = item.get("imdbid")
            labels = item.get("labels") if item.get("labels") else ''
            # 描述
            description = item.get('description') if item.get('description') else ''
            # 目标资源类型
            mtype = search_media.type if search_media else None
            # 识别种子名称
            log.info(f"【{self.client_name}】开始识别资源: {torrent_name} {description}")
            item_meta = MetaInfo(title=torrent_name, subtitle=f"{labels} {description}".strip(), mtype=mtype)
            if not item_meta.get_name():
                log.info(f"【{self.client_name}】{torrent_name} 无法识别到名称")
                index_match_fail += 1
                continue
            # 大小及促销等
            item_meta.set_torrent_info(size=size,
                                       imdbid=imdbid,
                                       upload_volume_factor=uploadvolumefactor,
                                       download_volume_factor=downloadvolumefactor,
                                       labels=labels,
                                       pubdate=item.get("pubdate"))

            # 先过滤掉可以明确的类型
            if item_meta.type == MediaType.TV and filter_args.get("type") == MediaType.MOVIE:
                log.info(
                    f"【{self.client_name}】{torrent_name} 是 {item_meta.type.value}，"
                    f"不匹配类型：{filter_args.get('type').value}")
                index_rule_fail += 1
                continue
            # 检查订阅过滤规则匹配
            match_flag, res_order, match_msg = self.filter.check_torrent_filter(
                meta_info=item_meta,
                filter_args=filter_args,
                uploadvolumefactor=uploadvolumefactor,
                downloadvolumefactor=downloadvolumefactor)
            if not match_flag:
                log.info(f"【{self.client_name}】{match_msg}")
                index_rule_fail += 1
                continue
            # 识别媒体信息
            if not search_media:
                # 不过滤
                media_info = item_meta
            else:
                # 0-识别并模糊匹配；1-识别并精确匹配
                if item_meta.imdb_id \
                        and search_media.imdb_id \
                        and str(item_meta.imdb_id) == str(search_media.imdb_id):
                    # IMDBID匹配，合并媒体数据
                    media_info = self.media.merge_media_info(item_meta, search_media)
                else:
                    # 查询缓存
                    cache_info = self.media.get_cache_info(item_meta)
                    if search_media \
                            and str(cache_info.get("id")) == str(search_media.tmdb_id):
                        # 缓存匹配，合并媒体数据
                        media_info = self.media.merge_media_info(item_meta, search_media)
                    else:

                        item_tmdb_info = search_media.tmdb_info
                        # 年份不匹配
                        if item_tmdb_info.release_date and not self.is_result_item_year_match(item_tmdb_info, item_meta):
                            log.warn(f"【{self.client_name}】{item_meta.get_name()} 资源年份不匹配")
                            index_error += 1
                            continue                   

                        # 名称、年份 都匹配时，不再额外请求tmdb进行比对
                        if self.is_result_item_name_match(item_tmdb_info, item_meta):
                            media_info = self.media.merge_media_info(item_meta, search_media)
                        else:
                            # 识别搜索结果的tmdb信息
                            search_kw = item_meta.get_name()
                            en_name = item_meta.get_en_name()
                            # 没有年份、但有英文名时, 结合英文名搜索
                            if not item_meta.year and en_name and en_name != search_kw:
                                search_kw = '{} {}'.format(search_kw, en_name)
                            # 查询tmdb数据
                            file_tmdb_info = self.media.query_tmdb_info(search_kw, item_meta.type, item_meta.year,
                                               item_meta.begin_season, append_to_response=None, chinese=StringUtils.contain_chinese(search_kw))
                            # 查询失败
                            if not file_tmdb_info:
                                log.warn(f"【{self.client_name}】{search_kw} 识别媒体信息出错！")
                                index_error += 1
                                continue

                            # TMDBID是否匹配
                            if str(file_tmdb_info.id) != str(search_media.tmdb_id):
                                log.info(
                                    f"【{self.client_name}】{search_kw} 识别为 "
                                    f"{item_meta.type.value}/{item_meta.get_title_string()}/{file_tmdb_info.id} "
                                    f"与 {search_media.type.value}/{search_media.get_title_string()}/{search_media.tmdb_id} 不匹配")
                                index_match_fail += 1
                                continue
                            # 资源匹配，合并媒体数据
                            media_info = self.media.merge_media_info(item_meta, search_media)
                # 过滤类型
                if filter_args.get("type"):
                    if (filter_args.get("type") == MediaType.TV and media_info.type == MediaType.MOVIE) \
                            or (filter_args.get("type") == MediaType.MOVIE and media_info.type == MediaType.TV):
                        log.info(
                            f"【{self.client_name}】{torrent_name} 是 {media_info.type.value}/"
                            f"{media_info.tmdb_id}，不是 {filter_args.get('type').value}")
                        index_rule_fail += 1
                        continue
                # 洗版
                if search_media.over_edition:
                    # 季集不完整的资源不要
                    if media_info.type != MediaType.MOVIE \
                            and media_info.get_episode_list():
                        log.info(f"【{self.client_name}】"
                                 f"{media_info.get_title_string()}{media_info.get_season_string()} "
                                 f"正在洗版，过滤掉季集不完整的资源：{torrent_name} {description}")
                        continue
                    # 检查优先级是否更好
                    if search_media.res_order \
                            and int(res_order) <= int(search_media.res_order):
                        log.info(
                            f"【{self.client_name}】"
                            f"{media_info.get_title_string()}{media_info.get_season_string()} "
                            f"正在洗版，已洗版优先级：{100 - int(search_media.res_order)}，"
                            f"当前资源优先级：{100 - int(res_order)}，"
                            f"跳过低优先级或同优先级资源：{torrent_name}"
                        )
                        continue
            
            if (media_info.type == MediaType.TV or media_info.type == MediaType.ANIME) \
                  and media_info.tmdb_info and media_info.tmdb_info.seasons:
                
                total_season = max(media_info.tmdb_info.seasons, key=lambda info: info.season_number).season_number
                # 匹配元数据错误, 季信息不匹配
                if media_info.begin_season and int(media_info.begin_season) > total_season:
                    continue
                if media_info.end_season and int(media_info.end_season) > total_season:
                    continue
                

            # 检查标题是否匹配季、集、年
            if not self.filter.is_torrent_match_sey(media_info,
                                                    filter_args.get("season"),
                                                    filter_args.get("season_name"),
                                                    filter_args.get("episode"),
                                                    filter_args.get("year")):
                log.info(
                    f"【{self.client_name}】{torrent_name} 识别为 {media_info.type.value}/"
                    f"{media_info.get_title_string()}/{media_info.get_season_episode_string()} 不匹配季/集/年份")
                index_match_fail += 1
                continue

            # 匹配到了
            log.info(
                f"【{self.client_name}】{torrent_name} {description} 识别为 {media_info.get_title_string()} "
                f"{media_info.get_season_episode_string()} 匹配成功")
            media_info.set_torrent_info(site=indexer.name,
                                        site_order=order_seq,
                                        enclosure=enclosure,
                                        res_order=res_order,
                                        filter_rule=filter_args.get("rule"),
                                        size=size,
                                        seeders=seeders,
                                        peers=peers,
                                        description=description,
                                        page_url=page_url,
                                        upload_volume_factor=uploadvolumefactor,
                                        download_volume_factor=downloadvolumefactor)
            if media_info not in ret_array:
                index_sucess += 1
                ret_array.append(media_info)
            else:
                index_rule_fail += 1
        # 循环结束
        # 计算耗时
        end_time = datetime.datetime.now()
        log.info(
            f"【{self.client_name}】{indexer.name} {len(result_array)} 条数据中，"
            f"过滤 {index_rule_fail}，"
            f"不匹配 {index_match_fail}，"
            f"错误 {index_error}，"
            f"有效 {index_sucess}，"
            f"耗时 {(end_time - start_time).seconds} 秒")
        self.progress.update(ptype=ProgressKey.Search,
                             text=f"{indexer.name} {len(result_array)} 条数据中，"
                                  f"过滤 {index_rule_fail}，"
                                  f"不匹配 {index_match_fail}，"
                                  f"错误 {index_error}，"
                                  f"有效 {index_sucess}，"
                                  f"耗时 {(end_time - start_time).seconds} 秒")
        return ret_array


    def is_result_item_name_match(self, item_tmdb_info, item_meta : MetaInfo):
        """
        检查名称是否完全匹配
        """
        if not item_tmdb_info:
            return False
        
        target_names = [item_tmdb_info.title, item_tmdb_info.original_title]

        # 名称完全匹配
        if item_meta.cn_name and item_meta.cn_name in target_names:
            return True
        
        # 没有中文名时，检查原始名称是否匹配
        if not item_meta.cn_name and item_meta.en_name and item_meta.en_name in target_names:
            return True
        
        if item_meta.subtitle:
            splited_text = re.split(r'%s' % SPLIT_CHARS, item_meta.subtitle)
            for splited_item in splited_text:
                if not splited_item:
                    continue
                if splited_item in target_names:
                    return True

        return False
    
    def is_result_item_year_match(self, item_tmdb_info, item_meta : MetaInfo):
        """
        检查年份是否匹配
        """
        if not item_tmdb_info:
            return False
        
        if not item_meta.year or not item_tmdb_info.release_date:
            return False
        
        return item_tmdb_info.release_date.startswith(item_meta.year)