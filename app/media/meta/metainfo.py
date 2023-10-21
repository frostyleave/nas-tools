import os.path
import regex as re
import PTN

import log
from app.conf import ModuleConf
from app.helper import WordsHelper
from app.media.meta.metaanime import MetaAnime
from app.media.meta.metavideo import MetaVideo
from app.utils import StringUtils, ReleaseGroupsMatcher
from app.utils.types import MediaType
from config import RMT_MEDIAEXT

NAME_NOSTRING_RE = r"高清影视之家发布|连载|日剧|美剧|电视剧|动画片|动漫|欧美|西德|日韩|超高清|高清|蓝光|翡翠台|梦幻天堂·龙网|★?\d?\+?\d*月?新?番★?|[日美国][漫剧]" \
                   r"|高码版|最终季|全集|合集|[多中国英葡法俄日韩德意西印泰台港粤双文语简繁体特效内封官译外挂]+[字|幕|配|音|轨]+|版本|出品|台版|港版|\w+字幕组|未删减版"
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
    # 所有【】换成[]、季名转英文
    rev_title = StringUtils.season_ep_name_to_en(rev_title)
    # 应用自定义识别词，获取识别词处理后名称
    rev_title, msg, used_info = WordsHelper().process(rev_title)
    if subtitle:
        subtitle, _, _ = WordsHelper().process(subtitle)

    if msg:
        for msg_item in msg:
            log.warn("【Meta】%s" % msg_item)

    # 判断是否处理文件
    if org_title and os.path.splitext(org_title)[-1] in RMT_MEDIAEXT:
        fileflag = True
    else:
        fileflag = False

    if mtype == MediaType.ANIME or is_anime(rev_title):
        meta_info = MetaAnime(rev_title, subtitle, fileflag)
    else:
        resource_team, rev_title = preprocess_title(rev_title)
        meta_info = MetaVideo(rev_title, subtitle, fileflag)
        if resource_team:
            meta_info.resource_team = resource_team

    # 如果没有解析出中文名，或解析出的中文名中不包含中文，则尝试调用第三方组件进行解析
    if not meta_info.cn_name or not StringUtils.contain_chinese(meta_info.cn_name):
        resource_team = meta_info.resource_team if meta_info.resource_team else ''
        t = PTN.parse(rev_title.replace('[', '.').replace(']', '.').replace(resource_team, '').strip('.'))
        t_title = t.get('title')
        if t_title and StringUtils.contain_chinese(t_title):
            meta_info.cn_name = t_title

    # 设置原始名称
    meta_info.org_string = org_title
    # 设置识别词处理后名称
    meta_info.rev_string = rev_title

    # 设置应用的识别词
    meta_info.ignored_words = used_info.get("ignored")
    meta_info.replaced_words = used_info.get("replaced")
    meta_info.offset_words = used_info.get("offset")

    return meta_info

# 标题信息预处理
def preprocess_title(rev_title):
    # 提取制作组/字幕组
    resource_team = ReleaseGroupsMatcher().match_list(title=rev_title)
    # 把标题中的制作组/字幕组去掉
    if resource_team:
        for item in resource_team:
            rev_title = rev_title.replace(item, '')
        resource_team = ReleaseGroupsMatcher().get_separator().join(resource_team)
    # []换成.
    rev_title = rev_title.replace('[', '.').replace(']', '.').strip('.')
    return resource_team, rev_title


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
    if re.search(r"S\d{2}\s*-\s*S\d{2}|S\d{2}|\s+S\d{1,2}|EP?\d{2,4}\s*-\s*EP?\d{2,4}|EP?\d{2,4}|\s+EP?\d{1,4}", check_name,
                 re.IGNORECASE):
        return False
    if re.search(r'\[[+0-9XVPI-]+]\s*\[', check_name, re.IGNORECASE):
        return True
    return False
