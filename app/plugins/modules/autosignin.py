import re
import time
import pytz

from datetime import datetime, timedelta
from lxml import etree
from threading import Event
from typing import Tuple

from apscheduler.schedulers.background import BackgroundScheduler
from playwright.sync_api import Page
from urllib.parse import urljoin

from app.helper import SubmoduleHelper, SiteHelper
from app.helper.cloudflare_helper import under_challenge
from app.indexer.client.browser import PlaywrightHelper
from app.message import Message
from app.plugins import EventHandler
from app.plugins.modules._base import _IPluginModule
from app.sites import PtSiteConf
from app.sites.siteconf import SiteConf
from app.sites.site_manager import SitesManager
from app.utils import RequestUtils, ExceptionUtils, SiteUtils, SchedulerUtils
from app.utils.types import EventType
from config import Config

from web.backend.wallpaper import get_bing_wallpaper


class AutoSignIn(_IPluginModule):
    # 插件名称
    module_name = "站点自动签到"
    # 插件描述
    module_desc = "站点自动签到保号，支持重试。"
    # 插件图标
    module_icon = "signin.png"
    # 主题色
    module_color = "#4179F4"
    # 插件版本
    module_version = "1.0"
    # 插件作者
    module_author = "thsrite"
    # 作者主页
    author_url = "https://github.com/thsrite"
    # 插件配置项ID前缀
    module_config_prefix = "autosignin_"
    # 加载顺序
    module_order = 0
    # 可使用的用户级别
    auth_level = 2

    # 私有属性
    siteconf = None
    _scheduler = None

    # 设置开关
    _enabled = False
    # 任务执行间隔
    _site_schema = []
    _cron = None
    """
    配置需要签到的站点id
    """
    _config_sites = None
    _queue_cnt = None
    _retry_keyword = None
    _special_sites = None
    _render_sites = None
    _onlyonce = False
    _notify = False
    _clean = False
    # 退出事件
    _event = Event()

    @staticmethod
    def get_fields():
        sites = {site.get("id"): site for site in SitesManager().get_site_dict()}
        return [
            {
                'type': 'div',
                'content': [
                    # 同一行
                    [
                        {
                            'title': '开启定时签到',
                            'required': "",
                            'tooltip': '开启后会根据周期定时签到指定站点。',
                            'type': 'switch',
                            'id': 'enabled',
                        },
                        {
                            'title': '运行时通知',
                            'required': "",
                            'tooltip': '运行签到任务后会发送通知（需要打开插件消息通知）',
                            'type': 'switch',
                            'id': 'notify',
                        },
                        {
                            'title': '立即运行一次',
                            'required': "",
                            'tooltip': '打开后立即运行一次',
                            'type': 'switch',
                            'id': 'onlyonce',
                        },
                        {
                            'title': '清理缓存',
                            'required': "",
                            'tooltip': '清理本日已签到（开启后全部站点将会签到一次)',
                            'type': 'switch',
                            'id': 'clean',
                        }
                    ]
                ]
            },
            {
                'type': 'div',
                'content': [
                    # 同一行
                    [
                        {
                            'title': '签到周期',
                            'required': "",
                            'tooltip': '自动签到时间，四种配置方法：1、配置间隔，单位小时，比如23.5；2、配置固定时间，如08:00；3、配置时间范围，如08:00-09:00，表示在该时间范围内随机执行一次；4、配置5位cron表达式，如：0 */6 * * *；配置为空则不启用自动签到功能。',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'cron',
                                    'placeholder': '0 0 0 ? *',
                                }
                            ]
                        },
                        {
                            'title': '签到队列',
                            'required': "",
                            'tooltip': '同时并行签到的站点数量，默认10（根据机器性能，缩小队列数量会延长签到时间，但可以提升成功率）',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'queue_cnt',
                                    'placeholder': '10',
                                }
                            ]
                        },
                        {
                            'title': '重试关键词',
                            'required': "",
                            'tooltip': '重新签到关键词，支持正则表达式；每天首次全签，后续如果设置了重试词则只签到命中重试词的站点，否则全签。',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'retry_keyword',
                                    'placeholder': '失败|错误',
                                }
                            ]
                        },
                    ]
                ]
            },
            {
                'type': 'details',
                'summary': '签到站点',
                'tooltip': '只有选中的站点才会执行签到任务，不选则默认为全选',
                'content': [
                    # 同一行
                    [
                        {
                            'id': 'sign_sites',
                            'type': 'form-selectgroup',
                            'content': sites
                        },
                    ]
                ]
            },
            {
                'type': 'details',
                'summary': '特殊站点',
                'tooltip': '选中的站点无论是否匹配重试关键词都会进行重签（如无需要可不设置）',
                'content': [
                    # 同一行
                    [
                        {
                            'id': 'special_sites',
                            'type': 'form-selectgroup',
                            'content': sites
                        },
                    ]
                ]
            },
            {
                'type': 'details',
                'summary': '仿真签到站点',
                'tooltip': '选中的站点使用仿真签到, 不受站点配置中的仿真选项影响',
                'content': [
                    [
                        {
                            'id': 'render_sites',
                            'type': 'form-selectgroup',
                            'content': sites
                        },
                    ]
                ]
            },
        ]

    def init_config(self, config=None):
        self.siteconf = SiteConf()

        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._retry_keyword = config.get("retry_keyword")
            self._config_sites = config.get("sign_sites")
            self._special_sites = config.get("special_sites") or []
            self._render_sites = config.get("render_sites") or []
            self._notify = config.get("notify")
            self._queue_cnt = config.get("queue_cnt")
            self._onlyonce = config.get("onlyonce")
            self._clean = config.get("clean")

        # 停止现有任务
        self.stop_service()

        # 启动服务
        if self._enabled or self._onlyonce:
            # 加载模块
            self._site_schema = SubmoduleHelper.import_submodules('app.plugins.modules._autosignin',
                                                                  filter_func=lambda _, obj: hasattr(obj, 'match'))
            self.debug(f"加载站点签到：{self._site_schema}")

            # 定时服务
            self._scheduler = BackgroundScheduler(timezone=Config().get_timezone())

            # 清理缓存即今日历史
            if self._clean:
                self.delete_history(key=datetime.today().strftime('%Y-%m-%d'))

            # 运行一次
            if self._onlyonce:
                self.info("签到服务启动，立即运行一次")
                run_time = datetime.now(tz=pytz.timezone(Config().get_timezone())) + timedelta(seconds=5)
                self._scheduler.add_job(self.sign_in, 'date', run_date=run_time)

            if self._onlyonce or self._clean:
                # 关闭一次性开关|清理缓存开关
                self._clean = False
                self._onlyonce = False
                self.update_config({
                    "enabled": self._enabled,
                    "cron": self._cron,
                    "retry_keyword": self._retry_keyword,
                    "sign_sites": self._config_sites,
                    "special_sites": self._special_sites,
                    "render_sites": self._render_sites,
                    "notify": self._notify,
                    "onlyonce": self._onlyonce,
                    "queue_cnt": self._queue_cnt,
                    "clean": self._clean
                })

            # 周期运行
            if self._cron:
                self.info(f"定时签到服务启动，周期：{self._cron}")
                SchedulerUtils.start_job(scheduler=self._scheduler,
                                         func=self.sign_in,
                                         func_desc="自动签到",
                                         cron=str(self._cron))

            # 启动任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    @staticmethod
    def get_command():
        """
        定义远程控制命令
        :return: 命令关键字、事件、描述、附带数据
        """
        return {
            "cmd": "/pts",
            "event": EventType.SiteSignin,
            "desc": "站点签到",
            "data": {}
        }

    @EventHandler.register(EventType.SiteSignin)
    def sign_in(self, event=None):
        """
        自动签到
        """
        # 日期
        today = datetime.today()
        yesterday = today - timedelta(days=1)
        yesterday_str = yesterday.strftime('%Y-%m-%d')
        # 删除昨天历史
        self.delete_history(yesterday_str)

        # 查看今天有没有签到历史
        today = today.strftime('%Y-%m-%d')
        today_history = self.get_history(key=today)
        # 已签到站点
        already_sign_sites = []

        # 今日没数据
        if not today_history:
            wait_sign_sites = self._config_sites
            self.info(f"今日 {today} 未签到，开始签到已选站点")
        else:
            # 今天已签到站点
            already_sign_sites = today_history['sign']
            # 今天需要重签站点
            wait_retry_sites = today_history['retry']
            # 今日未签站点
            no_sign_sites = [site_id for site_id in self._config_sites if site_id not in already_sign_sites]
            # 待签到站点 = 需要重签+今日未签+特殊站点
            wait_sign_sites = list(set(wait_retry_sites + no_sign_sites + self._special_sites))
            if wait_sign_sites:
                self.info(f"今日 {today} 已签到，开始重签重试站点、特殊站点、未签站点")
            else:
                self.info(f"今日 {today} 已签到，无重新签到站点，本次任务结束")
                return

        # 查询待签到站点信息
        sign_sites_info = SitesManager().get_sites(siteids=wait_sign_sites)
        if not sign_sites_info:
            self.info("没有可签到站点，停止运行")
            return

        # 执行签到
        self.info("开始执行签到任务")
   
        # 签到成功
        success_msg = []
        success_sites_name = []
        # 失败｜错误
        failed_msg = []
        failed_sites_info = []
        # 命中重试词的站点
        retry_msg = []   
        retry_sites_name = []
        retry_sites_id = []

        # 遍历站点执行签到
        for site_info in sign_sites_info:
            site_name = site_info.name
            site_id = str(site_info.id)
            # 执行签到
            success, sign_msg = self.signin_site(site_info)
            # 签到成功
            if success:
                success_msg.append(sign_msg)
                success_sites_name.append(site_name)
                already_sign_sites.append(site_id)
                continue            
            # 失败重试检查
            if self._retry_keyword:
                match = re.search(self._retry_keyword, sign_msg)
                if match:
                    self.info(f"站点 {site_name} 命中重试关键词 {self._retry_keyword}")
                    retry_sites_id.append(site_id)
                    retry_msg.append(sign_msg)
                    retry_sites_name.append(site_name)
                    continue
            # 记录失败
            failed_msg.append(sign_msg)
            failed_sites_info.append(f'{site_name}:{sign_msg}')

        self.info("站点签到任务完成！")        

        # 存入历史
        history = { "sign": already_sign_sites, "retry": retry_sites_id }
        if not today_history:
            self.history(key=today, value=history)
        else:
            self.update_history(key=today,value=history)

        # 发送通知
        if self._notify:
            # 签到详细信息 登录成功、签到成功、已签到、仿真签到成功、失败--命中重试
            signin_message = success_msg + failed_msg
            if len(retry_msg) > 0:
                signin_message.append("——————命中重试—————")
                signin_message += retry_msg
            Message().send_site_signin_message(signin_message)

            next_run_time = self._scheduler.get_jobs()[0].next_run_time.strftime('%Y-%m-%d %H:%M:%S')
            img_url, img_title, img_link = get_bing_wallpaper(today)
            # 签到汇总信息
            self.send_message(title="自动签到任务完成",
                              text=f"签到成功站点: {','.join(success_sites_name)} \n"
                                   f"签到失败站点: {','.join(failed_sites_info)} \n"
                                   f"命中重试站点: {','.join(retry_sites_name)} \n"
                                   f"强制签到数量: {len(self._special_sites)} \n"
                                   f"下次签到时间: {next_run_time}",
                              image=img_url)

    def __build_class(self, url):
        for site_schema in self._site_schema:
            try:
                if site_schema.match(url):
                    return site_schema
            except Exception as e:
                ExceptionUtils.exception_traceback(e)
        return None

    def signin_site(self, site_info:PtSiteConf) -> Tuple[bool, str]:
        """
        签到一个站点
        """
        site_module = self.__build_class(site_info.signurl)
        if site_module and hasattr(site_module, "signin"):
            try:
                return site_module().signin(site_info)
            except Exception as e:
                return False, f"[{site_info.name}]签到失败：{str(e)}"
        else:
            return self.__signin_base(site_info)

    def __signin_base(self, site_info:PtSiteConf) -> Tuple[bool, str]:
        """
        通用签到处理
        :param site_info: 站点信息
        :return: 签到结果信息
        """
        if not site_info:
            return False, "站点信息获取失败"

        site_name = site_info.name
        try:
            site_url = site_info.signurl
            site_cookie = site_info.cookie
            
            if not site_url or not site_cookie:
                err_msg = "未配置 %s 的站点地址或Cookie, 无法签到" % str(site_name)
                return False, err_msg

            home_url = SiteUtils.get_base_url(site_url)
            checkin_url = site_url if "pttime" in home_url else urljoin(home_url, "attendance.php")
            
            ua = site_info.ua

            site_id = str(site_info.id)
            if site_info.chrome or (self._render_sites and site_id in self._render_sites):

                self.info(f"[{site_name}]开始仿真签到..")
               
                def _click_sign(page: Page):
                    """
                    仿真签到
                    :param page: 网页对象
                    :return: 签到结果信息
                    """
                    html_text = page.content()
                    if not html_text:
                        return False, f"[{site_name}]仿真签到失败: 获取站点源码失败"
                    
                    # 查找签到按钮
                    html = etree.HTML(html_text)

                    if re.search(r'已签|签到已得|本次签到', html_text, re.IGNORECASE):
                        self.info("%s 今日已签到" % site_name)
                        return True, f"[{site_name}]今日已签到"
                    
                    xpath_str = None
                    for xpath in self.siteconf.get_checkin_conf():
                        if html.xpath(xpath):
                            xpath_str = xpath
                            self.info(f"站点[{site_name}]签到按钮: {xpath_str}")
                            break
                    
                    if not xpath_str:
                        if SiteHelper.is_logged_in(html_text):
                            return False, f"[{site_name}]仿真签到失败: 模拟登录成功, 未找到签到按钮"
                        else:
                            return False, f"[{site_name}]仿真签到失败: 模拟登录失败, 未找到签到按钮"
                    
                    page.click(xpath_str) 
                    # 等待3秒
                    time.sleep(3)
                    # 获取页面内容
                    content = page.content()

                    # 判断是否已签到   [签到已得125, 补签卡: 0]
                    if re.search(r'已签|签到已得|本次签到', content, re.IGNORECASE):
                        return True, f"[{site_name}]签到成功"
                    
                    return False, f"[{site_name}]仿真签到异常: 无法获取签到结果"
                
                result = PlaywrightHelper().action(url=checkin_url, 
                                                 ua=ua, 
                                                 cookies=site_cookie, 
                                                 proxy=True if site_info.proxy else False,
                                                 callback=_click_sign)
                if result is None:
                    return False, f"[{site_name}]仿真签到失败: 请求网页异常"
                
                return result
            else:
                
                self.info(f"[{site_name}]开始签到: {checkin_url}")

                # 代理
                proxies = Config().get_proxies() if site_info.proxy else None
                # 访问链接
                res = RequestUtils(cookies=site_cookie, ua=ua, proxies=proxies).get_res(url=checkin_url)
                if res is None:
                    return False, f"[{site_name}]签到失败: 无法打开网站"
                
                if res.status_code in [200, 500, 403]:
                    if SiteHelper.is_logged_in(res.text):
                        return True, f"[{site_name}]签到成功"
                    if under_challenge(res.text):
                        return False, f"[{site_name}]签到失败: 站点被Cloudflare防护,请开启浏览器仿真"
                    elif res.status_code == 200:
                        return False, f"[{site_name}]签到失败: Cookie已失效"
                    else:
                        return False, f"[{site_name}]签到失败: 状态码：{res.status_code}"
                else:
                    return False, f"[{site_name}]签到失败: 状态码：{res.status_code}"
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return False, f"[{site_name}]签到出错: {str(e)}"

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._event.set()
                    self._scheduler.shutdown()
                    self._event.clear()
                self._scheduler = None
        except Exception as e:
            print(str(e))

    def get_state(self):
        return self._enabled and self._cron
