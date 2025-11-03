
from app.indexer.client.browser import PlaywrightHelper
from app.plugins.modules._autosignin._base import _ISiteSigninHandler
from app.sites import PtSiteConf
from app.utils import SiteUtils, RequestUtils
from config import Config


class BTSchool(_ISiteSigninHandler):
    """
    学校签到
    """
    # 匹配的站点Url, 每一个实现类都需要设置为自己的站点Url
    site_url = "pt.btschool.club"
    index_url = 'https://pt.btschool.club/index.php'
    sign_url = 'https://pt.btschool.club/index.php?action=addbonu'

    # 已签到
    _sign_text = '每日签到'

    @classmethod
    def match(cls, url):
        """
        根据站点Url判断是否匹配当前站点签到类, 大部分情况使用默认实现即可
        :param url: 站点Url
        :return: 是否匹配, 如匹配则会调用该类的signin方法
        """
        return True if SiteUtils.url_equal(url, cls.site_url) else False

    def signin(self, site_info: PtSiteConf):
        """
        执行签到操作
        :param site_info: 站点信息, 含有站点Url、站点Cookie、UA等信息
        :return: 签到结果信息
        """
        site = site_info.name
        site_cookie = site_info.cookie
        ua = site_info.ua
        proxy = True if site_info.proxy else False

        # 首页
        if site_info.chrome:
            self.info(f"{site} 开始仿真签到")
            chrome = PlaywrightHelper()
            html_text = chrome.get_page_source(url=self.index_url,
                                                    ua=ua,
                                                    cookies=site_cookie,
                                                    proxy=proxy)
            # 仿真访问失败
            if html_text:
                self.error(f"访问页面[{self.index_url}]失败")
                return False, f'访问页面[{self.index_url}]失败'

            # 已签到
            if self._sign_text not in html_text:
                self.info("今日已签到")
                return True, f'【{site}】今日已签到'

            # 仿真签到
            html_text = chrome.get_page_source(url=self.sign_url,
                                               ua=ua,
                                               cookies=site_cookie,
                                               proxy=proxy)
            if not html_text:
                return False, f'访问页面[{self.sign_url}]失败'

            # 签到成功
            if self._sign_text not in html_text:
                self.info("签到成功")
                return True, f'【{site}】签到成功'
        else:
            self.info(f"{site} 开始签到")
            proxies = Config().get_proxies() if proxy else None
            html_res = RequestUtils(cookies=site_cookie, ua=ua, proxies=proxies).get_res(url=self.index_url)
            if not html_res:
                self.error("签到失败, 无法打开网站")
                return False, f'【{site}】签到失败, 无法打开网站'
            
            if html_res.status_code != 200:
                self.error(f"签到失败, 请检查站点连通性: {html_res.status_code}")
                return False, f'【{site}】签到失败, 请检查站点连通性'

            if "login.php" in html_res.text:
                self.error("签到失败, cookie失效")
                return False, f'【{site}】签到失败, cookie失效'

            # 已签到
            if self._sign_text not in html_res.text:
                self.info("今日已签到")
                return True, f'【{site}】今日已签到'

            sign_res = RequestUtils(cookies=site_cookie,
                                    ua=ua,
                                    proxies=proxies
                                    ).get_res(url=self.sign_url)
            if not sign_res or sign_res.status_code != 200:
                self.error("签到失败, 签到接口请求失败")
                return False, f'【{site}】签到失败, 签到接口请求失败'

            # 签到成功
            if self._sign_text not in sign_res.text:
                self.info("签到成功")
                return True, f'【{site}】签到成功'
            
            return False, f'【{site}】签到执行失败'
