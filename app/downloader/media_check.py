"""
媒体库存在性检查模块

负责检查媒体库中是否已存在指定媒体，返回缺失的季/集信息。
从 Downloader 类中提取，遵循单一职责原则。
"""

import log

from app.utils.types import MediaType


class MediaExistenceChecker:
    """
    媒体库存在性检查器

    检查媒体库（Emby/Jellyfin）或本地文件系统中是否已存在指定媒体。
    """

    def __init__(self, media, mediaserver, filetransfer):
        """
        :param media: Media 实例
        :param mediaserver: MediaServer 实例
        :param filetransfer: FileTransfer 实例
        """
        self._media = media
        self._mediaserver = mediaserver
        self._filetransfer = filetransfer

    def check(self, meta_info, no_exists=None, total_ep=None):
        """
        检查媒体库, 查询是否存在, 对于剧集同时返回不存在的季集信息
        :param meta_info: 已识别的媒体信息, 包括标题、年份、季、集信息
        :param no_exists: 在调用该方法前已经存储的不存在的季集信息
        :param total_ep: 各季的总集数
        :return: 当前媒体是否缺失, 各标题总的季集和缺失的季集, 需要发送的消息
        """
        if not no_exists:
            no_exists = {}
        if not total_ep:
            total_ep = {}

        # 查找的季
        if not meta_info.begin_season:
            search_season = None
        else:
            search_season = meta_info.get_season_list()
        # 查找的集
        search_episode = meta_info.get_episode_list()
        if search_episode and not search_season:
            search_season = [1]

        message_list = []
        if meta_info.type != MediaType.MOVIE:
            return self._check_tv(meta_info, search_season, search_episode, no_exists, total_ep, message_list)
        else:
            return self._check_movie(meta_info, message_list)

    def _check_tv(self, meta_info, search_season, search_episode, no_exists, total_ep, message_list):
        """检查电视剧是否已存在"""
        return_flag = False
        tv_info = self._media.get_tmdb_info(mtype=MediaType.TV, tmdbid=meta_info.tmdb_id)
        if tv_info:
            total_seasons = []
            if search_season:
                for season in search_season:
                    if total_ep.get(season):
                        episode_num = total_ep.get(season)
                    else:
                        episode_num = self._media.get_tmdb_season_episodes_num(tv_info=tv_info, season=season)
                    if not episode_num:
                        log.info("【Downloader】%s 第%s季 不存在" % (meta_info.get_title_string(), season))
                        message_list.append("%s 第%s季 不存在" % (meta_info.get_title_string(), season))
                        continue
                    total_seasons.append({"season_number": season, "episode_count": episode_num})
                    log.info("【Downloader】%s 第%s季 共有 %s 集" % (meta_info.get_title_string(), season, episode_num))
            else:
                total_seasons = self._media.get_tmdb_tv_seasons(tv_info=tv_info)
                log.info("【Downloader】%s %s 共有 %s 季" % (
                    meta_info.type.value, meta_info.get_title_string(), len(total_seasons)))
                message_list.append("%s %s 共有 %s 季" % (meta_info.type.value, meta_info.get_title_string(), len(total_seasons)))

            if not total_seasons:
                return_flag = None
            else:
                for season in total_seasons:
                    season_number = season.get("season_number")
                    episode_count = season.get("episode_count")
                    if not season_number or not episode_count:
                        continue

                    no_exists_episodes = self._mediaserver.get_no_exists_episodes(meta_info, season_number, episode_count)
                    if no_exists_episodes is None:
                        no_exists_episodes = self._filetransfer.get_no_exists_medias(meta_info, season_number, episode_count)

                    if no_exists_episodes:
                        no_exists_episodes.sort()
                        if not no_exists.get(meta_info.tmdb_id):
                            no_exists[meta_info.tmdb_id] = []
                        exists_tvs_str = "、".join(["%s" % tv for tv in no_exists_episodes])
                        if len(no_exists_episodes) >= episode_count:
                            no_item = {"season": season_number, "episodes": [], "total_episodes": episode_count}
                            log.info("【Downloader】%s 第%s季 缺失 %s 集" % (
                                meta_info.get_title_string(), season_number, episode_count))
                            if search_season:
                                message_list.append("%s 第%s季 缺失 %s 集" % (meta_info.title, season_number, episode_count))
                            else:
                                message_list.append("第%s季 缺失 %s 集" % (season_number, episode_count))
                        else:
                            no_item = {"season": season_number, "episodes": no_exists_episodes, "total_episodes": episode_count}
                            log.info("【Downloader】%s 第%s季 缺失集: %s" % (
                                meta_info.get_title_string(), season_number, exists_tvs_str))
                            if search_season:
                                message_list.append("%s 第%s季 缺失集: %s" % (meta_info.title, season_number, exists_tvs_str))
                            else:
                                message_list.append("第%s季 缺失集: %s" % (season_number, exists_tvs_str))
                        if no_item not in no_exists.get(meta_info.tmdb_id):
                            no_exists[meta_info.tmdb_id].append(no_item)
                        if search_episode:
                            if not set(search_episode).intersection(set(no_exists_episodes)):
                                msg = f"媒体库中已存在剧集: \n • {meta_info.get_title_string()} {meta_info.get_season_episode_string()}"
                                log.info(f"【Downloader】{msg}")
                                message_list.append(msg)
                                return_flag = True
                                break
                    else:
                        log.info("【Downloader】%s 第%s季 共%s集 已全部存在" % (
                            meta_info.get_title_string(), season_number, episode_count))
                        if search_season:
                            message_list.append("%s 第%s季 共%s集 已全部存在" % (meta_info.title, season_number, episode_count))
                        else:
                            message_list.append("第%s季 共%s集 已全部存在" % (season_number, episode_count))
        else:
            log.info("【Downloader】%s 无法查询到媒体详细信息" % meta_info.get_title_string())
            message_list.append("%s 无法查询到媒体详细信息" % meta_info.get_title_string())
            return_flag = None

        if return_flag is False and not no_exists.get(meta_info.tmdb_id):
            return_flag = True
        return return_flag, no_exists, message_list

    def _check_movie(self, meta_info, message_list):
        """检查电影是否已存在"""
        exists_movies = self._mediaserver.get_movies(meta_info.title, meta_info.year)
        if exists_movies is None:
            exists_movies = self._filetransfer.get_no_exists_medias(meta_info)
        if exists_movies:
            movies_str = "\n • ".join(["%s (%s)" % (m.get('title'), m.get('year')) for m in exists_movies])
            msg = f"媒体库中已存在电影: \n • {movies_str}"
            log.info(f"【Downloader】{msg}")
            message_list.append(msg)
            return True, {}, message_list
        return False, {}, message_list
