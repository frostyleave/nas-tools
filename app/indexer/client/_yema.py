import datetime
from typing import ClassVar
from urllib.parse import parse_qs, quote, urlparse

import log
from app.models.model import IndexerInfo
from app.utils import JsonUtils, RequestUtils, SiteUtils, TimeUtils
from app.utils.types import MediaType
from config import Config


class YemaSpider:
    """
    YemaPT 站点 API 索引器
    """
    _indexerid = None
    _name = ""
    _base_url = "https://www.yemapt.org"
    _cookie = None
    _apikey = None
    _ua = None
    _proxy = None
    _timeout = 15

    # 站点单页最多返回 40 条，超过会被静默忽略
    _size = 40

    # 站内接口（Cookie 鉴权）
    _search_path = "/api/torrent/fetchOpenTorrentList"
    _download_path = "/api/torrent/download?id=%s"
    _page_path = "%s/#/torrent/detail/%s"

    # 开放 API（API Auth Key 鉴权，Authorization 直接填 AuthKey）
    _openapi_search_path = "/openApi/torrent/fetchOpenTorrentList.json"
    _openapi_download_key_path = "/openApi/torrent/generateDownloadKey.json"
    # 临时下载凭证有效期 30 分钟，凭证中的特殊字符需要 URL 编码
    _download_token_path = "/api/torrent/download1?token=%s"

    # 促销枚举对应的下载/上传系数
    _download_factors: ClassVar[dict] = {
        "none": 1.0,
        "half": 0.5,
        "free": 0.0
    }
    _upload_factors: ClassVar[dict] = {
        "none": 1.0,
        "one_half": 1.5,
        "double_upload": 2.0
    }

    # 站点分类ID -> 媒体类型
    _category_types: ClassVar[dict] = {
        4: MediaType.MOVIE.value,
        5: MediaType.TV.value,
        14: MediaType.ANIME.value
    }

    # 搜索时按媒体类型收窄的分类ID
    # 接口只支持单个叶子分类，电视剧相关分类（剧集/综艺/纪录片/短剧）无法一次覆盖，因此不传
    _search_category_types: ClassVar[dict] = {
        MediaType.MOVIE: 4,
        MediaType.ANIME: 14
    }

    # 种子标签ID -> 名称，接口未返回 tagNameList 时使用
    _tag_names: ClassVar[dict] = {
        "1": "禁转",
        "2": "首发",
        "3": "官组",
        "4": "DIY",
        "5": "国语",
        "6": "中字",
        "7": "粤语",
        "8": "英字",
        "9": "HDR10",
        "10": "杜比视界",
        "11": "连载中",
        "12": "完结",
        "13": "多国字幕",
        "14": "HDR10+",
        "15": "杜比全景声(Atmos)",
        "16": "DTS-X",
        "17": "5.1/7.1声道",
        "18": "完结全集",
        "19": "SP/剧场版/OVA"
    }

    def __init__(self, indexer: IndexerInfo):
        if indexer:
            self._indexerid = indexer.id
            self._name = indexer.name
            self._base_url = SiteUtils.get_base_url(indexer.domain) or "https://www.yemapt.org"
            self._cookie = indexer.cookie
            # API Auth Key 优先取 API Key 字段，其次取 Authorization 字段
            self._apikey = indexer.apikey or indexer.token
            self._ua = indexer.ua or Config().get_ua()
            if indexer.proxy:
                self._proxy = Config().get_proxies()
            self._timeout = indexer.timeout or 15

    def search(self, keyword: str, mtype: MediaType = None, page: int = 0) -> tuple[bool, list]:
        """
        搜索
        """
        # 同时配置 API Auth Key 和 Cookie 时优先使用 API Auth Key
        use_apikey = bool(self._apikey)
        if not use_apikey and not self._cookie:
            log.warn("【INDEXER】%s 未配置Cookie或API Auth Key，无法搜索", self._name)
            return True, []

        params = {
            "keyword": keyword or "",
            "pageParam": {
                "current": int(page) + 1,
                "pageSize": self._size
            },
            "sorter": {}
        }
        # 按媒体类型收窄分类
        category_id = self._search_category_types.get(mtype) if mtype else None
        if category_id:
            params["categoryId"] = category_id

        search_path = self._openapi_search_path if use_apikey else self._search_path
        res = RequestUtils(
            headers=self.__api_headers(),
            cookies=None if use_apikey else self._cookie,
            proxies=self._proxy,
            timeout=self._timeout
        ).post_res(url=f"{self._base_url}{search_path}", json=params)

        torrents = []
        if res and res.status_code == 200:
            result = JsonUtils.loads(res.text, default=None, silent=True)
            if not isinstance(result, dict):
                log.warn("【INDEXER】%s 搜索失败：接口返回格式异常", self._name)
                return True, []
            if not result.get("success"):
                log.warn("【INDEXER】%s 搜索失败：%s", self._name,
                         result.get("errorMessage") or result.get("errorCode") or "接口返回异常")
                return True, []
            for item in result.get("data") or []:
                torrent = self.__build_torrent(item)
                if torrent:
                    torrents.append(torrent)
        elif res is not None:
            log.warn("【INDEXER】%s 搜索失败，错误码：%s", self._name, res.status_code)
            return True, []
        else:
            log.warn("【INDEXER】%s 搜索失败，无法连接 %s", self._name, self._base_url)
            return True, []

        return False, torrents

    def get_torrent(self, url: str):
        """
        下载种子文件；配置 API Auth Key 时先换取临时下载凭证，再用凭证下载
        """
        torrent_id = self.__parse_torrent_id(url)
        if not torrent_id:
            log.warn("【INDEXER】%s 无法从下载链接解析种子ID：%s", self._name, url)
            return None

        if self._apikey:
            download_key = self.__generate_download_key(torrent_id)
            if not download_key:
                return None
            # 下载凭证是 Base64 字符串，作为查询参数前必须编码
            download_url = f"{self._base_url}{self._download_token_path % quote(download_key, safe='')}"
            return RequestUtils(headers=self.__download_headers(),
                                proxies=self._proxy,
                                timeout=self._timeout
                                ).get_res(url=download_url)

        return RequestUtils(headers=self.__download_headers(),
                            cookies=self._cookie,
                            proxies=self._proxy,
                            timeout=self._timeout
                            ).get_res(url=f"{self._base_url}{self._download_path % torrent_id}")

    def __api_headers(self) -> dict:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "User-Agent": self._ua
        }
        if self._apikey:
            # API Auth Key 直接放在 Authorization 中，不加 Bearer 前缀
            headers["Authorization"] = self._apikey
        return headers

    def __download_headers(self) -> dict:
        return {
            "Accept": "application/octet-stream, */*",
            "User-Agent": self._ua
        }

    def __generate_download_key(self, torrent_id: str) -> str | None:
        """
        通过开放 API 生成临时下载凭证
        """
        res = RequestUtils(headers=self.__api_headers(),
                           proxies=self._proxy,
                           timeout=self._timeout
                           ).post_res(url=f"{self._base_url}{self._openapi_download_key_path}",
                                      params={"id": torrent_id})
        if not res or res.status_code != 200:
            log.warn("【INDEXER】%s 获取下载凭证失败", self._name)
            return None

        result = JsonUtils.loads(res.text, default=None, silent=True)
        if not isinstance(result, dict) or not result.get("success"):
            message = result.get("errorMessage") if isinstance(result, dict) else None
            log.warn("【INDEXER】%s 获取下载凭证失败：%s", self._name, message or "接口返回异常")
            return None

        download_key = result.get("data")
        if isinstance(download_key, dict):
            download_key = download_key.get("key") or download_key.get("token")
        if isinstance(download_key, str) and download_key:
            return download_key
        return None

    @staticmethod
    def __parse_torrent_id(url: str) -> str | None:
        if not url:
            return None
        torrent_id = (parse_qs(urlparse(url).query).get("id") or [None])[0]
        return str(torrent_id) if torrent_id else None

    def __build_torrent(self, item: dict) -> dict | None:
        """
        将接口返回的种子数据转换为索引器通用结构
        """
        torrent_id = item.get("id")
        title = item.get("showName")
        if torrent_id is None or not title:
            return None

        download_factor = self.__promotion_factor(item.get("downloadPromotion"),
                                                  item.get("downloadPromotionEndTime"),
                                                  self._download_factors)
        upload_factor = self.__promotion_factor(item.get("uploadPromotion"),
                                                item.get("uploadPromotionEndTime"),
                                                self._upload_factors)

        labels = []
        if download_factor == 0:
            labels.append("Free")
        if upload_factor > 1:
            labels.append(f"{upload_factor:g}X")
        tag_names = item.get("tagNameList")
        if not tag_names:
            tag_names = [self._tag_names.get(str(tag), str(tag)) for tag in item.get("tagList") or []]
        labels.extend(tag_names)

        return {
            "indexer": self._indexerid,
            "title": title,
            "description": item.get("shortDesc") or "",
            "enclosure": f"{self._base_url}{self._download_path % torrent_id}",
            "pubdate": item.get("listingTime"),
            "size": self.__to_int(item.get("fileSize")),
            "seeders": self.__to_int(item.get("seedNum")),
            "peers": self.__to_int(item.get("leechNum")),
            "grabs": 0,
            "downloadvolumefactor": download_factor,
            "uploadvolumefactor": upload_factor,
            "page_url": self._page_path % (self._base_url, torrent_id),
            "imdbid": self.__format_imdb(item.get("imdb")),
            "labels": "|".join(dict.fromkeys(label for label in labels if label)),
            "category": self._category_types.get(item.get("categoryId"), MediaType.UNKNOWN.value)
        }

    @classmethod
    def __promotion_factor(cls, promotion: str, end_time: str, factors: dict) -> float:
        """
        促销系数，已过期或不认识的促销类型按正常处理
        """
        factor = factors.get(promotion)
        if factor is None:
            return 1.0
        if end_time:
            try:
                if datetime.datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S") <= TimeUtils.now():
                    return 1.0
            except (TypeError, ValueError):
                return 1.0
        return factor

    @staticmethod
    def __format_imdb(imdb) -> str:
        """
        补全 imdbid 的 tt 前缀
        """
        if not imdb:
            return ""
        imdb = str(imdb).strip()
        if imdb.lower().startswith("tt"):
            return imdb
        return f"tt{imdb}" if imdb.isdigit() else imdb

    @staticmethod
    def __to_int(value) -> int:
        """
        转为整数，无法转换时返回 0
        """
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
