from typing import Any

import aiohttp
import httpx
from httpx import AsyncClient, Response

import log
from config import Config


class AsyncRequestUtils:

    http_session: aiohttp.ClientSession | None = None
    http_client: httpx.AsyncClient | None = None

    _headers: dict
    _proxies: dict | None = None
    _timeout: int = 20
    _session: AsyncClient | None = None
    _cookies: str | dict | None = None

    
    @classmethod
    def init_client(cls):
        """
        [全局初始化] 在应用启动时调用一次
        """
        if cls.http_session is None:
            connector = aiohttp.TCPConnector(limit=100, ssl=False, ttl_dns_cache=300)
            cls.http_session = aiohttp.ClientSession(connector=connector)
            
        if cls.http_client is None:
            # 限制最大连接数，防止并发过高
            limits = httpx.Limits(max_keepalive_connections=20, max_connections=100)
            cls.http_client = httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(10.0), limits=limits)

    @classmethod
    async def close_client(cls):
        """
        [全局关闭] 在应用退出时调用
        """
        if cls.http_session:
            await cls.http_session.close()
            cls.http_session = None            
        if cls.http_client:
            await cls.http_client.aclose()
            cls.http_client = None

    def __init__(self,
                 headers: dict | None = None,
                 ua: str | None = None,
                 cookies: str | dict | None = None,
                 proxies: dict | None = None,  # 接收 'http' 或 'http://' 格式
                 session: AsyncClient = None,
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
        
        # --- (START) 自动代理格式转换 ---
        if proxies:
            httpx_proxies = {}
            for key, value in proxies.items():
                if key == "http" and "http://" not in proxies:
                    httpx_proxies["http://"] = value
                elif key == "https" and "https://" not in proxies:
                    httpx_proxies["https://"] = value
                else:
                    # 保持已经是 httpx 格式 (http://) 或其他格式 (socks5://) 不变
                    httpx_proxies[key] = value
            self._proxies = httpx_proxies
        else:
            self._proxies = None
        # --- (END) 自动代理格式转换 ---
            
        if session:
            self._session = session
        if timeout:
            self._timeout = timeout

    async def request(self, method: str, url: str, raise_exception: bool = False, **kwargs) -> Response | None:
        """
        发起异步HTTP请求
        :param method: HTTP方法, 如 get, post, put 等
        :param url: 请求的URL
        :param raise_exception: 是否在发生异常时抛出异常, 否则默认拦截异常返回None
        :param kwargs: 其他请求参数, 如headers, cookies, proxies等
        :return: HTTP响应对象
        :raises: httpx.RequestError 仅raise_exception为True时会抛出
        """
        
        if "allow_redirects" in kwargs:
            kwargs["follow_redirects"] = kwargs.pop("allow_redirects")

        kwargs.setdefault("headers", self._headers)
        kwargs.setdefault("cookies", self._cookies)
        kwargs.setdefault("proxies", self._proxies) # 这里会使用已转换的代理
        kwargs.setdefault("timeout", self._timeout)
        kwargs.setdefault("verify", False)  

        try:
            if self._session:
                return await self._session.request(method, url, **kwargs)
            else:
                async with httpx.AsyncClient() as client:
                    return await client.request(method, url, **kwargs)

        except httpx.RequestError as e:
            log.exception(f"【Http】请求{url},method={method}  异常:")
            if raise_exception:
                raise
            return None

    async def post(self, url: str, data: Any = None, json: dict | None = None, **kwargs) -> Response | None:
        """
        发送异步POST请求
        """
        return await self.request(method="post", url=url, data=data, json=json, **kwargs)

    async def get(self, url: str, params: dict | None = None, **kwargs) -> str | None:
        """
        发送异步GET请求
        :return: 响应的文本内容, 若发生异常则返回None
        """
        response = await self.request(method="get", url=url, params=params, **kwargs)
        return response.text if response else None

    async def get_res(self, 
                      url: str,
                      params: dict | None = None,
                      data: Any = None,
                      json: dict | None = None,
                      allow_redirects: bool = True,
                      raise_exception: bool = False,
                      **kwargs) -> Response | None:
        
        return await self.request(method="get",
                                  url=url,
                                  params=params,
                                  data=data,
                                  json=json,
                                  allow_redirects=allow_redirects,
                                  raise_exception=raise_exception,
                                  **kwargs)

    async def post_res(self,
                       url: str,
                       data: Any = None,
                       params: dict | None = None,
                       allow_redirects: bool = True,
                       files: Any = None,
                       json: dict | None = None,
                       raise_exception: bool = False,
                       **kwargs) -> Response | None:
        
        return await self.request(method="post",
                                  url=url,
                                  data=data,
                                  params=params,
                                  allow_redirects=allow_redirects,
                                  files=files,
                                  json=json,
                                  raise_exception=raise_exception,
                                  **kwargs)

    async def get_json(self, url: str, params: dict | None = None, **kwargs) -> dict | None:
        """
        发送异步GET请求并返回JSON数据
        """
        response = await self.request(method="get", url=url, params=params, **kwargs)
        if response:
            try:
                data = response.json()
                return data
            except Exception as e:
                log.warn(f"【Http】解析JSON失败: {e}")
                return None
        return None

    async def post_json(self, url: str, data: Any = None, json: dict | None = None, **kwargs) -> dict | None:
        """
        发送异步POST请求并返回JSON数据
        """
        response = await self.request(method="post", url=url, data=data, json=json, **kwargs)
        if response:
            try:
                data = response.json()
                return data
            except Exception as e:
                log.warn(f"【Http】解析JSON失败: {e}")
                return None
        return None

    @staticmethod
    def cookie_parse(cookies_str: str, array: bool = False) -> list | dict:
        if not cookies_str:
            return [] if array else {}
        
        cookie_dict = {}
        try:
            cookies = cookies_str.split(";")
            for cookie in cookies:
                cstr = cookie.split("=")
                if len(cstr) > 1:
                    cookie_dict[cstr[0].strip()] = cstr[1].strip()
        except Exception as e:
            log.exception('【Http】cookie解析异常: ')
        if array:
            return [{"name": k, "value": v} for k, v in cookie_dict.items()]
        return cookie_dict

    @staticmethod
    def cookie_dict_to_string(data: dict[str, str]) -> str:
        return ";".join(f"{key}={value}" for key, value in data.items())