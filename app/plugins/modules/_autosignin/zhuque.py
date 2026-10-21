import json

from lxml import etree

from app.plugins.modules._autosignin._base import _ISiteSigninHandler
from app.models.model import UserSiteConf
from app.utils import SiteUtils, RequestUtils
from config import Config


class ZhuQue(_ISiteSigninHandler):
    """
    ZHUQUE签到
    """
    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = "zhuque.in"

    @classmethod
    def match(cls, url):
        """
        根据站点Url判断是否匹配当前站点签到类，大部分情况使用默认实现即可
        :param url: 站点Url
        :return: 是否匹配，如匹配则会调用该类的signin方法
        """
        return True if SiteUtils.url_equal(url, cls.site_url) else False

    def signin(self, site_info: UserSiteConf):
        """
        执行签到操作
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 签到结果信息
        """
        site_name = site_info.name
        site_cookie = site_info.cookie
        ua = site_info.ua if site_info.ua else Config().get_ua()
        proxy = Config().get_proxies() if site_info.proxy else None

        # 获取页面html
        html_res = RequestUtils(cookies=site_cookie,
                                ua=ua,
                                proxies=proxy
                                ).get_res(url="https://zhuque.in/gaming/genshin/character/list")
        
        if not html_res or html_res.status_code != 200:
            self.error(f"访问抽卡页失败，请检查站点连通性")
            return False, f'[{site_name}]访问抽卡页败，请检查站点连通性'

        if "login.php" in html_res.text:
            self.error(f"访问抽卡页失败，cookie失效")
            return False, f'[{site_name}]访问抽卡页失败，cookie失效'

        html = etree.HTML(html_res.text)
        if not html:
            return False, f'[{site_name}]抽卡页解析失败'

        # 释放技能
        x_csrf_token = html.xpath("//meta[@name='x-csrf-token']/@content")[0]
        if not x_csrf_token:
            return False, f'[{site_name}]无法获取x-csrf-token'
        
        msg = '失败'

        headers = {
            "x-csrf-token": str(x_csrf_token),
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": ua
        }
        data = { "all": 1, "resetModal": "true" }
        skill_res = RequestUtils(cookies=site_cookie,
                                 headers=headers,
                                 proxies=proxy
                                 ).post_res(url="https://zhuque.in/api/gaming/fireGenshinCharacterMagic", json=data)
        if not skill_res or skill_res.status_code != 200:
            self.error(f"签到失败：释放技能失败")
        else:
            skill_dict = json.loads(skill_res.text)
            if skill_dict['status'] == 200:
                bonus = int(skill_dict['data']['bonus'])
                msg = f'成功，获得{bonus}魔力'

        self.info(f'[{site_name}]签到{msg}')
        return True, f'[{site_name}]签到{msg}'
