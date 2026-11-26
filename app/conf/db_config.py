"""
数据库配置层

运行期配置存放在 SYSTEM_DICT 表（TYPE=SystemConfig，KEY=ConfigOverride），
启动时合并到内存配置，业务代码统一通过 Config().get_config(...) 读取。
"""
import copy
import os
from collections.abc import Mapping, MutableMapping

import log
from app.utils.commons import singleton
from app.utils.types import SystemConfigKey

# 由数据库管理的配置项
DB_CONFIG_SCHEMA = {
    "app": [
        "rmt_tmdbkey",
        "tmdb_domain",
        "tmdb_use_proxy",
        "tmdb_image_url",
        "rmt_match_mode",
        "domain",
        "user_agent",
        "wallpaper",
        "ocr_url",
        "init_files",
    ],
    "media": [
        "category",
        "media_server",
        "mediasync_interval",
        "min_filesize",
        "ignored_files",
        "ignored_paths",
        "filesize_cover",
        "movie_name_format",
        "tv_name_format",
        "nfo_poster",
        "default_rmt_mode",
        "tmdb_language",
    ],
    "emby": ["host", "api_key", "play_host"],
    "jellyfin": ["host", "api_key", "play_host"],
    "plex": ["host", "token", "play_host"],
    "pt": [
        "search_auto",
        "search_no_result_rss",
        "pt_check_interval",
        "search_rss_interval",
        "download_order",
        "ptrefresh_date_cron",
    ],
    "security": [
        "media_server_webhook_allow_ip",
        "telegram_webhook_allow_ip",
        "synology_webhook_allow_ip",
        "check_apikey",
    ],
    "laboratory": [
        "search_keyword",
        "search_tmdbweb",
        "tmdb_cache_expire",
        "use_douban_titles",
        "search_adult",
    ],
}

# 数据库为空时使用的默认值
DB_CONFIG_DEFAULTS = {
    "app": {
        "rmt_tmdbkey": "",
        "tmdb_domain": "api.themoviedb.org",
        "tmdb_use_proxy": False,
        "tmdb_image_url": "",
        "rmt_match_mode": "normal",
        "domain": "",
        "user_agent": "",
        "wallpaper": "bing",
        "ocr_url": "",
    },
    "media": {
        "category": "",
        "media_server": "",
        "mediasync_interval": "24",
        "min_filesize": "10",
        "ignored_files": "",
        "ignored_paths": "",
        "filesize_cover": True,
        "movie_name_format": "{title} ({year})/{title}-{part} ({year}) - {videoFormat}",
        "tv_name_format": "{title} ({year})/Season {season}/{title}-{part} - {season_episode} - 第{episode}集",
        "nfo_poster": False,
        "default_rmt_mode": "move",
        "tmdb_language": "zh",
    },
    "emby": {"host": "", "api_key": "", "play_host": ""},
    "jellyfin": {"host": "", "api_key": "", "play_host": ""},
    "plex": {"host": "", "token": "", "play_host": ""},
    "pt": {
        "search_auto": False,
        "search_no_result_rss": False,
        "pt_check_interval": "",
        "search_rss_interval": "",
        "download_order": "seeder",
        "ptrefresh_date_cron": "",
    },
    "security": {
        "media_server_webhook_allow_ip": {"ipv4": "0.0.0.0/0", "ipv6": "::/0"},
        "telegram_webhook_allow_ip": {"ipv4": "127.0.0.1", "ipv6": "::1"},
        "synology_webhook_allow_ip": {"ipv4": "127.0.0.1", "ipv6": "::1"},
        "check_apikey": True,
    },
    "laboratory": {
        "search_keyword": False,
        "search_tmdbweb": False,
        "tmdb_cache_expire": True,
        "use_douban_titles": False,
        "search_adult": False,
    },
}


