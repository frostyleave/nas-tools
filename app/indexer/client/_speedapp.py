import base64
import datetime
import hashlib
import hmac
import math
import re
import secrets
import threading
import time
from urllib.parse import parse_qs, urljoin, urlsplit

import requests

import log
from app.models.model import IndexerInfo
from app.utils import JsonUtils, RequestUtils, SiteUtils, TimeUtils
from app.utils.types import MediaType
from config import Config

# 站点网页端内置 OAuth 客户端：用配置的 Cookie 走授权码流程换取访问令牌。
# 站点更换客户端后，Cookie 方式会失效，可改用个人 API Token。
_OAUTH_BASE_URL = "https://speedapp.io"
_OAUTH_AUTHORIZE_PATH = "/oauth/v2/authorize"
_TOKEN_PATH = "/oauth/v2/token"
_OAUTH_CLIENT_ID = "a36aa65d2ced5d0d45656351ff73fc5a"
_OAUTH_REDIRECT_URI = "https://speedapp.io/oauth2/auth"
_OAUTH_REDIRECT_PATH = "/oauth2/auth"
# profile.full 提供真实做种体积，torrent.read 用于搜索，torrent.download 用于下载
_OAUTH_SCOPES = "profile.basic profile.full torrent.read torrent.download"

_TOKEN_EARLY_REFRESH_SECONDS = 60
_TOKEN_CACHE_MAX = 16
_TOKEN_LOCK = threading.Lock()
_TOKEN_CACHE: dict = {}
# 按凭据区分授权锁，令牌过期时不同站点/账号的请求互不阻塞
_TOKEN_KEY_LOCKS: dict = {}


def _token_key_lock(cache_key) -> threading.Lock:
    """
    获取指定凭据的授权锁
    """
    with _TOKEN_LOCK:
        lock = _TOKEN_KEY_LOCKS.get(cache_key)
        if lock is None:
            lock = _TOKEN_KEY_LOCKS[cache_key] = threading.Lock()
        return lock

_CATEGORY_TTL = 6 * 60 * 60
_CATEGORY_LOCK = threading.Lock()
_CATEGORY_CACHE: dict = {}

_CONTEXT_TTL = 5 * 60
_CONTEXT_LOCK = threading.Lock()
_CONTEXT_CACHE: dict = {}

_REDIRECT_CODES = (301, 302, 303, 307, 308)

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

_RESOLUTION_RE = re.compile(r"(?<![0-9])(2160p|1080p|720p|576p|480p|4k|8k)(?![0-9])", re.I)
_SOURCE_PATTERNS = (
    ("Remux", re.compile(r"\bremux\b", re.I)),
    ("BluRay", re.compile(r"\bblu-?ray\b", re.I)),
    ("WEB-DL", re.compile(r"\bweb[.\s-]?dl\b", re.I)),
    ("WEBRip", re.compile(r"\bweb[.\s-]?rip\b", re.I)),
    ("HDTV", re.compile(r"\bhdtv\b", re.I)),
    ("BDRip", re.compile(r"\bbdrip\b", re.I)),
    ("HDRip", re.compile(r"\bhdrip\b", re.I)),
    ("DVD", re.compile(r"\bdvd(?:rip|r|9|5)?\b", re.I)),
)


class SpeedAppError(Exception):
    """SpeedApp 接口错误"""


class SpeedAppAuthError(SpeedAppError):
    """SpeedApp 鉴权错误"""


