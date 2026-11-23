# author: https://github.com/jxxghp/MoviePilot/blob/v3/app/modules/indexer/spider/colapt.py
import datetime
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urlsplit

import log
from app.models.model import IndexerInfo
from app.utils import JsonUtils, RequestUtils, SiteUtils, TimeUtils
from app.utils.types import MediaType
from config import Config

# 搜索、用户数据需要「读取」范围，下载需要「下载」范围。
KEY_REQUIRED = "请在可乐「账号设置 → API Key」新建勾选「读取」和「下载」范围的 API Key，并填入站点 API Key"

# 站点注册域名，只用于解释本站详情页和签名下载路径。
_DETAIL_PATH = re.compile(r"/torrents/([1-9][0-9]*)/?")
_DOWNLOAD_PATH = re.compile(r"/downloads/[A-Za-z0-9_-]+/([1-9][0-9]*)")

# 开放 API 的固定分类；动漫、纪录片和其他可能是电影也可能是剧集，结果保持未知。
_CATEGORIES = ("movie", "tv", "anime", "variety", "documentary", "other")
_CATEGORY_TYPES = {
    "movie": MediaType.MOVIE.value,
    "tv": MediaType.TV.value,
    "variety": MediaType.TV.value,
}
# 按媒体类型搜索时只排除明确属于另一类型的分类，共享分类的种子保留给后续识别。
_MEDIA_CATEGORIES = {
    MediaType.MOVIE: ("movie", "anime", "documentary", "other"),
    MediaType.TV: ("tv", "anime", "variety", "documentary", "other"),
    MediaType.ANIME: ("anime",),
}

