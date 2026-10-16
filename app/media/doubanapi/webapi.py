import base64
import hashlib
import hmac
import json
import re
import requests

from cachetools import TTLCache, cached
from urllib import parse

from app.utils import RequestUtils
from app.utils.commons import singleton


@singleton
class DoubanWebApi(object):

    _base_url = "https://m.douban.com/rexxar/api/v2"
    _refer_url = "https://m.douban.com"

    _person_url = "https://www.douban.com/j"
    
    _urls = {

        "search_subject": "/search/subjects?q=%s",

        # 正在上映
        "movie_showing": "/subject_collection/movie_showing/items",
        # 即将上映
        "movie_soon": "/subject_collection/movie_soon/items",

        # TOP250
        "movie_top250": "/subject_collection/movie_top250/items",
        # 高分经典科幻片榜
        "movie_scifi": "/subject_collection/movie_scifi/items",
        # 高分经典喜剧片榜
        "movie_comedy": "/subject_collection/movie_comedy/items",
        # 高分经典动作片榜
        "movie_action": "/subject_collection/movie_action/items",
        # 高分经典爱情片榜
        "movie_love": "/subject_collection/movie_love/items",

        # 华语口碑周榜
        "tv_chinese_best_weekly": "/subject_collection/tv_chinese_best_weekly/items",
        # 全球口碑周榜
        "tv_global_best_weekly": "/subject_collection/tv_global_best_weekly/items",

        # 热门电影
        "movie_hot_gaia": "/subject/recent_hot/movie",
        # 热门剧集
        "tv_hot": "/subject/recent_hot/tv?category=tv&type=tv",
        # 国产剧
        "tv_domestic": "/subject/recent_hot/tv?category=tv&type=tv_domestic",
        # 欧美剧
        "tv_american": "/subject/recent_hot/tv?category=tv&type=tv_american",
        # 日剧
        "tv_japanese": "/subject/recent_hot/tv?category=tv&type=tv_japanese",
        # 韩剧
        "tv_korean": "/subject/recent_hot/tv?category=tv&type=tv_korean",
        # 动画
        "tv_animation": "/subject/recent_hot/tv?category=tv&type=tv_animation",
        # 综艺
        "tv_documentary": "/subject/recent_hot/tv?category=tv&type=tv_documentary",

        # 执门综艺
        "show_hot": "/subject/recent_hot/tv?category=show&type=show",
        # 国内综艺
        "show_domestic": "/subject/recent_hot/tv?category=show&type=show_domestic",
        # 国外综艺
        "show_foreign": "/subject/recent_hot/tv?category=show&type=show_foreign",

        # rank list
        "movie_rank_list": "/movie/rank_list",
        "movie_year_ranks": "/movie/year_ranks",
        "book_rank_list": "/book/rank_list",
        "tv_rank_list": "/tv/rank_list",

        # movie info
        "movie_detail": "/movie/%s",
        "movie_rating": "/movie/%s/rating",
        "movie_photos": "/movie/%s/photos",
        "movie_trailers": "/movie/%s/trailers",
        "movie_interests": "/movie/%s/interests",
        "movie_reviews": "/movie/%s/reviews",
        "movie_recommendations": "/movie/%s/recommendations",
        "movie_celebrities": "/movie/%s/celebrities",

        # tv info
        "tv_detail": "/tv/",
        "tv_rating": "/tv/%s/rating",
        "tv_photos": "/tv/%s/photos",
        "tv_trailers": "/tv/%s/trailers",
        "tv_interests": "/tv/%s/interests",
        "tv_reviews": "/tv/%s/reviews",
        "tv_recommendations": "/tv/%s/recommendations",
        "tv_celebrities": "/tv/%s/celebrities",
        
        # celebrity
        "celebrity_works": "/personage/%s/works?title=影视",

    }

    _user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    
    _session = None

    def __init__(self):
        self._session = requests.Session()

    @cached(cache=TTLCache(maxsize=256, ttl=7200))
    def __invoke(self, url: str, base_url=_base_url, **kwargs) -> dict:
        """
        GET请求
        """
        params: dict = {}
        if kwargs:
            params.update(kwargs)

        req_url = base_url + url
        resp = RequestUtils(
            ua=self._user_agent,
            referer=self._refer_url,
            session=self._session
        ).get_res(url=req_url, params=params)

        if not resp:
            return {}
        
        resp_str = resp.text
        if resp_str:
            resp_str = re.sub(r'qnmob\d+', 'img1', resp_str)

        try:
            return json.loads(resp_str)
        except json.JSONDecodeError as e:
            return {}

    def search(self, keyword, start=0, count=20):
        """
        关键字搜索
        """
        return self.__invoke(self._urls["search_subject"] % keyword, start=start, count=count)

    def book_search(self, keyword, start=0, count=20):
        return self.__invoke(self._urls["book_search"], q=keyword, start=start, count=count)

    def group_search(self, keyword, start=0, count=20):
        return self.__invoke(self._urls["group_search"], q=keyword, start=start, count=count)

    def movie_showing(self, start=0, count=20):
        return self.__invoke(self._urls["movie_showing"], start=start, count=count)

    def movie_soon(self, start=0, count=20):
        return self.__invoke(self._urls["movie_soon"], start=start, count=count)

    def movie_hot_gaia(self, start=0, count=20):
        return self.__invoke(self._urls["movie_hot_gaia"], start=start, count=count)

    def tv_hot(self, start=0, count=20):
        return self.__invoke(self._urls["tv_hot"], start=start, count=count)

    def tv_animation(self, start=0, count=20):
        return self.__invoke(self._urls["tv_animation"], start=start, count=count)

    def tv_variety_show(self, start=0, count=20):
        return self.__invoke(self._urls["tv_variety_show"], start=start, count=count)

    def tv_rank_list(self, start=0, count=20):
        return self.__invoke(self._urls["tv_rank_list"], start=start, count=count)

    def show_hot(self, start=0, count=20):
        return self.__invoke(self._urls["show_hot"], start=start, count=count)

    def movie_detail(self, subject_id):
        return self.__invoke(self._urls["movie_detail"] % subject_id)

    def search_agg(self, key_word, start=0, count=30):
        return self.__invoke(self._urls["search_agg"], q=key_word, start=start, count=count)

    def movie_celebrities(self, subject_id):
        return self.__invoke(self._urls["movie_celebrities"] % subject_id)

    def movie_photos(self, subject_id):
        return self.__invoke(self._urls["movie_photos"] % subject_id)

    def movie_recommendations(self, subject_id):
        return self.__invoke(self._urls["movie_recommendations"] % subject_id)
    
    def celebrity_works(self, people_id):
        return self.__invoke(self._urls["celebrity_works"] % people_id, self._person_url, count=10)
    
    def tv_detail(self, subject_id):
        return self.__invoke(self._urls["tv_detail"] + subject_id)

    def tv_celebrities(self, subject_id):
        return self.__invoke(self._urls["tv_celebrities"] % subject_id)

    def tv_recommendations(self, subject_id):
        return self.__invoke(self._urls["tv_recommendations"] % subject_id)

    def tv_photos(self, subject_id):
        return self.__invoke(self._urls["tv_photos"] % subject_id)

    def movie_top250(self, start=0, count=20):
        return self.__invoke(self._urls["movie_top250"], start=start, count=count)

    def movie_recommend(self, tags='', sort='R', start=0, count=20):
        return self.__invoke(self._urls["movie_recommend"], tags=tags, sort=sort, start=start, count=count)

    def tv_recommend(self, tags='', sort='R', start=0, count=20):
        return self.__invoke(self._urls["tv_recommend"], tags=tags, sort=sort, start=start, count=count)

    def tv_chinese_best_weekly(self, start=0, count=20):
        return self.__invoke(self._urls["tv_chinese_best_weekly"], start=start, count=count)

    def tv_global_best_weekly(self, start=0, count=20):
        return self.__invoke(self._urls["tv_global_best_weekly"], start=start, count=count)

    def doulist_detail(self, subject_id):
        """
        豆列详情
        :param subject_id: 豆列id
        :return:
        {
            "is_follow": false,
            "screenshot_title": "分享海报",
            "playable_count": 1226,
            "screenshot_url": "douban://partial.douban.com/screenshot/doulist/13712178/_content",
            "create_time": "2014-10-05 10:41:22",
            "owner": {
                "kind": "user",
                "name": "依然饭特稀",
                "url": "https://www.douban.com/people/56698183/",
                "uri": "douban://douban.com/user/56698183",
                "avatar": "https://img2.doubanio.com/icon/up56698183-12.jpg",
                "is_club": false,
                "type": "user",
                "id": "56698183",
                "uid": "yrftx"
            },
            "screenshot_type": "rexxar",
            "id": "13712178",
            "category": "movie",
            "is_merged_cover": false,
            "title": "评价人数超过十万的电影",
            "is_subject_selection": false,
            "followers_count": 53081,
            "is_private": false,
            "item_abstracts": [],
            "type": "doulist",
            "update_time": "2023-04-22 22:19:48",
            "list_type": "ugc_doulist",
            "tags": [],
            "syncing_note": null,
            "cover_url": "https://img9.doubanio.com/view/elanor_image/raw/public/91314905.jpg",
            "header_bg_image": "",
            "doulist_type": "",
            "done_count": 0,
            "desc": "谢谢大家的关注和点赞，不过我更希望大家能在留言板上补充遗漏。\r\n看腻了豆瓣的评分排序，不如试试评价人数排序。评价人数并不代表作品的优劣，但是它起码说明了作品的存在感。这不一定是选电影最好的方法，却一定是选电影风险最小的方法。\r\n欢迎关注我关于读书的两个豆列： \r\n豆瓣评价人数超过一万的外文书籍 \r\nhttp://www.douban.com/doulist/37912871/ \r\n豆瓣评价人数超过一万的中文书籍\r\nhttp://www.douban.com/doulist/36708212/",
            "items_count": 1453,
            "wechat_timeline_share": "url",
            "url": "https://www.douban.com/doulist/13712178/",
            "is_sys_private": false,
            "uri": "douban://douban.com/doulist/13712178",
            "sharing_url": "https://www.douban.com/doulist/13712178/"
        }
        """
        return self.__invoke(self._urls["doulist"] + subject_id)

    def doulist_items(self, subject_id, start=0, count=20):
        """
        豆列列表
        :param subject_id: 豆列id
        :param start: 开始
        :param count: 数量
        :param ts: 时间戳
        :return:
        {
            "count": 3,
            "start": 0,
            "total": 1453,
            "items": [{
                "comment": "",
                "rating": {
                    "count": 2834097,
                    "max": 10,
                    "star_count": 5.0,
                    "value": 9.7
                },
                "subtitle": "1994 / 美国 / 剧情 犯罪 / 弗兰克·德拉邦特 / 蒂姆·罗宾斯 摩根·弗里曼",
                "title": "肖申克的救赎",
                "url": "https://movie.douban.com/subject/1292052/",
                "target_id": "1292052",
                "uri": "douban://douban.com/movie/1292052",
                "cover_url": "https://qnmob3.doubanio.com/view/photo/m_ratio_poster/public/p480747492.jpg?imageView2/2/q/80/w/300/h/300/format/jpg",
                "create_time": "2014-10-05 10:41:51",
                "type": "movie",
                "id": "19877287"
            }, {
                "comment": "",
                "rating": {
                    "count": 2255839,
                    "max": 10,
                    "star_count": 4.5,
                    "value": 9.4
                },
                "subtitle": "1994 / 法国 美国 / 剧情 动作 犯罪 / 吕克·贝松 / 让·雷诺 娜塔莉·波特曼",
                "title": "这个杀手不太冷",
                "url": "https://movie.douban.com/subject/1295644/",
                "target_id": "1295644",
                "uri": "douban://douban.com/movie/1295644",
                "cover_url": "https://qnmob3.doubanio.com/view/photo/m_ratio_poster/public/p511118051.jpg?imageView2/2/q/80/w/300/h/300/format/jpg",
                "create_time": "2014-10-05 10:42:34",
                "type": "movie",
                "id": "19877286"
            }, {
                "comment": "",
                "rating": {
                    "count": 2198702,
                    "max": 10,
                    "star_count": 4.5,
                    "value": 9.4
                },
                "subtitle": "2001 / 日本 / 剧情 动画 奇幻 / 宫崎骏 / 柊瑠美 入野自由",
                "title": "千与千寻",
                "url": "https://movie.douban.com/subject/1291561/",
                "target_id": "1291561",
                "uri": "douban://douban.com/movie/1291561",
                "cover_url": "https://qnmob3.doubanio.com/view/photo/m_ratio_poster/public/p2557573348.jpg?imageView2/2/q/80/w/300/h/300/format/jpg",
                "create_time": "2014-10-05 10:47:12",
                "type": "movie",
                "id": "19877280"
            }]
        }
        """
        return self.__invoke(self._urls["doulist_items"] % subject_id, start=start, count=count)