def _to_plain(value):
    """
    把 ruamel 的 CommentedMap/CommentList 等转换为普通 dict/list，
    便于写入数据库和做相等比较
    """
    if isinstance(value, Mapping):
        return {str(k): _to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_plain(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    # YAML 可能把未加引号的值解析成 datetime/date 等非 JSON 类型
    return str(value)


@singleton
class DbConfig:
    """
    数据库配置的加载与保存
    """

    def init_config(self):
        """
        加载数据库配置并合并到内存配置
        """
        from app.conf.systemconfig import SystemConfig
        from config import Config

        cfg = Config().get_config()
        if not isinstance(cfg, MutableMapping):
            return

        # 刷新数据库缓存
        db_available = True
        db_cfg = {}
        try:
            SystemConfig().init_config()
            db_cfg = SystemConfig().get(SystemConfigKey.ConfigOverride)
        except Exception as e:
            db_available = False
            log.error(f"【Config】读取数据库配置失败，本次启动使用配置文件中的值：{e!s}")

        if not isinstance(db_cfg, Mapping) or not db_cfg:
            # 数据库中没有配置或值损坏时，使用配置文件与默认值
            db_cfg = self._seed_from_file(cfg)
            if db_available:
                try:
                    SystemConfig().set(SystemConfigKey.ConfigOverride, db_cfg)
                    log.info("【Config】已将运行期配置写入数据库")
                except Exception as e:
                    log.error(f"【Config】写入数据库配置失败，本次启动使用配置文件中的值：{e!s}")
            else:
                # 读库失败时仅补充 init_files
                db_cfg = {"app": {"init_files": self._default_init_files()}}
                log.warn("【Config】数据库配置不可用，本次启动仅使用配置文件中的引导配置")
        else:
            db_cfg = self._normalize(db_cfg)

        self._apply(cfg, db_cfg)

        # 写入文件时剔除数据库管理的配置项
        file_cfg = copy.deepcopy(cfg)
        if self._strip(file_cfg):
            try:
                Config()._write_config_file(file_cfg)
            except Exception as e:
                log.error(f"【Config】保存配置文件失败：{e!s}")

    def save(self, cfg):
        """
        保存配置到数据库（仅处理由数据库管理的配置项）
        """
        from app.conf.systemconfig import SystemConfig

        if not isinstance(cfg, Mapping):
            return
        current = SystemConfig().get(SystemConfigKey.ConfigOverride)
        if not isinstance(current, Mapping):
            # 缓存中没有时先重新读取数据库
            try:
                SystemConfig().init_config()
                current = SystemConfig().get(SystemConfigKey.ConfigOverride)
            except Exception as e:
                raise RuntimeError(f"数据库配置不可用：{e!s}") from e
        values = dict(current) if isinstance(current, Mapping) else {}

        for section, keys in DB_CONFIG_SCHEMA.items():
            node = cfg.get(section)
            if not isinstance(node, Mapping):
                continue
            section_values = dict(values.get(section) or {})
            for key in keys:
                if key in node:
                    section_values[key] = _to_plain(node[key])
            if section_values:
                values[section] = section_values

        if _to_plain(values) != _to_plain(current or {}):
            SystemConfig().set(SystemConfigKey.ConfigOverride, values)

    def get_file_config(self, cfg):
        """
        返回只包含 config.yaml 引导配置的副本
        """
        file_cfg = copy.deepcopy(cfg)
        if isinstance(file_cfg, MutableMapping):
            self._strip(file_cfg)
        return file_cfg

    def _seed_from_file(self, cfg):
        """
        以配置文件为准生成初始数据库配置，缺失项使用默认值
        """
        seeded = {}
        for section, keys in DB_CONFIG_SCHEMA.items():
            node = cfg.get(section)
            node = node if isinstance(node, Mapping) else {}
            defaults = DB_CONFIG_DEFAULTS.get(section, {})
            values = {}
            for key in keys:
                if key in node:
                    values[key] = _to_plain(node[key])
                elif key == "init_files":
                    values[key] = self._default_init_files()
                elif key in defaults:
                    values[key] = copy.deepcopy(defaults[key])
            if values:
                seeded[section] = values
        return seeded

    @staticmethod
    def _default_init_files():
        """
        默认的已执行 SQL 文件列表
        """
        try:
            from config import Config
            sql_dir = Config().get_script_path()
            return sorted(
                name for name in os.listdir(sql_dir) if name.endswith(".sql")
            )
        except Exception:
            return []

    @staticmethod
    def _normalize(db_cfg):
        """
        过滤不属于当前配置项的键
        """
        normalized = {}
        for section, keys in DB_CONFIG_SCHEMA.items():
            node = db_cfg.get(section)
            if not isinstance(node, Mapping):
                continue
            values = {key: _to_plain(node[key]) for key in keys if key in node}
            if values:
                normalized[section] = values
        return normalized

    @staticmethod
    def _apply(cfg, db_cfg):
        """
        把数据库配置覆盖到内存配置上
        """
        for section, values in db_cfg.items():
            keys = DB_CONFIG_SCHEMA.get(section)
            if not keys or not isinstance(values, Mapping):
                continue
            node = cfg.get(section)
            if not isinstance(node, MutableMapping):
                node = {}
                cfg[section] = node
            for key, value in values.items():
                if key in keys:
                    node[key] = copy.deepcopy(value)

    @staticmethod
    def _strip(cfg):
        """
        从配置中删除由数据库管理的配置项，返回是否有改动
        """
        changed = False
        for section, keys in DB_CONFIG_SCHEMA.items():
            node = cfg.get(section)
            if not isinstance(node, MutableMapping):
                continue
            for key in keys:
                if key in node:
                    del node[key]
                    changed = True
            if not node:
                del cfg[section]
                changed = True
        return changed
