import json
import threading
from typing import ClassVar

import log
from app.helper import DictHelper
from app.utils import JsonUtils
from app.utils.commons import singleton
from app.utils.types import SystemConfigKey


@singleton
class SystemConfig:
    # 系统设置
    systemconfig: ClassVar[dict] = {}
    # 保护缓存与写库的一致性
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self):
        self.dicthelper = DictHelper()
        self.init_config()

    def init_config(self):
        """
        缓存系统设置（整体重建，已删除的键不会残留）
        """
        config = {}
        for item in self.dicthelper.list("SystemConfig"):
            if not item:
                continue
            if self.__is_obj(item.VALUE):
                config[item.KEY] = JsonUtils.loads(item.VALUE, default=item.VALUE)
            else:
                config[item.KEY] = item.VALUE
        # 整体替换引用，避免读者在清空与填充之间读到空配置
        with self._lock:
            self.systemconfig = config

    @staticmethod
    def __is_obj(obj):
        if isinstance(obj, (list, dict)):
            return True
        else:
            return str(obj).startswith("{") or str(obj).startswith("[")

    def set(self, key: [SystemConfigKey, str], value):
        """
        设置系统设置：先写库，成功后再更新内存
        """
        if isinstance(key, SystemConfigKey):
            key = key.value
        db_value = value
        if self.__is_obj(value):
            db_value = json.dumps(value) if value is not None else ''
        with self._lock:
            if self.dicthelper.set("SystemConfig", key, db_value) is False:
                log.error(f"【Config】保存系统设置 {key} 失败")
                return False
            self.systemconfig[key] = value
        return True

    def get(self, key: [SystemConfigKey, str] = None):
        """
        获取系统设置
        """
        if not key:
            return self.systemconfig
        if isinstance(key, SystemConfigKey):
            key = key.value
        return self.systemconfig.get(key)
