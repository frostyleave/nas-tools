import logging
import threading
import time
from operator import attrgetter

from cachetools import TTLCache, cachedmethod
from requests import Response, Session
from urllib3.util.retry import Retry

from app.models.model import SSLAdapter
from config import Config

from .as_obj import AsObj
from .exceptions import TMDbException

logger = logging.getLogger(__name__)

# 全局共享 Session：复用连接，避免每次创建客户端都重新握手
_shared_session: Session | None = None
_shared_session_lock = threading.Lock()


def _get_shared_session() -> Session:
    """获取全局共享 Session（首次调用时创建）"""
    global _shared_session
    if _shared_session is None:
        with _shared_session_lock:
            if _shared_session is None:
                _shared_session = TMDb._create_session()
    return _shared_session


class TMDb:

    _session : Session | None = None

    _proxies: dict | None = None
    _language = 'zh'
    _domain = 'https://api.themoviedb.org/3'
    _api_key = ''

    _cache : TTLCache | None = None
    _debug = False
    _wait_on_rate_limit = False

    def __init__(self, 
                 session: Session | None = None,
                 cache_ttl: int = 3600,
                 cache_size: int = 512,
        ):

        self._session = session if session is not None else _get_shared_session()

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
        构建 TMDB 请求使用的代理

        仅在开启「使用代理」(app.tmdb_use_proxy) 时使用全局代理配置；
        直接给实例属性赋值，避免修改 ClassVar 导致多个实例互相污染。
        """
        self._proxies = None
        if not Config().get_config('app').get("tmdb_use_proxy", True):
            return
        proxy_conf = Config().get_proxies()
        if not proxy_conf:
            return
        self._proxies = {key: value for key, value in proxy_conf.items() if value}


    @staticmethod
    def _create_session() -> Session:

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

        adapter = SSLAdapter(pool_connections=10, pool_maxsize=10, max_retries=retry_strategy)

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


    def _do_request(self, method: str, url: str, data: dict | None = None) -> Response:
        """
        实际请求方法
        """
        headers = {}
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
    def _cache_request(self, method: str, url: str, data: dict | None = None) -> Response:
        """
        缓存请求
        """
        return self._do_request(method, url, data)

    def _call(self,
              action: str,
              append_to_response: str,
              call_cached: bool=True,
              method: str="GET", 
              data: dict | None=None
    ):
        if self._api_key is None or self._api_key == "":
            raise TMDbException("No API key found.")
        
        include_adult = Config().get_config('laboratory').get("search_adult")

        url = f"{self._domain}{action}?api_key={self._api_key}&{append_to_response}&language={self._language}&include_adult={include_adult!s}"

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
                logger.warning(f"Rate limit reached. Sleeping for: {sleep_time}")
                time.sleep(abs(sleep_time))
                # 递归重试
                return self._call(action, append_to_response, call_cached, method, data)
            else:
                raise TMDbException(f"Rate limit reached. Try again in {sleep_time} seconds.")

        json = req.json()

        if self._debug:
            logger.info(json)

        if "errors" in json:
            raise TMDbException(json["errors"])

        return json
    