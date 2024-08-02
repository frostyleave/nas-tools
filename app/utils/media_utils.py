import re
import zhconv

from config import ZHTW_SUB_RE, Config

class MediaUtils:

    @staticmethod
    def get_sort_str(download_info):

        # 繁体资源标记
        t_tag = "0" if re.match(ZHTW_SUB_RE, download_info.title) else "1"
        # 标题统一处理为简体中文
        zh_hant_title = t_tag + zhconv.convert(download_info.title, 'zh-hans')

        download_order = ''
        pt = Config().get_config('pt')
        if pt:
            download_order = pt.get("download_order")

        sort_str = str(zh_hant_title).ljust(100, ' ') + str(download_info.res_order).rjust(3, '0')
        if download_info.resource_pix:
            resource_pix = str(download_info.resource_pix).lower()
            if resource_pix.endswith('p'):
                resource_pix = resource_pix[0:-1]
            index = resource_pix.rfind('x')
            if index != -1:
                resource_pix = resource_pix[index + 1:]
            sort_str += resource_pix.rjust(4, '0')
        else:
            sort_str += '0000'

        # 排序：标题、资源类型、站点、做种、季集
        if download_order == "seeder":
            sort_str += str(download_info.seeders).rjust(10, '0')+str(download_info.site_order).rjust(3, '0')
        else:
            sort_str += str(download_info.site_order).rjust(3, '0') + str(download_info.seeders).rjust(10, '0')
        
        sort_str += str(len(download_info.get_season_list())).rjust(2, '0')
        sort_str += str(len(download_info.get_episode_list())).rjust(4, '0')

        return sort_str