import re
from typing import ClassVar

import log
from app.utils import RequestUtils, StringUtils
from config import Config


class TNodeSpider:
    # 站点标签枚举，对应搜索结果的 tags 字段
    _tags_map: ClassVar[dict[int, str]] = {
        601: "官方",
        602: "禁转",
        603: "国语",
        604: "中字",
        611: "杜比视界",
        613: "HDR10",
        614: "特效字幕",
        621: "完结",
        622: "分集",
    }

    _indexerid = None
    _domain = None
    _name = ""
    _proxy = None
    _cookie = None
    _ua = None
    _token = None
    _size = 100
    _searchurl = "%sapi/torrent/advancedSearch"
    _downloadurl = "%sapi/torrent/download/%s"
    _pageurl = "%storrent/info/%s"

    def __init__(self, indexer):
        if indexer:
            self._indexerid = indexer.id
            self._domain = indexer.domain
            self._searchurl = self._searchurl % self._domain
            self._name = indexer.name
            if indexer.proxy:
                self._proxy = Config().get_proxies()
            self._cookie = indexer.cookie
            self._ua = indexer.ua
        self.init_config()

    def init_config(self):
        self._size = 100
        self.__get_token()

    def __get_token(self):
        if not self._domain:
            return
        res = RequestUtils(ua=self._ua,
                           cookies=self._cookie,
                           proxies=self._proxy,
                           timeout=15).get_res(url=self._domain)
        if res and res.status_code == 200:
            csrf_token = re.search(r'<meta name="x-csrf-token" content="(.+?)">', res.text)
            if csrf_token:
                self._token = csrf_token.group(1)

    def search(self, keyword, page=0) -> tuple[bool, list]:
        
        if not self._token:
            log.warn(f"【INDEXER】{self._name} 未获取到token, 无法搜索")
            return True, []
        
        params = {
            "page": int(page) + 1,
            "size": self._size,
            "type": "title",
            "keyword": keyword or "",
            "sorter": "id",
            "order": "desc",
            "tags": [],
            "category": [501, 502, 503, 504],
            "medium": [],
            "videoCoding": [],
            "audioCoding": [],
            "resolution": [],
            "group": []
        }
        res = RequestUtils(
            headers={
                'X-CSRF-TOKEN': self._token,
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": f"{self._ua}"
            },
            cookies=self._cookie,
            proxies=self._proxy,
            timeout=30
        ).post_res(url=self._searchurl, json=params)
        torrents = []
        if res and res.status_code == 200:
            results = res.json().get('data', {}).get("torrents") or []
            for result in results:
                torrent = {
                    'indexer': self._indexerid,
                    'title': result.get('title'),
                    'description': result.get('subtitle'),
                    'enclosure': self._downloadurl % (self._domain, result.get('id')),
                    'pubdate': StringUtils.timestamp_to_date(result.get('upload_time')),
                    'size': result.get('size'),
                    'seeders': result.get('seeding'),
                    'peers': result.get('leeching'),
                    'grabs': result.get('complete'),
                    'downloadvolumefactor': result.get('downloadRate'),
                    'uploadvolumefactor': result.get('uploadRate'),
                    'page_url': self._pageurl % (self._domain, result.get('id')),
                    'imdbid': result.get('imdb_id') or result.get('imdb'),
                    'labels': self.__parse_labels(result),
                    'progress': self.__parse_progress(result)
                }
                torrents.append(torrent)
        elif res is not None:
            log.warn(f"【INDEXER】{self._name} 搜索失败，错误码：{res.status_code}")
            return True, []
        else:
            log.warn(f"【INDEXER】{self._name} 搜索失败，无法连接 {self._domain}")
            return True, []
        return False, torrents

    @classmethod
    def __parse_labels(cls, result: dict) -> str:
        """
        生成标签：促销标签 + 站点数字标签
        """
        labels = []
        if cls.__to_float(result.get('uploadRate')) == 2:
            labels.append("2xUp")
        if cls.__to_float(result.get('downloadRate')) == 0:
            labels.append("Free")
        for tag_id in result.get('tags') or []:
            try:
                tag_name = cls._tags_map.get(int(tag_id))
            except (TypeError, ValueError):
                tag_name = None
            if tag_name:
                labels.append(tag_name)
        return "|".join(labels)

    @classmethod
    def __parse_progress(cls, result: dict) -> str:
        """
        下载状态枚举换算为进度：3 下载中按 0%，2 已完成、4 做种中按 100%，其余为空
        """
        progress = cls.__to_float(result.get('progress'))
        if progress == 3:
            return "0%"
        if progress in (2, 4):
            return "100%"
        return ""

    @staticmethod
    def __to_float(value) -> float | None:
        """
        转为浮点数，无法转换时返回 None
        """
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
