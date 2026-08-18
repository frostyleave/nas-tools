import random
import log

from time import sleep

from app.media.doubanapi import DoubanScaper
from app.media.meta import MetaInfo
from app.utils import StringUtils
from app.utils import RequestUtils


import log


class DouBanUser:

    cookie = None
    scaper = None

    def __init__(self):
        self.init_config()

    def init_config(self):
        self.scaper = DoubanScaper()
        try:
            res = RequestUtils(timeout=5).get_res("https://www.douban.com/")
            if res:
                self.cookie = StringUtils.str_from_cookiejar(res.cookies)
        except Exception as err:
            log.exception(f"【Douban】获取cookie失败: ")

    def get_latest_douban_interests(self, dtype, userid, wait=False):
        """
        获取最新动态中的想看/在看/看过数据
        """
        if wait:
            time = round(random.uniform(1, 5), 1)
            log.info("【Douban】随机休眠: %s 秒" % time)
            sleep(time)
        if dtype == "do":
            web_infos = self.scaper.do_in_interests(userid=userid)
        elif dtype == "collect":
            web_infos = self.scaper.collect_in_interests(userid=userid)
        elif dtype == "wish":
            web_infos = self.scaper.wish_in_interests(userid=userid)
        else:
            web_infos = self.scaper.interests(userid=userid)
        if not web_infos:
            return []
        for web_info in web_infos:
            web_info["id"] = web_info.get("url").split("/")[-2]
        return web_infos

    def get_douban_wish(self, dtype, userid, start, wait=False):
        """
        获取豆瓣想看列表数据
        """
        if wait:
            time = round(random.uniform(1, 5), 1)
            log.info("【Douban】随机休眠: %s 秒" % time)
            sleep(time)
        if dtype == "do":
            web_infos = self.scaper.do(cookie=self.cookie, userid=userid, start=start)
        elif dtype == "collect":
            web_infos = self.scaper.collect(cookie=self.cookie, userid=userid, start=start)
        else:
            web_infos = self.scaper.wish(cookie=self.cookie, userid=userid, start=start)
        if not web_infos:
            return []
        for web_info in web_infos:
            web_info["id"] = web_info.get("url").split("/")[-2]
        return web_infos

    def get_user_info(self, userid, wait=False):
        if wait:
            time = round(random.uniform(1, 5), 1)
            log.info("【Douban】随机休眠: %s 秒" % time)
            sleep(time)
        return self.scaper.user(cookie=self.cookie, userid=userid)