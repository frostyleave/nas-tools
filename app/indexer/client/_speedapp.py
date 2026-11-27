import datetime
import math
import re
import threading
import time
from urllib.parse import urlsplit

import log
from app.models.model import IndexerInfo
from app.utils import JsonUtils, RequestUtils, SiteUtils, TimeUtils
from app.utils.types import MediaType
from config import Config

# 站点接口仅接受 Bearer 鉴权，使用站点生成的个人 API Token
_CATEGORY_TTL = 6 * 60 * 60
_CATEGORY_LOCK = threading.Lock()
_CATEGORY_CACHE: dict = {}

_CONTEXT_TTL = 5 * 60
_CONTEXT_LOCK = threading.Lock()
_CONTEXT_CACHE: dict = {}

# 用户等级名称
_CLASS_NAMES = {
    0: "农民",
    1: "用户",
    2: "超级用户",
    3: "精英用户",
    4: "极端用户",
    5: "超级用户",
    6: "传奇用户",
    7: "贵宾",
    8: "传奇贵宾",
    9: "超级播种机",
    10: "帮手",
    11: "初级上传者",
    12: "上传者",
    13: "精英上传者",
    14: "编码器",
    15: "名人堂",
    16: "初级主持人",
    17: "主持人",
    18: "行政人员",
    19: "导师",
    20: "编码器",
    21: "所有者"
}

_RESOLUTION_RE = re.compile(r"(?<![0-9])(2160p|1080p|720p|576p|480p|4k|8k)(?![0-9])", re.IGNORECASE)
# 摄录版本在片名中的写法，与名称识别的判定保持一致
_CAPTURE_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])(?:telesync|telecine|camrip|hdcam|hdts|cam|ts|tc)(?![A-Za-z0-9])",
                               re.IGNORECASE)
_CAPTURE_LABELS = {"CAM", "TS"}
_YEAR_RE = re.compile(r"(?<![0-9])(?:19|20)\d{2}(?![0-9])")
_SOURCE_PATTERNS = (
    ("Remux", re.compile(r"\bremux\b", re.IGNORECASE)),
    ("BluRay", re.compile(r"\bblu-?ray\b", re.IGNORECASE)),
    ("WEB-DL", re.compile(r"\bweb[.\s-]?dl\b", re.IGNORECASE)),
    ("WEBRip", re.compile(r"\bweb[.\s-]?rip\b", re.IGNORECASE)),
    ("HDTV", re.compile(r"\bhdtv\b", re.IGNORECASE)),
    ("BDRip", re.compile(r"\bbdrip\b", re.IGNORECASE)),
    ("HDRip", re.compile(r"\bhdrip\b", re.IGNORECASE)),
    ("DVD", re.compile(r"\bdvd(?:rip|r|9|5)?\b", re.IGNORECASE)),
)

# 站点来源标签（tag.type == source）转换后的来源标签
_SOURCE_TAG_LABELS = {
    "cam": "CAM",
    "ts": "TS",
    "bluray": "BluRay",
    "webdl": "WEB-DL",
    "hdtv": "HDTV",
    "dvd": "DVD",
    "dvdr": "DVD",
    "hddvd": "HD-DVD",
    "cd": "CD",
    "tv": "TV",
    "hd": "HD",
}

# 发布明细中的来源 token；片名可能包含同名影片，因此不参与判断
_SOURCE_TOKEN_LABELS = {
    "cam": "CAM",
    "camrip": "CAM",
    "hdcam": "CAM",
    "ts": "TS",
    "hdts": "TS",
    "tc": "TC",
}


class SpeedAppError(Exception):
    """SpeedApp 接口错误"""


class SpeedAppAuthError(SpeedAppError):
    """SpeedApp 鉴权错误"""


def integer(value, minimum: int = 0) -> int:
    """
    校验接口返回的计数和字节数，拒绝布尔值、浮点和负数
    """
    if isinstance(value, bool):
        raise TypeError("SpeedApp 数值字段无效")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and value.strip().isdigit():
        result = int(value.strip())
    else:
        raise ValueError("SpeedApp 数值字段无效")
    if result < minimum:
        raise ValueError("SpeedApp 数值字段无效")
    return result


