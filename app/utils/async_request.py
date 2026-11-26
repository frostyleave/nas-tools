import asyncio
import json
import re
import threading
from urllib.parse import urlparse

from charset_normalizer import from_bytes

import aiohttp
import log
from app.utils.commons import mask_url
from config import Config

# 按事件循环维护会话：aiohttp 会话只能在其创建时的事件循环内使用和关闭
_sessions: dict[asyncio.AbstractEventLoop, aiohttp.ClientSession] = {}
_sessions_lock = threading.Lock()

# 单个响应体上限，避免异常大响应占满内存
_MAX_BODY_SIZE = 20 * 1024 * 1024


def decode_bytes(content: bytes, encoding: str | None = None) -> str:
    """
    解码 HTTP 响应内容

    优先使用响应头 charset，其次识别页面内声明的 utf-8，最后按 utf-8 解码，
    失败时用 charset_normalizer 探测（替代 apparent_encoding）。
    """
    if encoding:
        try:
            return content.decode(encoding, errors="replace")
        except LookupError:
            pass

    head = content[:4096].lower()
    if b"charset=utf-8" in head or b'charset="utf-8"' in head:
        return content.decode("utf-8", errors="replace")

    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        best = from_bytes(content).best()
        if best:
            return str(best)
        return content.decode("utf-8", errors="replace")


def _create_session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit=100, ttl_dns_cache=300),
        # total=None 让大文件可以边下边传，连接与读取阶段分别限时
        timeout=aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=20),
    )


def init_async_client() -> aiohttp.ClientSession:
    """
    初始化当前事件循环的异步会话，必须在事件循环内调用
    """
    loop = asyncio.get_running_loop()
    with _sessions_lock:
        session = _sessions.get(loop)
        if session is None or session.closed:
            session = _create_session()
            _sessions[loop] = session
        return session


def get_async_session() -> aiohttp.ClientSession:
    """
    获取当前事件循环的异步会话；未初始化时兜底创建
    """
    return init_async_client()


async def close_loop_session(loop: asyncio.AbstractEventLoop):
    """
    关闭指定事件循环的会话；必须在对应循环内调用
    """
    with _sessions_lock:
        session = _sessions.pop(loop, None)
    if session and not session.closed:
        await session.close()


async def close_async_client():
    """
    关闭当前事件循环的异步会话
    """
    await close_loop_session(asyncio.get_running_loop())


class AsyncResponse:
    """
    简化版的 requests.Response 兼容外观

    仅保留业务代码常用属性，响应体在请求阶段已读取完毕，可脱离连接使用。
    """

    def __init__(self, status_code: int, headers, url: str, content: bytes):
        self.status_code = status_code
        self.headers = headers
        self.url = url
        self.content = content
        self._encoding = self._parse_encoding(headers)

    @staticmethod
    def _parse_encoding(headers) -> str | None:
        content_type = headers.get("Content-Type", "") if headers else ""
        matched = re.search(r"charset=([\w-]+)", content_type, re.I)
        return matched.group(1) if matched else None

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    @property
    def text(self) -> str:
        return decode_bytes(self.content, self._encoding)

    def json(self):
        return json.loads(self.text)

    def close(self):
        """兼容 requests.Response.close()"""


