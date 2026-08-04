"""
下载器配置管理模块

负责下载器配置、下载设置的加载、查询和管理。
从 Downloader 类中提取，遵循单一职责原则。
"""

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import log

from app.conf import ModuleConf
from app.conf import SystemConfig
from app.helper import DbHelper
from app.utils import SystemUtils, NumberUtils, StringUtils
from app.utils.constants import Constants
from app.utils.types import DownloaderType, SystemConfigKey

# 标签隔离
PT_TAG = "NASTOOL"


@dataclass
class DownloaderConfItem:
    """单个下载器配置"""
    id: int
    name: str
    type: str
    enabled: bool
    transfer: bool
    only_nastool: bool
    match_path: bool
    rmt_mode: str = ""
    rmt_mode_name: str = ""
    config: dict = field(default_factory=dict)
    download_dir: list = field(default_factory=list)


class DownloadConfig:
    """
    下载器配置管理

    负责从数据库加载下载器配置和下载设置，并提供查询接口。
    由 Downloader 持有，不单独作为单例。
    """

    def __init__(self):
        self._dbhelper: Optional[DbHelper] = None
        self._downloader_confs: dict[str, DownloaderConfItem] = {}
        self._download_settings: dict[str, dict] = {}
        self._monitor_downloader_ids: list[int] = []
        self._download_order: Optional[str] = None
        self._DownloaderEnum: Optional[Enum] = None

    def reload(self) -> None:
        """重新加载所有配置（从数据库）"""
        if self._dbhelper is None:
            self._dbhelper = DbHelper()

        # 清空
        self._downloader_confs = {}
        self._monitor_downloader_ids = []

        # 加载下载器配置
        for downloader_conf in self._dbhelper.get_downloaders():
            if not downloader_conf:
                continue
            did = downloader_conf.ID
            name = downloader_conf.NAME
            enabled = downloader_conf.ENABLED
            transfer = downloader_conf.TRANSFER
            only_nastool = downloader_conf.ONLY_NASTOOL
            match_path = downloader_conf.MATCH_PATH
            rmt_mode = downloader_conf.RMT_MODE
            rmt_mode_name = ModuleConf.RMT_MODES.get(rmt_mode).value if rmt_mode else ""

            if transfer:
                log_content = ""
                if only_nastool:
                    log_content += "标签隔离, "
                if match_path:
                    log_content += "目录隔离, "
                log.info(f"【Downloader】读取到监控下载器: {name}, {log_content}转移方式: {rmt_mode_name}")
                if enabled:
                    self._monitor_downloader_ids.append(did)
                else:
                    log.info(f"【Downloader】下载器: {name} 不进行监控: 下载器未启用")

            config = json.loads(downloader_conf.CONFIG)
            dtype = downloader_conf.TYPE

            self._downloader_confs[str(did)] = DownloaderConfItem(
                id=did,
                name=name,
                type=dtype,
                enabled=enabled,
                transfer=transfer,
                only_nastool=only_nastool,
                match_path=match_path,
                rmt_mode=rmt_mode,
                rmt_mode_name=rmt_mode_name,
                config=config,
                download_dir=json.loads(downloader_conf.DOWNLOAD_DIR),
            )

        # 生成下载器ID-名称枚举
        self._DownloaderEnum = Enum('DownloaderIdName',
                                    {did: conf.name for did, conf in self._downloader_confs.items()})

        # 加载下载设置
        self._load_download_settings()

    def _load_download_settings(self) -> None:
        """加载下载设置（含预设）"""
        from config import Config
        pt = Config().get_config('pt')
        if pt:
            self._download_order = pt.get("download_order")

        self._download_settings = {
            "-1": {
                "id": -1,
                "name": "预设",
                "category": '',
                "tags": PT_TAG,
                "is_paused": 0,
                "upload_limit": 0,
                "download_limit": 0,
                "ratio_limit": 0,
                "seeding_time_limit": 0,
                "downloader": "",
                "downloader_name": "",
                "downloader_type": ""
            }
        }

        download_settings = self._dbhelper.get_download_setting()
        for download_setting in download_settings:
            downloader_id = download_setting.DOWNLOADER
            download_conf = self._downloader_confs.get(str(downloader_id))
            if download_conf:
                downloader_name = download_conf.name
                downloader_type = download_conf.type
            else:
                downloader_name = ""
                downloader_type = ""
                downloader_id = ""

            self._download_settings[str(download_setting.ID)] = {
                "id": download_setting.ID,
                "name": download_setting.NAME,
                "category": download_setting.CATEGORY,
                "tags": download_setting.TAGS,
                "is_paused": download_setting.IS_PAUSED,
                "upload_limit": download_setting.UPLOAD_LIMIT,
                "download_limit": download_setting.DOWNLOAD_LIMIT,
                "ratio_limit": download_setting.RATIO_LIMIT / 100,
                "seeding_time_limit": download_setting.SEEDING_TIME_LIMIT,
                "downloader": downloader_id,
                "downloader_name": downloader_name,
                "downloader_type": downloader_type
            }

    # ---- 下载器配置查询 ----

    @property
    def downloader_confs(self) -> dict[str, DownloaderConfItem]:
        return self._downloader_confs

    def get_downloader_conf(self, did=None):
        """获取下载器配置，did 为 None 时返回全部"""
        if not did:
            return self._downloader_confs
        return self._downloader_confs.get(str(did))

    def get_downloader_conf_simple(self) -> dict:
        """获取简化下载器配置"""
        ret_dict = {}
        for conf in self._downloader_confs.values():
            ret_dict[str(conf.id)] = {
                "id": conf.id,
                "name": conf.name,
                "type": conf.type,
                "enabled": conf.enabled,
            }
        return ret_dict

    @property
    def downloader_enum(self) -> Optional[Enum]:
        """下载器ID-名称枚举"""
        return self._DownloaderEnum

    # ---- 默认下载器/设置 ----

    @property
    def default_downloader_id(self) -> str:
        """获取默认下载器ID"""
        default_id = SystemConfig().get(SystemConfigKey.DefaultDownloader)
        if not default_id or not self.get_downloader_conf(default_id):
            default_id = ""
        return default_id

    @property
    def default_download_setting_id(self) -> str:
        """获取默认下载设置ID"""
        default_id = SystemConfig().get(SystemConfigKey.DefaultDownloadSetting) or "-1"
        if not self._download_settings.get(default_id):
            default_id = "-1"
        return default_id

    # ---- 监控下载器 ----

    @property
    def monitor_downloader_ids(self) -> list[int]:
        return self._monitor_downloader_ids

    # ---- 下载设置查询 ----

    def get_download_setting(self, sid=None):
        """获取下载设置，sid 为 None 时返回全部"""
        # 更新预设的默认下载器
        preset_downloader_conf = self.get_downloader_conf(self.default_downloader_id)
        if preset_downloader_conf:
            self._download_settings["-1"]["downloader"] = self.default_downloader_id
            self._download_settings["-1"]["downloader_name"] = preset_downloader_conf.name
            self._download_settings["-1"]["downloader_type"] = preset_downloader_conf.type

        if not sid:
            return self._download_settings
        return self._download_settings.get(str(sid)) or {}

    def get_download_attr(self, download_setting) -> dict:
        """获取下载设置属性（带回退逻辑）"""
        # 不使用下载设置
        if download_setting == "-2":
            return {}

        if download_setting:
            download_attr = self.get_download_setting(download_setting)
            if download_attr:
                return download_attr

        # 回退到默认下载设置
        return self.get_download_setting(self.default_download_setting_id)

    # ---- 下载目录查询 ----

    def get_download_dirs(self, setting=None) -> list:
        """返回下载器中设置的保存目录"""
        if not setting:
            setting = self.default_download_setting_id
        download_setting = self.get_download_setting(sid=setting)
        downloader_conf = self.get_downloader_conf(download_setting.get("downloader"))
        if not downloader_conf:
            return []
        save_path_list = [attr.get("save_path") for attr in downloader_conf.download_dir
                          if attr.get("save_path")]
        save_path_list.sort()
        return list(set(save_path_list))

    def get_download_visit_dirs(self) -> list:
        """返回所有下载器中设置的访问目录"""
        download_dirs = []
        for conf in self._downloader_confs.values():
            download_dirs += conf.download_dir
        visit_path_list = [attr.get("container_path") or attr.get("save_path")
                           for attr in download_dirs if attr.get("save_path")]
        visit_path_list.sort()
        return list(set(visit_path_list))

    @property
    def download_order(self) -> Optional[str]:
        """获取下载排序设置"""
        return self._download_order

    # ---- 静态工具方法 ----

    @staticmethod
    def get_download_dir_info(media, downloaddir) -> dict:
        """根据媒体信息读取一个下载目录的信息"""
        if media:
            for attr in downloaddir or []:
                if not attr:
                    continue
                if attr.get("type") and attr.get("type") != media.type.value:
                    continue
                if attr.get("category") and attr.get("category") != media.category:
                    continue
                if not attr.get("save_path") and not attr.get("label"):
                    continue
                if (attr.get("container_path") or attr.get("save_path")) \
                        and os.path.exists(attr.get("container_path") or attr.get("save_path")) \
                        and media.size \
                        and SystemUtils.get_free_space(
                    attr.get("container_path") or attr.get("save_path")
                ) < NumberUtils.get_size_gb(
                    StringUtils.num_filesize(media.size)
                ):
                    continue
                return {
                    "path": attr.get("save_path"),
                    "category": attr.get("label")
                }
        return {"path": None, "category": None}

    @staticmethod
    def get_client_type(type_name) -> Optional[DownloaderType]:
        """根据名称返回下载器类型"""
        if not type_name:
            return None
        for dict_type in DownloaderType:
            if dict_type.name == type_name or dict_type.value == type_name:
                return dict_type