def number(value) -> float:
    """
    解析分享率、魔力值等数值字段
    """
    if value is None or isinstance(value, bool):
        raise ValueError("SpeedApp 数值字段无效")
    try:
        result = float(value)
    except (TypeError, ValueError) as err:
        raise ValueError("SpeedApp 数值字段无效") from err
    if not math.isfinite(result):
        raise ValueError("SpeedApp 数值字段无效")
    return result


def local_time(value) -> str | None:
    """
    把带时区的接口时间转换为本地日期时间文本
    """
    if not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    timezone = TimeUtils.get_timezone()
    if timezone is not None:
        parsed = parsed.astimezone(timezone)
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def class_name(value) -> str | None:
    """
    用户等级编号转换为名称
    """
    try:
        level = integer(value)
    except ValueError:
        return None
    return _CLASS_NAMES.get(level) or f"Level {level}"


def response_error(status_code: int, payload, retry_after=None) -> str:
    """
    根据 API 响应生成可读错误信息，不回显凭据
    """
    detail = ""
    if isinstance(payload, dict):
        detail = str(payload.get("detail") or payload.get("message") or payload.get("title") or "").strip()
        if not detail:
            violations = payload.get("violations")
            if isinstance(violations, list):
                messages = [str(item.get("message")) for item in violations[:3]
                            if isinstance(item, dict) and item.get("message")]
                detail = "；".join(messages)
    detail = " ".join(detail.split())[:200]

    if status_code == 401:
        return "SpeedApp API Token 已失效"
    if status_code == 403:
        reason = "搜索需要 torrent.read，下载需要 torrent.download"
        return f"SpeedApp 缺少所需范围（{reason}）{f'：{detail}' if detail else ''}"
    if status_code == 404:
        return "SpeedApp 资源不存在或无权查看"
    if status_code == 429:
        wait = f"请 {retry_after} 秒后重试" if retry_after else "请稍后重试"
        return f"SpeedApp 站点限流：{wait}"
    if status_code == 422:
        return f"SpeedApp 请求参数无效{f'：{detail}' if detail else ''}"
    if status_code >= 500:
        return f"SpeedApp 服务端错误，HTTP {status_code}"
    return f"SpeedApp API 请求失败，HTTP {status_code}{f'：{detail}' if detail else ''}"


def version_labels(name: str, release_details, tags=None) -> list:
    """
    从发布名、站点解析结果和来源标签中提取来源、分辨率标签
    """
    parts = [str(part) for part in release_details or [] if isinstance(part, str)]
    text = " ".join([str(name or "")] + parts)
    labels = []

    match = _RESOLUTION_RE.search(text)
    if match:
        resolution = match.group(1).lower()
        labels.append({"4k": "2160p", "8k": "4320p"}.get(resolution, resolution))
    elif re.search(r"\buhd\b", text, re.IGNORECASE):
        labels.append("2160p")

    for label, pattern in _SOURCE_PATTERNS:
        if label not in labels and pattern.search(text):
            labels.append(label)

    # 站点来源标签比片名更可靠，CAM/TS 这类版本只能通过标签或发布明细识别
    for tag in tags or []:
        if not isinstance(tag, dict) or tag.get("type") != "source":
            continue
        tag_name = str(tag.get("name") or "").strip()
        if not tag_name:
            continue
        key = tag_name.lower().removeprefix("tag.source.")
        label = _SOURCE_TAG_LABELS.get(key) or tag_name
        if label not in labels:
            labels.append(label)

    # 发布明细中的来源 token；标题可能包含同名影片，不能作为判断依据
    for part in parts:
        label = _SOURCE_TOKEN_LABELS.get(part.strip().lower())
        if label and label not in labels:
            labels.append(label)

    return labels


def title_with_capture(name: str, labels) -> str:
    """
    站点把摄录版本放在标签里，片名缺少对应信息时补到分辨率之后，供名称识别

    摄录词需出现在年份或分辨率之后才认定，避免把片名中的同名单词当成版本
    """
    capture = next((label for label in labels or [] if label in _CAPTURE_LABELS), "")
    if not capture:
        return name
    anchors = [match for match in (_YEAR_RE.search(name), _RESOLUTION_RE.search(name)) if match]
    if not anchors:
        return name
    anchor = min(anchors, key=lambda match: match.end())
    if _CAPTURE_TOKEN_RE.search(name, anchor.end()):
        return name
    resolution = _RESOLUTION_RE.search(name, anchor.end())
    insert_at = resolution.end() if resolution else anchor.end()
    return f"{name[:insert_at]} {capture}{name[insert_at:]}"


