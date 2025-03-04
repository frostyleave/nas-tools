from functools import lru_cache
from urllib.parse import quote

import cn2an
import re
import log

from app.media import Media, Bangumi, DouBan
from app.media.meta import MetaInfo
from app.media.meta._base import MetaBase
from app.utils import StringUtils, ExceptionUtils, SystemUtils, RequestUtils, IpUtils, MediaUtils
from app.utils.types import MediaType
from config import Config
from version import APP_VERSION

DB_SEASON_SUFFIX = '[第]+[0-9一二三四五六七八九十\-\s]+季'


class WebUtils:

    @staticmethod
    def get_location(ip):
        """
        根据IP址查询真实地址
        """
        if not IpUtils.is_ipv4(ip):
            return ""
        url = 'https://sp0.baidu.com/8aQDcjqpAAV3otqbppnN2DJv/api.php?co=&resource_id=6006&t=1529895387942&ie=utf8' \
              '&oe=gbk&cb=op_aladdin_callback&format=json&tn=baidu&' \
              'cb=jQuery110203920624944751099_1529894588086&_=1529894588088&query=%s' % ip
        try:
            r = RequestUtils().get_res(url)
            if r:
                r.encoding = 'gbk'
                html = r.text
                c1 = html.split('location":"')[1]
                c2 = c1.split('","')[0]
                return c2
            else:
                return ""
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return ""

    @staticmethod
    def get_current_version():
        """
        获取当前版本号
        """
        commit_id = SystemUtils.execute('git rev-parse HEAD')
        if commit_id and len(commit_id) > 7:
            commit_id = commit_id[:7]
        return "%s %s" % (APP_VERSION, commit_id)

    @staticmethod
    def get_latest_version():
        """
        获取最新版本号
        """
        try:
            releases_update_only = Config().get_config("app").get("releases_update_only")
            version_res = RequestUtils(proxies=Config().get_proxies()).get_res(
                f"https://nastool.cn/{quote(WebUtils.get_current_version())}/update")
            if version_res:
                ver_json = version_res.json()
                version = ver_json.get("latest")
                link = ver_json.get("link")
                if version and releases_update_only:
                    version = version.split()[0]
                return version, link
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
        return None, None

    @staticmethod
    def get_mediainfo_from_id(mediaid, mtype=None, wait=False):
        """
        根据TMDB/豆瓣/BANGUMI获取媒体信息
        """
        if not mediaid:
            return None
        media_info = None
        if str(mediaid).startswith("DB:"):
            # 豆瓣
            doubanid = mediaid[3:].split(',')[0]
            douban_info = DouBan().get_douban_detail(doubanid=doubanid, mtype=mtype, wait=wait)
            if not douban_info:
                return None
            
            title = douban_info.get("title")
            original_title = douban_info.get("original_title")
            year = douban_info.get("year")

            if not mtype and douban_info.get("subtype"):
                subtype = douban_info.get("subtype")
                mtype = MediaType.TV if subtype == 'tv' else MediaType.MOVIE

            begin_season = None
            # 剧集类型，去掉标题中的季信息
            if mtype == MediaType.TV and re.search(r'%s' % DB_SEASON_SUFFIX, title, flags=re.IGNORECASE):
                title, begin_season = MediaUtils.resolve_douban_season_tag(title)

            tmdb_info = Media().query_tmdb_info(title, mtype, year, begin_season, append_to_response="all")
            if not tmdb_info:
                log.warn("【Douban】根据名称[%s]查询tmdb数据失败" % title)
                if original_title:
                    log.info("【Douban】尝试根据别名[%s]查询tmdb数据" % original_title)
                    tmdb_info = Media().query_tmdb_info(original_title, mtype, year, begin_season, append_to_response="all")
                    if not tmdb_info:
                        log.info("【Douban】尝试根据别名[%s]查询tmdb数据失败" % original_title)
                    else:
                        log.info("【Douban】根据别名[%s]查询tmdb数据成功！" % original_title)

            if not tmdb_info:
                return None

            media_info = MetaInfo(title=tmdb_info.get("title") if mtype == MediaType.MOVIE else tmdb_info.get("name"))
            media_info.set_tmdb_info(tmdb_info)
            media_info.begin_season = begin_season
            media_info.douban_id = doubanid

            WebUtils.adjust_tv_search_name(mtype, title, media_info)

            return media_info
        if str(mediaid).startswith("BG:"):
            # BANGUMI
            bangumiid = str(mediaid)[3:]
            info = Bangumi().detail(bid=bangumiid)
            if not info:
                return None
            title = info.get("name")
            title_cn = info.get("name_cn")
            year = info.get("date")[:4] if info.get("date") else ""
            media_info = Media().get_media_info(title=f"{title} {year}",
                                                mtype=MediaType.ANIME,
                                                append_to_response="all")
            if not media_info or not media_info.tmdb_info:
                media_info = Media().get_media_info(title=f"{title_cn} {year}",
                                                    mtype=MediaType.ANIME,
                                                    append_to_response="all")
        else:
            # TMDB
            info = Media().get_tmdb_info(tmdbid=mediaid, mtype=mtype, append_to_response="all")
            if not info:
                return None
            title = info.get("title") if mtype == MediaType.MOVIE else info.get("name")
            media_info = MetaInfo(title)
            media_info.set_tmdb_info(info)
        
        # 豆瓣信息补全
        if media_info and info:
            imdb_id = ''
            if hasattr(info, 'imdb_id') and info.imdb_id:
                imdb_id = info.imdb_id
            elif hasattr(info, 'external_ids') and info.external_ids and hasattr(info.external_ids, 'imdb_id') and  info.external_ids.imdb_id:
                imdb_id = info.external_ids.imdb_id
            WebUtils.fill_douban_info(title, mtype, media_info, imdb_id)

        return media_info


    @staticmethod
    def fill_douban_info(title:str, mtype:MediaType, media_info:MetaBase, imdb_id:str = None):
        """
        补全豆瓣信息: 豆瓣id, 剧集名称
        """
        doubanapi = DouBan()                   
        media_info.douban_id = ''
        if not imdb_id:
            return
        try:
            douban_info = doubanapi.search_douban_info_by_imdbid(imdb_id)
            if not douban_info:
                return
            doubanid = douban_info.get("id")
            if not doubanid:
                return

            if not str(doubanid).isdigit():
                doubanid = re.search(r"\d+", doubanid).group(0)
            media_info.douban_id = doubanid

            # 电影类型，不再进行扩展搜索
            if mtype == MediaType.MOVIE:
                return

            douban_name = title
            imdb_name = douban_info.get("title")
            if StringUtils.contain_chinese(imdb_name):
                douban_name = imdb_name
            else:
                alt_title = douban_info.get("alt_title")
                if alt_title:
                    douban_name = alt_title.split(" ", 1)[0]

            # 豆瓣资源名和tmdb资源名不一致时调整
            WebUtils.adjust_tv_search_name(mtype, douban_name, media_info)
            # 剧集类型时，如果只有1季，也不在进行扩展搜索
            info = media_info.tmdb_info
            if info and len(info.seasons) <= 1:
                return
            # 计算季数大于0的季
            season_cnt = len(list(filter(lambda t: t.season_number > 0, info.seasons)))
            if season_cnt == 1:
                return
            
            # 解析季名称
            season_names = []
            for season_info in info.seasons:
                if season_info.season_number == 0:
                    continue
                season_name = WebUtils.convert_numbers_in_string(season_info.name)
                season_names.append(season_name)
            
            douban_ids = []

            # 根据名称查询豆瓣剧集信息
            start = 0
            page_size = 30
            while True:
                search_res = doubanapi.tv_search(douban_name, start, page_size)
                for res_item in search_res:
                    if not doubanapi.is_target_type_match(res_item.get("target_type"), mtype):
                        continue
                    target_info = res_item.get("target")
                    if not target_info:
                        continue
                    item_title = target_info.get("title")
                    if not item_title:
                        continue
                    if item_title == title or item_title == douban_name:
                        douban_ids.append(target_info.get("id"))
                        continue
                    # 移除名称
                    left_part = item_title.replace(douban_name, "", 1).strip()
                    if left_part in season_names:
                        douban_ids.append(target_info.get("id"))
                if len(search_res) == page_size:
                    start += page_size
                else:
                    break
            
            media_info.douban_id = ",".join(douban_ids)

        except Exception as err:
            ExceptionUtils.exception_traceback(err)            


    @staticmethod
    def int_to_chinese(num: int):
        """将 0~9999 范围内的整数转换为中文数字（简单实现）。"""
        digits = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九']
        if num == 0:
            return digits[0]
        
        num_str = str(num)
        length = len(num_str)
        result = ""
        for i, ch in enumerate(num_str):
            digit = int(ch)
            unit = length - i - 1  # 当前位数对应的单位（十、百、千）
            if digit != 0:
                result += digits[digit]
                if unit == 1:
                    result += "十"
                elif unit == 2:
                    result += "百"
                elif unit == 3:
                    result += "千"
            else:
                # 避免连续“零”
                if not result.endswith("零") and i != length - 1:
                    result += "零"
        # 去除末尾可能多余的“零”
        result = result.rstrip("零")
        # 特殊处理：例如 10、11 转换结果为“一十…”，改为“十…”
        if result.startswith("一十"):
            result = result[1:]
        return result

    @staticmethod
    def convert_numbers_in_string(s: str):
        """
        使用正则表达式查找字符串中所有数字（包含其两侧空白字符），
        并替换为转换后的中文数字，同时去掉两侧的空格。
        """
        # 匹配：任意数量空格 + 一段数字 + 任意数量空格
        pattern = re.compile(r'\s*(\d+)\s*')
        
        def repl(match):
            num = int(match.group(1))
            return WebUtils.int_to_chinese(num)
        
        return pattern.sub(repl, s)

    @staticmethod
    def adjust_tv_search_name(mtype:MediaType, douban_name:str, media_info:MetaBase):
        if not douban_name or MediaType.TV != mtype or media_info.cn_name in douban_name:
            return
        media_info.cn_name = douban_name
        media_info.title = douban_name
        media_info.rev_string = douban_name
        media_info.org_string = douban_name    

    @staticmethod
    def search_media_infos(keyword, source=None, page=1):
        """
        搜索TMDB或豆瓣词条
        :param: keyword 关键字
        :param: source 渠道 tmdb/douban
        :param: season 季号
        :param: episode 集号
        """
        if not keyword:
            return []
        mtype, key_word, season_num, episode_num, _, content = StringUtils.get_keyword_from_string(keyword)
        if source == "tmdb":
            use_douban_titles = False
        elif source == "douban":
            use_douban_titles = True
        else:
            use_douban_titles = Config().get_config("laboratory").get("use_douban_titles")
            
        if use_douban_titles:
            medias = DouBan().search_douban_medias(keyword=key_word,
                                                   mtype=mtype,
                                                   season=season_num,
                                                   episode=episode_num,
                                                   page=page)
        else:
            meta_info = MetaInfo(title=content)
            tmdbinfos = Media().get_tmdb_infos(title=meta_info.get_name(),
                                               year=meta_info.year,
                                               mtype=mtype,
                                               page=page)
            medias = []
            for info in tmdbinfos:
                tmp_info = MetaInfo(title=keyword)
                tmp_info.set_tmdb_info(info)
                if meta_info.type != MediaType.MOVIE and tmp_info.type == MediaType.MOVIE:
                    continue
                if tmp_info.begin_season:
                    tmp_info.title = "%s 第%s季" % (tmp_info.title, cn2an.an2cn(meta_info.begin_season, mode='low'))
                if tmp_info.begin_episode:
                    tmp_info.title = "%s 第%s集" % (tmp_info.title, meta_info.begin_episode)
                medias.append(tmp_info)
        return medias

    @staticmethod
    def get_page_range(current_page, total_page):
        """
        计算分页范围
        """
        if total_page <= 5:
            StartPage = 1
            EndPage = total_page
        else:
            if current_page <= 3:
                StartPage = 1
                EndPage = 5
            elif current_page >= total_page - 2:
                StartPage = total_page - 4
                EndPage = total_page
            else:
                StartPage = current_page - 2
                if total_page > current_page + 2:
                    EndPage = current_page + 2
                else:
                    EndPage = total_page
        return range(StartPage, EndPage + 1)

    @staticmethod
    @lru_cache(maxsize=128)
    def request_cache(url):
        """
        带缓存的请求
        """
        ret = RequestUtils().get_res(url)
        if ret:
            return ret.content
        return None
