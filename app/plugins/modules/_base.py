import json
import os
from abc import ABCMeta, abstractmethod
from threading import Event

from apscheduler.job import Job
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import log
from app.conf import SystemConfig
from app.core.jobcenter import JobCenter
from app.helper import DbHelper
from app.message import MessageService
from config import Config

# 插件运行历史中媒体状态/类型的中文说明
_HISTORY_MEDIA_STATES = {
    "NEW": "已加入同步列表",
    "RSS": "已添加订阅",
    "DOWNLOADED": "已下载",
}
_HISTORY_MEDIA_TYPES = {
    "MOV": "电影",
    "TV": "剧集",
    "ANIME": "动漫",
}


def _history_value_text(value) -> str:
    """嵌套的字典/列表压缩成单行 JSON，避免直接显示 Python repr"""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _history_text_of_media(value: dict) -> str:
    """把媒体类历史记录（豆瓣/TMDB 同步、榜单、随机订阅等）转换为友好文案"""
    name = value.get("name") or value.get("title") or "未知媒体"
    year = value.get("year")
    parts = [f"{name}（{year}）" if year else str(name)]
    media_type = value.get("type") or value.get("media_type")
    if media_type:
        parts.append(_HISTORY_MEDIA_TYPES.get(str(media_type).upper(), str(media_type)))
    state = value.get("state")
    if state:
        parts.append(_HISTORY_MEDIA_STATES.get(str(state).upper(), str(state)))
    rating = value.get("rating")
    if rating:
        try:
            parts.append(f"评分 {float(rating):.1f}")
        except (TypeError, ValueError):
            pass
    return " · ".join(parts)


def format_history_text(key, value) -> str:
    """
    把插件 history() 写入的值转换为用户友好的文本。

    子类如有特殊数据结构，可重写 _IPluginModule.format_history() 自行处理，
    其余情况统一走这里的通用转换。
    """
    if value is None or value == "":
        return "无数据"

    if isinstance(value, dict):
        # 媒体类：{name, year, type, state, rating, add_time}
        if "state" in value and ("name" in value or "title" in value):
            return _history_text_of_media(value)
        # 签到历史：{"sign": [...], "retry": [...]}
        if "sign" in value or "retry" in value:
            signed = value.get("sign") or []
            retry = value.get("retry") or []
            text = f"已签到 {len(signed)} 个站点"
            if signed:
                text += "：" + "、".join(str(item) for item in signed)
            if retry:
                text += f"\n待重试 {len(retry)} 个站点：" + "、".join(str(item) for item in retry)
            return text
        # 转种记录：{to_download, to_download_id, delete_source}
        if "to_download" in value:
            source = "已删除源任务" if value.get("delete_source") else "保留源任务"
            return (f"已转移至下载器 {value.get('to_download')}，"
                    f"任务ID：{value.get('to_download_id')}（{source}）")
        # IYUU 镜像站：{site, image, time}
        if "site" in value and "image" in value:
            return f"镜像站：{value.get('site')} → {value.get('image')}"
        # IYUU 绑定结果：{success, ...}
        if "success" in value:
            return "绑定成功" if value.get("success") else "绑定失败"
        # 域名 -> IP（TMDB IP 优选）
        if value and all(isinstance(item, str) for item in value.values()):
            return "\n".join(f"{domain} → {ip}" for domain, ip in value.items())
        # 其它键值对逐行展示
        return "\n".join(f"{k}：{_history_value_text(v)}"
                         for k, v in value.items()
                         if v not in (None, "", [], {}))

    if isinstance(value, list):
        if not value:
            return "无数据"
        # IYUU 辅种历史：[{downloader, torrents: [...]}]
        if all(isinstance(item, dict) and "downloader" in item for item in value):
            lines = []
            for item in value:
                torrents = item.get("torrents") or []
                if not isinstance(torrents, list):
                    torrents = [torrents]
                lines.append(f"下载器 {item.get('downloader')}：{len(torrents)} 个辅种")
            return "\n".join(lines)
        if all(isinstance(item, str) for item in value):
            return "、".join(value)
        return json.dumps(value, ensure_ascii=False, indent=2)

    return str(value)