def promotion_factors(item: dict, global_free: bool = False, global_double: bool = False) -> tuple[float, float]:
    """
    站点全站促销与种子促销合并后的下载、上传系数
    """
    if global_free or item.get("isFreeleech"):
        download_factor = 0.0
    elif item.get("isHalfDownload"):
        download_factor = 0.5
    else:
        download_factor = 1.0
    upload_factor = 2.0 if (global_double or item.get("isDoubleUpload")) else 1.0
    return download_factor, upload_factor


def promotion_labels(item: dict, global_free: bool = False, global_double: bool = False) -> list:
    """
    促销标签
    """
    labels = []
    if global_free or item.get("isFreeleech"):
        labels.append("Free")
    elif item.get("isHalfDownload"):
        labels.append("50%")
    if global_double or item.get("isDoubleUpload"):
        labels.append("2X")
    if item.get("isInternal"):
        labels.append("Internal")
    if item.get("isSticky"):
        labels.append("Sticky")
    if item.get("is3D"):
        labels.append("3D")
    if item.get("isNuked"):
        labels.append("Nuked")
    return labels


def category_type(category) -> str:
    """
    站点分类转换为媒体类型
    """
    category = category if isinstance(category, dict) else {}
    tags = {str(tag).lower() for tag in category.get("tags") or []}
    if "anime" in tags:
        return MediaType.ANIME.value
    if "tv" in tags:
        return MediaType.TV.value
    if "movies" in tags:
        return MediaType.MOVIE.value
    return MediaType.UNKNOWN.value


class SpeedAppApiClient:
    """
    SpeedApp API 请求客户端
    """

    def __init__(self, apikey: str, base_url: str,
                 ua: str | None = None, proxy=None, timeout: int = 15):
        self._apikey = (apikey or "").strip()
        self._base_url = (base_url or "https://speedapp.io").rstrip("/")
        self._ua = ua or Config().get_ua()
        self._proxy = proxy
        self._timeout = timeout or 15

    def get_json(self, path: str, params: dict | None = None) -> tuple[object | None, str | None]:
        """
        请求 API 并解析 JSON，返回 (数据, 错误信息)
        """
        try:
            res = self.__request(path, params=params)
        except SpeedAppAuthError as err:
            return None, str(err)
        if res is None:
            return None, "无法连接 SpeedApp API"
        try:
            payload = JsonUtils.loads(res.text, default=None, silent=True)
            if res.status_code != 200:
                return None, response_error(res.status_code, payload, res.headers.get("Retry-After"))
            if payload is None:
                return None, "SpeedApp API 响应结构无效"
            return payload, None
        finally:
            res.close()

    def download(self, path: str):
        """
        下载种子文件，返回原始响应
        """
        return self.__request(path, headers={"Accept": "application/x-bittorrent, */*"})

    def __request(self, path: str, params: dict | None = None, headers: dict | None = None):
        if not self._apikey:
            raise SpeedAppAuthError("未配置 SpeedApp API Token")
        req_headers = {
            "Authorization": f"Bearer {self._apikey}",
            "Accept": "application/json",
            "User-Agent": self._ua
        }
        if headers:
            req_headers.update(headers)
        return RequestUtils(headers=req_headers,
                            proxies=self._proxy,
                            timeout=self._timeout).get_res(
            url=f"{self._base_url}{path}",
            params=params
        )


def get_categories(api: SpeedAppApiClient, base_url: str) -> list:
    """
    获取站点分类，短时缓存
    """
    now = time.monotonic()
    with _CATEGORY_LOCK:
        cached = _CATEGORY_CACHE.get(base_url)
        if cached and cached[0] > now:
            return cached[1]

    payload, error = api.get_json("/api/categories")
    if error or not isinstance(payload, list):
        log.debug("【INDEXER】SpeedApp 获取分类失败：%s", error or "响应结构无效")
        return []
    with _CATEGORY_LOCK:
        _CATEGORY_CACHE[base_url] = (now + _CATEGORY_TTL, payload)
    return payload


