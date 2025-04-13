# -*- coding: utf-8 -*-
import time

from cacheout import CacheManager, LRUCache, Cache
from functools import lru_cache, wraps

CACHES = {
    "tmdb_supply": {'maxsize': 200}
}

cacheman = CacheManager(CACHES, cache_class=LRUCache)

TokenCache = Cache(maxsize=256, ttl=4*3600, timer=time.time, default=None)

ConfigLoadCache = Cache(maxsize=1, ttl=10, timer=time.time, default=None)

CategoryLoadCache = Cache(maxsize=2, ttl=3, timer=time.time, default=None)

OpenAISessionCache = Cache(maxsize=100, ttl=3600, timer=time.time, default=None)



def ttl_lru_cache(maxsize=128, ttl=600):
    """
    一个结合 lru_cache 与 TTL 功能的装饰器
    :param maxsize: lru_cache 最大缓存条目数
    :param ttl: 缓存有效时间（秒）
    """
    def decorator(func):
        cached_func = lru_cache(maxsize=maxsize)(func)
        # 初始化缓存过期时间
        cached_func.expiration = time.time() + ttl

        @wraps(func)
        def wrapper(*args, **kwargs):
            # 如果超过了过期时间，则清空缓存并重置时间
            if time.time() >= cached_func.expiration:
                cached_func.cache_clear()
                cached_func.expiration = time.time() + ttl
            return cached_func(*args, **kwargs)

        # 同时保留清除缓存的方法
        wrapper.cache_clear = cached_func.cache_clear
        return wrapper
    return decorator