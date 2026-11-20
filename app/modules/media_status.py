
from concurrent.futures import ThreadPoolExecutor, as_completed

import log
from app.media import Bangumi, MediaService
from app.media.meta import MetaInfo
from app.mediaserver import MediaServer
from app.modules.subscribe import Subscribe
from app.utils.commons import singleton
from app.utils.constants import Constants
from app.utils.types import MediaType
from config import Config


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
        tmdbid = None
        doubanid = None
        if str(mediaid).isdigit():
            tmdbid = mediaid
        elif str(mediaid).startswith("DB:"):
            doubanid = str(mediaid)[3:].split(',')[0]

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
            item_id = MediaServer().check_item_exists(mtype=mtype,
                                                      title=title,
                                                      year=year,
                                                      tmdbid=tmdbid,
                                                      doubanid=doubanid)
            if item_id:
                # 已下载
                fav = "2"
                item_url = MediaServer().get_play_url(item_id=item_id)
            else:
                # 未订阅、未下载
                fav = "0"
        return fav, rssid, item_url

    def iter_bangumi_tmdb_info(self, media_list):
        """
        第一阶段：逐个产出 Bangumi 条目的 TMDB 匹配结果与 R18 标记
        只做外部查询，按完成顺序返回，用于 SSE 流式更新
        :param media_list: [{id, bgmid, title, year}]
        """
        if not media_list:
            return

        def __match(item):
            bgmid = item.get("bgmid") or str(item.get("tmdbid") or "").replace("BG:", "")
            title = item.get("title") or ""
            year = item.get("year") or ""
            r18 = Bangumi.is_r18(bgmid)
            tmdb_info = MediaService().match_tmdb_tv_by_title(title, year) if title else None
            if not tmdb_info:
                return None, r18, "", 0
            # 一并返回 TMDB 封面和评分，前端用它们替换 Bangumi 原图与评分
            image = Config().get_tmdbimage_url(tmdb_info.get("poster_path")) \
                if tmdb_info.get("poster_path") else ""
            vote = tmdb_info.get("vote_average") or 0
            return tmdb_info.get("id"), r18 or bool(tmdb_info.get("adult")), image, vote

        executor = ThreadPoolExecutor(max_workers=8)
        try:
            futures = {executor.submit(__match, item): item for item in media_list}
            for future in as_completed(futures):
                item = futures[future]
                try:
                    tmdbid, r18, image, vote = future.result()
                except Exception as err:
                    log.error(f"【Bangumi】查询[{item.get('title')}]TMDB信息失败：{err!s}")
                    tmdbid, r18, image, vote = None, False, "", 0
                yield {
                    "id": item.get("id"),
                    "tmdbid": tmdbid,
                    "r18": bool(r18),
                    "image": image,
                    "vote": vote
                }
        finally:
            # 客户端提前断开时取消尚未完成的任务
            executor.shutdown(wait=False, cancel_futures=True)

    def iter_media_exists_info(self, media_list):
        """
        第二阶段：逐个产出订阅/在库状态
        :param media_list: [{id, tmdbid, type, title, year}]
        """
        for item in media_list or []:
            # 匹配到 TMDB 时按 TMDB ID 判断；BG:/DB: 或无 ID 时按名称判断
            fav, rssid, item_url = self.get_media_exists_info(
                mtype=item.get("type"),
                title=item.get("title"),
                year=item.get("year"),
                mediaid=item.get("tmdbid") or item.get("mediaid"))
            yield {
                "id": item.get("id"),
                "fav": fav,
                "rssid": rssid,
                "item_url": item_url
            }
