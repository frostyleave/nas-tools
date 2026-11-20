import re

from lxml import etree

from app.sites.siteuserinfo._base import SITE_BASE_ORDER
from app.sites.siteuserinfo.nexus_php import NexusPhpSiteUserInfo
from app.utils.string_utils import StringUtils
from app.utils.types import SiteSchema


class NexusAudiencesSiteUserInfo(NexusPhpSiteUserInfo):

    schema = SiteSchema.NexusPhpAudiences
    order = SITE_BASE_ORDER + 25

    @classmethod
    def match(cls, html_text):

        html = etree.HTML(html_text)

        exists = bool(
            html.xpath(
                "//*[contains(normalize-space(string(.)), '(c)') and "
                "contains(normalize-space(string(.)), 'Audiences') and "
                "contains(normalize-space(string(.)), 'Powered by') and "
                "contains(normalize-space(string(.)), 'NexusPHP') and "
                "re:match(normalize-space(string(.)), '2021-[0-9]{4}')]",
                namespaces={"re": "http://exslt.org/regular-expressions"}
            )
        )

        return exists
    

    def _parse_user_torrent_seeding_info(self, html_text, multi_page=False):
        """
        做种相关信息
        :param html_text:
        :param multi_page: 是否多页数据
        :return: 下页地址
        """

        # 1. 提取做种数
        total_records_match = re.search(r'<b>(\d+)</b>条记录', html_text)
        if total_records_match:
            self.seeding = StringUtils.str_int(total_records_match.group(1))

        # 2. 提取做种体积
        resource_total_match = re.search(r'Total:\s*([0-9.]+\s*[KMGT]B)', html_text)
        if resource_total_match:
            self.seeding_size = StringUtils.num_filesize(resource_total_match.group(1))

    def _parse_user_detail_info(self, html_text):
        """
        解析用户详情页（Audiences 定制的 ud-* 结构）
        包括：用户名、等级、加入日期、上传/下载/分享率、爆米花、做种/下载中数量
        :param html_text:
        :return:
        """
        html = etree.HTML(html_text)
        if not html:
            return

        def class_is(name):
            # 按类名 token 精确匹配，避免 ud-row 命中 ud-row__label
            return f'contains(concat(" ", normalize-space(@class), " "), " {name} ")'

        # 用户名：ud-hero__name 中的 <b>
        username = html.xpath(f'//*[{class_is("ud-hero__name")}]//b/text()')
        if username and username[0].strip():
            self.username = username[0].strip()

        # 用户等级：(步履不停)Insane User -> Insane User（去掉括号内的自定义头衔）
        user_level = html.xpath(f'//*[{class_is("ud-class")}]//text()')
        if user_level:
            level_text = re.sub(r'^[（(][^）)]*[）)]', '', ''.join(user_level).strip()).strip()
            if level_text:
                self.user_level = level_text
        if not self.user_level:
            badge = html.xpath('//@data-uploader-badge')
            if badge and badge[0].strip():
                level_text = re.sub(r'^[（(][^）)]*[）)]', '', badge[0].strip()).strip()
                if level_text:
                    self.user_level = level_text

        # 加入日期：<span>加入日期：2025-10-20 08:05:25 (<span title="...">1年前</span>)</span>
        meta_text = html.xpath(f'string(//*[{class_is("ud-hero__meta")}])')
        join_match = re.search(r'加入日期[:：]\s*(\d{4}-\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?)', meta_text)
        if join_match:
            self.join_at = StringUtils.unify_datetime_str(join_match.group(1))

        # 顶部统计卡片：上传量 / 下载量 / 分享率 / 爆米花 / 做种积分
        stats = {}
        for stat in html.xpath(f'//*[{class_is("ud-stat__body")}]'):
            label = stat.xpath(f'.//*[{class_is("ud-stat__label")}]//text()')
            value = stat.xpath(f'.//*[{class_is("ud-stat__value")}]//text()')
            if label and value:
                stats[''.join(label).strip()] = ''.join(value).strip()

        # 详情卡片行：账号信息 / 传输与时间 / 连接信息 等
        rows = {}
        for row in html.xpath(f'//*[{class_is("ud-row")}]'):
            label = row.xpath(f'.//*[{class_is("ud-row__label")}]//text()')
            value = row.xpath(f'.//*[{class_is("ud-row__value")}]')
            if label and value:
                rows[''.join(label).strip()] = ''.join(value[0].itertext()).strip()

        # UID（首页未取到时兜底）
        if not self.userid:
            uid_text = rows.get('UID', '').strip()
            if uid_text.isdigit():
                self.userid = uid_text
                self._torrent_seeding_page = f"getusertorrentlistajax.php?userid={self.userid}&type=seeding"

        # 上传量
        upload_text = stats.get('上传量') or rows.get('上传量')
        if upload_text:
            self.upload = StringUtils.num_filesize(upload_text)

        # 下载量
        download_text = stats.get('下载量') or rows.get('下载量')
        if download_text:
            self.download = StringUtils.num_filesize(download_text)

        # 分享率
        ratio_text = stats.get('分享率') or rows.get('分享率', '')
        ratio_match = re.search(r'[\d,.]+', ratio_text)
        if ratio_match:
            self.ratio = StringUtils.str_float(ratio_match.group())

        # 爆米花（魔力值）
        bonus_text = stats.get('爆米花') or rows.get('爆米花', '')
        bonus_match = re.search(r'[\d,.]+', bonus_text)
        if bonus_match:
            self.bonus = StringUtils.str_float(bonus_match.group())

        # 做种中 / 下载中：用户栏 "↑ 217 / ↓ 0"
        seeding_text = ''.join(html.xpath(
            f'//a[{class_is("site-userbar__compact-metric-inline-link--seeding")}]//text()'))
        seeding_match = re.search(r'\d+', seeding_text)
        if seeding_match:
            self.seeding = StringUtils.str_int(seeding_match.group())
        else:
            # 兜底：连接信息中的 Torrents:217
            torrents_match = re.search(r'Torrents[:：]\s*(\d+)', rows.get('BT客户端', ''), re.IGNORECASE)
            if torrents_match:
                self.seeding = StringUtils.str_int(torrents_match.group(1))

        leeching_text = ''.join(html.xpath(
            f'//a[{class_is("site-userbar__compact-metric-inline-link--leeching")}]//text()'))
        leeching_match = re.search(r'\d+', leeching_text)
        if leeching_match:
            self.leeching = StringUtils.str_int(leeching_match.group())

