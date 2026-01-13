import os
import pickle
import random
import time

from app.utils.commons import singleton
from config import Config

import log

CACHE_EXPIRE_TIMESTAMP_STR = "cache_expire_timestamp"
EXPIRE_TIMESTAMP = 7 * 24 * 3600


@singleton
class MetaHelper(object):
    """
    {
        "id": '',
        "title": '',
        "year": '',
        "type": MediaType
    }
    """
    _meta_data = {}

    _meta_path = None
    _tmdb_cache_expire = False

    def __init__(self):
        self.init_config()

    def init_config(self):
        laboratory = Config().get_config('laboratory')
        if laboratory:
            self._tmdb_cache_expire = laboratory.get("tmdb_cache_expire")
        self._meta_path = os.path.join(Config().get_config_path(), 'tmdb.dat')
        self._meta_data = self.__load_meta_data(self._meta_path)

    def clear_meta_data(self):
        """
        清空所有TMDB缓存
        """
        # 直接赋值为空字典（原子操作）
        self._meta_data = {}

    def get_meta_data_path(self):
        """
        返回TMDB缓存文件路径
        """
        return self._meta_path

    def get_meta_data_by_key(self, key):
        """
        根据KEY值获取缓存值
        """
        # 字典 get 是线程安全的
        info: dict = self._meta_data.get(key)
        if info:
            expire = info.get(CACHE_EXPIRE_TIMESTAMP_STR)
            if not expire or int(time.time()) < expire:
                # 修改字典中的嵌套对象可能会有并发风险，但在简单缓存场景下通常可接受
                info[CACHE_EXPIRE_TIMESTAMP_STR] = int(time.time()) + EXPIRE_TIMESTAMP
                # 这里调用 update 本质上是重复赋值，为了触发所谓的“更新”逻辑
                self.update_meta_data({key: info})
            elif expire and self._tmdb_cache_expire:
                self.delete_meta_data(key)
        return info or {}

    def dump_meta_data(self, search, page, num):
        """
        分页获取当前缓存列表
        """
        if page == 1:
            begin_pos = 0
        else:
            begin_pos = (page - 1) * num

        page_metas = []
        
        # 为了防止遍历时字典大小改变，先生成一个列表快照
        # list() 操作在 CPython 中相对安全，能迅速生成副本
        all_items_snapshot = list(self._meta_data.items())
        
        total_count = 0

        if not search:  # search 为空，直接按分页取数据
            total_count = len(all_items_snapshot)
            # 对快照进行切片
            items = all_items_snapshot[begin_pos: begin_pos + num]
            for k, v in items:
                if v.get("id") == 0:
                    continue
                page_metas.append({
                    "key": k,
                    "meta": {
                        "id": v.get("id"),
                        "title": v.get("title"),
                        "year": v.get("year"),
                        "media_type": v.get("type").value,
                        "poster_path": v.get("poster_path"),
                        "backdrop_path": v.get("backdrop_path")
                    }
                })
        else:  # search 不为空，按匹配处理
            current_index = 0
            start_index = begin_pos
            end_index = begin_pos + num
            search_key = search.lower()

            # 遍历快照，而不是 self._meta_data
            for k, v in all_items_snapshot:
                if search_key in k.lower() and v.get("id") != 0:
                    total_count += 1
                    if start_index <= current_index < end_index:
                        page_metas.append({
                            "key": k,
                            "meta": {
                                "id": v.get("id"),
                                "title": v.get("title"),
                                "year": v.get("year"),
                                "media_type": v.get("type").value,
                                "poster_path": v.get("poster_path"),
                                "backdrop_path": v.get("backdrop_path")
                            }
                        })
                    current_index += 1

        return total_count, page_metas

    def delete_meta_data(self, key):
        """
        删除缓存信息
        """
        # pop 是原子操作，无需锁
        return self._meta_data.pop(key, None)

    def delete_meta_data_by_tmdbid(self, tmdbid):
        """
        清空对应TMDBID的所有缓存记录
        """
        # 使用 list(keys) 创建键的副本进行遍历，防止遍历时删除报错
        for key in list(self._meta_data.keys()):
            # 为了防止 key 在此时被删，使用 .get 安全获取
            item = self._meta_data.get(key)
            if item and str(item.get("id")) == str(tmdbid):
                self._meta_data.pop(key, None)

    def delete_unknown_meta(self):
        """
        清除未识别的缓存记录
        """
        # 同样使用 list(keys) 创建副本
        for key in list(self._meta_data.keys()):
            item = self._meta_data.get(key)
            if item and str(item.get("id")) == '0':
                self._meta_data.pop(key, None)

    def modify_meta_data(self, key, title):
        """
        修改缓存信息
        """
        if self._meta_data.get(key):
            self._meta_data[key]['title'] = title
            self._meta_data[key][CACHE_EXPIRE_TIMESTAMP_STR] = int(time.time()) + EXPIRE_TIMESTAMP
        return self._meta_data.get(key)

    @staticmethod
    def __load_meta_data(path):
        """
        从文件中加载缓存
        """
        try:
            if os.path.exists(path):
                with open(path, 'rb') as f:
                    data = pickle.load(f)
                return data
            return {}
        except Exception as e:
            log.exception("从文件中加载缓存: ")
            return {}

    def update_meta_data(self, meta_data):
        """
        新增或更新缓存条目
        """
        if not meta_data:
            return
        # 字典的 update 并不完全保证并发时的原子性（如果是大批量），但逐个赋值是安全的
        # 这里为了保持逻辑一致，直接遍历
        for key, item in meta_data.items():
            if not self._meta_data.get(key):
                item[CACHE_EXPIRE_TIMESTAMP_STR] = int(time.time()) + EXPIRE_TIMESTAMP
                self._meta_data[key] = item
            else:
                # 原始逻辑里，如果 exist 就不更新整个 item，这里保持原逻辑
                pass

    def save_meta_data(self, force=False):
        """
        保存缓存数据到文件
        """
        # 加载旧数据用于比对
        old_meta_data_on_disk = self.__load_meta_data(self._meta_path)
        
        # 使用 copy() 创建当前内存数据的副本
        # 这样在后续筛选和 pickle.dump 时，即使主 _meta_data 发生变化也不会崩溃
        current_data_snapshot = self._meta_data.copy()
        
        # 基于副本进行过滤
        new_meta_data = {k: v for k, v in current_data_snapshot.items() if str(v.get("id")) != '0'}

        # 对比逻辑保持不变
        if not force \
                and not self._random_sample(new_meta_data) \
                and old_meta_data_on_disk.keys() == new_meta_data.keys():
            return

        with open(self._meta_path, 'wb') as f:
            # 这里的 pickle.dump 操作的是 new_meta_data（局部变量），完全线程安全
            pickle.dump(new_meta_data, f, pickle.HIGHEST_PROTOCOL)

    def _random_sample(self, new_meta_data):
        """
        采样分析是否需要保存
        注意：传入的 new_meta_data 必须是局部变量副本，否则 pop 操作会影响缓存
        """
        ret = False
        # 获取 keys 列表副本
        all_keys = list(new_meta_data.keys())
        
        if len(new_meta_data) < 25:
            for k in all_keys:
                info = new_meta_data.get(k)
                if not info: continue 
                
                expire = info.get(CACHE_EXPIRE_TIMESTAMP_STR)
                if not expire:
                    ret = True
                    info[CACHE_EXPIRE_TIMESTAMP_STR] = int(time.time()) + EXPIRE_TIMESTAMP
                elif int(time.time()) >= expire:
                    ret = True
                    if self._tmdb_cache_expire:
                        new_meta_data.pop(k, None)
        else:
            count = 0
            # random.sample 是安全的
            keys = random.sample(all_keys, 25)
            for k in keys:
                info = new_meta_data.get(k)
                if not info: continue

                expire = info.get(CACHE_EXPIRE_TIMESTAMP_STR)
                if not expire:
                    ret = True
                    info[CACHE_EXPIRE_TIMESTAMP_STR] = int(time.time()) + EXPIRE_TIMESTAMP
                elif int(time.time()) >= expire:
                    ret = True
                    if self._tmdb_cache_expire:
                        new_meta_data.pop(k, None)
                        count += 1
            if count >= 5:
                # 递归调用
                ret |= self._random_sample(new_meta_data)
        return ret

    def get_cache_title(self, key):
        """
        获取缓存的标题
        """
        cache_media_info = self._meta_data.get(key)
        if not cache_media_info or not cache_media_info.get("id"):
            return None
        return cache_media_info.get("title")

    def set_cache_title(self, key, cn_title):
        """
        重新设置缓存标题
        """
        cache_media_info = self._meta_data.get(key)
        if not cache_media_info:
            return
        self._meta_data[key]['title'] = cn_title