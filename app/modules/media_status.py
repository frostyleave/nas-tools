import log

from app.media.meta import MetaInfo
from app.mediaserver import MediaServer
from app.modules.subscribe import Subscribe
from app.utils.commons import singleton
from app.utils.constants import Constants
from app.utils.types import MediaType


@singleton
class MediaStatusChecker:

    def get_media_exists_info(self, mtype, title, year, mediaid):
        """
        获取媒体存在标记：是否存在、是否订阅
        :param: mtype 媒体类型
        :param: title 媒体标题
        :param: year 媒体年份
        :param: mediaid TMDBID/DB:豆瓣ID/BG:Bangumi的ID
        :return: 1-已订阅/2-已下载/0-不存在未订阅, RSSID, 如果已下载,还会有对应的媒体库的播放地址链接
        """
        if str(mediaid).isdigit():
            tmdbid = mediaid
        else:
            tmdbid = None

        rssid = None
        if mtype in Constants.MOVIE_TYPES:
            rssid = Subscribe().get_subscribe_id(mtype=MediaType.MOVIE,
                                                 title=title,
                                                 year=year,
                                                 tmdbid=tmdbid)
        else:
            if not tmdbid:
                meta_info = MetaInfo(title=title, no_extra=True)
                title = meta_info.get_name()
                season = meta_info.get_season_string()
                if season:
                    year = None
            else:
                season = None
            rssid = Subscribe().get_subscribe_id(mtype=MediaType.TV,
                                                 title=title,
                                                 year=year,
                                                 season=season,
                                                 tmdbid=tmdbid)
        item_url = None
        if rssid:
            # 已订阅
            fav = "1"
        else:
            # 检查媒体服务器是否存在
            item_id = MediaServer().check_item_exists(mtype=mtype, title=title, year=year, tmdbid=tmdbid)
            if item_id:
                # 已下载
                fav = "2"
                item_url = MediaServer().get_play_url(item_id=item_id)
            else:
                # 未订阅、未下载
                fav = "0"
        return fav, rssid, item_url
