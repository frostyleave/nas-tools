import re
import zhconv

from config import ZHTW_SUB_RE, Config

class MediaUtils:

    @staticmethod
    def get_sort_str(download_info):

        # 繁体资源标记(简体资源优先)
        t_tag = "0" if re.match(ZHTW_SUB_RE, download_info.title) else "1"

        # 标题统一处理为简体中文
        zh_hant_title = t_tag + zhconv.convert(download_info.title, 'zh-hans')
       
        # 排序：标题、季集、资源类型、站点、做种、发布日期、大小
        sort_str = str(zh_hant_title).ljust(100, ' ')
        # 季集
        sort_str += str(len(download_info.get_season_list())).rjust(2, '0')
        sort_str += str(len(download_info.get_episode_list())).rjust(4, '0')

        sort_str += str(download_info.res_order).rjust(3, '0')
        
        if download_info.resource_pix:
            resource_pix = str(download_info.resource_pix).lower().replace('x', '×').replace('*', '×')
            if resource_pix.endswith('p'):
                resource_pix = resource_pix[0:-1]
            index = resource_pix.rfind('×')
            if index != -1:
                resource_pix = resource_pix[index + 1:]
            sort_str += resource_pix.rjust(4, '0')
        else:
            sort_str += '0000'
        
        pt = Config().get_config('pt')
        if pt and pt.get("download_order") == "seeder":            
            sort_str += str(download_info.seeders).rjust(10, '0')
        
        if download_info.pubdate:
            sort_str += download_info.pubdate
        else:
            sort_str += '0000-00-00 00:00:00'
        
        # 添加文件大小，确保小文件排在前面
        if download_info.size:
            sort_str += str(9999999999 - int(download_info.size / 1024)).rjust(10, '0')
        else:
            sort_str += '0000000000'

        # 站点排序
        sort_str += str(download_info.site_order).rjust(3, '0')

        return sort_str