
from app.helper.site_signin_helper import SiteSigninHelper, Verdict
from app.models.model import UserSiteConf
from app.plugins.modules._autosignin._base import _ISiteSigninHandler
from app.utils import RequestUtils, SiteUtils
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
        return bool(SiteUtils.url_equal(url, cls.site_url))

    def signin(self, site_info: UserSiteConf):
        """
        执行签到操作
        :param site_info: 站点信息, 含有站点Url、站点Cookie、UA等信息
        :return: 签到结果信息
        """
        site = site_info.name
        site_cookie = site_info.cookie
        ua = site_info.ua
        proxy = bool(site_info.proxy)

        self.info(f"{site} 开始签到")
        proxies = Config().get_proxies() if proxy else None
        html_res = RequestUtils(cookies=site_cookie, ua=ua, proxies=proxies).get_res(url=self.index_url)

        sign_status = SiteSigninHelper.check_signin_result(html_res)
        if sign_status.verdict == Verdict.SUCCESS:
            self.info(f'[{site}]今日已签到')
            return True, f'[{site}]今日已签到'

        if sign_status.verdict == Verdict.FAIL:
            self.warn(f'[{site}]签到失败: {sign_status.reason}')
            return False, f'[{site}]签到失败: {sign_status.reason}'

        # 已签到
        if self._sign_text not in html_res.text:
            self.info("今日已签到")
            return True, f'[{site}]今日已签到'

        sign_res = RequestUtils(cookies=site_cookie,
                                ua=ua,
                                proxies=proxies
                                ).get_res(url=self.sign_url)
        if not sign_res or sign_res.status_code != 200:
            self.error("签到失败, 签到接口请求失败")
            return False, f'[{site}]签到失败, 签到接口请求失败'

        # 签到成功
        if self._sign_text not in sign_res.text:
            self.info("签到成功")
            return True, f'[{site}]签到成功'
        
        return False, f'[{site}]签到执行失败'
