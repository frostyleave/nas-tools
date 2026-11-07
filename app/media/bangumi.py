from typing import ClassVar
from urllib.parse import urlsplit, urlunsplit

import requests
from cachetools import TTLCache, cached

from app.utils import RequestUtils
from app.utils.time_utils import TimeUtils
from app.utils.types import MediaType
from config import Config


class Bangumi:
    """
    https://bangumi.github.io/api/
    """

    _urls: ClassVar[dict] = {
        "calendar": "calendar",
        "detail": "v0/subjects/%s",
    }
    _base_url = "https://api.bgm.tv/"
    _req = RequestUtils(session=requests.Session(), proxies=Config().get_proxies())
    _page_num = 30
    # Bangumi 中表示成人内容的标签
    _r18_tags = ("R18", "18禁", "18X", "NSFW")

    def __init__(self):
        pass

    @classmethod
    @cached(cache=TTLCache(maxsize=128, ttl=3600))
    def __invoke(cls, url, **kwargs):
        req_url = cls._base_url + url
        params = {}
        if kwargs:
            params.update(kwargs)
        resp = cls._req.get_res(url=req_url, params=params)
        return resp.json() if resp else None

    def calendar(self):
        """
        获取每日放送
        """
        return self.__invoke(self._urls["calendar"], _ts=TimeUtils.now_str('%Y%m%d'))

    def detail(self, bid):
        """
        获取番剧详情
        """
        return self.__invoke(self._urls["detail"] % bid, _ts=TimeUtils.now_str('%Y%m%d'))

    @classmethod
    @cached(cache=TTLCache(maxsize=2048, ttl=24 * 3600))
    def is_r18(cls, bid):
        """
        判断 Bangumi 条目是否为 R18
        详情接口的 nsfw 字段并不可靠，改用 meta_tags/标签中的 R18 等标记
        :param bid: Bangumi 条目 ID
        """
        if not bid:
            return False
        info = cls().detail(bid=bid)
        if not info:
            return False
        tags = [str(tag) for tag in (info.get("meta_tags") or [])]
        tags += [str(tag.get("name")) for tag in (info.get("tags") or []) if isinstance(tag, dict)]
        return any(tag.upper() in cls._r18_tags for tag in tags)

    @staticmethod
    def __resize_image(url, width=600):
        """
        把 Bangumi 封面原图转为指定宽度的缩略图
        图片服务支持 /r/{width}/pic/... 形式，仅对 /pic/cover/l/ 原图路径有效
        :param url: 原始图片地址
        :param width: 目标宽度（像素）
        """
        if not url:
            return ""
        parts = urlsplit(url)
        if not parts.path.startswith("/pic/") or parts.path.startswith("/r/"):
            return url
        path = f"/r/{width}{parts.path}"
        return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))

    @staticmethod
    def __dict_item(item, weekday, media_type=MediaType.ANIME):
        """
        转换为字典
        """
        bid = item.get("id")
        detail = item.get("url")
        title = item.get("name_cn") or item.get("name")
        air_date = item.get("air_date")
        rating = item.get("rating")
        if rating:
            score = rating.get("score")
        else:
            score = 0
        images = item.get("images") or {}
        # 原图（large）通过图片服务缩放到 600px，避免 common（约 150px）过糊或 large 过大
        large_image = images.get("large")
        if large_image:
            image = Bangumi.__resize_image(large_image)
        else:
            image = images.get("common", "")
        summary = item.get("summary")
        return {
            'id': f"BG:{bid}",
            'orgid': bid,
            'title': title,
            'year': air_date[:4] if air_date else "",
            'type': str(media_type),
            'media_type': media_type.value,
            'vote': score,
            'image': image,
            'overview': summary,
            'url': detail,
            'weekday': weekday
        }

    def get_bangumi_calendar(self, page=1, week=None):
        """
        获取每日放送（每周内按评分倒序）
        """
        infos = self.calendar()
        if not infos:
            return []

        ret_list = []

        # 没有指定周数
        if not week:
            for info in infos:
                weekday = info.get("weekday", {}).get("cn")
                if not weekday:
                    continue
                weekitems = []
                items = info.get("items")
                for item in items:
                    if not item.get("images"):
                        continue
                    weekitems.append(self.__dict_item(item, weekday))
                # 转换后按评分倒序（无评分的排在最后）
                weekitems.sort(key=lambda x: x.get("vote") or 0, reverse=True)
                ret_list.append({ "weekday" : info.get("weekday"), "items" : weekitems })
            return ret_list

        start_pos = (int(page) - 1) * self._page_num
        for info in infos:
            weeknum = info.get("weekday", {}).get("id")
            if week and int(weeknum) != int(week):
                continue
            weekday = info.get("weekday", {}).get("cn")
            weekitems = []
            for item in info.get("items"):
                if not item.get("images"):
                    continue
                weekitems.append(self.__dict_item(item, weekday))
            # 转换后按评分倒序，再按页截取
            weekitems.sort(key=lambda x: x.get("vote") or 0, reverse=True)
            ret_list = weekitems[start_pos:start_pos + self._page_num]
            break

        return ret_list
