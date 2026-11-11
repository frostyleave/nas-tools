import json
import os.path
from concurrent.futures import ThreadPoolExecutor
from threading import RLock, Semaphore, Thread

import log
from app.conf import SystemConfig
from app.helper import SubmoduleHelper
from app.plugins.event_manager import EventManager
from app.utils import ImageUtils, PathUtils, SystemUtils
from app.utils.commons import singleton
from app.utils.types import SystemConfigKey
from config import Config

# 事件处理线程池大小：单个插件处理慢不再阻塞其它插件的同类事件
EVENT_WORKERS = 4
# 线程池最多排队任务数，超过后事件消费线程等待，形成背压
EVENT_MAX_PENDING = EVENT_WORKERS * 5


@singleton
class PluginManager:
    """
    插件管理器
    """
    systemconfig = None
    eventmanager = None

    # 用户插件目录
    user_plugin_path = None
    # 内部插件目录
    system_plugin_path = None

    # 插件列表
    _plugins: dict
    # 运行态插件列表
    _running_plugins: dict
    # 配置Key
    _config_key = "plugin.%s"
    # 事件消费线程
    _thread = None
    # 事件处理线程池
    _executor = None
    # 在途/排队任务计数，用于背压
    _inflight = None
    # 每个插件的执行锁，保证同一插件的处理串行、不同插件并行
    _plugin_locks: dict
    # 开关
    _active = False

    def __init__(self):
        # config/plugins 是插件py文件目录，config/plugins/xxx是插件数据目录
        self.user_plugin_path = Config().get_user_plugin_path()
        if not os.path.exists(self.user_plugin_path):
            os.makedirs(self.user_plugin_path)
        self.system_plugin_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "modules")
        # windows 可能不存在插件目录，需要进行创建
        if not os.path.exists(self.system_plugin_path):
            os.makedirs(self.system_plugin_path)
        if os.path.exists(self.user_plugin_path):
            for plugin_file in PathUtils.get_dir_level1_files(self.user_plugin_path, [".py"]):
                SystemUtils.copy(plugin_file, self.system_plugin_path)
        self._plugins = {}
        self._running_plugins = {}
        self._plugin_locks = {}
        self.init_config()

    def init_config(self):
        self.systemconfig = SystemConfig()
        self.eventmanager = EventManager()
        # 停止已有插件
        self.stop_service()
        # 启动插件
        self.start_service()

    def __run(self):
        """
        事件消费线程：只负责分发，具体处理交给线程池
        """
        while self._active:
            event, handlers = self.eventmanager.get_event()
            if not event:
                continue
            log.info(f"处理事件：{event.event_type} - {handlers}")
            for handler in handlers:
                # 限制排队任务数，超出时阻塞消费线程，
                # 由有界事件队列负责丢弃后续事件，避免内存无限增长
                if not self._inflight.acquire(timeout=1):
                    if not self._active:
                        break
                    self._inflight.acquire()
                executor = self._executor
                if not executor:
                    # 服务正在停止
                    self._inflight.release()
                    break
                try:
                    executor.submit(self.__handle_event, handler, event)
                except RuntimeError:
                    # 线程池已关闭（服务正在停止）
                    self._inflight.release()
                    break
                except Exception:
                    self._inflight.release()
                    log.exception("‼️ 提交事件处理任务出错: ")

    def __handle_event(self, handler, event):
        """
        在线程池中执行单个事件处理函数
        """
        try:
            names = handler.__qualname__.split(".")
            self.run_plugin(names[0], names[1], event)
        except Exception:
            log.exception("‼️ 事件处理出错: ")
        finally:
            self._inflight.release()

    def start_service(self):
        """
        启动
        """
        # 加载插件
        self.__load_plugins()
        # 将事件管理器设为启动
        self._active = True
        self._inflight = Semaphore(EVENT_MAX_PENDING)
        self._executor = ThreadPoolExecutor(max_workers=EVENT_WORKERS,
                                            thread_name_prefix="plugin-event")
        self._thread = Thread(target=self.__run, name="plugin-event-queue")
        # 启动事件处理线程
        self._thread.start()

    def stop_service(self):
        """
        停止
        """
        # 将事件管理器设为停止
        self._active = False
        # 先通知插件停止其后台任务（设置退出事件、移除定时任务）
        self.__stop_plugins()
        # 等待事件处理线程退出（get_event 有 1s 超时，这里再兜底限制等待时间）
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                log.warn("【Plugin】事件处理线程未在 5 秒内退出，继续后续关闭流程")
        # 关闭线程池：取消尚未开始的任务，正在执行的任务自然结束
        executor = self._executor
        self._executor = None
        if executor:
            executor.shutdown(wait=False, cancel_futures=True)

    def __load_plugins(self):
        """
        加载所有插件
        """
        # 扫描插件目录
        plugins = SubmoduleHelper.import_submodules(
            "app.plugins.modules",
            filter_func=lambda _, obj: hasattr(obj, 'module_name')
        )
        # 排序
        plugins.sort(key=lambda x: x.module_order if hasattr(x, "module_order") else 0)
        # 用户已安装插件列表
        user_plugins = self.systemconfig.get(SystemConfigKey.UserInstalledPlugins) or []
        self._running_plugins = {}
        self._plugins = {}
        for plugin in plugins:
            module_id = plugin.__name__
            self._plugins[module_id] = plugin
            # 未安装的跳过加载
            if module_id not in user_plugins:
                continue
            # 生成实例
            self._running_plugins[module_id] = plugin()
            # 初始化配置
            self.reload_plugin(module_id)
            log.info(f"✔️  已加载插件：{plugin.__name__}")

    def run_plugin(self, pid, method, *args, **kwargs):
        """
        运行插件
        """
        if not self._running_plugins.get(pid):
            return None
        if not hasattr(self._running_plugins[pid], method):
            return
        # 同一插件的处理串行执行，避免并发触发同一实例的内部状态；
        # 不同插件之间由线程池并行，慢插件不再阻塞其它插件
        plugin_lock = self._plugin_locks.setdefault(pid, RLock())
        with plugin_lock:
            try:
                return getattr(self._running_plugins[pid], method)(*args, **kwargs)
            except Exception as err:
                log.exception(f"‼️ 执行插件 {pid}-{method} 方法异常: ")

    def reload_plugin(self, pid):
        """
        生效插件配置
        :return: 初始化失败返回 False；未运行或成功返回 None
        """
        if not pid:
            return
        if not self._running_plugins.get(pid):
            return
        if hasattr(self._running_plugins[pid], "init_config"):
            try:
                self._running_plugins[pid].init_config(self.get_plugin_config(pid))
                log.debug(f"生效插件配置：{pid}")
            except Exception as err:
                log.exception(f"‼️ 初始化插件{pid}配置出错: ")
                return False

    def __stop_plugins(self):
        """
        停止所有插件
        """
        for plugin in self._running_plugins.values():
            if hasattr(plugin, "stop_service"):
                plugin.stop_service()

    def get_plugin_config(self, pid):
        """
        获取插件配置
        """
        if not self._plugins.get(pid):
            return {}
        return self.systemconfig.get(self._config_key % pid) or {}

    def get_plugin_page(self, pid):
        """
        获取插件额外页面数据
        :return: 标题，页面内容，确定按钮响应函数
        """
        if not self._running_plugins.get(pid):
            return None, None, None
        if not hasattr(self._running_plugins[pid], "get_page"):
            return None, None, None
        return self._running_plugins[pid].get_page()

    def get_plugin_script(self, pid):
        """
        获取插件额外脚本
        """
        if not self._running_plugins.get(pid):
            return None
        if not hasattr(self._running_plugins[pid], "get_script"):
            return None
        return self._running_plugins[pid].get_script()

    def get_plugin_state(self, pid):
        """
        获取插件状态
        """
        if not self._running_plugins.get(pid):
            return None
        if not hasattr(self._running_plugins[pid], "get_state"):
            return None
        return self._running_plugins[pid].get_state()

    def format_plugin_history(self, pid, key, value):
        """
        调用插件把运行历史值转换为用户友好的文本
        :param pid: 插件ID
        :param key: 历史记录键
        :param value: 历史记录原始值（JSON 字符串会自动解析）
        """
        if isinstance(value, str) and value[:1] in ("{", "["):
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                pass
        plugin = self._running_plugins.get(pid)
        if plugin and hasattr(plugin, "format_history"):
            try:
                return plugin.format_history(key, value)
            except Exception:
                log.exception(f"‼️ 格式化插件 {pid} 运行历史出错: ")
        # 插件未运行或格式化失败时，使用通用格式化
        from app.plugins.modules._base import format_history_text
        return format_history_text(key, value)

    def save_plugin_config(self, pid, conf):
        """
        保存插件配置
        """
        if not self._plugins.get(pid):
            return False
        return self.systemconfig.set(self._config_key % pid, conf)

    @staticmethod
    def __get_plugin_color(plugin):
        """
        获取插件的主题色
        """
        if hasattr(plugin, "module_color") and plugin.module_color:
            return plugin.module_color
        if hasattr(plugin, "module_icon"):
            icon_path = os.path.join(Config().get_root_path(),
                                     "web", "static", "img", "plugins",
                                     plugin.module_icon)
            return ImageUtils.calculate_theme_color(icon_path)
        return ""

    def get_plugins_conf(self, auth_level):
        """
        获取所有插件配置
        """
        all_confs = {}
        for pid, plugin in self._running_plugins.items():
            # 基本属性
            conf = {}
            # 权限
            if hasattr(plugin, "auth_level") \
                    and plugin.auth_level > auth_level:
                continue
            # 名称
            if hasattr(plugin, "module_name"):
                conf.update({"name": plugin.module_name})
            # 描述
            if hasattr(plugin, "module_desc"):
                conf.update({"desc": plugin.module_desc})
            # 版本号
            if hasattr(plugin, "module_version"):
                conf.update({"version": plugin.module_version})
            # 图标
            if hasattr(plugin, "module_icon"):
                conf.update({"icon": plugin.module_icon})
            # ID前缀
            if hasattr(plugin, "module_config_prefix"):
                conf.update({"prefix": plugin.module_config_prefix})
            # 插件额外的页面（只取标题，避免加载页面数据造成阻塞）
            if hasattr(plugin, "get_page"):
                conf.update({"page": plugin.get_page_title()})
            # 插件额外的脚本
            if hasattr(plugin, "get_script"):
                conf.update({"script": plugin.get_script()})
            # 主题色
            conf.update({"color": self.__get_plugin_color(plugin)})
            # 配置项
            conf.update({"fields": plugin.get_fields() or {}})
            # 配置值
            conf.update({"config": self.get_plugin_config(pid)})
            # 状态
            conf.update({"state": plugin.get_state()})
            # 汇总
            all_confs[pid] = conf
        return all_confs

    def get_plugin_apps(self, auth_level):
        """
        获取所有插件
        """
        all_confs = {}
        installed_apps = self.systemconfig.get(SystemConfigKey.UserInstalledPlugins) or []
        for pid, plugin in self._plugins.items():
            # 基本属性
            conf = {}
            # 权限
            if hasattr(plugin, "auth_level") \
                    and plugin.auth_level > auth_level:
                continue
            # ID
            conf.update({"id": pid})
            # 安装状态
            if pid in installed_apps:
                conf.update({"installed": True})
            else:
                conf.update({"installed": False})
            # 名称
            if hasattr(plugin, "module_name"):
                conf.update({"name": plugin.module_name})
            # 描述
            if hasattr(plugin, "module_desc"):
                conf.update({"desc": plugin.module_desc})
            # 版本
            if hasattr(plugin, "module_version"):
                conf.update({"version": plugin.module_version})
            # 图标
            if hasattr(plugin, "module_icon"):
                conf.update({"icon": plugin.module_icon})
            # 主题色
            conf.update({"color": self.__get_plugin_color(plugin)})
            if hasattr(plugin, "module_author"):
                conf.update({"author": plugin.module_author})
            # 作者链接
            if hasattr(plugin, "author_url"):
                conf.update({"author_url": plugin.author_url})
            # 汇总
            all_confs[pid] = conf
        return all_confs

    def get_plugin_commands(self):
        """
        获取插件命令
        [{
            "cmd": "/xx",
            "event": EventType.xx,
            "desc": "xxxx",
            "data": {}
        }]
        """
        ret_commands = []
        for plugin in self._running_plugins.values():
            if hasattr(plugin, "get_command"):
                ret_commands.append(plugin.get_command())
        return ret_commands

    def run_plugin_method(self, pid, method, *args, **kwargs):
        """
        运行插件方法
        """
        if not self._running_plugins.get(pid):
            return None
        if not hasattr(self._running_plugins[pid], method):
            return None
        # 与事件处理共用插件锁，避免前端操作与事件处理并发操作同一实例
        plugin_lock = self._plugin_locks.setdefault(pid, RLock())
        with plugin_lock:
            return getattr(self._running_plugins[pid], method)(*args, **kwargs)