class AsyncRequestUtils:
    """
    异步 HTTP 请求工具

    与 RequestUtils 保持相近的方法签名，供异步链路使用。不要在同步代码中直接调用，
    同步业务应通过事件循环（协程）或 asyncio.run / to_thread 驱动。
    """

    _headers = None
    _proxies = None
    _timeout = 20
    _session = None
    _cookies = None

    def __init__(self,
                 headers: dict | None = None,
                 ua: str | None = None,
                 cookies: str | dict | None = None,
                 proxies: dict | None = None,
                 session: aiohttp.ClientSession = None,
                 timeout: int | None = None,
                 referer: str | None = None,
                 content_type: str | None = None,
                 accept_type: str | None = None):
        if not content_type:
            content_type = "application/x-www-form-urlencoded; charset=UTF-8"
        if headers:
            self._headers = headers
        else:
            self._headers = {
                "User-Agent": ua if ua else Config().get_ua(),
                "Content-Type": content_type,
                "Accept": accept_type,
                "referer": referer
            }

        if cookies:
            if isinstance(cookies, str):
                self._cookies = self.cookie_parse(cookies)
            else:
                self._cookies = cookies
        if proxies:
            self._proxies = proxies
        if session:
            self._session = session
        if timeout:
            self._timeout = timeout

    def _pick_proxy(self, url: str):
        """按请求协议选择代理，aiohttp 每次请求只接受一个 proxy 参数"""
        if not self._proxies:
            return None
        scheme = (urlparse(url).scheme or "http").lower()
        return self._proxies.get(scheme) or self._proxies.get("all") or self._proxies.get("http")

    async def request(self, method: str, url: str, raise_exception: bool = False, **kwargs):
        """
        发起异步 HTTP 请求

        :return: AsyncResponse，异常时返回 None（raise_exception=True 时抛出）
        """
        session = self._session or get_async_session()

        headers = {k: v for k, v in (kwargs.pop("headers", None) or self._headers).items()
                   if v is not None}
        cookies = kwargs.pop("cookies", None) or self._cookies
        proxies = kwargs.pop("proxies", None) or self._proxies
        params = kwargs.pop("params", None)
        data = kwargs.pop("data", None)
        json_data = kwargs.pop("json", None)
        allow_redirects = kwargs.pop("allow_redirects", True)
        # requests 专有参数，aiohttp 不接受
        kwargs.pop("stream", None)
        kwargs.pop("verify", None)
        kwargs.pop("timeout", None)

        if params:
            params = {k: v for k, v in params.items() if v is not None}

        timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=self._timeout)
        request_kwargs = {
            "headers": headers,
            "cookies": cookies or None,
            "params": params,
            "proxy": self._pick_proxy(url),
            "allow_redirects": allow_redirects,
            "timeout": timeout,
        }
        if data is not None:
            request_kwargs["data"] = data
        if json_data is not None:
            request_kwargs["json"] = json_data

        try:
            async with session.request(method, url, **request_kwargs) as response:
                content_length = response.content_length
                if content_length and content_length > _MAX_BODY_SIZE:
                    log.warn(f"【Http】响应体过大({content_length} bytes)，已丢弃: {mask_url(url)}")
                    return None
                content = await response.read()
                if len(content) > _MAX_BODY_SIZE:
                    log.warn(f"【Http】响应体过大({len(content)} bytes)，已丢弃: {mask_url(url)}")
                    return None
                return AsyncResponse(response.status,
                                     response.headers.copy(),
                                     str(response.url),
                                     content)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception(f"【Http】异步请求{mask_url(url)},method={method}  异常:")
            if raise_exception:
                raise
            return None

    async def get_res(self,
                      url: str,
                      params: dict | None = None,
                      data=None,
                      json: dict | None = None,
                      allow_redirects: bool = True,
                      raise_exception: bool = False,
                      **kwargs):
        """发送 GET 请求并返回响应对象"""
        return await self.request(method="get",
                                  url=url,
                                  params=params,
                                  data=data,
                                  json=json,
                                  allow_redirects=allow_redirects,
                                  raise_exception=raise_exception,
                                  **kwargs)

    async def get_json(self, url: str, params: dict | None = None, **kwargs):
        """发送 GET 请求并返回 JSON 数据"""
        response = await self.request(method="get", url=url, params=params, **kwargs)
        if response:
            try:
                return response.json()
            except Exception as e:
                log.warn(f"【Http】解析JSON失败: {e}")
        return None

    async def get(self, url: str, params: dict | None = None, **kwargs) -> str | None:
        """发送 GET 请求并返回文本内容"""
        response = await self.request(method="get", url=url, params=params, **kwargs)
        return response.text if response else None

    @staticmethod
    def cookie_parse(cookies_str: str, array: bool = False) -> list | dict:
        """
        解析cookie, 转化为字典或者数组
        """
        if not cookies_str:
            return []
        cookie_dict = {}
        try:
            for cookie in cookies_str.split(";"):
                cstr = cookie.split("=")
                if len(cstr) > 1:
                    cookie_dict[cstr[0].strip()] = cstr[1].strip()
        except Exception:
            log.exception('【Http】cookie解析异常: ')
        if array:
            return [{"name": k, "value": v} for k, v in cookie_dict.items()]
        return cookie_dict
