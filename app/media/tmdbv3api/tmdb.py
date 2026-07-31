# -*- coding: utf-8 -*-
import logging
import time

from cachetools import TTLCache, cachedmethod
from operator import attrgetter
from requests import Session, Response
from typing import Dict, Optional
from urllib3.util.retry import Retry

from app.models.model import SSLAdapter
from config import Config

from .as_obj import AsObj
from .exceptions import TMDbException

logger = logging.getLogger(__name__)


class TMDb(object):

    _session : Optional[Session] = None

    _proxies = {}
    _language = 'zh'
    _domain = 'https://api.themoviedb.org/3'
    _api_key = ''

    _cache : Optional[TTLCache] = None
    _debug = False
    _wait_on_rate_limit = False

    def __init__(self, 
                 session: Optional[Session] = None,
                 cache_ttl: int = 3600,
                 cache_size: int = 512,
        ):

        self._session = self._create_session() if session is None else session

        self._cache = TTLCache(maxsize=cache_size, ttl=cache_ttl)
        self._remaining = 40
        self._reset = None
        
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
        
        for key, value in proxy_conf.items():
            if not value:
                continue
            self._proxies[key] = value


    def _create_session(self) -> Session:

        s = Session()
        s.trust_env = False

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


    def _do_request(self, method: str, url: str, data: Optional[Dict] = None) -> Response:
        """
        实际请求方法
        """
        headers = {}
        if method.upper() == "GET":
            headers["Connection"] = "close"
        resp = self._session.request(
            method,
            url,
            headers=headers,
            data=data,
            proxies=self._proxies,
            timeout=(10, 20),
            verify=False
        )
        resp.raise_for_status()
        return resp
    
    @cachedmethod(cache=attrgetter('_cache'),
                  key=lambda self, method, url, data: (
                      method.upper(),
                      url,
                      frozenset(data.items()) if data else None
                    )
                )
    def _cache_request(self, method: str, url: str, data: Optional[Dict] = None) -> Response:
        """
        缓存请求
        """
        return self._do_request(method, url, data)

    def _call(self,
              action: str,
              append_to_response: str,
              call_cached: bool=True,
              method: str="GET", 
              data: Optional[Dict]=None
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

        use_cache = call_cached and method.upper() != "POST"
        if use_cache:
            req = self._cache_request(method, url, data)
        else:
            req = self._do_request(method, url, data)

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
    