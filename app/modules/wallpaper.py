import datetime

from cachetools import TTLCache, cached

import log
from app.media import MediaService
from app.utils import RequestUtils
from config import Config


def get_login_wallpaper(time_now=None):
    """
    获取登录页壁纸信息
    """
    if not time_now:
        time_now = datetime.datetime.now()
    wallpaper = Config().get_config('app').get('wallpaper')
    tmdbkey = Config().get_config('app').get('rmt_tmdbkey')
    if (not wallpaper or wallpaper == "themoviedb") and tmdbkey:
        # 每小时更新
        curr_time = datetime.datetime.strftime(time_now, '%Y%m%d%H')
        return __get_themoviedb_wallpaper(curr_time)
    else:
        # 每天更新
        today = datetime.datetime.strftime(time_now, '%Y%m%d')
        return get_bing_wallpaper(today)


@cached(cache=TTLCache(maxsize=512, ttl=3600))
def __get_themoviedb_wallpaper(cache_tag):
    """
    获取TheMovieDb的随机背景图
    cache_tag 缓存标记, 相同时会命中缓存
    """
    return MediaService().get_random_discover_backdrop()


@cached(cache=TTLCache(maxsize=512, ttl=3600))
def get_bing_wallpaper(today):
    """
    获取Bing每日壁纸
    """
    url = f"https://cn.bing.com/HPImageArchive.aspx?format=js&idx=0&n=1&today={today}"
    try:
        resp = RequestUtils(timeout=5).get_res(url)
    except Exception as err:
        log.exception('【System】获取Bing每日壁纸失败: ')
        return ""
    if resp and resp.status_code == 200:
        try:
            result = resp.json()
            if isinstance(result, dict):
                for image in result.get('images') or []:
                    img_url = f"https://cn.bing.com{image.get('url')}" if 'url' in image else ''
                    img_title = image.get('title', '')
                    img_link = image.get('copyrightlink', '')
                    return img_url, img_title, img_link
        except Exception as err:
            print(str(err))
    return '', '', ''
