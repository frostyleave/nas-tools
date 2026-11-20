import re
from urllib.parse import quote

import log
from app.utils import RequestUtils
from config import Config


class TheRarbg:
    """
    TheRarBg 公开 BT 站点索引器
    站点按 IMDB ID 聚合资源，imdb-detail 页面提供 JSON 数据（?format=json），
    一次请求即可拿到种子名称、大小、做种/下载数、info_hash 与 tracker
    """

    # 默认搜索路径，可由 INDEXER_SITES.SEARCH 覆盖
    _search_path = "imdb-detail/{keyword}/"
    # 站点未返回 tracker 时使用的兜底 tracker
    _default_tracker = "udp://tracker.therarbg.to:6969/announce"

    def __init__(self, indexer):
        self._indexer = indexer
        self._domain = indexer.domain or ""
        if self._domain and not self._domain.endswith("/"):
            self._domain = self._domain + "/"
        self._proxy = Config().get_proxies() if indexer.proxy else None
        self._timeout = indexer.timeout or 30
        # 搜索路径优先取站点配置
        paths = (indexer.search or {}).get("paths") or []
        if paths and paths[0].get("path"):
            self._search_path = paths[0].get("path")

    def search(self, keyword, page=None) -> tuple[bool, list]:
        """
        按 IMDB ID 搜索种子
        :param keyword: IMDB ID，如 tt0000000
        :param page: 无需翻页，站点会返回该影片的全部种子
        :return: (是否出错, 种子列表)
        """
        if not keyword:
            return False, []
        # 只支持 IMDB ID 检索，其他关键字直接跳过
        if not re.match(r"^tt\d+$", str(keyword)):
            log.debug(f"【INDEXER】{self._indexer.name} 仅支持 IMDB ID 检索，跳过: {keyword}")
            return False, []

        searchurl = self._domain + self._search_path.format(keyword=quote(str(keyword), safe=""))
        log.info(f"【INDEXER】{self._indexer.name} 开始搜索: {searchurl}")

        res = RequestUtils(
            headers={
                "Accept": "application/json",
                "User-Agent": self._indexer.ua or Config().get_ua()
            },
            proxies=self._proxy,
            timeout=self._timeout
        ).get_res(searchurl, params={"format": "json"})

        if res is None:
            log.warn(f"【INDEXER】{self._indexer.name} 搜索失败，无法连接 {self._domain}")
            return True, []
        if res.status_code != 200:
            log.warn(f"【INDEXER】{self._indexer.name} 搜索失败，错误码：{res.status_code}")
            return True, []

        try:
            result = res.json()
        except Exception:
            log.exception(f"【INDEXER】{self._indexer.name} 返回数据解析失败：")
            return True, []

        imdb_info = result.get("imdb") or {}
        imdb_id = imdb_info.get("imdb_id") or keyword

        torrents = []
        for post in result.get("trb_posts") or []:
            name = post.get("name")
            info_hash = post.get("info_hash")
            # 无名称或哈希的种子无法下载，直接跳过
            if not name or not info_hash:
                continue
            torrents.append({
                'indexer': self._indexer.id,
                'title': name,
                'enclosure': self.__build_magnet(post),
                'pubdate': post.get("timestamp"),
                'size': self.__to_int(post.get("size")),
                'seeders': self.__to_int(post.get("seeders")),
                'peers': self.__to_int(post.get("leechers")),
                'grabs': self.__to_int(post.get("downloads")),
                'downloadvolumefactor': 0,
                'uploadvolumefactor': 1,
                'page_url': self.__build_page_url(post),
                'imdbid': post.get("imdb") or imdb_id
            })

        log.info(f"【INDEXER】{self._indexer.name} 搜索完成，共 {len(torrents)} 条")
        return False, torrents

    def __build_magnet(self, post) -> str:
        """
        由 info_hash 与 tracker 列表拼接 magnet 链接
        """
        magnet = f"magnet:?xt=urn:btih:{post.get('info_hash')}&dn={quote(str(post.get('name') or ''), safe='')}"
        trackers = [item.get("tracker") for item in post.get("trackers") or [] if item and item.get("tracker")]
        if not trackers:
            trackers = [self._default_tracker]
        for tracker in trackers:
            magnet = magnet + f"&tr={quote(tracker, safe='')}"
        return magnet

    def __build_page_url(self, post) -> str:
        """
        拼接详情页地址：/post-detail/{eid}/{slug}/，slug 由名称转换，与站点规则一致
        """
        eid = post.get("eid")
        if not eid:
            return self._domain
        slug = re.sub(r"[^a-z0-9]+", "-", str(post.get("name") or "").lower()).strip("-")
        if slug:
            return f"{self._domain}post-detail/{eid}/{slug}/"
        return f"{self._domain}post-detail/{eid}/"

    @staticmethod
    def __to_int(value) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0
