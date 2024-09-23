import random
import zhconv
import log

from threading import Lock
from time import sleep
from typing import Optional

from app.media.doubanapi import DoubanApi, DoubanWeb
from app.media.meta import MetaInfo
from app.utils import ExceptionUtils, StringUtils
from app.utils import RequestUtils
from app.utils.commons import singleton
from app.utils.types import MediaType

lock = Lock()


@singleton
class DouBan:
    cookie = None
    doubanapi = None
    doubanweb = None
    message = None
    _movie_num = 20
    _tv_num = 20

    def __init__(self):
        self.init_config()

    def init_config(self):
        self.doubanapi = DoubanApi()
        self.doubanweb = DoubanWeb()
        try:
            res = RequestUtils(timeout=5).get_res("https://www.douban.com/")
            if res:
                self.cookie = StringUtils.str_from_cookiejar(res.cookies)
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            log.warn(f"【Douban】获取cookie失败: {format(err)}")

    # 聚合搜索
    def agg_search(self, key_word, mtype : Optional[MediaType] = None):
        log.info("【Douban】正在通过关键字查询豆瓣详情: %s" % key_word)
        douban_info = self.doubanapi.search_agg(key_word)
        if not douban_info:
            log.warn("【Douban】%s 未找到豆瓣详细信息" % key_word)
            return None
        if douban_info.get("localized_message"):
            log.warn("【Douban】查询豆瓣详情错误: %s" % douban_info.get("localized_message"))
            return None

        result_items = []
        
        # 搜索结果融合
        subject = douban_info.get("subjects")
        if subject and subject.get("items"):
            result_items.extend(subject.get("items"))
        if douban_info.get('smart_box'):
            result_items.extend(douban_info['smart_box'])

        if len(result_items) == 0:
            log.warn("【Douban】%s 查询结果为空" % key_word)
            return None

        # 根据媒体资源类型过滤
        detail_list = []
        for item in result_items:
            if self.is_target_type_match(item.get("target_type"), mtype):
                detail_list.append(item.get("target"))
    
        return detail_list
    
    def search_multi_season_tv(self, original_title, title):
        """
        查询多季剧集信息
        """
        douban_info = self.doubanapi.movie_search(title)
        if not douban_info:
            return None
        
        total = min(douban_info.get('total', 0), 100)
        if total == 0 or not douban_info.get('subjects'):
            return None

        subjects = douban_info.get("subjects")
        detail_list = self.filter_search_result(subjects, original_title, title)

        if total > 20:
            total_page = int(total / 20)
            if total % 20 > 0:
                total_page = total_page + 1
            for i in range(1, total_page):
                douban_info = self.doubanapi.movie_search(title, i * 20)
                if not douban_info:
                    break
                subjects = douban_info.get("subjects")
                if not subjects:
                    break
                detail_list.extend(self.filter_search_result(subjects, original_title, title))
                if len(subjects) < 20:
                    break

        return detail_list


    def filter_search_result(self, subjects, original_title, title):
        """
        过滤剧集搜索结果
        """
        detail_list = []
        for subject_item in subjects:
            subtype = subject_item.get('subtype')
            if subtype != 'tv':
                continue
            item_original_title = subject_item.get('original_title', '')
            item_title = subject_item.get('title', '')
            if not item_original_title.startswith(original_title) and not item_title.startswith(title):
                continue
            detail_item = {
                'id' : subject_item.get('id'),
                'title': item_title,
                'year' : subject_item.get('year'),
                'uri': subject_item.get('alt')
            }
            detail_list.append(detail_item)
        return detail_list
    
    def search_agg_by_page(self, key_word, page, mtype : Optional[MediaType] = None):
        douban_info = self.doubanapi.search_agg(key_word)
        if not douban_info:
            return None
        if douban_info.get("localized_message"):
            log.warn("【Douban】查询豆瓣详情错误: %s" % douban_info.get("localized_message"))
            return None

        result_items = []
        
        # 搜索结果融合
        subject = douban_info.get("subjects")
        if subject and subject.get("items"):
            result_items.extend(subject.get("items"))
        if douban_info.get('smart_box'):
            result_items.extend(douban_info['smart_box'])

        if len(result_items) == 0:
            return None

        # 根据媒体资源类型过滤
        detail_list = []
        for item in result_items:
            if self.is_target_type_match(item.get("target_type"), mtype):
                detail_list.append(item.get("target"))
    
        return detail_list
    
    # 媒体资源类型是否适用
    def is_target_type_match(self, item_type, mtype : Optional[MediaType] = None):
        if not item_type:
            return False
        if item_type != 'tv' and item_type != 'movie':
            return False
        if not mtype:
            return True
        if mtype == MediaType.MOVIE:
            return item_type == 'movie'
        return item_type != 'movie'

    # 从豆瓣网页抓取演职人员信息
    def scraper_media_celebrities(self, douban_id):

        crews, actors = [], []

        celebrities = self.doubanapi.movie_celebrities(douban_id)
        # 导演
        if celebrities.get("directors"):
            for item in celebrities.get("directors"):
                name = item.get('name')
                actor = {
                    # 'id': 'DB:' + item.get('id'),
                    'id': 'DB:' + name,
                    'name': name,
                    'original_name': name,
                    'en_name': item.get('latin_name'),
                    'image': item.get('avatar', {}).get('normal'),
                    'role': item.get('character'),
                    'profile': item.get('url')
                }
                crews.append(actor)
        # 演员
        if celebrities.get("actors"):
            for item in celebrities.get("actors"):
                name = item.get('name')
                actor = {
                    # 'id': 'DB:' + item.get('id'),
                    'id': 'DB:' + name,
                    'name': name,
                    'original_name': name,
                    'en_name': item.get('latin_name'),
                    'image': item.get('avatar', {}).get('normal'),
                    'role': item.get('character'),
                    'profile': item.get('url')
                }
                actors.append(actor)

        return crews, actors

    def get_douban_detail(self, doubanid, mtype=None, wait=False):
        """
        根据豆瓣ID返回豆瓣详情，带休眠
        """
        log.info("【Douban】正在通过API查询豆瓣详情: %s" % doubanid)
        # 随机休眠
        if wait:
            time = round(random.uniform(1, 5), 1)
            log.info("【Douban】随机休眠: %s 秒" % time)
            sleep(time)

        douban_info = self.doubanapi.movie_detail(doubanid)

        if not douban_info:
            log.warn("【Douban】%s 豆瓣详细信息查询失败" % doubanid)
            return None
        
        title = douban_info.get('title')
        if not title or title == "未知电影" or title == "未知电视剧":
            return None
        
        log.info("【Douban】查询到数据: %s" % title)

        original_title = douban_info.get("original_title")
        # 如果标题中包含原始标题，则去除原始标题部分
        if original_title and title.find(original_title) > 0:
            douban_info['title'] = title.replace(original_title, '').strip()

        return douban_info

    def __search_douban_id(self, metainfo):
        """
        给定名称和年份, 查询一条豆瓣信息返回对应ID
        :param metainfo: 已进行识别过的媒体信息
        """
        if metainfo.year:
            year_range = [int(metainfo.year), int(metainfo.year) + 1, int(metainfo.year) - 1]
        else:
            year_range = []
        if metainfo.type == MediaType.MOVIE:
            search_res = self.doubanapi.movie_search(metainfo.title).get("items") or []
            if not search_res:
                return None
            for res in search_res:
                douban_meta = MetaInfo(title=res.get("target", {}).get("title"))
                if metainfo.title == douban_meta.get_name() \
                        and (int(res.get("target", {}).get("year")) in year_range or not year_range):
                    return res.get("target_id")
            return None
        elif metainfo.type == MediaType.TV:
            search_res = self.doubanapi.tv_search(metainfo.title).get("items") or []
            if not search_res:
                return None
            for res in search_res:
                douban_meta = MetaInfo(title=res.get("target", {}).get("title"))
                if metainfo.title == douban_meta.get_name() \
                        and (str(res.get("target", {}).get("year")) == str(metainfo.year) or not metainfo.year):
                    return res.get("target_id")
                if metainfo.title == douban_meta.get_name() \
                        and metainfo.get_season_string() == douban_meta.get_season_string():
                    return res.get("target_id")
            return search_res[0].get("target_id")

    def get_douban_info(self, metainfo):
        """
        查询附带演职人员的豆瓣信息
        :param metainfo: 已进行识别过的媒体信息
        """
        doubanid = self.__search_douban_id(metainfo)
        if not doubanid:
            return None
        if metainfo.type == MediaType.MOVIE:
            douban_info = self.doubanapi.movie_detail(doubanid)
            celebrities = self.doubanapi.movie_celebrities(doubanid)
            if douban_info and celebrities:
                douban_info["directors"] = celebrities.get("directors")
                douban_info["actors"] = celebrities.get("actors")
            return douban_info
        elif metainfo.type == MediaType.TV:
            douban_info = self.doubanapi.tv_detail(doubanid)
            celebrities = self.doubanapi.tv_celebrities(doubanid)
            if douban_info and celebrities:
                douban_info["directors"] = celebrities.get("directors")
                douban_info["actors"] = celebrities.get("actors")
            return douban_info

    def get_latest_douban_interests(self, dtype, userid, wait=False):
        """
        获取最新动态中的想看/在看/看过数据
        """
        if wait:
            time = round(random.uniform(1, 5), 1)
            log.info("【Douban】随机休眠: %s 秒" % time)
            sleep(time)
        if dtype == "do":
            web_infos = self.doubanweb.do_in_interests(userid=userid)
        elif dtype == "collect":
            web_infos = self.doubanweb.collect_in_interests(userid=userid)
        elif dtype == "wish":
            web_infos = self.doubanweb.wish_in_interests(userid=userid)
        else:
            web_infos = self.doubanweb.interests(userid=userid)
        if not web_infos:
            return []
        for web_info in web_infos:
            web_info["id"] = web_info.get("url").split("/")[-2]
        return web_infos

    def get_douban_wish(self, dtype, userid, start, wait=False):
        """
        获取豆瓣想看列表数据
        """
        if wait:
            time = round(random.uniform(1, 5), 1)
            log.info("【Douban】随机休眠: %s 秒" % time)
            sleep(time)
        if dtype == "do":
            web_infos = self.doubanweb.do(cookie=self.cookie, userid=userid, start=start)
        elif dtype == "collect":
            web_infos = self.doubanweb.collect(cookie=self.cookie, userid=userid, start=start)
        else:
            web_infos = self.doubanweb.wish(cookie=self.cookie, userid=userid, start=start)
        if not web_infos:
            return []
        for web_info in web_infos:
            web_info["id"] = web_info.get("url").split("/")[-2]
        return web_infos

    def get_user_info(self, userid, wait=False):
        if wait:
            time = round(random.uniform(1, 5), 1)
            log.info("【Douban】随机休眠: %s 秒" % time)
            sleep(time)
        return self.doubanweb.user(cookie=self.cookie, userid=userid)

    def search_douban_medias(self, keyword, mtype: MediaType = None, season=None, episode=None, page=1):
        """
        根据关键字搜索豆瓣，返回可能的标题和年份信息
        """
        if not keyword:
            return []
        result = self.doubanapi.search(keyword)
        if not result:
            return []
        ret_medias = []
        for item_obj in result.get("items"):
            if mtype and mtype.value != item_obj.get("type_name"):
                continue
            if item_obj.get("type_name") not in (MediaType.TV.value, MediaType.MOVIE.value):
                continue
            item = item_obj.get("target")
            meta_info = MetaInfo(title=item.get("title"))
            meta_info.title = item.get("title")
            if item_obj.get("type_name") == MediaType.MOVIE.value:
                meta_info.type = MediaType.MOVIE
            else:
                meta_info.type = MediaType.TV
            if season:
                if meta_info.type != MediaType.TV:
                    continue
                if season != 1 and meta_info.begin_season != season:
                    continue
            if episode and str(episode).isdigit():
                if meta_info.type != MediaType.TV:
                    continue
                meta_info.begin_episode = int(episode)
                meta_info.title = "%s 第%s集" % (meta_info.title, episode)
            meta_info.year = item.get("year")
            meta_info.tmdb_id = "DB:%s" % item.get("id")
            meta_info.douban_id = item.get("id")
            meta_info.overview = item.get("card_subtitle") or ""
            meta_info.poster_path = item.get("cover_url").split('?')[0]
            meta_info.vote_average = item.get("rating", {}).get("value")
            if meta_info not in ret_medias:
                ret_medias.append(meta_info)

        return ret_medias[(page - 1) * 20:page * 20]

    def get_media_detail_from_web(self, doubanid):
        """
        从豆瓣详情页抓紧媒体信息
        :param doubanid: 豆瓣ID
        :return: {title, year, intro, cover_url, rating{value}, episodes_count}
        """
        log.info("【Douban】正在通过网页查询豆瓣详情: %s" % doubanid)
        web_info = self.doubanweb.detail(cookie=self.cookie, doubanid=doubanid.split(',')[0])
        if not web_info:
            return {}
        ret_media = {}
        try:
            # 标题
            title = web_info.get("title")
            if title:
                title = title
                metainfo = MetaInfo(title=title)
                if metainfo.cn_name:
                    title = metainfo.cn_name
                    # 有中文的去掉日文和韩文
                    if title and StringUtils.contain_chinese(title) and " " in title:
                        titles = title.split()
                        title = titles[0]
                        for _title in titles[1:]:
                            # 忽略繁体
                            if zhconv.convert(_title, 'zh-hans') == title:
                                break
                            # 忽略日韩文
                            if not StringUtils.is_japanese(_title) \
                                    and not StringUtils.is_korean(_title):
                                title = f"{title} {_title}"
                                break
                            else:
                                break
                else:
                    title = metainfo.en_name
                if not title:
                    return None
                ret_media['title'] = title
                ret_media['season'] = metainfo.begin_season
            else:
                return None
            # 年份
            year = web_info.get("year")
            if year:
                ret_media['year'] = year[1:-1]
            # 简介
            ret_media['summary'] = "".join(
                [str(x).strip() for x in web_info.get("intro") or []])
            # 封面图
            cover_url = web_info.get("cover")
            if cover_url:
                ret_media['images'] = { 'large' : cover_url.replace("s_ratio_poster", "m_ratio_poster") }
            # 评分
            rating = web_info.get("rate")
            if rating:
                ret_media['rating'] = {"average": float(rating)}
            # 季数
            season_num = web_info.get("season_num")
            if season_num:
                ret_media['season'] = int(season_num)
            # 集数
            episode_num = web_info.get("episode_num")
            if episode_num:
                ret_media['episodes_count'] = int(episode_num)
            # IMDBID
            imdbid = web_info.get('imdb')
            if imdbid:
                ret_media['imdbid'] = str(imdbid).strip()
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
        if ret_media:
            log.info("【Douban】查询到数据: %s" % ret_media.get("title"))
        else:
            log.warn("【Douban】%s 未查询到豆瓣数据: %s" % doubanid)
        return ret_media

    def get_douban_online_movie(self, page=1):
        if not self.doubanapi:
            return []
        infos = self.doubanapi.movie_showing(start=(page - 1) * self._movie_num,
                                             count=self._movie_num)
        if not infos:
            return []
        return self.__dict_items(infos.get("subject_collection_items"))

    def get_douban_hot_movie(self, page=1):
        if not self.doubanapi:
            return []
        infos = self.doubanapi.movie_hot_gaia(start=(page - 1) * self._movie_num,
                                              count=self._movie_num)
        if not infos:
            return []
        return self.__dict_items(infos.get("subject_collection_items"))

    def get_douban_hot_anime(self, page=1):
        if not self.doubanapi:
            return []
        infos = self.doubanapi.tv_animation(start=(page - 1) * self._tv_num,
                                            count=self._tv_num)
        if not infos:
            return []
        return self.__dict_items(infos.get("subject_collection_items"), MediaType.ANIME)

    def get_douban_hot_tv(self, page=1):
        if not self.doubanapi:
            return []
        infos = self.doubanapi.tv_hot(start=(page - 1) * self._tv_num,
                                      count=self._tv_num)
        if not infos:
            return []
        return self.__dict_items(infos.get("subject_collection_items"))

    def get_douban_new_movie(self, page=1):
        if not self.doubanapi:
            return []
        infos = self.doubanapi.movie_soon(start=(page - 1) * self._movie_num,
                                          count=self._movie_num)
        if not infos:
            return []
        return self.__dict_items(infos.get("subject_collection_items"))

    def get_douban_hot_show(self, page=1):
        if not self.doubanapi:
            return []
        infos = self.doubanapi.show_hot(start=(page - 1) * self._tv_num,
                                        count=self._tv_num)
        if not infos:
            return []
        return self.__dict_items(infos.get("subject_collection_items"))

    def get_douban_top250_movie(self, page=1):
        if not self.doubanapi:
            return []
        infos = self.doubanapi.movie_top250(start=(page - 1) * self._movie_num,
                                            count=self._movie_num)
        if not infos:
            return []
        return self.__dict_items(infos.get("subject_collection_items"))

    def get_douban_chinese_weekly_tv(self, page=1):
        if not self.doubanapi:
            return []
        infos = self.doubanapi.tv_chinese_best_weekly(start=(page - 1) * self._tv_num,
                                                      count=self._tv_num)
        if not infos:
            return []
        return self.__dict_items(infos.get("subject_collection_items"))

    def get_douban_weekly_tv_global(self, page=1):
        if not self.doubanapi:
            return []
        infos = self.doubanapi.tv_global_best_weekly(start=(page - 1) * self._tv_num,
                                                     count=self._tv_num)
        if not infos:
            return []
        return self.__dict_items(infos.get("subject_collection_items"))

    def get_douban_disover(self, mtype, sort, tags, page=1):
        if not self.doubanapi:
            return []
        if mtype == MediaType.MOVIE:
            infos = self.doubanapi.movie_recommend(start=(page - 1) * self._movie_num,
                                                   count=self._movie_num,
                                                   sort=sort,
                                                   tags=tags)
        else:
            infos = self.doubanapi.tv_recommend(start=(page - 1) * self._tv_num,
                                                count=self._tv_num,
                                                sort=sort,
                                                tags=tags)
        if not infos:
            return []
        return self.__dict_items(infos.get("items"), poster_filter=True)

    @staticmethod
    def __dict_items(infos, media_type=None, poster_filter=False):
        """
        转化为字典
        """
        # ID
        ret_infos = []
        for info in infos:
            rid = info.get("id")
            # 评分
            rating = info.get('rating')
            if rating:
                vote_average = float(rating.get("value"))
            else:
                vote_average = 0
            # 标题
            title = info.get('title')
            # 年份
            year = info.get('year')

            if not media_type:
                if info.get("type") not in ("movie", "tv"):
                    continue
                mtype = MediaType.MOVIE if info.get("type") == "movie" else MediaType.TV
                if mtype == MediaType.TV and len(info.get("tags")) > 0 and next(filter(lambda x: x.get("name") == '动画', info.get("tags")), None) is not None:
                    mtype = MediaType.ANIME
            else:
                mtype = media_type

            if mtype == MediaType.MOVIE:
                type_str = "MOV"
                # 海报
                poster_path = info.get('cover', {}).get("url")
                if not poster_path:
                    poster_path = info.get('cover_url')
                if not poster_path:
                    poster_path = info.get('pic', {}).get("large")
            else:
                type_str = "TV"
                # 海报
                poster_path = info.get('pic', {}).get("normal")

            # 简介
            overview = info.get("card_subtitle") or ""
            if not year and overview:
                if overview.split("/")[0].strip().isdigit():
                    year = overview.split("/")[0].strip()

            # 高清海报
            if poster_path:
                if poster_filter and ("movie_large.jpg" in poster_path
                                      or "tv_normal.png" in poster_path):
                    continue
                poster_path = poster_path.replace("s_ratio_poster", "m_ratio_poster")
            elif poster_filter:
                continue

            ret_infos.append({
                'id': "DB:%s" % rid,
                'orgid': rid,
                'title': title,
                'type': type_str,
                'media_type': mtype.value,
                'year': year[:4] if year else "",
                'vote': vote_average,
                'image': poster_path,
                'overview': overview
            })
        return ret_infos
