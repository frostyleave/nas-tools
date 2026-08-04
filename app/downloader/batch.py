"""
批量下载编排模块

负责根据搜索命中的媒体信息列表，智能选择并添加下载任务。
支持整季匹配、分集匹配、以及从整季种子中选取部分集等策略。
从 Downloader 类中提取，遵循单一职责原则。
"""

from typing import TYPE_CHECKING

import log

from app.utils import TorrentUtils
from app.utils.types import MediaType, SearchType

if TYPE_CHECKING:
    from app.downloader.downloader import Downloader


class BatchDownloader:
    """
    批量下载编排器

    根据搜索命中的媒体信息和缺失的剧集清单，采用多种策略匹配并添加下载任务。
    """

    def __init__(self, downloader: 'Downloader'):
        self._downloader = downloader

    def execute(self,
                in_from: SearchType,
                media_list: list,
                need_tvs: dict = None,
                user_name=None):
        """
        根据命中的种子媒体信息, 添加下载, 由RSS或Searcher调用
        :param in_from: 来源
        :param media_list: 命中并已经识别好的媒体信息列表
        :param need_tvs: 缺失的剧集清单
        :param user_name: 用户名称
        :return: 已经添加了下载的媒体信息表、剩余未下载到的媒体信息
        """
        return_items = []
        download_list = TorrentUtils.get_download_list(
            media_list, self._downloader._config.download_order)

        # 下载掉所有的电影
        for item in download_list:
            if item.type == MediaType.MOVIE:
                self._download_single(item, in_from, user_name, return_items)

        # 电视剧整季匹配
        if need_tvs:
            need_tvs = self._match_full_seasons(download_list, need_tvs, return_items, in_from, user_name)

        # 电视剧季内的集匹配
        if need_tvs:
            need_tvs = self._match_episodes_in_season(download_list, need_tvs, return_items, in_from, user_name)

        # 仍然缺失的剧集, 从整季中选择需要的集数文件下载
        if need_tvs:
            self._select_episodes_from_season(download_list, need_tvs, return_items, in_from, user_name)

        return return_items, need_tvs

    def _download_single(self, item, in_from, user_name, return_items):
        """下载单个媒体项"""
        downloader = self._downloader
        _downloader_id, did, _ = downloader.download(
            media_info=item,
            download_dir=item.save_path,
            download_setting=item.download_setting,
            in_from=in_from,
            user_name=user_name)
        if did and item not in return_items:
            return_items.append(item)

    def _match_full_seasons(self, download_list, need_tvs, return_items, in_from, user_name):
        """整季匹配：查找整季包含的种子"""
        downloader = self._downloader

        need_seasons = {}
        for need_tmdbid, need_tv in need_tvs.items():
            for tv in need_tv:
                if not tv:
                    continue
                if not tv.get("episodes"):
                    need_seasons.setdefault(need_tmdbid, []).append(tv.get("season") or 1)

        for need_tmdbid, need_season in need_seasons.items():
            for item in download_list:
                if item.type == MediaType.MOVIE or item.get_episode_list():
                    continue
                item_season = item.get_season_list()
                if need_tmdbid == item.tmdb_id and set(item_season).issubset(set(need_season)):
                    torrent_episodes = None
                    torrent_path = None
                    if len(item_season) == 1:
                        torrent_episodes, torrent_path = downloader.get_torrent_episodes(
                            url=item.enclosure, page_url=item.page_url)
                        total_eps = self._get_season_episodes(need_tmdbid, item_season[0], need_tvs)
                        if not torrent_episodes or len(torrent_episodes) >= total_eps:
                            _, download_id = self._do_download(
                                item, torrent_path, in_from, user_name, return_items)
                        else:
                            log.info(f"【Downloader】种子 {item.org_string} 未含集数信息, 解析文件数为 {len(torrent_episodes)}")
                            continue
                    else:
                        _, download_id = self._do_download(
                            item, None, in_from, user_name, return_items)

                    if download_id:
                        need_season = self._update_seasons(need_tmdbid, need_season, item_season, need_tvs)
        return need_tvs

    def _match_episodes_in_season(self, download_list, need_tvs, return_items, in_from, user_name):
        """集匹配：查找单季含集的种子"""
        need_tv_list = list(need_tvs)
        for need_tmdbid in need_tv_list:
            need_tv = need_tvs.get(need_tmdbid)
            if not need_tv:
                continue
            for idx, tv in enumerate(need_tv):
                need_season = tv.get("season") or 1
                need_episodes = tv.get("episodes")
                total_episodes = tv.get("total_episodes")
                if not need_episodes:
                    need_episodes = list(range(1, total_episodes + 1))
                for item in download_list:
                    if item.type == MediaType.MOVIE or item in return_items:
                        continue
                    if item.tmdb_id == need_tmdbid:
                        item_season = item.get_season_list()
                        if len(item_season) != 1 or item_season[0] != need_season:
                            continue
                        item_episodes = item.get_episode_list()
                        if not item_episodes:
                            continue
                        if set(item_episodes).issubset(set(need_episodes)):
                            _, download_id = self._do_download(item, None, in_from, user_name, return_items)
                            if download_id:
                                need_episodes = self._update_episodes(
                                    need_tmdbid, idx, need_episodes, item_episodes, need_tvs)
        return need_tvs

    def _select_episodes_from_season(self, download_list, need_tvs, return_items, in_from, user_name):
        """从整季中选择需要的集下载（仅支持QB和TR）"""
        downloader = self._downloader
        need_tv_list = list(need_tvs)
        for need_tmdbid in need_tv_list:
            need_tv = need_tvs.get(need_tmdbid)
            if not need_tv:
                continue
            for idx, tv in enumerate(need_tv):
                need_season = tv.get("season") or 1
                need_episodes = tv.get("episodes")
                if not need_episodes:
                    continue
                for item in download_list:
                    if item.type == MediaType.MOVIE or item in return_items:
                        continue
                    if not need_episodes:
                        break
                    if (item.tmdb_id == need_tmdbid
                            and (not item.get_episode_list()
                                 or set(item.get_episode_list()).intersection(set(need_episodes)))
                            and len(item.get_season_list()) == 1
                            and item.get_season_list()[0] == need_season):
                        torrent_episodes, torrent_path = downloader.get_torrent_episodes(
                            url=item.enclosure, page_url=item.page_url)
                        selected_episodes = set(torrent_episodes).intersection(set(need_episodes))
                        if not selected_episodes:
                            log.info("【Downloader】%s 没有需要的集, 跳过..." % item.org_string)
                            continue

                        downloader_id, download_id = self._do_download(
                            item, torrent_path, in_from, user_name, return_items, is_paused=True)
                        if not download_id:
                            continue

                        need_episodes = self._update_episodes(
                            need_tmdbid, idx, need_episodes, selected_episodes, need_tvs)

                        log.info("【Downloader】从 %s 中选取集: %s" % (item.org_string, selected_episodes))
                        downloader.set_files_status(tid=download_id, need_episodes=selected_episodes,
                                                    downloader_id=downloader_id)
                        log.info("【Downloader】%s 开始下载 " % item.org_string)
                        downloader.start_torrents(ids=download_id, downloader_id=downloader_id)
                        return_items.append(item)

    def _do_download(self, item, torrent_file=None, tag=None, is_paused=None,
                     in_from=None, user_name=None, return_items=None):
        """执行下载并记录"""
        downloader = self._downloader
        _downloader_id, did, _ = downloader.download(
            media_info=item,
            download_dir=item.save_path,
            download_setting=item.download_setting,
            torrent_file=torrent_file,
            tag=tag,
            is_paused=is_paused,
            in_from=in_from,
            user_name=user_name)
        if did:
            if item not in return_items:
                return_items.append(item)
        return _downloader_id, did

    @staticmethod
    def _update_seasons(tmdbid, need, current, need_tvs):
        """更新 need_tvs 季数"""
        need = list(set(need).difference(set(current)))
        for cur in current:
            for nt in need_tvs.get(tmdbid):
                if cur == nt.get("season") or (cur == 1 and not nt.get("season")):
                    need_tvs[tmdbid].remove(nt)
        if not need_tvs.get(tmdbid):
            need_tvs.pop(tmdbid)
        return need

    @staticmethod
    def _update_episodes(tmdbid, seq, need, current, need_tvs):
        """更新 need_tvs 集数"""
        need = list(set(need).difference(set(current)))
        if need:
            need_tvs[tmdbid][seq]["episodes"] = need
        else:
            need_tvs[tmdbid].pop(seq)
            if not need_tvs.get(tmdbid):
                need_tvs.pop(tmdbid)
        return need

    @staticmethod
    def _get_season_episodes(tmdbid, season, need_tvs):
        """获取需要的季的集数"""
        if not need_tvs.get(tmdbid):
            return 0
        for nt in need_tvs.get(tmdbid):
            if season == nt.get("season"):
                return nt.get("total_episodes")
        return 0
