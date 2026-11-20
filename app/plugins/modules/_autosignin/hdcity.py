from app.helper.site_signin_helper import SiteSigninHelper, Verdict
from app.models.model import UserSiteConf
from app.plugins.modules._autosignin._base import _ISiteSigninHandler
from app.utils import RequestUtils, SiteUtils
from config import Config


class HDCity(_ISiteSigninHandler):
    """
    城市签到
    """
    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = "hdcity.city"

    # 签到成功
    _success_text = '本次签到获得魅力'
    # 重复签到
    _repeat_text = '已签到'

    @classmethod
    def match(cls, url):
        """
        根据站点Url判断是否匹配当前站点签到类，大部分情况使用默认实现即可
        :param url: 站点Url
        :return: 是否匹配，如匹配则会调用该类的signin方法
        """
        return bool(SiteUtils.url_equal(url, cls.site_url))

    def signin(self, site_info: UserSiteConf):
        """
        执行签到操作
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 签到结果信息
        """
        site = site_info.name
        site_cookie = site_info.cookie
        ua = site_info.ua
        proxy = Config().get_proxies() if site_info.proxy else None

        # 获取页面html
        html_res = RequestUtils(cookies=site_cookie,
                                ua=ua,
                                proxies=proxy
                                ).get_res(url="https://hdcity.city/sign")
        
        sign_status = SiteSigninHelper.check_signin_result(html_res, [self._success_text, self._repeat_text])
        if sign_status.verdict == Verdict.SUCCESS:
            self.info(f'[{site}]今日已签到')
            return True, f'[{site}]今日已签到'

        self.warn(f'[{site}]签到失败: {sign_status.reason}')
        return False, f'[{site}]签到失败: {sign_status.reason}'