def parse_cookie(cookie: str) -> dict:
    """
    解析站点 Cookie，值中的等号保留
    """
    result = {}
    for part in (cookie or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        if key:
            result[key] = value.strip()
    return result


def integer(value, minimum: int = 0) -> int:
    """
    校验接口返回的计数和字节数，拒绝布尔值、浮点和负数
    """
    if isinstance(value, bool):
        raise ValueError("SpeedApp 数值字段无效")
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
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
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
        return "SpeedApp Cookie 或个人 API Token 已失效"
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


def version_labels(name: str, release_details) -> list:
    """
    从发布名和站点解析结果中提取来源、分辨率标签
    """
    parts = [str(part) for part in release_details or [] if isinstance(part, str)]
    text = " ".join([str(name or "")] + parts)
    labels = []

    match = _RESOLUTION_RE.search(text)
    if match:
        resolution = match.group(1).lower()
        labels.append({"4k": "2160p", "8k": "4320p"}.get(resolution, resolution))
    elif re.search(r"\buhd\b", text, re.I):
        labels.append("2160p")

    for label, pattern in _SOURCE_PATTERNS:
        if label not in labels and pattern.search(text):
            labels.append(label)

    return labels


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


class SpeedAppTokenProvider:
    """
    SpeedApp 访问令牌提供器

    配置个人 API Token 时直接使用；只配置 Cookie 时，用站点网页端 OAuth 客户端
    走授权码 + PKCE 流程换取访问令牌，并在内存中缓存、过期前刷新。
    """

    def __init__(self, base_url: str, cookie: str | None = None, apikey: str | None = None,
                 ua: str | None = None, proxy=None, timeout: int = 15):
        self._base_url = (base_url or "https://speedapp.io").rstrip("/")
        self._cookie = (cookie or "").strip()
        self._apikey = (apikey or "").strip()
        self._ua = ua or Config().get_ua()
        self._proxy = proxy
        self._timeout = timeout or 15
        digest = hashlib.sha256(self._cookie.encode()).hexdigest() if self._cookie else ""
        self._cache_key = (self._base_url, digest)

    def get_access_token(self) -> str:
        """
        获取可用的 Bearer 令牌
        """
        if self._apikey:
            return self._apikey
        if not self._cookie:
            raise SpeedAppAuthError("未配置 SpeedApp Cookie 或个人 API Token")

        token = self.__cached_token()
        if token:
            return token

        # 同一凭据的授权串行执行，网络请求不持有全局缓存锁
        with _token_key_lock(self._cache_key):
            token = self.__cached_token()
            if token:
                return token

            with _TOKEN_LOCK:
                entry = _TOKEN_CACHE.get(self._cache_key)
                refresh_token = entry.get("refresh_token") if entry else ""

            if refresh_token:
                refreshed = self.__refresh(refresh_token)
                if refreshed:
                    self.__store(refreshed)
                    return refreshed["access_token"]

            entry = self.__authorize()
            self.__store(entry)
            return entry["access_token"]

    def __cached_token(self) -> str | None:
        """
        读取尚未临近过期的缓存令牌
        """
        with _TOKEN_LOCK:
            entry = _TOKEN_CACHE.get(self._cache_key)
            if entry and entry.get("access_token") \
                    and entry.get("expires_at", 0) - time.monotonic() > _TOKEN_EARLY_REFRESH_SECONDS:
                return entry["access_token"]
        return None

    def __store(self, entry: dict):
        with _TOKEN_LOCK:
            self.__save(entry)

    def invalidate(self):
        """
        丢弃 Cookie 方式缓存的令牌
        """
        if self._apikey:
            return
        with _TOKEN_LOCK:
            _TOKEN_CACHE.pop(self._cache_key, None)

    def __save(self, entry: dict):
        # 调用方需持有 _TOKEN_LOCK
        if self._cache_key not in _TOKEN_CACHE and len(_TOKEN_CACHE) >= _TOKEN_CACHE_MAX:
            _TOKEN_CACHE.pop(next(iter(_TOKEN_CACHE)))
        _TOKEN_CACHE[self._cache_key] = entry

    def __request_kwargs(self) -> dict:
        kwargs = {"timeout": self._timeout}
        if self._proxy:
            kwargs["proxies"] = self._proxy
        return kwargs

    def __authorize(self) -> dict:
        """
        使用 Cookie 执行 OAuth2 授权码 + PKCE 流程
        """
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)

        params = {
            "client_id": _OAUTH_CLIENT_ID,
            "redirect_uri": _OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": _OAUTH_SCOPES,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256"
        }
        with requests.Session() as session:
            session.headers.update({
                "User-Agent": self._ua,
                "Accept": "text/html,application/xhtml+xml"
            })
            try:
                with session.get(f"{_OAUTH_BASE_URL}{_OAUTH_AUTHORIZE_PATH}",
                                 params=params,
                                 cookies=parse_cookie(self._cookie),
                                 allow_redirects=False,
                                 **self.__request_kwargs()) as res:
                    status_code = res.status_code
                    location_header = res.headers.get("Location", "")
            except requests.RequestException as err:
                raise SpeedAppAuthError("无法连接 SpeedApp 登录接口") from err

            if status_code not in _REDIRECT_CODES:
                if status_code == 200:
                    raise SpeedAppAuthError("SpeedApp Cookie 需要重新授权：请用浏览器登录站点后再试，或改用个人 API Token")
                if status_code in (401, 403):
                    raise SpeedAppAuthError("SpeedApp Cookie 已失效，请重新登录或改用个人 API Token")
                raise SpeedAppAuthError(f"SpeedApp 登录接口请求失败，HTTP {status_code}")

            location = urljoin(f"{_OAUTH_BASE_URL}/", location_header)
            parts = urlsplit(location)
            if parts.netloc != urlsplit(_OAUTH_BASE_URL).netloc:
                raise SpeedAppAuthError("SpeedApp OAuth 返回了异常的跳转地址")
            if parts.path != _OAUTH_REDIRECT_PATH:
                # 未登录时授权端点会跳回登录页，而不是带回授权码
                raise SpeedAppAuthError("SpeedApp Cookie 已失效，请重新登录站点或改用个人 API Token")

            query = parse_qs(parts.query)
            code = (query.get("code") or [""])[0]
            if not code:
                reason = (query.get("error_description") or query.get("error") or [""])[0]
                raise SpeedAppAuthError(f"SpeedApp OAuth 授权失败{f'：{reason[:120]}' if reason else ''}")
            returned_state = (query.get("state") or [""])[0]
            if not hmac.compare_digest(returned_state, state):
                raise SpeedAppAuthError("SpeedApp OAuth 授权状态校验失败")

            try:
                with session.post(f"{_OAUTH_BASE_URL}{_TOKEN_PATH}",
                                  data={
                                      "grant_type": "authorization_code",
                                      "client_id": _OAUTH_CLIENT_ID,
                                      "code": code,
                                      "redirect_uri": _OAUTH_REDIRECT_URI,
                                      "code_verifier": verifier
                                  },
                                  **self.__request_kwargs()) as token_res:
                    status_code = token_res.status_code
                    payload = JsonUtils.loads(token_res.text, default=None, silent=True)
            except requests.RequestException as err:
                raise SpeedAppAuthError("无法连接 SpeedApp 令牌接口") from err

        if status_code != 200 or not isinstance(payload, dict) or not payload.get("access_token"):
            reason = ""
            if isinstance(payload, dict):
                reason = str(payload.get("error_description") or payload.get("error")
                             or payload.get("message") or "").strip()
            raise SpeedAppAuthError(f"SpeedApp 获取访问令牌失败{f'：{reason[:120]}' if reason else ''}")

        return self.__token_entry(payload)

    def __refresh(self, refresh_token: str) -> dict | None:
        """
        刷新访问令牌；刷新令牌失效时返回 None，由调用方重新授权
        """
        try:
            res = requests.post(f"{_OAUTH_BASE_URL}{_TOKEN_PATH}",
                                data={
                                    "grant_type": "refresh_token",
                                    "client_id": _OAUTH_CLIENT_ID,
                                    "refresh_token": refresh_token
                                },
                                headers={"User-Agent": self._ua, "Accept": "application/json"},
                                **self.__request_kwargs())
        except requests.RequestException as err:
            raise SpeedAppAuthError("无法连接 SpeedApp 令牌接口") from err

        if res.status_code in (400, 401):
            return None
        payload = JsonUtils.loads(res.text, default=None, silent=True)
        if res.status_code != 200 or not isinstance(payload, dict) or not payload.get("access_token"):
            raise SpeedAppAuthError(response_error(res.status_code, payload, res.headers.get("Retry-After")))
        entry = self.__token_entry(payload)
        if not entry.get("refresh_token"):
            entry["refresh_token"] = refresh_token
        return entry

    @staticmethod
    def __token_entry(payload: dict) -> dict:
        try:
            expires_in = int(payload.get("expires_in") or 3600)
        except (TypeError, ValueError):
            expires_in = 3600
        if expires_in <= 0:
            expires_in = 3600
        return {
            "access_token": str(payload.get("access_token") or ""),
            "refresh_token": str(payload.get("refresh_token") or ""),
            "expires_at": time.monotonic() + expires_in
        }


