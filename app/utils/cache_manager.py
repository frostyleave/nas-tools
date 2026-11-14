from cachetools import LRUCache

# TMDB 搜索结果缓存：按名称缓存搜索结果，LRU 淘汰
cacheman = {
    "tmdb_supply": LRUCache(maxsize=200)
}
