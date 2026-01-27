# -*- coding: utf-8 -*-
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
    
        return None