def get_browse_context(api: SpeedAppApiClient, base_url: str) -> dict:
    """
    获取浏览上下文中的全站促销和可见分类，短时缓存
    """
    now = time.monotonic()
    with _CONTEXT_LOCK:
        cached = _CONTEXT_CACHE.get(base_url)
        if cached and cached[0] > now:
            return cached[1]

    payload, error = api.get_json("/api/browse_contexts/browse")
    if error or not isinstance(payload, dict):
        # 失败结果不缓存，避免限流或异常期间把全站促销误判为无促销
        log.debug("【INDEXER】SpeedApp 获取浏览上下文失败：%s", error or "响应结构无效")
        return {}
    with _CONTEXT_LOCK:
        _CONTEXT_CACHE[base_url] = (now + _CONTEXT_TTL, payload)
    return payload


def speedapp_base_url(value: str | None) -> str:
    """
    站点地址转换为 API 基地址，统一使用 https 以免明文传输访问令牌
    """
    base_url = (SiteUtils.get_base_url(value) or "https://speedapp.io").rstrip("/")
    if base_url.startswith("http://"):
        base_url = f"https://{base_url[len('http://'):]}"
    return base_url


_TORRENT_ID_PATTERNS = (
    re.compile(r"/api/torrents/([1-9][0-9]*)(?:/|$)"),
    re.compile(r"/api/torrent/([1-9][0-9]*)(?:/|$)"),
    re.compile(r"/browse/([1-9][0-9]*)(?:/|$)"),
)

_SEARCH_CATEGORY_TAGS = {
    MediaType.MOVIE: "movies",
    MediaType.TV: "tv",
    MediaType.ANIME: "anime"
}


