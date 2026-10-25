import re

from dataclasses import dataclass
from enum import Enum

from lxml import etree
from requests import Response
from typing import List, Optional

from app.helper.cloudflare_helper import under_challenge


class Verdict(Enum):
    FAIL        = "签到失败"     # 签到失败
    SUCCESS     = "签到成功"     # 签到成功
    UNKNOWN     = "unknown"     # 无法判定


@dataclass
class CheckResult:
    verdict: Verdict
    reason: str


# 维护页通常非常短，超过这个长度就不再当维护页，避免误伤正文里的 maintenance
MAINT_MAX_LEN = 2000

# ---------- 反向：维护页特征 ----------
MAINTENANCE_PATTERNS = [
    re.compile(r"站点关闭维护"),
    re.compile(r"系统维护"),
    re.compile(r"升级维护"),
    re.compile(r"服务器维护"),
    re.compile(r"暂停访问"),
    re.compile(r"请稍后再访问"),
    re.compile(r"\bmaintenance\b", re.I),
]

# ---------- 反向：拦截页特征 ----------
BLOCK_PATTERNS = [
    re.compile(r"<title[^>]*>\s*(401|403|404|50\d)\b", re.I),
    re.compile(r"<h1>\s*403\s+forbidden\s*</h1>", re.I),
    re.compile(r"<center>\s*403\s+forbidden", re.I),
    re.compile(r"access\s+denied", re.I),
    re.compile(r"\bnginx\b.*forbidden", re.I | re.S),
]

# ---------- 正向：自己站点的“正常页面必有”特征 ----------
SITE_MARKERS = [
    re.compile(r'<meta\s+name="generator"\s+content="NexusPHP"', re.I),
    re.compile(r'id="info_block"'),
    re.compile(r'href="/torrents\.php'),
    re.compile(r'class="[^"]*\btorrents\b'),
    re.compile(r'<a[^>]+id="logout"'),
]

# ---------- 用户面板元素XPATH ----------
USER_INFO_XPATHS = [
    '//a[contains(@href, "logout")'
    ' or contains(@data-url, "logout")'
    ' or contains(@href, "mybonus") '
    ' or contains(@onclick, "logout")'
    ' or contains(@href, "usercp")]',
    '//form[contains(@action, "logout")]',
    '//div[@class="user-info-side"]'
]

class SiteSigninHelper:


    @staticmethod
    def check_signin_result(html_res: Optional[Response], sign_success_regexs:Optional[List]=None):
        """
        判断是否签到成功
        """

        if not html_res:
            return CheckResult(verdict=Verdict.FAIL, reason='无法打开网站')

        if html_res.status_code != 200:
            return CheckResult(verdict=Verdict.FAIL, reason=f'请检查站点连通性: {html_res.status_code}')

        html_text = re.sub(r"#\d+", "", re.sub(r"\d+px", "", html_res.text))
        if "login.php" in html_res.text:
            return CheckResult(verdict=Verdict.FAIL, reason='cookie失效')

        # 判断是否签到成功
        if sign_success_regexs:
            for regex in sign_success_regexs:
                if re.search(str(regex), html_text):
                    return CheckResult(verdict=Verdict.SUCCESS, reason='签到成功')
                
        if under_challenge(html_res.text):
            return CheckResult(verdict=Verdict.FAIL, reason='站点被Cloudflare防护')
            
        # 1. 维护页：短页面 + 维护关键词
        if len(html_text) < MAINT_MAX_LEN:
            for p in MAINTENANCE_PATTERNS:
                if p.search(html_text):
                    return CheckResult(Verdict.FAIL, '站点维护中')

        # 2. 拦截页
        for p in BLOCK_PATTERNS:
            if p.search(html_text):
                return CheckResult(Verdict.FAIL, '访问被拦截')

        # 3. 正常访问站点
        for p in SITE_MARKERS:
            if p.search(html_text):
                return CheckResult(Verdict.UNKNOWN, "签到失败(已登陆)")
            
        html_tree = etree.HTML(html_res.text)
        if not html_tree:
            return CheckResult(verdict=Verdict.FAIL, reason='页面解析失败')
        
        # 4. 存在明显的密码输入框，说明未登录
        if html_tree.xpath("//input[@type='password']"):
            return CheckResult(Verdict.FAIL, "签到失败(未登陆)")

        # 5. 是否存在登出和用户面板等链接
        for xpath in USER_INFO_XPATHS:
            if html_tree.xpath(xpath):
                return CheckResult(Verdict.UNKNOWN, "签到失败(已登陆)")

        return CheckResult(Verdict.UNKNOWN, "签到未成功")


    @staticmethod
    def sign_in_result(html_text, regexs):
        """
        判断是否签到成功
        """
        if not regexs:
            return False
        
        html_text = re.sub(r"#\d+", "", re.sub(r"\d+px", "", html_text))
        for regex in regexs:
            if re.search(str(regex), html_text):
                return True
            
        return False