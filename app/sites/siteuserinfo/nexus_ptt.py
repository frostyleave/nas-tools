# -*- coding: utf-8 -*-
import re
from lxml import etree

from app.sites.siteuserinfo._base import SITE_BASE_ORDER
from app.sites.siteuserinfo.nexus_php import NexusPhpSiteUserInfo
from app.utils.string_utils import StringUtils
from app.utils.types import SiteSchema

import log


class NexusProjectSiteUserInfo(NexusPhpSiteUserInfo):
    schema = SiteSchema.PTTNP
    order = SITE_BASE_ORDER + 25

    @classmethod
    def match(cls, html_text):
        return 'Powered by PTT-NP' in html_text
    

    def _parse_user_base_info(self, html_text):
        self._user_traffic_page = ''
            

    def __parse_user_traffic_info(self, html_text):

        html_text = self._prepare_html_text(html_text)       
        html = etree.HTML(html_text)
           
        # PTT 核心数据
        td_texts = html.xpath('//tr/td[text()="核心数据"]/following-sibling::td[1]')
        if td_texts:
            try:
            
                td_text = td_texts[0].xpath("string(.)").replace('\xa0', ' ')  # 提取文本并替换 nbsp
                
                bonus_match = re.search(r'魔力值[:：]?\s*([\d,.]+)', td_text)
                if bonus_match:
                    self.bonus = StringUtils.str_float(bonus_match.group(1).replace(',', ''))

                # 上传
                uploaded_match = re.search(r'上传量[:：]?\s*([\d,.]+[KMGTP]?B)', td_text, flags=re.I)
                if uploaded_match:
                    self.upload = StringUtils.num_filesize(uploaded_match.group(1))
                
                # 下载
                downloaded_match = re.search(r'下载量[:：]?\s*([\d,.]+[KMGTP]?B)', td_text, flags=re.I)
                self.download = StringUtils.num_filesize(downloaded_match.group(1))

                # 分享率
                share_match = re.search(r'分享率[:：]?\s*([\d,.]+)', td_text)
                if share_match:
                    self.ratio = StringUtils.str_float(share_match.group(1).replace(',', ''))

            except Exception as err:
                log.exception("PTT数据解析出错", err)

    def _parse_user_torrent_seeding_info(self, html_text, multi_page=False):
        """
        做种相关信息
        :param html_text:
        :param multi_page: 是否多页数据
        :return: 下页地址
        """
        html = etree.HTML(str(html_text).replace(r'\/', '/'))
        if not html:
            return None
        
        # 1. 提取“共有…条记录”
        total_records_match = re.search(r'共有<b>(\d+)</b>条记录', html_text)
        if total_records_match:
            self.seeding = StringUtils.str_int(total_records_match.group(1))

        # 2. 提取“资源总量”、“下载总量”、“上传总量”
        resource_total_match = re.search(r'<b>资源总量：</b>([\d.]+(?:[KMGT]B))', html_text)
        if resource_total_match:
            self.seeding_size = StringUtils.num_filesize(resource_total_match.group(1))
    
        return None


    def _parse_user_detail_info(self, html_text):

        """
        解析用户额外信息，加入时间，等级
        :param html_text:
        :return:
        """
        html = etree.HTML(html_text)
        if not html:
            return
        
        self.__parse_user_traffic_info(html_text)

        self.__get_user_level(html)

        # 用户名
        username_elem = html.xpath('//tr/td[text()="用户名"]/following-sibling::td[1]//a[@class="PowerUser_Name"]/b/text()')
        if username_elem:
            self.username = username_elem[0].strip()

        # 加入日期
        join_td = html.xpath('//tr/td[text()="加入日期"]/following-sibling::td[1]//text()')
        if join_td:
            raw_text = ''.join(join_td).strip()
            # 去掉括号里的内容，只保留实际日期时间
            match = re.match(r'([\d\- :]+)', raw_text)
            if match:
                self.join_at = StringUtils.unify_datetime_str(match.group(1).strip())

    def __get_user_level(self, html):

        # --- 情况1：表格里，img 带 title ---
        user_levels_text = html.xpath(
            '//tr/td[text()="等級" or text()="等级" or text()="用户等级" or *[text()="等级" or text()="用户等级"]]/following-sibling::td[1]/img[1]/@title'
        )
        if user_levels_text:
            self.user_level = user_levels_text[0].strip()
            return

        # --- 情况2：表格里，<b> 带 title 或 alt ---
        user_levels_text = html.xpath(
            '//tr/td[text()="等級" or text()="等级" or text()="用户等级"]/following-sibling::td[1]/b[@title or @alt]/@title'
            '|//tr/td[text()="等級" or text()="等级" or text()="用户等级"]/following-sibling::td[1]/b[@alt]/@alt'
        )
        if user_levels_text:
            self.user_level = user_levels_text[0].strip()
            return