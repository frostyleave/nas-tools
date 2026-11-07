import time

from cachetools import LRUCache, TTLCache

# TMDB 搜索结果缓存：按名称缓存搜索结果，LRU 淘汰
cacheman = {
    "tmdb_supply": LRUCache(maxsize=200)
}

# config.yaml 10 秒内只加载一次
ConfigLoadCache = TTLCache(maxsize=1, ttl=10, timer=time.time)

# config.yaml 重新加载后 10 秒内不再加载二级分类策略文件
ConfigLoadBlockCache = TTLCache(maxsize=1, ttl=10, timer=time.time)

# 正在使用的二级分类策略文件 3 秒内只加载一次
CategoryLoadCache = TTLCache(maxsize=2, ttl=3, timer=time.time)
