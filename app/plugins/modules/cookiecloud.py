import json

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event

from app.helper import ThreadHelper
from app.helper.dict_helper import DictHelper
from app.indexer.manager import IndexerManager
from app.plugins.modules._base import _IPluginModule
from app.sites import SitesManager
from app.utils import RequestUtils

@dataclass
class CookieCloudSyncResult:
    """CookieCloudAPI请求结果"""
    success: bool = False
    ret_msg: str = ""
    content: dict| None = None
    update_time: datetime| None = None

# 时间字符串格式
TIME_FORMART = '%Y-%m-%d %H:%M:%S'

class CookieCloud(_IPluginModule):
    # 插件名称
    module_name = "CookieCloud同步"
    # 插件描述
    module_desc = "从CookieCloud云端同步数据，自动更新已有站点Cookie。"
    # 插件图标
    module_icon = "cloud.png"
    # 主题色
    module_color = "#77B3D4"
    # 插件版本
    module_version = "1.0"
    # 插件作者
    module_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    module_config_prefix = "cookiecloud_"
    # 加载顺序
    module_order = 21
    # 可使用的用户级别
    auth_level = 2

    # 私有属性
    sites_manager = None
    index_helper = None
    request_handler = None

    # 设置开关
    _enabled = False
    # 任务执行间隔
    _cron = None
    # 参数
    _server = None
    _key = None
    _password = None
    # 选项:
    # 运行一次
    _onlyonce = False
    # 发送执行通知
    _notify = False
    # 自动导入
    _autoimport = False
    # 强制覆盖
    _forceimport = False

    # 退出事件
    _event = Event()
    # 需要忽略的Cookie
    _ignore_cookies = ['CookieAutoDeleteBrowsingDataCleanup']

    # 上次执行同步时CookieCloud数据的更新时间
    _cc_upd_time = None


    @staticmethod
    def get_fields():
        return [
            # 同一板块
            {
                'type': 'div',
                'content': [
                    # 同一行
                    [
                        {
                            'title': '服务器地址',
                            'required': "required",
                            'tooltip': '参考https://github.com/easychen/CookieCloud搭建私有CookieCloud服务器；也可使用默认的公共服务器，公共服务器不会存储任何非加密用户数据，也不会存储用户KEY、端对端加密密码，但要注意千万不要对外泄露加密信息，否则Cookie数据也会被泄露！',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'server',
                                    'placeholder': 'https://nastool.cn/cookiecloud'
                                }
                            ]

                        },
                        {
                            'title': '执行周期',
                            'required': "",
                            'tooltip': '设置自动同步时间周期，支持5位cron表达式',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'cron',
                                    'placeholder': '0 0 0 ? *',
                                }
                            ]
                        },
                    ]
                ]
            },
            {
                'type': 'div',
                'content': [
                    # 同一行
                    [
                        {
                            'title': '用户KEY',
                            'required': 'required',
                            'tooltip': '浏览器CookieCloud插件中获取，使用公共服务器时注意不要泄露该信息',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'key',
                                    'placeholder': '',
                                }
                            ]
                        },
                        {
                            'title': '端对端加密密码',
                            'required': "",
                            'tooltip': '浏览器CookieCloud插件中获取，使用公共服务器时注意不要泄露该信息',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'password',
                                    'placeholder': ''
                                }
                            ]
                        }
                    ]
                ]
            },
            {
                'type': 'div',
                'content': [
                    [
                        {
                            'title': '自动导入新站点数据',
                            'required': "",
                            'tooltip': '读取到可对接的站点cookie时自动导入系统',
                            'type': 'switch',
                            'id': 'autoimport',
                        },
                        {
                            'title': '强制使用CookieCloud数据覆盖',
                            'required': "",
                            'tooltip': '不判断系统内的站点cookie是否有效, 直接使用CookieCloud数据覆盖',
                            'type': 'switch',
                            'id': 'forceimport',
                        }
                    ],
                    [
                        {
                            'title': '运行时通知',
                            'required': "",
                            'tooltip': '运行任务后会发送通知（需要打开插件消息通知）',
                            'type': 'switch',
                            'id': 'notify',
                        },
                        {
                            'title': '立即运行一次',
                            'required': "",
                            'tooltip': '打开后立即运行一次（点击此对话框的确定按钮后即会运行，周期未设置也会运行），关闭后将仅按照定时周期运行（同时上次触发运行的任务如果在运行中也会停止）',
                            'type': 'switch',
                            'id': 'onlyonce',
                        }
                    ]
                ]
            }
        ]

    def init_config(self, config=None):

        self.sites_manager = SitesManager()
        self.index_helper = IndexerManager()
        self.dicthelper = DictHelper()

        # 读取配置
        if config:
            self.request_handler = RequestUtils(content_type="application/json")
            self.__load_config(config)

        # 停止现有任务
        self.stop_service()

        # 启动服务
        if self._enabled:
            # 运行一次
            if self._onlyonce:
                self.info(f"同步服务启动，立即运行一次")
                ThreadHelper().start_thread(self.__cookie_sync, ())
                # 关闭一次性开关
                self._onlyonce = False
                self.update_config({
                    "server": self._server,
                    "cron": self._cron,
                    "key": self._key,
                    "password": self._password,
                    "autoimport": self._autoimport,
                    "forceimport": self._forceimport,
                    "notify": self._notify,
                    "onlyonce": self._onlyonce,
                })
            # 周期运行
            if self._cron:
                self._cron_job = self.add_cron_job(self.__cookie_sync, self._cron, 'CookieCloud同步')

    def __load_config(self, config):

        self._server = config.get("server")
        self._key = config.get("key")
        self._password = config.get("password")

        if not self._server or not self._key or not self._password:
            self._enabled = False
            return

        self._cron = self.quartz_cron_compatible(config.get("cron"))
        self._autoimport = config.get("autoimport")
        self._forceimport = config.get("forceimport")
        self._notify = config.get("notify")
        self._onlyonce = config.get("onlyonce")

        plugin_id = "plugin.%s" % self.__class__.__name__
        extra = self.dicthelper.get_note("SystemConfig", plugin_id)
        if extra:
            extra_data = json.loads(extra)
            if extra_data:
                self._cc_upd_time = self.__parse_to_datetime(extra_data.get("cc_upd_time"))

        if not self._server.startswith("http"):
            self._server = "http://%s" % self._server

        if self._server.endswith("/"):
            self._server = self._server[:-1]

        # 测试
        ret = self.__download_data()
        if ret.success:
            self._enabled = True
        else:
            self._enabled = False
            self.info(ret.ret_msg)

    def get_state(self):
        return self._enabled and self._cron

    def __download_data(self) -> CookieCloudSyncResult:
        """
        从CookieCloud下载数据
        """
        if not self._server or not self._key or not self._password:
            return CookieCloudSyncResult(ret_msg="CookieCloud参数不正确")
        
        req_url = "%s/get/%s" % (self._server, self._key)
        ret = self.request_handler.post_res(url=req_url, json={"password": self._password})
        if not ret:
            return CookieCloudSyncResult(ret_msg="CookieCloud请求失败，请检查服务器地址、用户KEY及加密密码是否正确")

        if ret.status_code != 200:
            return CookieCloudSyncResult(ret_msg="同步CookieCloud失败，错误码：%s" % ret.status_code)
        
        result = ret.json()
        if not result:
            return CookieCloudSyncResult(success=True)

        update_time = self.__parse_iso_utc_to_datetime(result.get("update_time"))               
        return CookieCloudSyncResult(success=True, content=result.get("cookie_data"), update_time=update_time)

    def __cookie_sync(self):
        """
        同步站点Cookie
        """
        # 同步数据
        self.info("同步服务开始 ...")
        cloud_data = self.__download_data()

        if not cloud_data.success:
            self.error(cloud_data.ret_msg)
            self.__send_message(cloud_data.ret_msg)
            return

        contents = cloud_data.content
        if not contents:
            self.info("未从CookieCloud获取到数据")
            self.__send_message(cloud_data.ret_msg)
            return

        if self._cc_upd_time and cloud_data.update_time and self._cc_upd_time >= cloud_data.update_time:
            msg = f"CookieCloud数据时间 {cloud_data.update_time} <= {self._cc_upd_time}, 不执行更新"
            self.info(msg)
            self.__send_message(msg)
            return

        # 计数
        update_sites = []
        add_sites = []

        # 整理数据,使用domain域名的最后两级作为分组依据
        domain_groups = self.__sort_domain_cookies(contents)
        for domain, content_list in domain_groups.items():

            if self._event.is_set():
                self.info(f"同步服务停止")
                return
            
            # 只有cf的cookie过滤掉
            if not content_list or all(map(lambda c: c["name"] == "cf_clearance", content_list)):
                continue

            # 拼接Cookie
            cookie_str = self.__join_cookie(content_list)
            # 域名
            domain_url = ".".join(domain)
            # 查询站点
            site_info = self.sites_manager.get_sites_by_suffix(domain_url)
            if site_info:
                site_id = site_info.id
                if self._forceimport:
                    self.sites_manager.update_site_cookie(siteid=site_id, cookie=cookie_str)
                    update_sites.append(site_info.name)
                else:
                    if cookie_str == site_info.cookie:
                        self.info(f"[{domain_url}]站点cookie无更新")
                        continue
                    # 检查站点连通性
                    success, _, _ = self.sites_manager.test_connection(site_id=site_id)
                    if not success:
                        # 已存在且连通失败的站点更新Cookie
                        self.sites_manager.update_site_cookie(siteid=site_id, cookie=cookie_str)
                        update_sites.append(site_info.name)
                    else:
                        self.info(f"[{domain_url}]站点cookie未过期, 暂不更新")
            elif self._autoimport:
                # 查询是否在索引器范围
                indexer_base = self.index_helper.get_indexer_base(domain_url)
                if indexer_base:
                    # 支持则新增站点
                    site_pri = self.sites_manager.get_max_site_pri() + 1
                    self.sites_manager.add_site(
                        name=indexer_base.name,
                        signurl=indexer_base.domain,
                        site_pri=site_pri,
                        cookie=cookie_str,
                        rss_uses='T'
                    )
                    add_sites.append(indexer_base.name)

        if cloud_data.update_time:
            # 更新到DB
            self._cc_upd_time = cloud_data.update_time
            plugin_id = "plugin.%s" % self.__class__.__name__
            extra_data = {"cc_upd_time": self._cc_upd_time.strftime(TIME_FORMART)}
            self.dicthelper.update_note("SystemConfig", plugin_id, json.dumps(extra_data))

        # 发送消息
        lines = []
        if update_sites:
            lines.append(f"更新: {','.join(update_sites)}")
        if add_sites:
            lines.append(f"新增: {','.join(add_sites)}")
        msg = '\n'.join(lines) if lines else "同步完成，但未更新任何站点数据！"

        self.info(msg)
        # 发送消息
        self.__send_message(msg)

    def __sort_domain_cookies(self, contents):
        # 整理数据,使用domain域名的最后两级作为分组依据
        domain_groups = defaultdict(list)
        for site, cookies in contents.items():
            self.debug(f"加载[{site}]站点cookie")
            for cookie in cookies:
                domain_parts = cookie["domain"].split(".")[-2:]
                domain_key = tuple(domain_parts)
                domain_groups[domain_key].append(cookie)
        return domain_groups

    def __join_cookie(self, content_list: dict):
        cookie_str = ";".join(
                [f"{content.get('name')}={content.get('value')}"
                 for content in content_list
                 if content.get("name") and content.get("name") not in self._ignore_cookies]
            )
        return cookie_str

    def __send_message(self, msg):
        """
        发送通知
        """
        if not self._notify:
            return
        self.send_message(
            title="【CookieCloud同步任务执行完成】",
            text=msg
        )

    def stop_service(self):
        """
        退出插件
        """
        try:
            self.remove_job(self._cron_job)
        except Exception as e:
            print(str(e))

    def __parse_iso_utc_to_datetime(self, iso_str: str) -> datetime:
        """
        将 '2026-07-31T07:27:36.428Z' 解析为带 UTC 时区的 datetime 对象
        """
        if not iso_str:
            return None
        
        # 兼容毫秒位数的变化（可能不足3位），并处理末尾的 Z
        fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
        dt_naive = datetime.strptime(iso_str, fmt)
        # 加上 UTC 时区，并去掉微秒，只保留到秒
        return dt_naive.replace(tzinfo=timezone.utc, microsecond=0)

    def __parse_to_datetime(self, time_str: str) -> datetime:
        """
        将数据库中的 '2026-07-31 07:27:36' 转换回带 UTC 时区的 datetime 对象
        （假设该字符串表示的是 UTC 时间）
        """
        if not time_str:
            return None
        dt_naive = datetime.strptime(time_str, TIME_FORMART)
        return dt_naive.replace(tzinfo=timezone.utc)