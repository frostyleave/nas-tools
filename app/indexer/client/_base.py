import regex as re
import datetime

from abc import ABCMeta, abstractmethod
from typing import List

import log

from app.filter import Filter
from app.helper import ProgressHelper
from app.media import Media
from app.media.meta import MetaInfo
from app.utils import StringUtils, MediaUtils
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
    def search(self, 
               order_seq,
               indexer,
               key_word,
               filter_args: dict,
               match_media,
               in_from: SearchType):
        """
        根据关键字多线程搜索
        """
        pass

    def filter_search_results(self, 
                              result_array: list,
                              order_seq,
                              indexer,
                              filter_args: dict,
                              search_media,
                              start_time,
                              in_from: SearchType) -> List[MetaInfo]:
        """
        从搜索结果中匹配符合资源条件的记录
        """

        filter_time = datetime.datetime.now()
        ret_array = []
        index_sucess = 0
        index_rule_fail = 0
        index_match_fail = 0
        index_error = 0

        target_year = []
        item_tmdb_info = search_media.tmdb_info if search_media else None
        # 目标资源类型
        mtype = search_media.type if search_media else None
        if item_tmdb_info:
            if mtype == MediaType.MOVIE:
                if hasattr(search_media.tmdb_info, 'release_date') and search_media.tmdb_info.release_date:
                    target_year.append(search_media.tmdb_info.release_date[0:4])
            else:
                if hasattr(search_media.tmdb_info, 'seasons') and search_media.tmdb_info.seasons:
                    for season_info in search_media.tmdb_info.seasons:
                        if not season_info.air_date:
                            continue
                        target_year.append(season_info.air_date[0:4])

        for item in result_array:
            # 名称
            torrent_name = item.get('title')
            if not torrent_name:
                index_error += 1
                continue

            seeders = item.get('seeders')
            # 全匹配模式下，非公开站点，过滤掉做种数为0的
            if filter_args.get("seeders") and not indexer.public and str(seeders) == "0":
                log.info("【%s】%s 做种数为0", self.client_name, torrent_name)
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
            # 识别种子名称
            log.debug("【%s】开始识别资源: %s %s", self.client_name, torrent_name, description)

            # 公共站点的资源, 格式化剧集资源名称
            if indexer.public:
                torrent_name, description = MediaUtils.format_tv_file_name(torrent_name, description)
                log.info("【%s】资源名称预处理结果: %s %s", self.client_name, torrent_name, description)
            
            item_meta = MetaInfo(title=torrent_name, subtitle=f"{labels} {description}".strip(), mtype=mtype)
            if not item_meta.get_name():
                log.info("【%s】%s 无法识别到名称", self.client_name, torrent_name)
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
                log.info("【%s】%s 是 %s, 不匹配类型：%s", self.client_name, torrent_name, item_meta.type.value, filter_args.get('type').value)
                index_rule_fail += 1
                continue

            # 检查订阅过滤规则匹配
            match_flag, res_order, match_msg = self.filter.check_torrent_filter(meta_info=item_meta,
                                                                                filter_args=filter_args,
                                                                                uploadvolumefactor=uploadvolumefactor,
                                                                                downloadvolumefactor=downloadvolumefactor)            
            if not match_flag:
                log.info("【%s】%s", self.client_name, match_msg)
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
                    if str(cache_info.get("id")) == str(search_media.tmdb_id):
                        # 缓存匹配，合并媒体数据
                        media_info = self.media.merge_media_info(item_meta, search_media)
                    else:
                        # 年份不匹配, 直接跳过
                        if target_year and item_meta.year and item_meta.year not in target_year:
                            log.warn("【%s】%s 资源年份不匹配", self.client_name, item_meta.get_name())
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
                            file_tmdb_info = self.media.query_tmdb_info(search_kw, 
                                                                        item_meta.type, 
                                                                        item_meta.year,
                                                                        item_meta.begin_season, 
                                                                        append_to_response=None, 
                                                                        chinese=StringUtils.contain_chinese(search_kw))
                            # 查询失败
                            if not file_tmdb_info:
                                log.warn("【%s】%s 识别媒体信息出错！", self.client_name, search_kw)
                                index_error += 1
                                continue

                            # TMDBID是否匹配
                            if str(file_tmdb_info.id) != str(search_media.tmdb_id):
                                log.info("【%s】%s 识别为 %s/%s/%s 与 %s/%s/%s 不匹配", 
                                         self.client_name, search_kw, item_meta.type.value, item_meta.get_title_string(), file_tmdb_info.id,
                                         search_media.type.value, search_media.get_title_string(), search_media.tmdb_id)
                                index_match_fail += 1
                                continue
                            # 资源匹配，合并媒体数据
                            media_info = self.media.merge_media_info(item_meta, search_media)
                filter_type = filter_args.get("type")
                # 过滤类型
                if filter_type:
                    if (filter_type == MediaType.TV and media_info.type == MediaType.MOVIE) \
                            or (filter_type == MediaType.MOVIE and media_info.type == MediaType.TV):
                        log.info("【%s】%s 是 %s/%s, 不是%s", self.client_name, torrent_name, media_info.type.value,media_info.tmdb_id, filter_args.get('type').value)
                        index_rule_fail += 1
                        continue
                # 洗版
                if search_media.over_edition:
                    # 季集不完整的资源不要
                    if media_info.type != MediaType.MOVIE and media_info.get_episode_list():
                        log.info("【%s】%s %s 正在洗版，过滤掉季集不完整的资源：%s %s", self.client_name, media_info.get_title_string(), media_info.get_season_string(), torrent_name, description)
                        continue
                    # 检查优先级是否更好
                    if search_media.res_order and int(res_order) <= int(search_media.res_order):
                        log.info("【%s】%s %s 正在洗版，已洗版优先级：%s, 当前资源优先级：%s, 跳过低优先级或同优先级资源：%s", 
                                 self.client_name, media_info.get_title_string(), media_info.get_season_string(), 100 - int(search_media.res_order), 100 - int(res_order), torrent_name)
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
                log.info("【%s】%s 识别为 %s/%s/%s 不匹配季/集/年份",
                         self.client_name, torrent_name, media_info.type.value, media_info.get_title_string(), media_info.get_season_episode_string())
                index_match_fail += 1
                continue

            # 匹配到了
            log.info("【%s】%s %s 识别为 %s %s 匹配成功", 
                     self.client_name, torrent_name, description, media_info.get_title_string(), media_info.get_season_episode_string())
            
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

        # 循环结束, 计算耗时
        cost_time = datetime.datetime.now()
        time_span = (cost_time - start_time).seconds
        filter_span = (cost_time - filter_time).seconds
        text_info = f"【{self.client_name}】{indexer.name} {len(result_array)} 条数据中，过滤:{index_rule_fail}，不匹配:{index_match_fail}，错误:{index_error}，有效:{index_sucess}，耗时:{filter_span} 秒, 总耗时:{time_span} 秒"

        log.info(text_info)
        if SearchType.WEB == in_from:
            self.progress.update(ptype=ProgressKey.Search, text=text_info)

        return ret_array


    def is_result_item_name_match(self, item_tmdb_info, item_meta : MetaInfo):
        """
        检查名称是否完全匹配
        """
        if not item_tmdb_info:
            return False
        
        target_names = []
        if hasattr(item_tmdb_info, 'title') and item_tmdb_info.title:
            target_names.append(item_tmdb_info.title)
        if hasattr(item_tmdb_info, 'original_title') and item_tmdb_info.original_title:
            target_names.append(item_tmdb_info.original_title)
        if hasattr(item_tmdb_info, 'name') and item_tmdb_info.name:
            target_names.append(item_tmdb_info.name)
        if hasattr(item_tmdb_info, 'original_name') and item_tmdb_info.original_name:
            target_names.append(item_tmdb_info.original_name)
        
        if not target_names:
            return False

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