class _IPluginModule(metaclass=ABCMeta):
    """
    插件模块基类，通过继续该类实现插件功能
    除内置属性外，还有以下方法可以扩展或调用：
    - get_fields() 获取配置字典，用于生成插件配置表单
    - get_state() 获取插件启用状态，用于展示运行状态
    - stop_service() 停止插件服务
    - get_config() 获取配置信息
    - update_config() 更新配置信息
    - init_config() 生效配置信息
    - info(msg) 记录INFO日志
    - warn(msg) 记录插件WARN日志
    - error(msg) 记录插件ERROR日志
    - debug(msg) 记录插件DEBUG日志
    - get_page() 插件额外页面数据，在插件配置页面左下解按钮展示
    - get_script() 插件额外脚本（Javascript），将会写入插件页面，可在插件元素中绑定使用，，XX_PluginInit为初始化函数
    - send_message() 发送消息
    - get_data_path() 获取插件数据保存目录
    - history() 记录插件运行数据，key需要唯一，value为对象
    - get_history() 获取插件运行数据
    - update_history() 更新插件运行数据
    - delete_history() 删除插件运行数据
    - format_history() 把运行历史转换为用户友好的展示文本，可重写
    - get_command() 获取插件命令，使用消息机制通过远程控制

    """
    
    # 执行器最大线程
    MAX_EXECUTORS_WORKERS = 3

    # 插件名称
    module_name = ""
    # 插件描述
    module_desc = ""
    # 插件图标
    module_icon = ""
    # 主题色
    module_color = ""
    # 插件版本
    module_version = "1.0"
    # 插件作者
    module_author = ""
    # 作者主页
    author_url = ""
    # 插件配置项ID前缀：为了避免各插件配置表单相冲突，配置表单元素ID自动在前面加上此前缀
    module_config_prefix = "plugin_"
    # 显示顺序
    module_order = 0
    # 可使用的用户级别
    auth_level = 1
    # 插件额外页面的标题（列表展示用，避免为了取标题而加载整个页面）
    module_page_title = ""
    # 后台任务退出事件
    _event = Event()
    # 定时任务
    _cron_job : Job | None = None

    def set_stop_event(self):
        """通知插件后台任务退出"""
        self._event.set()

    def reset_stop_event(self):
        """
        启动新的后台任务前换用新的退出事件
        旧线程启动时捕获的是旧事件对象，仍保持置位状态，不会被重新清除
        """
        self._event = Event()

    @staticmethod
    @abstractmethod
    def get_fields():
        """
        获取配置字典，用于生成表单
        """
        pass

    @abstractmethod
    def get_state(self):
        """
        获取插件启用状态
        """
        pass

    @abstractmethod
    def init_config(self, config: dict = None):
        """
        生效配置信息
        :param config: 配置信息字典
        """
        pass

    @abstractmethod
    def stop_service(self):
        """
        停止插件
        """
        pass

    @staticmethod
    def __is_obj(obj):
        if isinstance(obj, (list, dict)):
            return True
        else:
            return str(obj).startswith("{") or str(obj).startswith("[")

    def update_config(self, config: dict, plugin_id=None):
        """
        更新配置信息
        :param config: 配置信息字典
        :param plugin_id: 插件ID
        """
        if not plugin_id:
            plugin_id = self.__class__.__name__
        return SystemConfig().set(f"plugin.{plugin_id}", config)

    def get_config(self, plugin_id=None):
        """
        获取配置信息
        :param plugin_id: 插件ID
        """
        if not plugin_id:
            plugin_id = self.__class__.__name__
        return SystemConfig().get(f"plugin.{plugin_id}")

    def get_data_path(self, plugin_id=None):
        """
        获取插件数据保存目录
        """
        if not plugin_id:
            plugin_id = self.__class__.__name__
        data_path = os.path.join(Config().get_user_plugin_path(), plugin_id)
        if not os.path.exists(data_path):
            os.makedirs(data_path)
        return data_path

    def history(self, key, value):
        """
        记录插件运行数据，key需要唯一，value为对象是自动转换为str，
        """
        if not key or not value:
            return
        if self.__is_obj(value):
            value = json.dumps(value)
        DbHelper().insert_plugin_history(plugin_id=self.__class__.__name__,
                                         key=key,
                                         value=value)

    def get_history(self, key=None, plugin_id=None):
        """
        获取插件运行数据，只返回一条，自动识别转换为对象
        """
        if not plugin_id:
            plugin_id = self.__class__.__name__

        historys = DbHelper().get_plugin_history(plugin_id=plugin_id, key=key)
        if not isinstance(historys, list):
            historys = [historys]
        result = []
        for history in historys:
            if not history:
                continue
            if self.__is_obj(history.VALUE):
                try:
                    if key:
                        return json.loads(history.VALUE)
                    else:
                        result.append(json.loads(history.VALUE))
                    continue
                except Exception as err:
                    print(str(err))
            if key:
                return history.VALUE
            else:
                result.append(history.VALUE)
        return None if key else result

    def update_history(self, key, value, plugin_id=None):
        """
        更新插件运行数据
        """
        if not key or not value:
            return False
        if not plugin_id:
            plugin_id = self.__class__.__name__
        if self.__is_obj(value):
            value = json.dumps(value)
        return DbHelper().update_plugin_history(plugin_id=plugin_id, key=key, value=value)

    def delete_history(self, key, plugin_id=None):
        """
        删除插件运行数据
        """
        if not key:
            return False
        if not plugin_id:
            plugin_id = self.__class__.__name__
        return DbHelper().delete_plugin_history(plugin_id=plugin_id, key=key)

    def format_history(self, key, value):
        """
        将单条运行历史转换为用户友好的文本，插件可重写以提供更贴切的展示
        :param key: 历史记录键
        :param value: 历史记录值（已自动解析 JSON）
        """
        return format_history_text(key, value)

    @staticmethod
    def send_message(title, text=None, image=None):
        """
        发送消息
        """
        return MessageService().send_plugin_message(title=title,
                                             text=text,
                                             image=image)

    def info(self, msg):
        """
        记录INFO日志
        :param msg: 日志信息
        """
        log.info(f"【Plugin】{self.module_name} - {msg}")

    def warn(self, msg):
        """
        记录插件WARN日志
        :param msg: 日志信息
        """
        log.warn(f"【Plugin】{self.module_name} - {msg}")

    def error(self, msg):
        """
        记录插件ERROR日志
        :param msg: 日志信息
        """
        log.error(f"【Plugin】{self.module_name} - {msg}")

    def debug(self, msg):
        """
        记录插件Debug日志
        :param msg: 日志信息
        """
        log.debug(f"【Plugin】{self.module_name} - {msg}")
    
    def quartz_cron_compatible(self, cron_expr):
        """
        quartz_cron表达式兼容
        :param msg: 日志信息
        """
        if not cron_expr:
            return cron_expr
        
        values = cron_expr.split()
        if len(values) != 6:
            return cron_expr
        # 移除最左边的“秒”部分
        return ' '.join(values[1:]).replace('?', '*')
    
    def get_page_title(self) -> str:
        """
        获取插件额外页面的标题

        用于插件列表展示；不要在列表接口中调用 get_page()，否则会触发页面数据加载（可能包含网络请求）。
        """
        return self.module_page_title

    def get_scheduler(self) -> BackgroundScheduler:
        """获取任务管理器"""
        return JobCenter().get_plugin_scheduler()
    
    def add_cron_job(self, func, cron:str, func_name:str) -> Job | None:
        """
        向任务管理器添加定时任务
        :param scheduler: 任务管理器
        :param func: 任务函数
        :param func_name: 任务名称
        :param cron: cron表达式
        :param start: 是否立即启动
        """
        if cron:
            try:
                cron_job = self.get_scheduler().add_job(func, CronTrigger.from_crontab(cron), name=func_name)
                if cron_job:
                    self.info(f"{func_name}服务启动，周期: {cron}, 下次执行时间: {cron_job.next_run_time.strftime('%Y-%m-%d %H:%M:%S')}")
                return cron_job
            except Exception as err:
                log.exception(f'【Plugin】定时任务{func_name}注册失败: ')
        return None

    def add_interval_job(self, func, func_name: str, **interval) -> Job | None:
        """
        向任务管理器添加 interval 定时任务
        :param func: 任务函数
        :param func_name: 任务名称
        :param interval: interval 参数，如 hours=1、seconds=30
        """
        if not interval:
            return None
        try:
            job = self.get_scheduler().add_job(func, 'interval', name=func_name, **interval)
            if job:
                self.info(f"{func_name}服务启动，周期: {job.trigger}, "
                          f"下次执行时间: {job.next_run_time.strftime('%Y-%m-%d %H:%M:%S')}")
            return job
        except Exception as err:
            log.exception(f'【Plugin】定时任务{func_name}注册失败: ')
        return None

    def remove_job(self, job_info:Job | None):
        """
        移除任务管理器中的定时任务
        """
        if job_info:
            try:
                self.get_scheduler().remove_job(job_info.id)
            except JobLookupError:
                # 任务已随配置重载被统一清理
                pass
            except Exception as err:
                log.exception(f'【Plugin】定时任务{job_info.id}移除失败: ')