class SpeedAppSpider:
    """
    SpeedApp API 索引器

    站点网页为单页应用，搜索、统计和下载都走 /api，认证使用个人 API Token。
    """

    # 接口单页最多 100 条
    _size = 100

    _indexerid = None
    _name = "SpeedApp"
    _base_url = "https://speedapp.io"
    _apikey = ""
    _ua = None
    _timeout = 15

    def __init__(self, indexer: IndexerInfo):
        if indexer:
            self._indexerid = indexer.id
            self._name = indexer.name or "SpeedApp"
            self._base_url = speedapp_base_url(indexer.domain)
            self._apikey = str(indexer.apikey or indexer.token or "").strip()
            self._ua = indexer.ua or Config().get_ua()
            self._timeout = indexer.timeout or 15
            proxies = Config().get_proxies() if indexer.proxy else None
        else:
            proxies = None

        self._api = SpeedAppApiClient(
            self._apikey,
            self._base_url,
            ua=self._ua,
            proxy=proxies,
            timeout=self._timeout
        )

    def search(self, keyword: str, mtype: MediaType = None, page: int = 0) -> tuple[bool, list]:
        """
        搜索种子
        """
        if not self._apikey:
            log.warn("【INDEXER】%s 未配置 API Token，无法搜索", self._name)
            return True, []

        category_ids = self.__category_ids(mtype)
        if category_ids is not None and not category_ids:
            return False, []

        context = get_browse_context(self._api, self._base_url)
        allowed_ids = {cid for cid in context.get("categoryIds") or [] if isinstance(cid, int)}
        if category_ids is not None and allowed_ids:
            category_ids = [cid for cid in category_ids if cid in allowed_ids]
            if not category_ids:
                return False, []

        params = {
            "itemsPerPage": self._size,
            "page": int(page or 0) + 1,
            "scope": "browse"
        }
        keyword = str(keyword or "").strip()
        if keyword:
            params["search"] = keyword[:255]
        if category_ids:
            params["categories[]"] = category_ids

        payload, error = self._api.get_json("/api/torrents", params=params)
        if error:
            log.warn("【INDEXER】%s 搜索失败：%s", self._name, error)
            return True, []
        if not isinstance(payload, list):
            log.warn("【INDEXER】%s 搜索失败：接口返回结构无效", self._name)
            return True, []

        global_free = bool(context.get("isGlobalFreeleechActive"))
        global_double = bool(context.get("isGlobalDoubleUploadActive"))
        torrents = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                torrent = self.__build_torrent(item, global_free, global_double)
            except (TypeError, ValueError) as err:
                log.debug("【INDEXER】%s 跳过无效种子：%s", self._name, err)
                continue
            if torrent:
                torrents.append(torrent)

        return False, torrents

    def get_torrent(self, url: str):
        """
        使用个人 API Token 下载种子文件
        """
        torrent_id = self.__parse_torrent_id(url)
        if not torrent_id:
            log.warn("【INDEXER】%s 无法从下载链接解析种子ID：%s", self._name, url)
            return None

        try:
            res = self._api.download(f"/api/torrents/{torrent_id}/download")
        except SpeedAppAuthError as err:
            log.warn("【INDEXER】%s 下载种子失败：%s", self._name, err)
            return None
        if res is not None and res.status_code != 200:
            log.warn("【INDEXER】%s 下载种子失败，错误码：%s", self._name, res.status_code)
        return res

    def test_connection(self) -> tuple[bool, str]:
        """
        使用账号接口验证凭据
        """
        if not self._apikey:
            return False, "未配置 SpeedApp API Token"
        payload, error = self._api.get_json("/api/me")
        if error:
            return False, error
        try:
            integer(payload.get("id") if isinstance(payload, dict) else None, minimum=1)
        except ValueError:
            return False, "SpeedApp API 响应结构无效"
        return True, "连接成功"

    def __category_ids(self, mtype: MediaType = None) -> list | None:
        """
        按媒体类型收窄站点分类；返回 None 表示不筛选
        """
        if not mtype:
            return None
        tag = _SEARCH_CATEGORY_TAGS.get(mtype)
        if not tag:
            return None

        categories = get_categories(self._api, self._base_url)
        if not categories:
            return None

        category_ids = []
        for category in categories:
            if not isinstance(category, dict):
                continue
            tags = {str(item).lower() for item in category.get("tags") or []}
            if "adult" in tags or tag not in tags:
                continue
            try:
                category_ids.append(integer(category.get("id"), minimum=1))
            except ValueError:
                continue
        return category_ids

    def __build_torrent(self, item: dict, global_free: bool = False, global_double: bool = False) -> dict | None:
        """
        将接口返回的种子转换为索引器通用结构
        """
        torrent_id = integer(item.get("id"), minimum=1)
        title = item.get("name")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("SpeedApp 种子标题无效")

        category = item.get("category")
        download_factor, upload_factor = promotion_factors(item, global_free, global_double)

        version = version_labels(title, item.get("releaseDetails"), item.get("tags"))
        labels = promotion_labels(item, global_free, global_double)
        labels.extend(version)

        description = item.get("shortDescription") or ""
        genres = item.get("genres")
        if not description and isinstance(genres, list):
            description = ", ".join(str(genre) for genre in genres if genre)

        slug = item.get("slug")
        page_url = f"{self._base_url}/browse/{torrent_id}"
        if isinstance(slug, str) and slug:
            page_url = f"{page_url}/t/{slug}"

        return {
            "indexer": self._indexerid,
            "title": title_with_capture(title.strip(), version),
            "description": description,
            "enclosure": f"{self._base_url}/api/torrents/{torrent_id}/download",
            "pubdate": local_time(item.get("refreshedAt") or item.get("updatedAt") or item.get("createdAt")),
            "size": integer(item.get("size")),
            "seeders": integer(item.get("seeders") or 0),
            "peers": integer(item.get("leechers") or 0),
            "grabs": integer(item.get("timesCompleted") or 0),
            "downloadvolumefactor": download_factor,
            "uploadvolumefactor": upload_factor,
            "page_url": page_url,
            "imdbid": "",
            "labels": "|".join(dict.fromkeys(label for label in labels if label)),
            "category": category_type(category)
        }

    @staticmethod
    def __parse_torrent_id(url: str) -> str | None:
        if not url:
            return None
        path = urlsplit(url).path
        for pattern in _TORRENT_ID_PATTERNS:
            match = pattern.search(path)
            if match:
                return match.group(1)
        return None
