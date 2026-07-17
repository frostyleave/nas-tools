import re
import requests

from lxml import etree
from urllib.parse import urljoin

from app.plugins.modules._autosignin._base import _ISiteSigninHandler
from app.sites import PtSiteConf
from app.utils import SiteUtils, RequestUtils

from config import Config


class FreeFarm(_ISiteSigninHandler):
    """
    自由农场
    """
    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = "https://pt.0ff.cc/"

    # 签到页地址
    _attendance_url = "https://pt.0ff.cc/attendance.php"

    # 已签到
    _sign_regex = ['签到已得']

    # 签到成功，待补充
    _success_regex = ['今日签到排名']

    @classmethod
    def match(cls, url):
        """
        根据站点Url判断是否匹配当前站点签到类，大部分情况使用默认实现即可
        :param url: 站点Url
        :return: 是否匹配，如匹配则会调用该类的signin方法
        """
        return True if SiteUtils.url_equal(url, cls.site_url) else False

    def signin(self, site_info: PtSiteConf):
        """
        执行签到操作
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 签到结果信息
        """
        site_name = site_info.name
        site_cookie = site_info.cookie
        site_ua = site_info.ua if site_info.ua else Config().get_ua()

        session = requests.Session()
        session.headers.update({
            "User-Agent": site_ua, 
            "Referer": self._attendance_url
        })
        session.cookies.update(RequestUtils.cookie_parse(site_cookie))

        # 访问签到页面
        index_res = session.get(self._attendance_url)

        # 判断今日是否已签到       
        if not index_res or index_res.status_code != 200:
            self.error(f"签到失败，请检查站点连通性")
            return False, f'【{site_name}】签到失败，请检查站点连通性'

        if "login.php" in index_res.text:
            self.error(f"签到失败，cookie失效")
            return False, f'【{site_name}】签到失败，cookie失效'

        sign_status = self.sign_in_result(index_res.text, self._sign_regex)
        if sign_status:
            self.info(f"今日已签到")
            return True, f'【{site_name}】今日已签到'

        # 解析html
        html = etree.HTML(index_res.text)
        if not html:
            return False, f'【{site_name}】签到失败(主页面解析失败)'
        
        js_src = html.xpath("//script[contains(@src, 'slide_check_')]/@src")
        if not js_src:
            return False, f'【{site_name}】签到失败(js文件名解析失败)'
        
        js_url = js_src[0]
        # 如果 js_url 是相对路径，补全域名
        if js_url.startswith('/'):
            js_url = urljoin(self.site_url, js_url)

        # 2. 下载 JS 文件
        js_res = session.get(url=js_url)
        js_res.raise_for_status()
        js_content = js_res.text
        
        # 3. 用正则提取 requestUrl 的值
        match = re.search(r'requestUrl\s*=\s*"([^"]+)"', js_content)
        if not match:
            return False, f'【{site_name}】签到失败("未找到 requestUrl)'
        
        sign_url = match.group(1)
        print("提取到的 requestUrl:", sign_url)

        # 请求从 JS 中提取的 set_access_token 接口
        resp = session.get(sign_url, allow_redirects=False)   # 禁止跟随重定向，便于观察

        print("Status:", resp.status_code)
        print("Body (empty):", resp.text)          # 空是正常的
        print("Set-Cookie:", resp.headers.get("Set-Cookie"))
        print("All cookies now:", session.cookies.get_dict())

        # 再次请求 attendance.php 检查签到结果
        sign_res = session.get(self._attendance_url)
        sign_status = self.sign_in_result(sign_res.text, self._success_regex)
        
        if sign_status:
            self.info(f"签到成功")
            return True, f'【{site_name}】签到成功'

        self.error(f"签到失败，签到接口返回 {sign_res.text}")
        return False, f'【{site_name}】签到失败'