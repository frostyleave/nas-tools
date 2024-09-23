import base64
import time

from lxml import etree
from typing import Tuple, Optional
from playwright.sync_api import Page


import log
from app.helper import ProgressHelper, OcrHelper, SiteHelper
from app.indexer.client.browser import PlaywrightHelper
from app.sites.siteconf import SiteConf
from app.sites.sites import Sites
from app.utils import StringUtils, RequestUtils
from app.utils.commons import singleton
from app.utils.types import ProgressKey
from app.utils.system_utils import SystemUtils


@singleton
class SiteCookie(object):
    progress = None
    sites = None
    siteconf = None
    ocrhelper = None
    captcha_code = {}

    def __init__(self):
        self.init_config()

    def init_config(self):
        self.progress = ProgressHelper()
        self.sites = Sites()
        self.siteconf = SiteConf()
        self.ocrhelper = OcrHelper()
        self.captcha_code = {}

    def set_code(self, code, value):
        """
        设置验证码的值
        """
        self.captcha_code[code] = value

    def get_code(self, code):
        """
        获取验证码的值
        """
        return self.captcha_code.get(code)

    def __get_site_cookie_ua(self,
                             url,
                             username,
                             password,
                             twostepcode=None,
                             ocrflag=False,
                             proxy=False):
        """
        获取站点cookie和ua
        :param url: 站点地址
        :param username: 用户名
        :param password: 密码
        :param twostepcode: 两步验证
        :param ocrflag: 是否开启OCR识别
        :param proxy: 是否使用内置代理
        :return: cookie、ua、message
        """
        if not url or not username or not password:
            return None, None, "参数错误"
        
        noGraphical = SystemUtils.is_windows() is False and SystemUtils.is_macos() is False
        # 无图形界面时, 强制走ocr识别
        if noGraphical:
            ocrflag = True

        def __page_handler(page: Page) -> Tuple[Optional[str], Optional[str], str]:
            if not page:
                return None, None, "访问页面失败"

            html_text = page.content()
            if not html_text:
                return None, None, "获取源码失败"
            
            # 当前Cookie未失效
            if SiteHelper.is_logged_in(html_text):
                return SiteHelper.parse_cookies(page.context.cookies()), \
                    page.evaluate("() => window.navigator.userAgent"), ""
            
            # 站点配置
            login_conf = self.siteconf.get_login_conf()
            # 查找用户名输入框
            html = etree.HTML(html_text)
            username_xpath = None
            for xpath in login_conf.get("username"):
                if html.xpath(xpath):
                    username_xpath = xpath
                    break
            if not username_xpath:
                return None, None, "未找到用户名输入框"
            # 查找密码输入框
            password_xpath = None
            for xpath in login_conf.get("password"):
                if html.xpath(xpath):
                    password_xpath = xpath
                    break
            if not password_xpath:
                return None, None, "未找到密码输入框"

            # 二步验证码
            twostep_xpath = None
            if twostepcode:
                for xpath in login_conf.get("twostep"):
                    if html.xpath(xpath):
                        twostep_xpath = xpath
                        break
            # 查找验证码输入框
            captcha_xpath = None
            for xpath in login_conf.get("captcha"):
                if html.xpath(xpath):
                    captcha_xpath = xpath
                    break
            # 查找验证码图片
            captcha_img_url = None
            if captcha_xpath:
                for xpath in login_conf.get("captcha_img"):
                    if html.xpath(xpath):
                        captcha_img_url = html.xpath(xpath)[0]
                        break
                if not captcha_img_url:
                    return None, None, "未找到验证码图片"
            # 查找登录按钮
            submit_xpath = None
            for xpath in login_conf.get("submit"):
                if html.xpath(xpath):
                    submit_xpath = xpath
                    break
            if not submit_xpath:
                return None, None, "未找到登录按钮"
            # 点击登录按钮
            try:
                # 等待登录按钮准备好
                page.wait_for_selector(submit_xpath)
                # 输入用户名
                page.fill(username_xpath, username)
                # 输入密码
                page.fill(password_xpath, password)
                # 输入二步验证码
                if twostep_xpath:
                    page.fill(twostep_xpath, twostepcode)
                # 识别验证码
                if captcha_xpath and captcha_img_url:
                    captcha_element = page.query_selector(captcha_xpath)
                    if captcha_element.is_visible():
                        # 验证码图片地址
                        code_url = self.__get_captcha_url(url, captcha_img_url)
                        # 获取当前的cookie和ua
                        cookie = SiteHelper.parse_cookies(page.context.cookies())
                        ua = page.evaluate("() => window.navigator.userAgent")
                        if ocrflag:
                            # 自动OCR识别验证码
                            captcha = self.get_captcha_text(cookie, ua, code_url)
                            if not captcha:
                                return None, None, "验证码识别失败"
                            log.info("验证码地址为：%s，识别结果：%s" % (code_url, captcha))                                
                        else:
                            # 等待用户输入
                            captcha = None
                            code_key = StringUtils.generate_random_str(5)
                            for sec in range(30, 0, -1):
                                if self.get_code(code_key):
                                    # 用户输入了
                                    captcha = self.get_code(code_key)
                                    log.info("【Sites】接收到验证码：%s" % captcha)
                                    self.progress.update(ptype=ProgressKey.SiteCookie,
                                                         text="接收到验证码：%s" % captcha)
                                    break
                                else:
                                    # 获取验证码图片base64
                                    code_bin = self.get_captcha_base64(cookie, ua, code_url)
                                    if not code_bin:
                                        return None, None, "获取验证码图片数据失败"
                                    else:
                                        code_bin = f"data:image/png;base64,{code_bin}"
                                    # 推送到前端
                                    self.progress.update(ptype=ProgressKey.SiteCookie,
                                                         text=f"{code_bin}|{code_key}")
                                    time.sleep(1)
                            if not captcha:
                                return None, None, "验证码输入超时"
                        # 输入验证码
                        captcha_element.fill(captcha)
                    else:
                        # 不可见元素不处理
                        pass
                # 点击登录按钮
                page.click(submit_xpath)
                page.wait_for_load_state("networkidle", timeout=30 * 1000)
            except Exception as e:
                log.error(f"仿真登录失败：{str(e)}")
                return None, None, f"仿真登录失败：{str(e)}"
            # 对于某二次验证码为单页面的站点，输入二次验证码
            if "verify" in page.url:
                if not twostepcode:
                    return None, None, "需要二次验证码"
                html = etree.HTML(page.content())
                for xpath in login_conf.get("twostep"):
                    if html.xpath(xpath):
                        try:
                            page.fill(xpath, twostepcode)
                            # 登录按钮 xpath 理论上相同，不再重复查找
                            page.click(submit_xpath)
                            page.wait_for_load_state("networkidle", timeout=30 * 1000)
                        except Exception as e:
                            log.error(f"二次验证码输入失败：{str(e)}")
                            return None, None, f"二次验证码输入失败：{str(e)}"
                        break
            # 登录后的源码
            html_text = page.content()
            if not html_text:
                return None, None, "获取网页源码失败"
            if SiteHelper.is_logged_in(html_text):
                return SiteHelper.parse_cookies(page.context.cookies()), \
                    page.evaluate("() => window.navigator.userAgent"), ""
            else:
                # 读取错误信息
                error_xpath = None
                for xpath in login_conf.get("error"):
                    if html.xpath(xpath):
                        error_xpath = xpath
                        break
                if not error_xpath:
                    return None, None, "登录失败"
                else:
                    error_msg = html.xpath(error_xpath)[0]
                    return None, None, error_msg
        
        return PlaywrightHelper().action(url=url,
                                         callback=__page_handler,
                                         headless=noGraphical,
                                         proxies=proxy)

    def get_captcha_text(self, cookie: str, ua: str, code_url: str):
        """
        识别验证码图片的内容
        """
        code_b64 = self.get_captcha_base64(cookie,ua,code_url)
        if not code_b64:
            return ""
        return self.ocrhelper.get_captcha_text(image_b64=code_b64)

    @staticmethod
    def __get_captcha_url(siteurl, imageurl):
        """
        获取验证码图片的URL
        """
        if not siteurl or not imageurl:
            return ""
        if imageurl.startswith("/"):
            imageurl = imageurl[1:]
        return "%s/%s" % (StringUtils.get_base_url(siteurl), imageurl)

    def update_sites_cookie_ua(self,
                               username,
                               password,
                               twostepcode=None,
                               siteid=None,
                               ocrflag=False):
        """
        更新所有站点Cookie和ua
        """
        # 获取站点列表
        sites = self.sites.get_sites(siteid=siteid)
        if siteid:
            sites = [sites]
        # 总数量
        site_num = len(sites)
        # 当前数量
        curr_num = 0
        # 返回码、返回消息
        retcode = 0
        messages = []
        # 开始进度
        self.progress.start(ProgressKey.SiteCookie)
        for site in sites:
            if not site.get("signurl") and not site.get("rssurl"):
                log.info("【Sites】%s 未设置地址，跳过" % site.get("name"))
                continue
            log.info("【Sites】开始更新 %s Cookie和User-Agent ..." % site.get("name"))
            self.progress.update(ptype=ProgressKey.SiteCookie,
                                 text="开始更新 %s Cookie和User-Agent ..." % site.get("name"))
            # 登录页面地址
            baisc_url = StringUtils.get_base_url(site.get("signurl") or site.get("rssurl"))
            site_conf = self.siteconf.get_grap_conf(url=baisc_url)
            if site_conf.get("LOGIN"):
                login_url = "%s/%s" % (baisc_url, site_conf.get("LOGIN"))
            else:
                login_url = "%s/login.php" % baisc_url
            # 获取Cookie和User-Agent
            cookie, ua, msg = self.__get_site_cookie_ua(url=login_url,
                                                        username=username,
                                                        password=password,
                                                        twostepcode=twostepcode,
                                                        ocrflag=ocrflag,
                                                        proxy=site.get("proxy"))
            # 更新进度
            curr_num += 1
            if not cookie:
                log.error("【Sites】获取 %s 信息失败：%s" % (site.get("name"), msg))
                messages.append("%s %s" % (site.get("name"), msg))
                self.progress.update(ptype=ProgressKey.SiteCookie,
                                     value=round(100 * (curr_num / site_num)),
                                     text="%s %s" % (site.get("name"), msg))
                retcode = 1
            else:
                self.sites.update_site_cookie(siteid=site.get("id"), cookie=cookie, ua=ua)
                log.info("【Sites】更新 %s 的Cookie和User-Agent成功" % site.get("name"))
                messages.append("%s %s" % (site.get("name"), msg or "更新Cookie和User-Agent成功"))
                self.progress.update(ptype=ProgressKey.SiteCookie,
                                     value=round(100 * (curr_num / site_num)),
                                     text="%s %s" % (site.get("name"), msg or "更新Cookie和User-Agent成功"))
        self.progress.end(ProgressKey.SiteCookie)
        return retcode, messages

    @staticmethod
    def get_captcha_base64(cookie: str, ua: str, image_url: str):
        """
        根据图片地址，使用浏览器获取验证码图片base64编码
        """
        if not image_url:
            return ""
        ret = RequestUtils(headers=ua,
                           cookies=cookie).get_res(image_url)
        if ret:
            return base64.b64encode(ret.content).decode()
        return ""
