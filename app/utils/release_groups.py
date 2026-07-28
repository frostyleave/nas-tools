import regex as re

from app.utils.commons import singleton


@singleton
class ReleaseGroupsMatcher(object):
    """
    识别制作组、字幕组
    """
    __release_groups = None
    custom_release_groups = None
    custom_separator = None
    RELEASE_GROUPS = {
        "0ff": ['FF(?:(?:A|WE)B|CD|E(?:DU|B)|TV)'],
        "1pt": ['1PTBA'],
        "52pt": ['52pt'],
        "audiences": ['Audies', 'AD(?:Audio|E(?:|book)|Music|Web)'],
        "beitai": ['BeiTai'],
        "btschool": ['Bts(?:CHOOL|HD|PAD|TV)', 'Zone'],
        "BeyondHD": ['BYNDR'],
        "carpt": ['CarPT'],
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
                   'N(?:oGroup|T(?:b|G))', 'PandaMoon', 'SMURF', 'T(?:EPES|aengoo|rollHD )'],
        "anime": ['ANi', 'HYSUB', 'KTXP', 'LoliHouse', 'MCE', 'Nekomoe kissaten', r'(\d|\w|[\u4e00-\u9fa5])+-Raws',
                  '织梦字幕组', '豌豆字幕组&风之圣殿字幕组', '豌豆&风之圣殿字幕组', '风之圣殿字幕组', '豌豆字幕组']
    }

    def __init__(self):
        release_groups = []
        for site_groups in self.RELEASE_GROUPS.values():
            for release_group in site_groups:
                release_groups.append(release_group)
        self.__release_groups = '|'.join(release_groups)

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
        if not groups:
            if self.custom_release_groups:
                groups = f"{self.__release_groups}|{self.custom_release_groups}"
            else:
                groups = self.__release_groups
        title = f"{title} "
        groups_re = re.compile(r"(?<=[-@\[￡【&])(?:%s)(?=[@.\s\]\[】&])" % groups, re.I)
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
