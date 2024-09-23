import os.path
import regex as re
import PTN
import anitopy

import log
from app.conf import ModuleConf
from app.helper import WordsHelper
from app.media.meta.metaanime import MetaAnime
from app.media.meta.metavideo import MetaVideo
from app.utils import StringUtils, ReleaseGroupsMatcher, MediaUtils
from app.utils.types import MediaType
from config import RMT_MEDIAEXT

import zhconv

NAME_NOSTRING_RE = r"高清影视之家发布|连载|日剧|美剧|电视剧|动画片|动漫|欧美|西德|日韩|超高清|高清|蓝光|翡翠台|梦幻天堂·龙网|★?\d?\+?\d*月?新?番★?|[日美国][漫剧]" \
                   r"|高码版|最终季|全集|合集|[多中国英葡法俄日韩德意西印泰台港粤双文语简繁体特效内封官译外挂]+[字|幕|配|音|轨]+|版本|出品|台版|港版|未删减版"


def MetaInfo(title, subtitle=None, mtype=None):
    """
    媒体整理入口，根据名称和副标题，判断是哪种类型的识别，返回对应对象
    :param title: 标题、种子名、文件名
    :param subtitle: 副标题、描述
    :param mtype: 指定识别类型，为空则自动识别类型
    :return: MetaAnime、MetaVideo
    """

    # 记录原始名称
    org_title = title
    
    # 预去除一些无用的词
    rev_title = re.sub(r'%s' % NAME_NOSTRING_RE, "", title, flags=re.IGNORECASE)

    # 判断是否处理文件、格式化剧集文件名
    if org_title and os.path.splitext(org_title)[-1] in RMT_MEDIAEXT:
        fileflag = True
        rev_title = MediaUtils.clean_episode_range_from_file_name(rev_title)
    else:
        fileflag = False
        rev_title = MediaUtils.format_tv_file_name(rev_title)

    # 应用自定义识别词，获取识别词处理后名称
    rev_title, msg, used_info = WordsHelper().process(rev_title)
    if subtitle:
        subtitle, _, _ = WordsHelper().process(subtitle)

    if msg:
        for msg_item in msg:
            log.warn("【Meta】%s" % msg_item)

    anime_flag = is_anime(rev_title)

    if mtype == MediaType.ANIME or anime_flag:
        meta_info = MetaAnime(rev_title, subtitle, fileflag)
    else:
        resource_team, rev_title = preprocess_title(rev_title)
        meta_info = MetaVideo(rev_title, subtitle, fileflag)
        # 识别出为剧集、且有年份，但是没有集数，去掉标题中年份，重新识别
        if MediaType.MOVIE != meta_info.type and not meta_info.begin_episode and meta_info.year:
            year = meta_info.year
            meta_info = MetaVideo(rev_title.replace(meta_info.year, ''), subtitle, fileflag)
            meta_info.year = year
        if resource_team:
            meta_info.resource_team = resource_team
        # 动漫文件集数信息补全
        if anime_flag and fileflag and not meta_info.begin_episode:
            anitopy_info = anitopy.parse(meta_info.org_string)
            if anitopy_info and anitopy_info.get("episode_number"):
                episode_number = anitopy_info.get("episode_number")
                meta_info.begin_episode = episode_number if isinstance(episode_number, int) else int(episode_number)

    # 信息修正
    # info_fix(meta_info, rev_title)

    # 设置原始名称
    meta_info.org_string = org_title
    # 设置识别词处理后名称
    meta_info.rev_string = rev_title
    if meta_info.cn_name:
        cn_name = zhconv.convert(meta_info.cn_name, "zh-hans")
        meta_info.cn_name = cn_name

    # 设置应用的识别词
    meta_info.ignored_words = used_info.get("ignored")
    meta_info.replaced_words = used_info.get("replaced")
    meta_info.offset_words = used_info.get("offset")

    return meta_info


def info_fix(meta_info, rev_title):
    # 移除字幕组信息
    resource_team = meta_info.resource_team if meta_info.resource_team else ''
    # 移除部分副标题
    title = re.sub(meta_info._subtitle_season_all_re, '', rev_title, flags=re.IGNORECASE)
    title = re.sub(meta_info._subtitle_episode_all_re, '', title, flags=re.IGNORECASE)
    # 移除年份
    if hasattr(meta_info, 'year') and meta_info.year:
        title = title.replace(meta_info.year, '')

    title = StringUtils.remve_redundant_symbol(title.replace(resource_team, '')).strip('.')
    title = title.replace('-', '_')

    t = PTN.parse(title)
    t_title = t.get('title')

    if t_title:
        # 如果没有解析出中文名，或解析出的中文名中不包含中文，则尝试进行修正
        if (not meta_info.cn_name or StringUtils.is_all_chinese_and_mark(meta_info.cn_name) == False) \
                and StringUtils.contain_chinese(t_title):
            meta_info.cn_name = t_title
        if not meta_info.en_name and StringUtils.is_english_or_number(t_title):
            meta_info.en_name = t_title

    t_episode = t.get('episode')
    if t_episode:
        meta_info.type = MediaType.TV
        if isinstance(t_episode, list):
            meta_info.begin_episode = t_episode[0]
            meta_info.end_episode = t_episode[len(t_episode) - 1]
        elif not meta_info.begin_episode:
            meta_info.begin_episode = t_episode


# 标题信息预处理
def preprocess_title(rev_title):
    # 提取制作组/字幕组
    resource_team = ReleaseGroupsMatcher().match_list(title=rev_title)
    # anitopy 辅助提取
    try:
        # 调用 anitopy
        anitopy_info_origin = anitopy.parse(rev_title)
        if anitopy_info_origin and anitopy_info_origin.get("release_group"):
            release_group = anitopy_info_origin.get("release_group")
            if not resource_team:
                resource_team = []
                resource_team.append(release_group)
            elif release_group not in resource_team:
                resource_team.append(release_group)
    except Exception as err:
        log.warn("【Meta】anitopy提取字幕组信息出错: %s 不存在" % str(err))

    # 把标题中的制作组/字幕组去掉
    if resource_team:
        for item in resource_team:
            rev_title = rev_title.replace(item, '')
        resource_team = ReleaseGroupsMatcher().get_separator().join(resource_team)

    return resource_team, StringUtils.remve_redundant_symbol(rev_title)


def is_anime(name):
    """
    判断是否为动漫
    :param name: 名称
    :return: 是否动漫
    """
    if not name:
        return False

    check_name = name
    # 去除分辨率部分再进行判断
    pix_re = ModuleConf.TORRENT_SEARCH_PARAMS["pix"]
    if pix_re:
        values = '|'.join(list(pix_re.values()))
        check_name = re.sub(r'%s' % values, "", name, flags=re.IGNORECASE)

    if re.search(r'【[+0-9XVPI-]+】\s*【', check_name, re.IGNORECASE):
        return True
    if re.search(r'\s+-\s+[\dv]{1,4}\s+', check_name, re.IGNORECASE):
        return True
    if re.search(r"S\d{2}\s*-\s*S\d{2}|S\d{2}|\s+S\d{1,2}|EP?\d{2,4}\s*-\s*EP?\d{2,4}|EP?\d{2,4}|\s+EP?\d{1,4}",
                 check_name,
                 re.IGNORECASE):
        return False
    if re.search(r'\[[+0-9XVPI-]+]\s*\[', check_name, re.IGNORECASE):
        return True
    return False
