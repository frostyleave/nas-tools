import re
from decimal import Decimal
from typing import ClassVar

import log
from app.media.meta import aniparse_utils
from app.media.meta._base import MetaBase
from app.media.meta.customization import CustomizationMatcher
from app.utils import StringUtils
from app.utils import zhconv_compat as zhconv
from app.utils.constants import Constants
from app.utils.release_groups import ReleaseGroupsMatcher
from app.utils.types import MediaType


class MetaAnime(MetaBase):
    """
    识别动漫
    """
    _anime_no_words: ClassVar[list[str]] = ['CHS&CHT', 'MP4', 'GB MP4', 'WEB-DL']
    _name_nostring_re = r"S\d{2}\s*-\s*S\d{2}|S\d{2}|\s+S\d{1,2}|EP?\d{2,4}\s*-\s*EP?\d{2,4}|EP?\d{2,4}|\s+EP?\d{1,4}"

    def __init__(self, title, subtitle=None, fileflag=False):
        super().__init__(title, subtitle, fileflag)
        if not title:
            return
        # 调用第三方模块识别动漫
        try:
            original_title = title
            # 字幕组预识别
            aniparse_info_origin = aniparse_utils.parse(original_title)
            release_group = aniparse_utils.get_release_group(aniparse_info_origin) or ''
            # 标题信息预处理
            title = self.__prepare_title(title)
            aniparse_info = aniparse_utils.parse(title)
            if aniparse_info:
                # 字幕组
                release_group = aniparse_utils.get_release_group(aniparse_info) or release_group
                # 名称
                name = aniparse_utils.get_title(aniparse_info)
                if not name:
                    aniparse_info = aniparse_utils.parse(
                        StringUtils.remve_redundant_symbol(title.replace(release_group, '')))
                    name = aniparse_utils.get_title(aniparse_info)
                if name and name.find("/") != -1:
                    name_arr = name.split("/")
                    name = next(filter(lambda x: StringUtils.contain_chinese(x), name_arr), name_arr[-1].strip())

                if not name or name in self._anime_no_words or (len(name) < 5 and not StringUtils.contain_chinese(name)):
                    aniparse_info = aniparse_utils.parse("[ANIME]" + title)
                    name = aniparse_utils.get_title(aniparse_info)
                if not name or name in self._anime_no_words or (len(name) < 5 and not StringUtils.contain_chinese(name)):
                    name_match = re.search(r'\[(.+?)]', title.replace(release_group, ''))
                    if name_match and name_match.group(1):
                        name = name_match.group(1).strip()
                # 拆份中英文名称
                if name:
                    lastword_type = ""
                    for word in name.split():
                        if not word:
                            continue
                        word = word.removesuffix(']')
                        if word.isdigit():
                            if lastword_type == "cn":
                                self.cn_name = "{} {}".format(self.cn_name or "", word)
                            elif lastword_type == "en":
                                self.en_name = "{} {}".format(self.en_name or "", word)
                        elif StringUtils.contain_chinese(word):
                            self.cn_name = "{} {}".format(self.cn_name or "", word)
                            lastword_type = "cn"
                        else:
                            self.en_name = "{} {}".format(self.en_name or "", word)
                            lastword_type = "en"
                if self.cn_name:
                    _, self.cn_name, _, _, _, _ = StringUtils.get_keyword_from_string(self.cn_name)
                    if self.cn_name:
                        self.cn_name = re.sub(rf'{self._name_nostring_re}', '', self.cn_name,
                                              flags=re.IGNORECASE).strip()
                        if StringUtils.contain_traditional_chinese(self.cn_name):
                            self.cn_name = zhconv.convert(self.cn_name, "zh-hans")
                if self.en_name:
                    self.en_name = re.sub(rf'{self._name_nostring_re}', '', self.en_name,
                                          flags=re.IGNORECASE).strip().title()
                    self._name = StringUtils.str_title(self.en_name)
                # 年份
                year = aniparse_utils.get_year(aniparse_info)
                if str(year).isdigit():
                    self.year = str(year)
                # 季号
                begin_season, end_season = aniparse_utils.get_season_range(aniparse_info)
                if begin_season:
                    self.begin_season = int(begin_season)
                    if end_season and int(end_season) != self.begin_season:
                        self.end_season = int(end_season)
                        self.total_seasons = (self.end_season - self.begin_season) + 1
                    else:
                        self.total_seasons = 1
                    self.type = MediaType.TV
                # 集号
                begin_episode, end_episode = aniparse_utils.get_episode_range(aniparse_info)
                if begin_episode:
                    try:
                        self.begin_episode = int(Decimal(str(begin_episode)))
                        if end_episode and (end_episode_int := int(Decimal(str(end_episode)))) != self.begin_episode:
                            self.end_episode = end_episode_int
                            self.total_episodes = (self.end_episode - self.begin_episode) + 1
                        else:
                            self.total_episodes = 1
                    except Exception as err:
                        self.begin_episode = None
                        self.end_episode = None
                        log.exception('【Meta】动漫剧集范围解析出错: ')

                    self.type = MediaType.TV
                # 类型
                if not self.type:
                    anime_type = aniparse_utils.get_type(aniparse_info)
                    if anime_type and str(anime_type).upper() == "TV":
                        self.type = MediaType.TV
                    else:
                        self.type = MediaType.MOVIE
                # 分辨率
                self.resource_pix = aniparse_utils.get_resolution(aniparse_info)
                # 制作组/字幕组
                self.resource_team = ReleaseGroupsMatcher().match(title=original_title) or release_group
                # 自定义占位符
                self.customization = CustomizationMatcher().match(title=original_title) or None
                # 视频编码
                self.video_encode = aniparse_utils.get_video_term(aniparse_info)
                # 音频编码
                self.audio_encode = aniparse_utils.get_audio_term(aniparse_info)
                # 解析副标题，只要季和集
                self.init_subtitle(self.org_string)
                if not self._subtitle_flag and self.subtitle:
                    self.init_subtitle(self.subtitle)
            if not self.type:
                self.type = MediaType.TV
        except Exception as e:
            log.exception(f'【Meta】解析动漫名称[{title}]出错: ')

    def __prepare_title(self, title):
        """
        对命名进行预处理
        """
        if not title:
            return title
        # 截掉xx番剧漫
        match = re.search(r"新番|月?番|[日美国][漫剧]", title)
        if match and match.span()[1] < len(title) - 1:
            title = re.sub(".*番.|.*[日美国][漫剧].", "", title)
        elif match:
            title = title[:title.rfind('[')]
        # 截掉分类
        first_item = title.split(']')[0]
        if first_item and re.search(
                r"[动漫画纪录片电影视连续剧集日美韩中港台海外亚洲华语大陆综艺原盘高清]{2,}|TV|Animation|Movie|Documentar|Anime",
                zhconv.convert(first_item, "zh-hans"),
                re.IGNORECASE):
            title = re.sub(r"^[^]]*]", "", title).strip()
        # 去掉大小
        title = re.sub(r'[0-9.]+\s*[MGT]i?B(?![A-Z]+)', "", title, flags=re.IGNORECASE)
        # 将TVxx改为xx
        title = re.sub(r"\[TV\s+(\d{1,4})", r"[\1", title, flags=re.IGNORECASE)
        # 将4K转为2160p
        title = re.sub(r'\[4k]', '2160p', title, flags=re.IGNORECASE)
        # 移除部分副标题
        title = re.sub(self._subtitle_season_all_re, '', title, flags=re.IGNORECASE)
        title = re.sub(self._subtitle_episode_all_re, '', title, flags=re.IGNORECASE)
        # 剧集范围仅保留1个E
        title = re.sub(r'(E\d{2,3})-E(\d{2,3})', r'\1-\2', title)
        title = title.replace('[]','')
        # 处理/分隔的中英文标题
        names = title.split("]")
        if len(names) > 1 and title.find("- ") == -1:
            titles = []
            for name in names:
                if not name:
                    continue
                left_char = ''
                if name.startswith('['):
                    left_char = '['
                    name = name[1:]
                if name and name in self._anime_no_words:
                    continue
                if name and name.find("/") > 0:
                    name_list = list(filter(None, name.split("/")))
                    # 名称超过2个时，取一个中文和一个非中文
                    if len(name_list) > 2:
                        name_cn = next(filter(lambda x: StringUtils.contain_chinese(x), name_list), None)
                        name_other = next(filter(lambda x: not StringUtils.contain_chinese(x), name_list), None)
                        name_list = [name_cn, name_other]
                        name_list = list(filter(lambda x: x is not None, name_list))
                        name = "/".join(name_list)
                    
                    if len(name_list) == 2:
                        name_cn = next(filter(lambda x: StringUtils.contain_chinese(x), name_list), None)
                        name_other = next(filter(lambda x: not StringUtils.contain_chinese(x), name_list), None)
                        if name_cn and name_other:
                            splited_text = list(filter(None, re.split(r'%s' % Constants.SPLIT_CHARS, name_other)))
                            if len(splited_text) > 2:
                                numbers = list(filter(lambda x: x.isdigit(), splited_text))
                                if len(numbers) > 1:
                                    pos = name_other.find(numbers[0])
                                    name_other = name_other[:pos] + 'S' + name_other[pos:]
                                    name =  name_cn + "/" + name_other

                if name:
                    if name == '[':
                        titles.append("")
                    else:
                        titles.append(f"{left_char}{name.strip()}")

            title = "]".join(titles)
            
            lastX = title.rfind("]")
            if lastX > 0:
                lastY = title.rfind("[")
                if lastY > lastX:
                    title += ']'

        # 移除数字前的空格
        return title
    
   
