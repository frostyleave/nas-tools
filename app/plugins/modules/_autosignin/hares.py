import json

from app.helper.site_signin_helper import SiteSigninHelper, Verdict
from app.models.model import UserSiteConf
from app.plugins.modules._autosignin._base import _ISiteSigninHandler
from app.utils import RequestUtils, SiteUtils
from config import Config


class Hares(_ISiteSigninHandler):
    """
    白兔签到
    """
    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = "club.hares.top"

    # 已签到
    _sign_text = '已签到'

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
                                ).get_res(url="https://club.hares.top")
        
        sign_status = SiteSigninHelper.check_signin_result(html_res)
        if sign_status.verdict == Verdict.SUCCESS:
            self.info(f'[{site}]今日已签到')
            return True, f'[{site}]今日已签到'

        if sign_status.verdict == Verdict.FAIL:
            self.warn(f'[{site}]签到失败: {sign_status.reason}')
            return False, f'[{site}]签到失败: {sign_status.reason}'
        
        # if self._sign_text in html_res.text:
        #     self.info(f"今日已签到")
        #     return True, f'[{site}]今日已签到'

        headers = {
            'Accept': 'application/json',
            "User-Agent": ua
        }
        sign_res = RequestUtils(cookies=site_cookie,
                                headers=headers,
                                proxies=proxy
                                ).get_res(url="https://club.hares.top/attendance.php?action=sign")
        if not sign_res or sign_res.status_code != 200:
            self.error("签到失败，签到接口请求失败")
            return False, f'[{site}]签到失败，签到接口请求失败'

        # {"code":1,"msg":"您今天已经签到过了"}
        # {"code":0,"msg":"签到成功"}
        sign_dict = json.loads(sign_res.text)
        if sign_dict['code'] == 0:
            self.info("签到成功")
            return True, f'[{site}]签到成功'
        else:
            self.info("今日已签到")
            return True, f'[{site}]今日已签到'