_IMDB_ID = re.compile(r"tt[0-9]{7,10}")
_INTEGER = re.compile(r"0|[1-9][0-9]*")
_DECIMAL = re.compile(r"(0|[1-9][0-9]*)(\.[0-9]+)?")
_SIGNED_DECIMAL = re.compile(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?")


def response_data(status_code: int, payload: object, apikey: str = "") -> dict:
    """
    校验开放 API 响应，按错误码而不是 HTTP 状态猜测失败原因

    :param status_code: 原始 HTTP 状态码，成功为 200 或 201
    :param payload: 已解码的 JSON；非 JSON 响应可以传入 None
    :param apikey: 本次密钥，仅用于移除错误消息中可能的凭据回显
    :return: 成功响应的 JSON 对象
    :raises ValueError: 鉴权、范围、权限、限流或响应结构无效
    """
    envelope = payload if isinstance(payload, dict) else {}
    raw_error = envelope.get("error")
    error: dict = raw_error if isinstance(raw_error, dict) else {}
    code = str(error.get("code") or "")
    message = str(error.get("message") or "").strip()
    if status_code in (200, 201) and isinstance(payload, dict) and "error" not in payload:
        return payload
    if status_code == 401 or code in ("authentication_required", "invalid_credentials"):
        message = "ColaPT API Key 已失效或无效"
    elif code == "api_key_scope_denied":
        message = "ColaPT API Key 缺少所需范围：搜索和用户数据需「读取」，下载需「下载」"
    elif code == "password_change_required":
        message = "ColaPT 账号需先在网页端修改密码"
    elif status_code == 429 or code == "rate_limited":
        retry_after = error.get("retry_after")
        wait = f"请 {retry_after} 秒后重试" if isinstance(retry_after, int) and retry_after > 0 else "请稍后重试"
        message = f"ColaPT 站点限流：{wait}"
    elif status_code == 403 or code == "permission_denied":
        message = f"ColaPT 账号无权进行此操作{f'：{message}' if message else ''}"
    elif status_code == 404 or code == "not_found":
        message = "ColaPT 种子不存在或无权查看"
    elif status_code in (200, 201):
        message = "ColaPT API 响应结构无效"
    else:
        message = f"ColaPT API 请求失败，HTTP {status_code}{f'：{message}' if message else ''}"
    if apikey:
        message = message.replace(apikey, "[已隐藏]")
    raise ValueError(" ".join(message.split())[:300])


def integer(value: object, minimum: int = 0) -> int:
    """
    校验 ID、计数和十进制字符串字节数，拒绝布尔值、浮点和负数

    :param value: JSON 整数或十进制整数字符串
    :param minimum: 允许的最小值，种子 ID 使用 1
    :return: 已校验的整数
    :raises ValueError: 格式或范围无效；错误不回显原值
    """
    if isinstance(value, bool) or not isinstance(value, (str, int)) \
            or not _INTEGER.fullmatch(str(value)):
        raise ValueError("ColaPT API 整数字段无效")
    result = int(value)
    if result < minimum:
        raise ValueError("ColaPT API 整数字段无效")
    return result


def decimal(value: object, signed: bool = False) -> float:
    """
    校验分享率和瓶盖余额这类定点小数字符串

    :param value: 形如 1.2345 的十进制字符串
    :param signed: 是否允许负数，瓶盖余额可以为负
    :return: 有限数值
    :raises ValueError: 类型、格式或范围无效；错误不回显原值
    """
    pattern = _SIGNED_DECIMAL if signed else _DECIMAL
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError("ColaPT API 数值字段无效")
    try:
        return float(Decimal(value))
    except (InvalidOperation, OverflowError) as err:
        raise ValueError("ColaPT API 数值字段无效") from err


def local_time(value: object):
    """
    把 RFC 3339 时间转换为本地日期时间文本，与其他站点的发布时间口径一致

    :param value: 带时区的 RFC 3339 时间或 None
    :return: 本地 %Y-%m-%d %H:%M:%S 文本；未提供时为 None
    :raises ValueError: 时间格式无效
    """
    if value is None:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(str(value))
    except ValueError as err:
        raise ValueError("ColaPT API 时间字段无效") from err
    if parsed.tzinfo is None:
        raise ValueError("ColaPT API 时间字段无效")
    timezone = TimeUtils.get_timezone()
    if timezone is not None:
        parsed = parsed.astimezone(timezone)
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


class ColaPTSpider:
    """
    可乐开放 API 索引器，搜索与空关键词最新列表共用按种子分页的 view=torrents
    """

    # listMedia 单页最多 100 条
    _size = 100

    _indexerid = None
    _name = "可乐"
    _base_url = "https://www.colapt.com"
    _api_url = "https://www.colapt.com/api/v1"
    _apikey = None
    _ua = None
    _proxy = None
    _timeout = 15
    # 站点配置中声明的服务端分类，显式分类优先于媒体类型
    _category = None

    def __init__(self, indexer: IndexerInfo):
        if indexer:
            self._indexerid = indexer.id
            self._name = indexer.name or "可乐"
            self._base_url = SiteUtils.get_base_url(indexer.domain) or "https://www.colapt.com"
            self._api_url = f"{self._base_url}/api/v1"
            self._apikey = str(indexer.apikey or "").strip()
            self._ua = indexer.ua or Config().get_ua()
            if indexer.proxy:
                self._proxy = Config().get_proxies()
            self._timeout = indexer.timeout or 15
            if isinstance(indexer.search, dict):
                self._category = indexer.search.get("category")

    def search(self, keyword: str | None = None, mtype: MediaType = None, page: int = 0) -> tuple[bool, list]:
        """
        搜索或浏览最新种子，不回退到 Cookie 页面

        :param keyword: 普通关键词、完整 IMDb ID 或空值
        :param mtype: 未指定分类时使用的媒体类型
        :param page: 零起始页码
        :return: 是否失败及当前页资源
        """
        if not self._apikey:
            log.warn("【INDEXER】%s %s", self._name, KEY_REQUIRED)
            return True, []

        params = self.__params(keyword, self.__categories(mtype), page)
        res = RequestUtils(headers=self.__api_headers(),
                           proxies=self._proxy,
                           timeout=self._timeout).get_res(url=f"{self._api_url}/media",
                                                          params=params,
                                                          allow_redirects=False)
        try:
            return self.__process_response(res, params["page"])
        finally:
            if res is not None:
                res.close()

    def get_torrent(self, url: str):
        """
        使用当前 API Key 按站内 ID 签发 30 分钟临时地址，再下载种子文件

        :param url: 种子详情页或签名下载地址
        :return: 种子响应对象
        """
        torrent_id = None
        if SiteUtils.get_url_domain(url) == SiteUtils.get_url_domain(self._base_url):
            torrent_id = self.__parse_torrent_id(url)
        if not torrent_id:
            log.warn("【INDEXER】%s 无法从下载链接解析种子ID：%s", self._name, url)
            return None
        if not self._apikey:
            log.warn("【INDEXER】%s %s", self._name, KEY_REQUIRED)
            return None

        res = RequestUtils(headers=self.__api_headers(),
                           proxies=self._proxy,
                           timeout=self._timeout).post_res(
            url=f"{self._api_url}/torrents/{torrent_id}/download-links",
            allow_redirects=False
        )
        if res is None:
            log.warn("【INDEXER】%s 无法连接 ColaPT API", self._name)
            return None
        try:
            payload = JsonUtils.loads(res.text, default=None, silent=True)
            download_url = self.__parse_download_response(res.status_code, payload, torrent_id)
        except (TypeError, ValueError) as err:
            log.warn("【INDEXER】%s 获取下载地址失败：%s", self._name, err)
            return None
        finally:
            res.close()

        # 最终下载只使用签名地址，不携带 API Key
        return RequestUtils(headers={"Accept": "application/octet-stream, */*", "User-Agent": self._ua},
                            proxies=self._proxy,
                            timeout=self._timeout).get_res(url=download_url)

    def test_connection(self) -> tuple[bool, str]:
        """
        使用会员数据接口验证 API Key 的「读取」范围和账号身份

        :return: 账号是否可用及可以展示的认证、范围或接口失败原因
        """
        if not self._apikey:
            return False, KEY_REQUIRED
        res = RequestUtils(headers=self.__api_headers(),
                           proxies=self._proxy,
                           timeout=self._timeout).get_res(url=f"{self._api_url}/me/stats",
                                                          allow_redirects=False)
        if res is None:
            return False, "无法连接 ColaPT API"
        try:
            payload = JsonUtils.loads(res.text, default=None, silent=True)
            data = response_data(res.status_code, payload, self._apikey)
            user = data.get("user")
            integer(user.get("id") if isinstance(user, dict) else None, minimum=1)
            return True, "连接成功"
        except (TypeError, ValueError) as err:
            return False, str(err)
        finally:
            res.close()

    def __api_headers(self) -> dict:
        """
        构造仅使用 API Key 的 JSON 请求头，不带 Cookie、Authorization 或 Origin
        """
        return {"X-API-Key": self._apikey, "Accept": "application/json", "User-Agent": self._ua}

    def __categories(self, mtype: MediaType = None):
        """
        把站点分类或媒体类型转换为服务端多选分类，一次请求完成筛选

        :param mtype: 未指定分类时使用的媒体类型
        :return: 去重后逗号分隔的 category 参数；不筛选时为 None
        """
        raw = self._category
        if isinstance(raw, (list, tuple)):
            parts = [str(part).strip() for part in raw]
        else:
            parts = [part.strip() for part in str(raw or "").split(",")]
        selected = list(dict.fromkeys(value for value in parts if value in _CATEGORIES))
        if not selected and mtype:
            selected = list(_MEDIA_CATEGORIES.get(mtype, ()))
        return ",".join(selected) or None

    def __params(self, keyword: str, category: str, page: int) -> dict:
        """
        构造按种子全局分页的查询，完整 IMDb ID 使用精确筛选
        """
        params = {
            "view": "torrents",
            "sort": "latest",
            "direction": "desc",
            "official_first": "false",
            "page": int(page or 0) + 1,
            "page_size": self._size,
        }
        keyword = str(keyword or "").strip()
        if keyword:
            if _IMDB_ID.fullmatch(keyword):
                params["imdb_id"] = keyword
            else:
                params["q"] = keyword[:255]
        if category:
            params["category"] = category
        return params

    def __process_response(self, res, page: int) -> tuple[bool, list]:
        """
        校验分页事实与条目，错误不能被当成成功空列表
        """
        if res is None:
            log.warn("【INDEXER】%s 搜索失败，无法连接 %s", self._name, self._api_url)
            return True, []
        try:
            payload = JsonUtils.loads(res.text, default=None, silent=True)
            data = response_data(res.status_code, payload, self._apikey)
            items = data.get("items")
            if not isinstance(items, list):
                raise TypeError("ColaPT API 种子分页结构无效")
            if integer(data.get("page"), minimum=1) != page:
                raise ValueError("ColaPT API 返回了错误页码")
            
            integer(data.get("total_pages"))
            torrents = []
            for group in items:
                torrent = self.__build_torrent(group)
                if torrent:
                    torrents.append(torrent)
            return False, torrents
        except (TypeError, ValueError) as err:
            message = str(err)
            if self._apikey:
                message = message.replace(self._apikey, "[已隐藏]")
            log.warn("【INDEXER】%s 搜索失败：%s", self._name, message)
            return True, []

    def __build_torrent(self, group: object) -> dict | None:
        """
        将 view=torrents 的单版本分组转换为索引器通用结构

        :param group: items 中的一条分组，每组至多一个版本
        :return: 标准种子字段；没有版本的作品返回 None
        """
        if not isinstance(group, dict) or not isinstance(group.get("versions"), list):
            raise TypeError("ColaPT API 种子条目无效")
        if not group["versions"]:
            return None

        item, media = group["versions"][0], group.get("media")
        if not isinstance(item, dict) or not isinstance(media, (dict, type(None))):
            raise TypeError("ColaPT API 种子条目无效")
        
        media = media or {}

        torrent_id = integer(item.get("id"), minimum=1)
        title = item.get("release_name")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("ColaPT API 种子标题无效")

        download_factor, upload_factor = self.__promotion(item)

        hit_and_run = item.get("hit_and_run", False)
        if not isinstance(hit_and_run, bool):
            raise TypeError("ColaPT API H&R 字段无效")

        labels = [tag for tag in item.get("tags") or [] if isinstance(tag, str)]
        if hit_and_run:
            labels.append("H&R")

        imdb_id = str(media.get("imdb_id") or "")
        detail_url = f"{self._base_url}/torrents/{torrent_id}"

        return {
            "indexer": self._indexerid,
            "title": title,
            "description": item.get("subtitle") or media.get("title") or "",
            "enclosure": detail_url,
            "pubdate": local_time(item.get("published_at")),
            "size": integer(item.get("size_bytes")),
            "seeders": integer(item.get("seeders") or 0),
            "peers": integer(item.get("leechers") or 0),
            "grabs": integer(item.get("completions") or 0),
            "downloadvolumefactor": download_factor,
            "uploadvolumefactor": upload_factor,
            "page_url": detail_url,
            "imdbid": imdb_id if _IMDB_ID.fullmatch(imdb_id) else "",
            "labels": "|".join(dict.fromkeys(label for label in labels if label)),
            "category": _CATEGORY_TYPES.get(str(media.get("category") or ""), MediaType.UNKNOWN.value)
        }

    @staticmethod
    def __promotion(item: dict) -> tuple[float, float]:
        """
        读取服务端当前计费的促销倍率；没有促销即正常计费
        """
        promotion = item.get("promotion")
        if promotion is None:
            return 1.0, 1.0
        if not isinstance(promotion, dict):
            raise TypeError("ColaPT API 促销字段无效")
        factors = []
        for name in ("download", "upload"):
            ratio = promotion.get(name)
            if not isinstance(ratio, dict):
                raise TypeError("ColaPT API 促销字段无效")
            factors.append(integer(ratio.get("num")) / integer(ratio.get("den"), minimum=1))
        return factors[0], factors[1]

    def __parse_download_response(self, status_code: int, payload: object, torrent_id: str) -> str:
        """
        校验签发结果，只接受本站、所选种子且带签名的 HTTPS 地址

        :return: 30 分钟内有效的签名下载地址
        :raises ValueError: 连接、签发、地址或资源身份校验失败
        """
        data = response_data(status_code, payload, self._apikey)
        url = str(data.get("download_url") or "").strip()
        if url.startswith("/"):
            url = f"{self._base_url}{url}"
        if not url.startswith("https://") or len(url) > 2048:
            raise ValueError("ColaPT API 未返回有效的本站下载地址")

        parts = urlsplit(url)
        match = _DOWNLOAD_PATH.fullmatch(parts.path)
        query = parse_qs(parts.query)
        if parts.username is not None or parts.password is not None \
                or SiteUtils.get_url_domain(url) != SiteUtils.get_url_domain(self._base_url) \
                or match is None or not query.get("exp") or not query.get("sig"):
            raise ValueError("ColaPT API 未返回有效的本站下载地址")
        if match[1] != str(torrent_id):
            raise ValueError("ColaPT API 返回的下载地址与所选种子不符")
        return url

    @staticmethod
    def __parse_torrent_id(url: str) -> str | None:
        """
        从本站详情页或签名下载路径提取稳定种子 ID
        """
        if not url:
            return None
        match = _DETAIL_PATH.fullmatch(urlsplit(url).path) or _DOWNLOAD_PATH.fullmatch(urlsplit(url).path)
        return match[1] if match else None
