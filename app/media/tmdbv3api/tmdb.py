# -*- coding: utf-8 -*-
import ast
import logging
import threading
import requests
import time

from cachetools import TTLCache, cached
from urllib3.util.retry import Retry
from typing import Dict, Optional

from app.model import SSLAdapter
from config import Config

from .as_obj import AsObj
from .exceptions import TMDbException

logger = logging.getLogger(__name__)


class TMDb(object):

    _session_ins = None
    _session_ts = 0
    _session_lock = threading.Lock()
    _SESSION_TTL = 300  # 5 分钟

    _proxies = 'None'
    _proxies_dict = {}
    _language = 'zh'
    _domain = 'https://api.themoviedb.org/3'
    _api_key = ''

    _cache = True
    _debug = False
    _wait_on_rate_limit = False

    def __init__(self, obj_cached=True):

        self._remaining = 40
        self._reset = None
        self.obj_cached = obj_cached
        
        # 域名
        self._domain = Config().get_tmdbapi_url() or "https://api.themoviedb.org/3"
        # api key
        self._api_key = Config().get_config('app').get('rmt_tmdbkey')            
        # 语言
        self._language = Config().get_config('media').get("tmdb_language", "zh") or "zh"            
        # 代理
        self._build_proxies()

    
    def _build_proxies(self):
        """
        从 Config 中构建 requests 可用的 proxies dict
        """
        proxy_conf = Config().get_proxies()
        if not proxy_conf:
            return
        
        proxies_strs = []
        for key, value in proxy_conf.items():
            if not value:
                continue
            proxies_strs.append("'%s': '%s'" % (key, value))
            self._proxies_dict[key] = value

        if proxies_strs:
            self._proxies = "{%s}" % ",".join(proxies_strs)

    @classmethod
    def _get_shared_session(cls):

        now = time.time()

        with cls._session_lock:
            if (
                cls._session_ins is None
                or now - cls._session_ts > cls._SESSION_TTL
            ):
                if cls._session_ins:
                    try:
                        cls._session_ins.close()
                    except Exception:
                        pass

                cls._session_ins = cls._create_session()
                cls._session_ts = now

        return cls._session_ins

    @classmethod
    def _parse_proxy(cls, proxy_str):
        if proxy_str and proxy_str != 'None': 
            try: 
                proxies_dict = ast.literal_eval(proxy_str)
                return proxies_dict
            except Exception:
                logger.warning(f"Failed to parse proxies: {proxy_str}")
        return {}

    @staticmethod
    def _create_session():

        s = requests.Session()
        s.trust_env = False
        s.headers.update({"Connection": "close"})  # 代理场景建议

        retry_strategy = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            raise_on_status=False,
        )

        adapter = SSLAdapter(pool_connections=1, pool_maxsize=1, max_retries=retry_strategy)

        s.mount("https://", adapter)
        s.mount("http://", adapter)
        return s

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
        proxies_dict = TMDb._parse_proxy(proxies)        
        # 获取 Session
        session = TMDb._get_shared_session()
        
        return session.request(method,
                               url,
                               data=data,
                               proxies=proxies_dict,
                               timeout=(10, 20),
                               verify=False,
                               headers={"Connection": "close"}  # 双保险
                            )

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
        # 1. 如果走缓存，调用静态 cached_request
        # 2. 如果不走缓存，直接使用 全局 Session
        
        if self._cache and self.obj_cached and call_cached and method != "POST":
            req = self.cached_request(method, url, data, self._proxies)
        else:           
            session = TMDb._get_shared_session()
            req = session.request(method,
                                  url,
                                  data=data,
                                  proxies=self.proxies_dict,
                                  timeout=(10, 20),
                                  verify=False)

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
