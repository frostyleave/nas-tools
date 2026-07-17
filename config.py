import json
import os
import shutil
import sys

from threading import Lock

import ruamel.yaml


# 收藏了的媒体的目录名，名字可以改，在Emby中点击红星则会自动将电影转移到此分类下，需要在Emby Webhook中配置用户行为通知
RMT_FAVTYPE = '精选'

# 线程锁
lock = Lock()

# 全局实例
_CONFIG = None

def singleconfig(cls):
    def _singleconfig(*args, **kwargs):
        global _CONFIG
        if not _CONFIG:
            with lock:
                _CONFIG = cls(*args, **kwargs)
        return _CONFIG

    return _singleconfig


@singleconfig
class Config(object):
    
    _config = {}
    _config_path = None
    _user = None

    # 默认User-Agent
    default_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"

    # TMDB域名地址
    tmdb_api_domain = 'api.themoviedb.org'
    tmdb_img_domain = 'image.tmdb.org'

    def __init__(self):
        self.menu = None
        self.services = None
        self._config_path = os.environ.get('NASTOOL_CONFIG')
        if not self._config_path:
            print("【Config】NASTOOL_CONFIG 环境变量未设置，使用config文件夹下默认配置文件")
            separator = '\\' if os.name == "nt" else '/'
            this_path = sys.argv[0]
            dir_path = this_path[:this_path.rfind(separator)]
            self._config_path = os.path.join(dir_path, "config", "config.yaml")
        if not os.environ.get('TZ'):
            os.environ['TZ'] = 'Asia/Shanghai'
        self.init_config()

    def init_config(self):
        try:
            inner_cfg_path = self.get_inner_config_path()
            if not os.path.exists(self._config_path):
                os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
                cfg_tp_path = os.path.join(inner_cfg_path, "config.yaml")
                cfg_tp_path = cfg_tp_path.replace("\\", "/")
                shutil.copy(cfg_tp_path, self._config_path)
                print("【Config】config.yaml 配置文件不存在，已将配置文件模板复制到配置目录...")

            with open(self._config_path, mode='r', encoding='utf-8') as cf:
                try:
                    # 读取配置
                    print("正在加载配置：%s" % self._config_path)
                    self._config = ruamel.yaml.YAML().load(cf)
                except Exception as e:
                    print("【Config】配置文件 config.yaml 格式出现严重错误! 请检查：%s" % str(e))
                    self._config = {}

            with open(os.path.join(inner_cfg_path, "menu.json"), "rb") as f:
                try:
                    self.menu = json.loads(f.read())
                except Exception as e:
                    print("menu.json解析出现严重错误! 请检查：%s" % str(e))

            with open(os.path.join(inner_cfg_path, "services.json"), "rb") as f:
                try:
                    self.services = json.loads(f.read())
                except Exception as e:
                    print("services.json解析出现严重错误! 请检查：%s" % str(e))

        except Exception as err:
            print("【Config】加载 config.yaml 配置出错：%s" % str(err))
            return False

    def get_proxies(self):
        return self.get_config('app').get("proxies", {})

    def get_ua(self):
        return self.get_config('app').get("user_agent") or self.default_ua

    def get_config(self, node=None):
        if not node:
            return self._config
        return self._config.get(node, {})

    def save_config(self, new_cfg):
        self._config = new_cfg
        with open(self._config_path, mode='w', encoding='utf-8') as sf:
            yaml = ruamel.yaml.YAML()
            return yaml.dump(new_cfg, sf)

    def get_config_path(self):
        return os.path.dirname(self._config_path)

    def get_temp_path(self):
        return os.path.join(self.get_config_path(), "temp")

    @staticmethod
    def get_root_path():
        return os.path.dirname(os.path.realpath(__file__))

    def get_inner_config_path(self):
        return os.path.join(self.get_root_path(), "config")

    def get_script_path(self):
        return os.path.join(self.get_root_path(), "scripts", "sqls")

    def get_user_plugin_path(self):
        return os.path.join(self.get_config_path(), "plugins")

    def get_domain(self):
        domain = (self.get_config('app') or {}).get('domain')
        if domain and not domain.startswith('http'):
            domain = "http://" + domain
        if domain and str(domain).endswith("/"):
            domain = domain[:-1]
        return domain

    @staticmethod
    def get_timezone():
        return os.environ.get('TZ')

    @staticmethod
    def update_favtype(favtype):
        global RMT_FAVTYPE
        if favtype:
            RMT_FAVTYPE = favtype

    def get_tmdbapi_url(self):
        return f"https://{self.get_config('app').get('tmdb_domain') or self.tmdb_api_domain}/3"

    def get_tmdbimage_url(self, path, prefix="w500"):
        if not path:
            return ""
        tmdb_image_url = self.get_config("app").get("tmdb_image_url")
        if tmdb_image_url:
            return tmdb_image_url + f"/t/p/{prefix}{path}"
        return f"https://{self.tmdb_img_domain}/t/p/{prefix}{path}"

    @property
    def category_path(self):
        category = self.get_config('media').get("category")
        if category:
            return os.path.join(Config().get_config_path(), f"{category}.yaml")
        return None
