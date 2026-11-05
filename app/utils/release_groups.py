from itertools import chain
from typing import ClassVar

import regex as re

from app.utils.commons import singleton


@singleton
class ReleaseGroupsMatcher:
    """
    识别制作组、字幕组
    """
    __release_groups = None
    custom_release_groups = None
    custom_separator = None
    RELEASE_GROUPS: ClassVar[dict[str, list[str]]] = {
        "0ff": ['FF(?:(?:A|WE)B|CD|E(?:DU|B)|TV)'],
        "1pt": ['1PTBA'],
        "52pt": ['52pt'],
        "audiences": ['Audies', 'AD(?:Audio|E(?:|book)|Music|Web)'],
        "beitai": ['BeiTai'],
        "btschool": ['Bts(?:CHOOL|HD|PAD|TV)', 'Zone'],
        "BeyondHD": ['BYNDR'],
        "carpt": ['CarPT'],
        "colapt": ['COLAWEB'],
        "cspt": ['CSWEB','CSPT','HSWEB','HSPT'],
        "chdbits": ['CHD(?:|Bits|PAD|(?:|HK)TV|WEB)', 'StBOX', 'OneHD', 'Lee', 'xiaopie'],
        "dstudio": ['DS','DStudio','DepWeb','DSAudio'],
        "eastgame": ['(?:(?:iNT|(?:HALFC|Mini(?:S|H|FH)D))-|)TLF'],
        "gainbound": ['(?:DG|GBWE)B'],
        "hares": ['Hares(?:|(?:M|T)V|Web)'],
        "hdarea": ['HDA(?:pad|rea|TV)', 'EPiC'],
        "hdchina": ['HDC(?:|hina|TV)', 'k9611', 'tudou', 'iHD'],
        "hddolby": ['D(?:ream|BTV)', '(?:HD|QHstudI)o'],
        "hdfans": ['beAst(?:|TV)'],
        "hdhome": ['HDH(?:|ome|Pad|TV|WEB)'],
        "hdpt": ['HDPT(?:|Web)'],
        "hdsky": ['HDS(?:|ky|TV|Pad|WEB)', 'AQLJ'],
        "hdvideo": ['HDV', 'HDVWEB', 'HDVTV', 'HDVMV'],
        "hdzone": ['HDZ(?:|one)'],
        "hhanclub": ['HHWEB'],
        "htpt": ['HTPT'],
        "keepfrds": ['FRDS', 'Yumi', 'cXcY'],
        "lemonhd": ['L(?:eague(?:(?:C|H)D|(?:M|T)V|NF|WEB)|HD)', 'i18n', 'CiNT'],
        "mteam": ['MTeam(?:|TV)', 'MPAD', 'MWeb'],
        "ourbits": ['Our(?:Bits|TV)', 'FLTTH', 'Ao', 'PbK', 'MGs', 'iLove(?:HD|TV)'],
        "piggo": ['PiGo(?:NF|(?:H|WE)B)'],
        "panda": ['AilMWeb', 'Panda', 'AilME', 'AilMTV', 'AilMUpscale'],
        "pterclub": ['PTer(?:|DIY|Game|(?:M|T)V|WEB)'],
        "pthome": ['PTH(?:|Audio|eBook|music|ome|tv|WEB)'],
        "ptsbao": ['PTsbao', 'OPS', 'F(?:Fans(?:AIeNcE|BD|D(?:VD|IY)|TV|WEB)|HDMv)', 'SGXT'],
        "putao": ['PuTao'],
        "springsunday": ['CMCT(?:|V)'],
        "sharkpt": ['Shark(?:|WEB|DIY|TV|MV)'],
        "tjupt": ['TJUPT'],
        "totheglory": ['TTG', 'WiKi', 'NGB', 'DoA', '(?:ARi|ExRE)N'],
        "ubits": ['UBWEB', 'UBits'],
        "xingyungept": ['StarfallWeb'],
        "zmpt": ['ZmWeb', 'ZmAudio'],
        "others": ['B(?:MDru|eyondHD|TN)', 'C(?:fandora|trlhd|MRG)', 'DON', 'EVO', 'FLUX', 'HONE(?:|yG)',
                   'N(?:oGroup|T(?:b|G))', 'PandaMoon', 'SMURF', 'T(?:EPES|aengoo|rollHD )', 
                   'Kitsune', 'SPWEB', 'SLOT', 'FLIX', 'KyoGo', 'TeamSyndicate'],
        "anime": ['ANi', 'HYSUB', 'KTXP', 'LoliHouse', 'MCE', 'Nekomoe kissaten', r'(\d|\w|[\u4e00-\u9fa5])+-Raws',
                  '织梦字幕组', '豌豆字幕组&风之圣殿字幕组', '豌豆&风之圣殿字幕组', '风之圣殿字幕组', '豌豆字幕组']
    }

    _GROUP_PATTERN = r"(?<=[-@\[￡【&])(?:{})(?=[@.\s\]\[】&])"

    def __init__(self):
        self.__release_groups = '|'.join(
            chain.from_iterable(self.RELEASE_GROUPS.values())
        )
        # 预编译正则，避免每次匹配都重新编译
        self.__release_groups_re = self.__compile_groups(self.__release_groups)
        self.__custom_groups_re = None

    @classmethod
    def __compile_groups(cls, groups):
        return re.compile(cls._GROUP_PATTERN.format(groups), re.I)

    def match(self, title=None, groups=None):
        """
        :param title: 资源标题或文件名
        :param groups: 制作组/字幕组
        :return: 匹配结果
        """
        if not title:
            return ""
        unique_groups = self.match_list(title, groups)
        separator = self.get_separator()
        return separator.join(unique_groups)

    def match_list(self, title=None, groups=None):
        """
        :param title: 资源标题或文件名
        :param groups: 制作组/字幕组
        :return: 匹配结果
        """
        if not title:
            return ""
        if groups:
            # 调用方显式传入制作组列表，只能临时编译
            groups_re = self.__compile_groups(groups)
        elif self.__custom_groups_re is not None:
            groups_re = self.__custom_groups_re
        else:
            groups_re = self.__release_groups_re
        title = f"{title} "
        # 处理一个制作组识别多次的情况，保留顺序
        unique_groups = []
        for match in re.finditer(groups_re, title):
            unique_groups.append(match.group())
        return unique_groups

    def get_separator(self):
        return self.custom_separator or "@"

    def update_custom(self, release_groups=None, separator=None):
        """
        更新自定义制作组/字幕组，自定义分隔符
        """
        self.custom_release_groups = release_groups
        self.custom_separator = separator
        if release_groups:
            self.__custom_groups_re = self.__compile_groups(
                f"{self.__release_groups}|{release_groups}")
        else:
            self.__custom_groups_re = None
