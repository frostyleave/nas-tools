# -*- coding: utf-8 -*-

import logging
import requests
import time

from typing import Dict, Optional
from cachetools import TTLCache, cached

from config import Config

from .as_obj import AsObj
from .exceptions import TMDbException

logger = logging.getLogger(__name__)


class TMDb(object):

    _proxies = 'None'
    _language = 'zh'
    _domain = 'https://api.themoviedb.org/3'
    _api_key = ''

    _cache = True
    _debug = False
    _wait_on_rate_limit = False

    def __init__(self, obj_cached=True, session=None):
        self._session = requests.Session() if session is None else session
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
        # 代理
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
        return requests.request(method, url, data=data, proxies=eval(proxies), verify=False, timeout=10)

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

        if self._cache and self.obj_cached and call_cached and method != "POST":
            req = self.cached_request(method, url, data, self._proxies)
        else:
            req = self._session.request(method, url, data=data, proxies=eval(self._proxies), timeout=10, verify=False)

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
                self._call(action, append_to_response, call_cached, method, data)
            else:
                raise TMDbException(
                    "Rate limit reached. Try again in %d seconds." % sleep_time
                )

        json = req.json()

        if self._debug:
            logger.info(json)
            logger.info(self.cached_request.cache_info())

        if "errors" in json:
            raise TMDbException(json["errors"])

        return json
