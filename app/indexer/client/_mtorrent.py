# author: https://github.com/jxxghp/MoviePilot/blob/main/app/modules/indexer/mtorrent.py
import re
from typing import ClassVar

import log as logger
from app.models.model import IndexerInfo
from app.utils import RequestUtils, SiteUtils, StringUtils
from app.utils.types import MediaType
from config import Config


class MTorrentSpider:
    """
    mTorrent API
    """
    _indexerid = None
    _domain = None
    _url = None
    _name = ""
    _proxy = None
    _ua = None
    _size = 100
    _search_url = "https://api.%s/api/torrent/search"
    _download_url = "https://api.%s/api/torrent/genDlToken"
    _subtitle_url = "https://api.%s/api/subtitle/list"
    _subtitle_link = "https://api.%s/api/subtitle/genlink"
    _pageurl = "%sdetail/%s"
    _timeout = 15

    _host = None

    # 电影分类
    _movie_category: ClassVar[list[str]] = ['401', '419', '420', '421', '439', '405', '404']
    _tv_category: ClassVar[list[str]] = ['403', '402', '435', '438', '404', '405']

    # API KEY
    _apikey = None
    # JWT Token
    _token = None

    # 标签
    _labels: ClassVar[dict] = {
        "0": "",
        "1": "DIY",
        "2": "国配",
        "3": "DIY 国配",
        "4": "中字",
        "5": "DIY 中字",
        "6": "国配 中字",
        "7": "DIY 国配 中字"
    }

    def __init__(self, indexer: IndexerInfo):
        if indexer:
            self._indexerid = indexer.id
            self._url = indexer.domain
            self._domain = SiteUtils.get_url_domain(self._url)
            self._host = SiteUtils.get_url_netloc(self._url)
            self._search_url = self._search_url % self._domain
            self._subtitle_url = self._subtitle_url % self._domain
            self._name = indexer.name
            if indexer.proxy:
                self._proxy = Config().get_proxies()
            self._ua = indexer.ua if indexer.ua else Config().get_ua()
            self._apikey = indexer.apikey
            self._token = indexer.token
            self._timeout = indexer.timeout or 15

    def search(self, keyword: str, mtype: MediaType = None, page: int = 0) -> tuple[bool, list]:
        """
        搜索
        """
        # 检查ApiKey
        if not self._apikey:
            return True, []

        if not mtype:
            categories = []
        elif mtype == MediaType.TV or mtype == MediaType.ANIME:
            categories = self._tv_category
        else:
            categories = self._movie_category

        params = {
            "keyword": keyword,
            "categories": categories,
            "pageNumber": int(page) + 1,
            "pageSize": self._size,
            "visible": 1
        }
        res = RequestUtils(
            headers={
                "Content-Type": "application/json",
                "User-Agent": f"{self._ua}",
                "x-api-key": self._apikey
            },
            proxies=self._proxy,
            timeout=self._timeout
        ).post_res(url=self._search_url, json=params)

        torrents = []

        if res and res.status_code == 200:
            results = res.json().get('data', {}).get("data") or []
            for result in results:

                category_value = result.get('category')
                if category_value in self._tv_category \
                        and category_value not in self._movie_category:
                    category = MediaType.TV.value
                elif category_value in self._movie_category:
                    category = MediaType.MOVIE.value
                else:
                    category = MediaType.UNKNOWN.value

                labels = result.get('labelsNew')
                if not labels:
                    labels_value = self._labels.get(result.get('labels') or "0") or ""
                    if labels_value:
                        labels = labels_value.split()
                    else:
                        labels = []

                status_info = result.get('status', {})
                
                torrent = {
                    'title': result.get('name'),
                    'description': result.get('smallDescr'),
                    'enclosure': self.__get_download_url(result.get('id')),
                    'pubdate': StringUtils.timestamp_to_date(result.get('createdDate')),
                    'size': int(result.get('size') or '0'),
                    'seeders': int(status_info.get("seeders") or '0'),
                    'peers': int(status_info.get("leechers") or '0'),
                    'grabs': int(status_info.get("timesCompleted") or '0'),
                    'downloadvolumefactor': self.__get_downloadvolumefactor(status_info.get("discount")),
                    'uploadvolumefactor': self.__get_uploadvolumefactor(status_info.get("discount")),
                    'page_url': self._pageurl % (self._url, result.get('id')),
                    'imdbid': self.__find_imdbid(result.get('imdb')),
                    'labels': "|".join(labels),
                    'category': category
                }
                torrents.append(torrent)
        elif res is not None:
            logger.warn(f"{self._name} 搜索失败，错误码：{res.status_code}")
            return True, []
        else:
            logger.warn(f"{self._name} 搜索失败，无法连接 {self._domain}")
            return True, []
        return False, torrents

    @staticmethod
    def __find_imdbid(imdb: str) -> str:
        """
        从imdb链接中提取imdbid
        """
        if imdb:
            m = re.search(r"tt\d+", imdb)
            if m:
                return m.group(0)
        return ""

    @staticmethod
    def __get_downloadvolumefactor(discount: str) -> float:
        """
        获取下载系数
        """
        discount_dict = {
            "FREE": 0,
            "PERCENT_50": 0.5,
            "PERCENT_70": 0.3,
            "_2X_FREE": 0,
            "_2X_PERCENT_50": 0.5
        }
        if discount:
            return discount_dict.get(discount, 1)
        return 1

    @staticmethod
    def __get_uploadvolumefactor(discount: str) -> float:
        """
        获取上传系数
        """
        uploadvolumefactor_dict = {
            "_2X": 2.0,
            "_2X_FREE": 2.0,
            "_2X_PERCENT_50": 2.0
        }
        if discount:
            return uploadvolumefactor_dict.get(discount, 1)
        return 1
    
    def __get_download_url(self, torrent_id: str) -> str:
        """
        获取下载链接，返回base64编码的json字符串及URL
        """
        url = self._download_url % self._domain
        return f'{url}?id={torrent_id}'

    def get_torrent(self, url: str) -> str:
        """
        获取下载链接
        """
        headers={
            "Accept": "application/json, text/plain, */*",
            "User-Agent": f"{self._ua}",
            "x-api-key": self._apikey
        }

        res = RequestUtils(headers=headers, 
                           proxies=self._proxy,
                           timeout=self._timeout
                           ).post_res(url=url)
        
        if not res:
            return None

        if res.status_code == 200:
            results = res.json().get('data', {})
            if results:
                return RequestUtils().get_res(results)

        return res
        
    def get_subtitle_list(self, torrent_id: str) -> str:
        """
        获取字幕列表
        [
            {
                "anonymous": false,
                "author": "314055",
                "createdDate": "2026-11-08 00:40:21",
                "ext": "zip",
                "filename": "The.Odyssey.2026.2160p.USA.UHD.Blu-ray.HDR.HEVC.DTS-HD.MA.5.1-TMT.简&英.zip",
                "hits": "1028",
                "id": "69193",
                "lang": "25",
                "lastModifiedDate": "2026-11-08 19:35:26",
                "name": "The.Odyssey.2026.2160p.USA.UHD.Blu-ray.HDR.HEVC.DTS-HD.MA.5.1-TMT.简&英",
                "savePath": "subtitle/2026/1108/01a1b6e1-ec11-7262-8c98-3cba9af3c1df.zip",
                "size": "2316102",
                "torrent": "1286839"
            },
            {
                "anonymous": true,
                "author": null,
                "createdDate": "2026-11-07 18:28:55",
                "ext": "ass",
                "filename": "奥德赛 The Odyssey (2026) 简体中文.zh-CN.ass",
                "hits": "1315",
                "id": "69186",
                "lang": "25",
                "lastModifiedDate": "2026-11-08 19:36:28",
                "name": "奥德赛 The Odyssey (2026) 简体中文.zh-CN",
                "savePath": "subtitle/2026/1107/01a1b58d-dbba-71bc-b15c-77dafe95e3e0.ass",
                "size": "624492",
                "torrent": "1286839"
            }
        ]
        """
        if not torrent_id:
            return None

        headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": f"{self._ua}",
            "x-api-key": self._apikey
        }
        params = { "id": torrent_id }

        res = RequestUtils(headers=headers, 
                           proxies=self._proxy,
                           timeout=self._timeout
                           ).post_res(url=self._subtitle_url, json=params)
        
        if not res:
            return None

        if res.status_code == 200:
            return res.json().get('data', [])

        return None

    def __get_subtitle_url(self, subtitle_id: str) -> str:
        """
        获取字幕下载链接
        """
        headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": f"{self._ua}",
            "x-api-key": self._apikey
        }
        params = { "id": subtitle_id }
        url = self._subtitle_link % self._domain
        res = RequestUtils(headers=headers, 
                           proxies=self._proxy,
                           timeout=self._timeout
                           ).post_res(url=url, json=params)
        if not res:
            return None

        data = res.json().get('data')
        if not data:
            return None

        return f'https://api.m-team.io/api/subtitle/dlV2?credential={data}'