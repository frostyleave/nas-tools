import json
import re

import log

from app.downloader.downloader import Downloader
from app.media import Media, DouBan
from app.media.meta import MetaInfo
from app.message import Message
from app.modules.searcher import Searcher
from app.modules.media_status import MediaStatusChecker

from app.utils.string_utils import StringUtils
from app.utils.media_utils import MediaUtils
from app.utils.types import MediaType, SearchType

from config import Config

class SearchProxy:

    def search_torrents_from_web(self,
                                 content,
                                 ident_flag=True,
                                 filters=None,
                                 tmdbid=None,
                                 media_type=None,
                                 task_id=None):
        """
        WEB资源搜索
        :param content: 关键字文本，可以包括 类型、标题、季、集、年份等信息，使用 空格分隔，也支持种子的命名格式
        :param ident_flag: 是否进行媒体信息识别
        :param filters: 其它过滤条件
        :param tmdbid: TMDBID或DB:豆瓣ID
        :param media_type: 媒体类型, 配合tmdbid传入
        :return: 错误码，错误原因，成功时直接插入数据库
        """
        mtype, key_word, season_num, episode_num, year, content = StringUtils.get_keyword_from_string(content)
        if not key_word:
            log.info("【Web】%s 搜索关键字有误！" % content)
            return -1, "%s 未识别到搜索关键字！" % content
        
        # 类型
        if media_type:
            mtype = media_type

        _media = Media()

        # 识别媒体
        media_info = None
        if ident_flag:
            # 有TMDBID或豆瓣ID
            if tmdbid:
                media_info = _media.get_mediainfo_from_id(mediaid=tmdbid, mtype=mtype)
            else:
                # 按输入名称查
                media_info = _media.get_media_info(mtype=media_type or mtype, title=content)
            # 整合集
            if media_info:
                if season_num:
                    media_info.begin_season = int(season_num)
                if episode_num:
                    media_info.begin_episode = int(episode_num)
            if media_info and media_info.tmdb_info:
                # 查询到TMDB信息
                log.info("【Web】从TMDB中匹配到 %s: %s", media_info.type.value, media_info.get_title_string())
                # 查找的季
                if media_info.begin_season is None:
                    search_season = None
                else:
                    search_season = media_info.get_season_list()
                # 查找的集
                search_episode = media_info.get_episode_list()
                if search_episode and not search_season:
                    search_season = [1]
                # 中文名
                if media_info.cn_name:
                    search_cn_name = media_info.cn_name
                else:
                    search_cn_name = media_info.title
                first_search_name = search_cn_name
                season_name = None
                if season_num and 1 < season_num <= len(media_info.tmdb_info.seasons):
                    match_season = next(filter(lambda x: x.season_number == season_num, media_info.tmdb_info.seasons), None)
                    if match_season and match_season.name:
                        season_name = match_season.name
                filter_args = {"season": search_season,
                            "season_name": season_name,
                            "episode": search_episode,
                            "year": media_info.year,
                            "type": media_info.type}
            else:
                # 查询不到数据，使用快速搜索
                log.info("【Web】 未从TMDB匹配到媒体信息, 将使用快速搜索...", content)
                ident_flag = False
                media_info = None
                first_search_name = key_word
                filter_args = {
                    "season": season_num,
                    "episode": episode_num,
                    "year": year
                }    
        else:
            # 快速搜索
            first_search_name = key_word
            filter_args = {
                "season": season_num,
                "episode": episode_num,
                "year": year
            }
        # 整合高级查询条件
        if filters:
            filter_args.update(filters)

        log.info("【Web】开始搜索 %s ...", content)
            
        # 开始搜索
        media_list = Searcher().search_torrents(key_word=first_search_name,
                                                filter_args=filter_args,
                                                match_media=media_info,
                                                search_theme=content,
                                                in_from=SearchType.WEB,
                                                task_id=task_id,
                                                ident_flag=ident_flag)

        result_count = len(media_list)
        if result_count == 0:
            log.info("【Web】%s 未搜索到任何资源" % content)
            return 1, "%s 未搜索到任何资源" % content
        else:
            log.info("【Web】共搜索到 %s 个有效资源" % result_count)       
            return 0, ""


    def search_one_torrent(self,
                           media_info,
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
        filter_args = {
            "season": search_season,
            "episode": search_episode,
            "year": media_info.year,
            "type": media_info.type,
            "site": sites,
            "seeders": True
        }
        if filters:
            filter_args.update(filters)

        if media_info.keyword:
            search_name = media_info.keyword # 直接使用搜索词搜索
        else:
            if media_info.cn_name:  # 优先中文名
                search_name = media_info.cn_name
            else:
                search_name = media_info.title

        log.info("【Searcher】开始搜索 %s ..." % search_name)

        # 开始搜索
        media_list = Searcher().search_torrents(search_name, filter_args, media_info, in_from)

        if len(media_list) == 0:
            log.info("【Searcher】 未搜索到任何资源")
            return None, no_exists, 0, 0
        
        if in_from in Message().get_search_types():
            # 未开自动下载
            _search_auto = Config().get_config("pt").get('search_auto', True)
            if not _search_auto:
                return None, no_exists, len(media_list), None
            
        # 择优下载
        download_items, left_medias = Downloader().batch_download(in_from=in_from,
                                                                  media_list=media_list,
                                                                  need_tvs=no_exists,
                                                                  user_name=user_name)
        if not download_items:
            log.info("【Searcher】%s 未下载到资源" % media_info.title)
            return None, left_medias, len(media_list), 0

        # 统计下载情况
        log.info("【Searcher】实际下载了 %s 个资源" % len(download_items))
        # 还有剩下的缺失，说明没下完，返回False
        if left_medias:
            return None, left_medias, len(media_list), len(download_items)
        
        # 全部下完了
        return download_items[0], no_exists, len(media_list), len(download_items)

        
    def search_media_by_keyword(self, keyword, source=None, page=1, media_type: MediaType = None):

        """
        搜索TMDB或豆瓣词条
        :param: keyword 关键字
        :param: source 渠道 tmdb/douban
        :param: season 季号
        :param: episode 集号
        """
        if not keyword:
            return []
        
        mtype, key_word, season_num, episode_num, _, content = StringUtils.get_keyword_from_string(keyword)
        if media_type:
            mtype = media_type
        if source == "tmdb":
            use_douban_titles = False
        elif source == "douban":
            use_douban_titles = True
        else:
            use_douban_titles = Config().get_config("laboratory").get("use_douban_titles")
            
        if use_douban_titles:
            medias = DouBan().search_douban_medias(keyword=key_word,
                                                   mtype=mtype,
                                                   season=season_num,
                                                   episode=episode_num,
                                                   page=page)
        else:
            meta_info = MetaInfo(title=content)
            tmdbinfos = Media().get_tmdb_infos(title=meta_info.get_name(),
                                               year=meta_info.year,
                                               mtype=mtype,
                                               page=page)
            medias = []
            for info in tmdbinfos:
                tmp_info = MetaInfo(title=keyword)
                tmp_info.set_tmdb_info(info)
                if meta_info.type != MediaType.MOVIE and tmp_info.type == MediaType.MOVIE:
                    continue
                if tmp_info.begin_season:
                    tmp_info.title = "%s 第%s季" % (tmp_info.title, StringUtils.number_to_cn(meta_info.begin_season))
                if tmp_info.begin_episode:
                    tmp_info.title = "%s 第%s集" % (tmp_info.title, meta_info.begin_episode)
                medias.append(tmp_info)

        return medias


    def get_torrent_search_result(self):
        """
        查询资源搜索结果
        """
        search_results = {}
        
        res = Searcher().get_search_results()
        total = len(res)
        for item in res:
            # 质量(来源、效果)、分辨率
            if item.RES_TYPE:
                try:
                    res_mix = json.loads(item.RES_TYPE)
                except Exception as err:
                    log.exception("[act]解析质量配置异常:")
                    continue
                respix = res_mix.get("respix") or ""
                video_encode = res_mix.get("video_encode") or ""
                restype = res_mix.get("restype") or ""
                reseffect = res_mix.get("reseffect") or ""
            else:
                restype = ""
                respix = ""
                reseffect = ""
                video_encode = ""

            # 分组标识 (来源，分辨率)
            group_key = re.sub(r"[-.\s@|]", "", f"{respix}_{restype}").lower()
            # 分组信息
            group_info = {
                "respix": respix,
                "restype": restype,
            }
            # 种子唯一标识 （大小，质量(来源、效果)，制作组组成）
            unique_key = re.sub(r"[-.\s@|]", "",
                                f"{respix}_{restype}_{video_encode}_{reseffect}_{item.SIZE}_{item.OTHERINFO}").lower()
            # 标识信息
            unique_info = {
                "video_encode": video_encode,
                "size": item.SIZE,
                "reseffect": reseffect,
                "releasegroup": item.OTHERINFO
            }
            # 结果
            title_string = f"{item.TITLE}"
            if item.YEAR:
                title_string = f"{title_string} ({item.YEAR})"
            # 电视剧季集标识
            mtype = item.TYPE or ""
            SE_key = item.ES_STRING if item.ES_STRING and mtype != "MOV" else "MOV"
            media_type = {"MOV": "电影", "TV": "电视剧", "ANI": "动漫"}.get(mtype)
            # 只需要部分种子标签
            labels = [label for label in str(item.NOTE).split("|")
                      if label in ["官方", "官组", "中字", "中配", "国语", "粤语", "特效", "特效字幕", "杜比视界"]]

            pubdate = item.PUBDATE or ''
            if pubdate.endswith(' 00:00:00'):
                pubdate = pubdate[:-9]

            # 种子信息
            torrent_item = {
                "id": item.ID,
                "seeders": item.SEEDERS,
                "enclosure": item.ENCLOSURE,
                "site": item.SITE,
                "torrent_name": item.TORRENT_NAME,
                "description": item.DESCRIPTION,
                "pageurl": item.PAGEURL,
                "uploadvalue": item.UPLOAD_VOLUME_FACTOR,
                "downloadvalue": item.DOWNLOAD_VOLUME_FACTOR,
                "pubdate": pubdate,
                "size": item.SIZE,
                "respix": respix,
                "restype": restype,
                "reseffect": reseffect,
                "releasegroup": item.OTHERINFO,
                "video_encode": video_encode,
                "labels": labels
            }
            # 促销
            free_item = {
                "value": f"{item.UPLOAD_VOLUME_FACTOR} {item.DOWNLOAD_VOLUME_FACTOR}",
                "name": MediaUtils.get_free_string(item.UPLOAD_VOLUME_FACTOR, item.DOWNLOAD_VOLUME_FACTOR)
            }
            # 制作组、字幕组
            if item.OTHERINFO is None:
                releasegroup = "未知"
            else:
                releasegroup = item.OTHERINFO
            # 季
            filter_season = SE_key.split()[0] if SE_key and SE_key not in [
                "MOV", "TV"] else None
            # 合并搜索结果
            if search_results.get(title_string):
                # 种子列表
                result_item = search_results[title_string]
                torrent_dict = search_results[title_string].get("torrent_dict")
                SE_dict = torrent_dict.get(SE_key)
                if SE_dict:
                    group = SE_dict.get(group_key)
                    if group:
                        unique = group.get("group_torrents").get(unique_key)
                        if unique:
                            unique["torrent_list"].append(torrent_item)
                            group["group_total"] += 1
                        else:
                            group["group_total"] += 1
                            group.get("group_torrents")[unique_key] = {
                                "unique_info": unique_info,
                                "torrent_list": [torrent_item]
                            }
                    else:
                        SE_dict[group_key] = {
                            "group_info": group_info,
                            "group_total": 1,
                            "group_torrents": {
                                unique_key: {
                                    "unique_info": unique_info,
                                    "torrent_list": [torrent_item]
                                }
                            }
                        }
                else:
                    torrent_dict[SE_key] = {
                        group_key: {
                            "group_info": group_info,
                            "group_total": 1,
                            "group_torrents": {
                                unique_key: {
                                    "unique_info": unique_info,
                                    "torrent_list": [torrent_item]
                                }
                            }
                        }
                    }
                # 过滤条件
                torrent_filter = dict(result_item.get("filter"))
                if free_item not in torrent_filter.get("free"):
                    torrent_filter["free"].append(free_item)
                if releasegroup not in torrent_filter.get("releasegroup"):
                    torrent_filter["releasegroup"].append(releasegroup)
                if item.SITE not in torrent_filter.get("site"):
                    torrent_filter["site"].append(item.SITE)
                if video_encode \
                        and video_encode not in torrent_filter.get("video"):
                    torrent_filter["video"].append(video_encode)
                if filter_season \
                        and filter_season not in torrent_filter.get("season"):
                    torrent_filter["season"].append(filter_season)
            else:
                fav, rssid = 0, None
                # 存在标志
                if item.TMDBID:
                    fav, rssid, item_url = MediaStatusChecker().get_media_exists_info(
                        mtype=mtype,
                        title=item.TITLE,
                        year=item.YEAR,
                        mediaid=item.TMDBID)

                search_results[title_string] = {
                    "key": item.ID,
                    "title": item.TITLE,
                    "year": item.YEAR,
                    "type_key": mtype,
                    "image": item.IMAGE,
                    "type": media_type,
                    "vote": item.VOTE,
                    "tmdbid": item.TMDBID,
                    "backdrop": item.IMAGE,
                    "poster": item.POSTER,
                    "overview": item.OVERVIEW,
                    "fav": fav,
                    "rssid": rssid,
                    "torrent_dict": {
                        SE_key: {
                            group_key: {
                                "group_info": group_info,
                                "group_total": 1,
                                "group_torrents": {
                                    unique_key: {
                                        "unique_info": unique_info,
                                        "torrent_list": [torrent_item]
                                    }
                                }
                            }
                        }
                    },
                    "filter": {
                        "site": [item.SITE],
                        "free": [free_item],
                        "releasegroup": [releasegroup],
                        "video": [video_encode] if video_encode else [],
                        "season": [filter_season] if filter_season else []
                    }
                }

        # 提升整季的顺序到顶层
        def se_sort(k):
            k = re.sub(r" +|(?<=s\d)\D*?(?=e)|(?<=s\d\d)\D*?(?=e)",
                       " ", k[0], flags=re.I).split()
            # 如果只有一个元素，检查是否包含 '-'
            if len(k) == 1:
                if re.match(r"^(S\d+)-S\d+$", k[0], flags=re.I) or re.match(r"^(E\d+)-E\d+$", k[0], flags=re.I):
                    parts = k[0].split('-')  # 按 '-' 拆分
                    if len(parts) == 2:
                        return (parts[1], parts[0])  # 翻转顺序
                return (k[0], "FF")

            if re.match(r"^(E\d+)-E\d+$", k[1], flags=re.I):
                parts = k[1].split('-')  # 按 '-' 拆分
                if len(parts) == 2:
                    return (k[0], '{}-{}'.format(parts[1], parts[0]))

            return (k[0], k[1])

        # 开始排序季集顺序
        for title, item in search_results.items():
            # 排序筛选器 季
            item["filter"]["season"].sort(reverse=True)
            # 排序筛选器 制作组、字幕组.  将未知放到最后
            item["filter"]["releasegroup"] = sorted(item["filter"]["releasegroup"], key=lambda x: (x == "未知", x))
            # 排序种子列 集
            item["torrent_dict"] = sorted(item["torrent_dict"].items(),
                                          key=se_sort,
                                          reverse=True)
            
        return {"code": 0, "total": total, "result": search_results}