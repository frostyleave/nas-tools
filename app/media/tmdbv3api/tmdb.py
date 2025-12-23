# -*- coding: utf-8 -*-
import ast
import logging
import requests
import time

from cachetools import TTLCache, cached
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from typing import Dict, Optional

from config import Config

from .as_obj import AsObj
from .exceptions import TMDbException

logger = logging.getLogger(__name__)


class TMDb(object):
    
    # --- 类变量：全局共享 Session ---
    _shared_session = None
    
    _proxies = 'None'
    _language = 'zh'
    _domain = 'https://api.themoviedb.org/3'
    _api_key = ''

    _cache = True
    _debug = False
    _wait_on_rate_limit = False

    def __init__(self, obj_cached=True, session=None):
        """
        :param session: 允许外部传入 session，如果未传入则使用内部全局 session
        """
        # 如果外部传入了 session，则使用外部的（优先）；否则设为 None，后续调用时会去取 _shared_session
        self._external_session = session
        
        self._remaining = 40
        self._reset = None
        self.obj_cached = obj_cached
        
        # 域名
        self._domain = Config().get_tmdbapi_url() or "https://api.themoviedb.org/3"
        # api key
        app_conf = Config().get_config('app')
        if app_conf:
            self._api_key = app_conf.get('rmt_tmdbkey')
        # 语言
        media_conf = Config().get_config('media')
        if media_conf:
            self._language = media_conf.get("tmdb_language", "zh") or "zh"
            
        # 代理处理
        proxy_conf = Config().get_proxies()
        if proxy_conf:
            proxies_strs = []
            for key, value in proxy_conf.items():
                if not value:
                    continue
                proxies_strs.append("'%s': '%s'" % (key, value))
            if proxies_strs:
                self._proxies = "{%s}" % ",".join(proxies_strs)
            else:
                self._proxies = 'None'

    @classmethod
    def _get_shared_session(cls):
        """
        获取或创建全局共享的 Session
        """
        if cls._shared_session is None:
            cls._shared_session = requests.Session()
            
            # 配置连接池和重试策略
            # pool_connections: 缓存的连接数
            # pool_maxsize: 最大连接数（并发高时需要调大）
            retry_strategy = Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
            )
            adapter = HTTPAdapter(pool_connections=20, pool_maxsize=100, max_retries=retry_strategy)
            
            cls._shared_session.mount("https://", adapter)
            cls._shared_session.mount("http://", adapter)
            
        return cls._shared_session

    @property
    def _session(self):
        """
        属性包装器：优先返回外部传入的 session，否则返回全局共享 session
        """
        if self._external_session:
            return self._external_session
        return self._get_shared_session()

    @staticmethod
    def _get_obj(result, key="results", all_details=False):
        if "success" in result and result["success"] is False:
            raise TMDbException(result["status_message"])
        if all_details is True or key is None:
            return AsObj(**result)
        else:
            return [AsObj(**res) for res in result[key]]

    @staticmethod
    @cached(cache=TTLCache(maxsize=512, ttl=3600))
    def cached_request(method, url, data, proxies):
        """
        静态方法：执行缓存请求
        不再创建新连接，而是复用 TMDb 类的全局 Session
        """
        # 安全地将字符串转为字典
        proxies_dict = {}
        if proxies and proxies != 'None':
            try:
                # 使用 ast.literal_eval 替代 eval，更安全
                proxies_dict = ast.literal_eval(proxies)
            except Exception:
                logger.warning(f"Failed to parse proxies: {proxies}")
        
        # 获取全局 Session
        session = TMDb._get_shared_session()
        
        return session.request(method, url, data=data, proxies=proxies_dict, verify=False, timeout=10)

    def cache_clear(self):
        return self.cached_request.cache_clear()

    def _call(
            self, action: str, append_to_response: str, call_cached: bool=True, method: str="GET", data: Optional[Dict]=None
    ):
        if self._api_key is None or self._api_key == "":
            raise TMDbException("No API key found.")
        
        include_adult = Config().get_config('laboratory').get("search_adult")

        url = "%s%s?api_key=%s&%s&language=%s&include_adult=%s" % (
            self._domain,
            action,
            self._api_key,
            append_to_response,
            self._language,
            str(include_adult)
        )

        # 逻辑：
        # 1. 如果走缓存，调用静态 cached_request (内部现已复用 session)
        # 2. 如果不走缓存，直接使用 self._session (也指向全局 session 或外部 session)
        
        if self._cache and self.obj_cached and call_cached and method != "POST":
            req = self.cached_request(method, url, data, self._proxies)
        else:
            proxies_dict = {}
            if self._proxies and self._proxies != 'None':
                 try:
                    proxies_dict = ast.literal_eval(self._proxies)
                 except:
                    pass
            
            req = self._session.request(method, url, data=data, proxies=proxies_dict, timeout=10, verify=False)

        headers = req.headers

        if "X-RateLimit-Remaining" in headers:
            self._remaining = int(headers["X-RateLimit-Remaining"])

        if "X-RateLimit-Reset" in headers:
            self._reset = int(headers["X-RateLimit-Reset"])

        if self._remaining < 1:
            current_time = int(time.time())
            sleep_time = self._reset - current_time

            if self._wait_on_rate_limit:
                logger.warning("Rate limit reached. Sleeping for: %d" % sleep_time)
                time.sleep(abs(sleep_time))
                # 递归重试
                return self._call(action, append_to_response, call_cached, method, data)
            else:
                raise TMDbException(
                    "Rate limit reached. Try again in %d seconds." % sleep_time
                )

        json = req.json()

        if self._debug:
            logger.info(json)

        if "errors" in json:
            raise TMDbException(json["errors"])

        return json