class SpeedAppApiClient:
    """
    SpeedApp API 请求客户端
    """

    def __init__(self, provider: SpeedAppTokenProvider, base_url: str,
                 ua: str | None = None, proxy=None, timeout: int = 15):
        self._provider = provider
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
        res = None
        for attempt in range(2):
            token = self._provider.get_access_token()
            req_headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": self._ua
            }
            if headers:
                req_headers.update(headers)
            res = RequestUtils(headers=req_headers,
                               proxies=self._proxy,
                               timeout=self._timeout).get_res(
                url=f"{self._base_url}{path}",
                params=params
            )
            if res is None:
                return None
            if res.status_code != 401 or attempt == 1:
                # 重试后仍为 401 时保留响应供调用方读取错误，不再返回已关闭的连接
                return res
            res.close()
            self._provider.invalidate()
        return res


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

    站点网页为单页应用，搜索、统计和下载都走 /api；认证优先使用个人 API Token，
    未配置时用 Cookie 换取站点网页端的 OAuth 访问令牌。
    """

    # 接口单页最多 100 条
    _size = 100

    _indexerid = None
    _name = "SpeedApp"
    _base_url = "https://speedapp.io"
    _cookie = ""
    _apikey = ""
    _ua = None
    _timeout = 15

    def __init__(self, indexer: IndexerInfo):
        if indexer:
            self._indexerid = indexer.id
            self._name = indexer.name or "SpeedApp"
            self._base_url = speedapp_base_url(indexer.domain)
            self._cookie = (indexer.cookie or "").strip()
            self._apikey = str(indexer.apikey or indexer.token or "").strip()
            self._ua = indexer.ua or Config().get_ua()
            self._timeout = indexer.timeout or 15
            proxies = Config().get_proxies() if indexer.proxy else None
        else:
            proxies = None

        self._provider = SpeedAppTokenProvider(
            self._base_url,
            cookie=self._cookie,
            apikey=self._apikey,
            ua=self._ua,
            proxy=proxies,
            timeout=self._timeout
        )
        self._api = SpeedAppApiClient(
            self._provider,
            self._base_url,
            ua=self._ua,
            proxy=proxies,
            timeout=self._timeout
        )

    def search(self, keyword: str, mtype: MediaType = None, page: int = 0) -> tuple[bool, list]:
        """
        搜索种子
        """
        if not self._cookie and not self._apikey:
            log.warn("【INDEXER】%s 未配置 Cookie 或个人 API Token，无法搜索", self._name)
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
        使用访问令牌下载种子文件
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
        if not self._cookie and not self._apikey:
            return False, "未配置 SpeedApp Cookie 或个人 API Token"
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

        labels = promotion_labels(item, global_free, global_double)
        labels.extend(version_labels(title, item.get("releaseDetails")))

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
            "title": title.strip(),
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
