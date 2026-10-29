import time

from cacheout import Cache, CacheManager, LRUCache

CACHES = {
    "tmdb_supply": {'maxsize': 200}
}

cacheman = CacheManager(CACHES, cache_class=LRUCache)

TokenCache = Cache(maxsize=256, ttl=4*3600, timer=time.time, default=None)

ConfigLoadCache = Cache(maxsize=1, ttl=10, timer=time.time, default=None)

CategoryLoadCache = Cache(maxsize=2, ttl=3, timer=time.time, default=None)
