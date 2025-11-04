import re
import time

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from lxml import etree
from threading import Event
from typing import List, Tuple

from apscheduler.schedulers.background import BackgroundScheduler
from playwright.sync_api import Page
from urllib.parse import urljoin

from app.helper import SubmoduleHelper, SiteHelper
from app.helper.cloudflare_helper import under_challenge
from app.helper.thread_helper import ThreadHelper
from app.indexer.client.browser import PlaywrightHelper
from app.plugins import EventHandler
from app.plugins.modules._base import _IPluginModule
from app.sites import PtSiteConf
from app.sites.siteconf import SiteConf
from app.sites.site_manager import SitesManager
from app.utils import RequestUtils, SiteUtils, SchedulerUtils
from app.utils.types import EventType

from config import Config
from web.backend.wallpaper import get_bing_wallpaper

import log


@dataclass
class SignInResults:
    """
    一个数据类，用于封装签到循环的结果。
    """
    success_names: List[str] = field(default_factory=list)
    failed_info: List[str] = field(default_factory=list)  # 格式: '站点名:失败信息'
    retry_names: List[str] = field(default_factory=list)
    retry_ids: List[str] = field(default_factory=list)
    
    # 跟踪所有最终签到成功的站点ID（包括本次成功和历史已成功）
    all_signed_site_ids: List[str] = field(default_factory=list)

    def __post_init__(self):
        # 允许在创建实例时传入已签到的ID列表
        # 这里我们创建一个副本，以防修改原始列表
        self.all_signed_site_ids = list(self.all_signed_site_ids)

    def add_success(self, site_name: str, site_id: str):
        """记录一个成功的签到"""
        self.success_names.append(site_name)
        # 只有当它不在列表里时才添加（防止重复）
        if site_id not in self.all_signed_site_ids:
            self.all_signed_site_ids.append(site_id)

    def add_fail(self, site_name: str, sign_msg: str):
        """记录一个失败的签到"""
        self.failed_info.append(f'{site_name}:{sign_msg}')
    
    def add_retry(self, site_name: str, site_id: str):
        """记录一个需要重试的签到"""
        self.retry_names.append(site_name)
        self.retry_ids.append(site_id)
        
    def add_script_error(self, site_name: str):
        """记录一个签到脚本执行时的意外错误"""
        self.failed_info.append(f'{site_name}:签到时发生脚本错误')


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
            self.debug(f"加载站点签到模块：{self._site_schema}")

            # 清理缓存即今日历史
            if self._clean:
                self.delete_history(key=datetime.today().strftime('%Y-%m-%d'))

            # 运行一次
            if self._onlyonce:
                ThreadHelper().start_thread(self.sign_in, ())
                self.info("签到任务启动，立即运行一次")

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
                self._scheduler = BackgroundScheduler(executors=self.DEFAULT_EXECUTORS_CONFIG, timezone=Config().get_timezone())
                self.info(f"注册定时签到任务，执行周期：{self._cron}")
                self._cron_job = SchedulerUtils.add_job(scheduler=self._scheduler,
                                                        func=self.sign_in,
                                                        func_desc="自动签到",
                                                        cron=str(self._cron))
                # 启动任务
                if self._cron_job:
                    self._scheduler.print_jobs()
                    self._scheduler.start()
                    self.info(f"定时签到服务启动，下次执行时间：{self._cron_job.next_run_time.strftime('%Y-%m-%d %H:%M:%S')}")
                    

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
        self.info("自动签到任务开始")
        try:
            # 1. 准备工作：获取日期并清理昨日历史
            today_str, yesterday_str = self._setup_dates()
            self.delete_history(yesterday_str)

            # 2. 决定任务：计算需要签到的站点
            wait_site_ids, already_signed_ids, history_exists = self._determine_sites_to_sign(today_str)
            
            if not wait_site_ids:
                self.info(f"今日 {today_str} 无需签到/重签站点，任务结束")
                return

            # 3. 获取数据：查询站点信息
            sites_to_sign_info = self._get_sites_info(wait_site_ids)
            if not sites_to_sign_info:
                self.info("没有可签到站点信息，停止运行")
                return

            # 4. 执行签到：遍历并处理每个站点
            self.info("开始执行签到任务")
            # 传入已签到列表，以便追加本次成功的站点
            results = self._execute_sign_in_loop(sites_to_sign_info, already_signed_ids)
            
            # 5. 保存状态：将本次结果更新到历史记录
            self._save_sign_in_history(
                today_str,
                results.all_signed_site_ids,
                results.retry_ids,
                history_exists
            )
            
            # 6. 发送通知
            if self._notify:
                self._send_notification(today_str, results)

        except Exception as ex:
            log.exception(f'【自动签到】任务执行失败: {ex}')
        finally:
            self.info("站点签到任务结束")

    def _setup_dates(self) -> Tuple[str, str]:
        """获取今天和昨天的日期字符串"""
        today_dt = datetime.today()
        yesterday_dt = today_dt - timedelta(days=1)
        return today_dt.strftime('%Y-%m-%d'), yesterday_dt.strftime('%Y-%m-%d')

    def _determine_sites_to_sign(self, today_str: str) -> Tuple[List[str], List[str], bool]:
        """
        根据历史记录，决定今天要签到的站点列表。
        
        返回:
            (待签到站点ID列表, 已签到站点ID列表, 今日历史是否存在)
        """
        today_history = self.get_history(key=today_str)
        
        if not today_history:
            self.info(f"今日 {today_str} 未签到，开始签到已选站点")
            wait_sign_sites = self._config_sites
            already_sign_sites = []
            history_exists = False
        else:
            self.info(f"今日 {today_str} 已有签到记录，检查重试/未签站点")
            # 使用 .get 增加代码健壮性，防止 'sign' 或 'retry' 键不存在
            already_sign_sites = today_history.get('sign', [])
            wait_retry_sites = today_history.get('retry', [])
            
            # 使用集合(set)可以更高效、更清晰地处理列表逻辑
            config_set = set(self._config_sites)
            already_set = set(already_sign_sites)
            special_set = set(self._special_sites)
            retry_set = set(wait_retry_sites)

            # 未签站点 = 配置中 - 已签到
            no_sign_sites = config_set - already_set
            
            # 待签站点 = 重试 + 未签 + 特殊（集合会自动去重）
            wait_sign_set = retry_set | no_sign_sites | special_set
            wait_sign_sites = list(wait_sign_set)
            
            if wait_sign_sites:
                self.info(f"开始重签重试站点、特殊站点、未签站点")
            
            history_exists = True

        return wait_sign_sites, already_sign_sites, history_exists

    def _get_sites_info(self, site_ids: List[str]) -> List[PtSiteConf]:
        """
        查询待签到站点信息。
        """
        return SitesManager().get_sites(siteids=site_ids)

    def _execute_sign_in_loop(self, sites_to_sign_info: List[PtSiteConf], initial_already_signed_ids: List[str]) -> SignInResults:
        """
        遍历站点执行签到，并收集结果。
        
        **关键改进**: 在循环内部添加 try...except，
        防止单个站点的失败导致整个签到任务中断。
        """
        # 传入已签到列表，并创建一个副本，用于安全地追加
        results = SignInResults(all_signed_site_ids=list(initial_already_signed_ids))

        for site_info in sites_to_sign_info:
            site_name = site_info.name
            site_id = str(site_info.id)
            
            try:
                success, sign_msg = self.signin_site(site_info)
                
                if success:
                    results.add_success(site_name, site_id)
                    continue

                # 失败重试检查
                if self._retry_keyword and re.search(self._retry_keyword, sign_msg):
                    self.info(f"站点 {site_name} 命中重试关键词 {self._retry_keyword}")
                    results.add_retry(site_name, site_id)
                    continue
                    
                # 记录失败
                results.add_fail(site_name, sign_msg)

            except Exception as e:
                # 捕获单个站点的执行错误，记录并继续
                log.exception(f"签到站点 {site_name} (ID: {site_id}) 时发生意外错误: ", e)
                results.add_script_error(site_name)
        
        return results

    def _save_sign_in_history(self, today_str: str, all_signed_ids: List[str], retry_ids: List[str], history_exists: bool):
        """
        将签到结果存入历史。
        """
        history = {"sign": all_signed_ids, "retry": retry_ids}
        
        if not history_exists:
            self.history(key=today_str, value=history)
        else:
            self.update_history(key=today_str, value=history)
        self.info(f"今日 {today_str} 签到历史已更新")

    def _send_notification(self, today_str: str, results: SignInResults):
        """
        发送签到结果通知。
        **关键改进**: 将通知逻辑包裹在 try...except 中，
        防止通知失败（如网络问题）导致任务状态显示为失败。
        """
        try:
            # 获取下次执行时间
            next_run_time = '获取失败'
            if self._cron_job:
                next_run_time = self._cron_job.next_run_time.strftime('%Y-%m-%d %H:%M:%S')
            
            # 获取Bing壁纸
            img_url, img_title, img_link = get_bing_wallpaper(today_str)
            
            # 准备通知文本
            text_parts = [
                f"签到成功站点: {','.join(results.success_names) or '无'}",
                f"签到失败站点: {','.join(results.failed_info) or '无'}",
                f"命中重试站点: {','.join(results.retry_names) or '无'}",
                f"强制签到数量: {len(self._special_sites)}",
                f"下次签到时间: {next_run_time}"
            ]
            
            self.send_message(
                title="自动签到任务完成",
                text=" \n".join(text_parts),
                image=img_url
            )
            self.info("签到通知已发送")
        except Exception as e:
            log.exception(f"发送签到通知失败: ", e)

    def __build_class(self, url):
        for site_schema in self._site_schema:
            try:
                if site_schema.match(url):
                    return site_schema
            except Exception as e:
                log.exception(f"【自动签到】[{url}]签到插件加载失败: ", e)
        return None

    def signin_site(self, site_info:PtSiteConf) -> Tuple[bool, str]:
        """
        签到一个站点
        """
        site_module = self.__build_class(site_info.signurl)
        if site_module and hasattr(site_module, "signin"):
            try:
                return site_module().signin(site_info) or (False, "签到函数未返回明确结果")
            except Exception as e:
                log.exception(f"【自动签到】[{site_info.name}]签到失败: ", e)
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
            log.exception(f"【自动签到】[{site_name}]签到出错: ", e)
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
            log.exception("【自动签到】退出插件异常: ", e)
            print(str(e))

    def get_state(self):
        return self._enabled and self._cron
