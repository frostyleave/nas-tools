import cn2an
import PTN
import re
import zhconv

import log

from config import ZHTW_SUB_RE, Config

class MediaUtils:

    @staticmethod
    def get_sort_str(download_info):
        """
        生成排序字符
        """
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


    @staticmethod
    def format_tv_file_name(title):
        """
        格式化剧集文件名
        """
        # 所有【】换成[]
        title = title.replace("【", "[").replace("】", "]").strip()
        # 季、期 统一：改为英文，方便三方插件识别
        clean_title = MediaUtils.name_ch_to_number(title, r"([第|全|共][^第|全|共]+[季|期])", 'S')
        # 集数 统一：改为英文，方便三方插件识别
        clean_title = MediaUtils.name_ch_to_number(clean_title, r"([第|全|共][^第|全|共]+[集|话|話])", 'E')
        clean_title = MediaUtils.name_ch_to_number(clean_title, r"(\d+)(集|话|話)全", 'E')
        clean_title = MediaUtils.name_ch_to_number(clean_title, r"(?<!第)(?<!全)(?<!共)(?<!\d)\b\d+[集话話]", 'E')

        if title != clean_title:
            return MediaUtils.adjust_tv_se_position(clean_title)

        return title
    
    @staticmethod
    def resolve_douban_season_tag(title: str):
        """
        解析豆瓣剧集名称中的季信息
        """
        season_match = re.findall(r'([第][^第]+[季|期])', title)
        if not season_match:
            return title, 0
        first_season = season_match[0]

        clean_name = title[0: title.find(first_season)].strip()
        # 去掉首尾
        first_season = first_season[1:-1]
        if first_season.isdigit():
            return clean_name, int(first_season)
        
        try:
            x = cn2an.cn2an(first_season, "smart")
            return clean_name, int(x)
        except Exception:
            return clean_name, 1


    @staticmethod
    def clean_episode_range_from_file_name(filename: str):
        """
        清除文件名中的集数范围信息
        """
        episode_pattern = r"([全|共][^全|共]+[集|话|話])|(\d+)(集|话|話)全|(?<!全)(?<!共)(?<!\d)\b\d+[集话話]"
        clean_title = re.sub(episode_pattern, '', filename)
        return MediaUtils.adjust_tv_se_position(clean_title)        

    @staticmethod
    def name_ch_to_number(title, reg_pattern, format_str):
        """
        中文序号转为数字
        """
        offset = 0
        new_list = set()
        for raw in list(re.finditer(reg_pattern, title, flags=re.IGNORECASE))[::-1]:
            info = raw.group()
            # 截掉这部分内容
            title = title[0:raw.regs[0][0]] + title[raw.regs[0][1]:]
            # 偏移量
            if offset == 0:
                offset = raw.regs[0][0]
            else:
                offset -= (raw.regs[0][1] - raw.regs[0][0] + 1)

            info = MediaUtils.move_last_char_to_front(info, '全')
            tag = info[0]
            # 去掉头尾取中间需要转换的部分
            if tag.isdigit() is False:
                info = info[1:-1]
            else:
                info = info[0:-1]
            # 正则取中文，转化为数字
            numbers = list(re.finditer(r'[\d\u4e00-\u9fa5]+', info))[::-1]
            for ep in numbers:
                try:
                    x = cn2an.cn2an(ep.group(), "smart")
                    info = info[0: ep.regs[0][0]] + str(int(x)).rjust(2, '0') + info[ep.regs[0][1]:]
                except Exception as err:
                    log.error(f"季集信息转换出错出错：{str(err)}")
            
            if len(numbers) == 1 and (tag =='全' or tag =='共'):
                info = f'{format_str}01-{format_str}{info}'
            else:
                info = format_str + info

            new_list.add(info)

        if len(new_list) == 0:
            return title

        new_info = '.{}.'.format(' '.join(new_list))
        if offset == 0:
            cn_char = re.search('[A-Za-z]+', title, flags=re.IGNORECASE)
            if cn_char:
                offset = cn_char.regs[0][0]
        title = title[0: offset].strip() + new_info + title[offset:].strip()
        return title.strip('.').strip()
    
    @staticmethod
    def move_last_char_to_front(s: str, target: str) -> str:
        # 如果字符串以目标字符结尾
        if s[-len(target):] == target:
            # 将末尾的目标字符移到最前面
            return target + s[:-len(target)]
        return s

    @staticmethod
    def adjust_tv_se_position(filename:str):
        """
        调整剧集文件的季、集信息所在位置
        """
        # 正则表达式匹配季和集信息
        season_pattern = r"(S\d{1,2})"
        episode_pattern = r"(E\d{1,3})"

        # 查找季和集信息
        season_match = re.findall(season_pattern, filename)
        episode_match = re.findall(episode_pattern, filename)

        cleaned_filename = filename
        if season_match:
            if len(season_match) > 2:
                return filename
            first_season = season_match[0]
            cleaned_filename = MediaUtils.insert_season_to_sw(first_season, cleaned_filename)
            
            if len(season_match) == 2:
                second_season = season_match[1]
                cleaned_filename = MediaUtils.insert_season_to_sw(second_season, cleaned_filename)
        
        if episode_match:
            # 真实季数大于1的, 不保留集信息
            season_match = re.findall(season_pattern, cleaned_filename)
            if len(season_match) > 1 and len(list({s.upper() for s in season_match})) > 1:
                return re.sub(episode_pattern, '', cleaned_filename)

            if len(episode_match) > 2:
                return filename
            
            first_episode = episode_match[0]
            cleaned_filename = MediaUtils.insert_episode_to_sw(first_episode, cleaned_filename)
            
            if len(episode_match) == 2:
                second_episode = episode_match[1]
                cleaned_filename = MediaUtils.insert_episode_to_sw(second_episode, cleaned_filename)

        return re.sub(r"\.+", ".", cleaned_filename)

    @staticmethod
    def insert_season_to_sw(first_season:str, target_str:str):
        """
        把季信息插入合适的位置
        """
        if not target_str.startswith(first_season):
            return target_str
        
        target_str = target_str[len(first_season):].strip(".-")

        # 正则表达式匹配季和集信息
        season_pattern = r"(S\d{1,2})"
        season_match = re.findall(season_pattern, target_str)
        if season_match:
            second_season = season_match[0]
            p_index = target_str.find(second_season)
            # 有第2个季信息、且不在开头, 则不用考虑其他情况
            if p_index > 0:
                sep = int(second_season[1:])
                fep = int(first_season[1:])
                # 相同的丢弃, 不同则根据大小放到适当位置
                if fep != sep:
                    if sep > fep:
                        insert_pos = p_index
                        insert_str = first_season + '-'
                    else:
                        insert_pos = p_index + len(second_season)
                        insert_str = '-' + first_season
                    target_str = target_str[0:insert_pos] + insert_str + target_str[insert_pos:]
                return target_str

        episode_pattern = r"(E\d{1,3})"
        episode_match = re.findall(episode_pattern, target_str)
        if episode_match:
            # 放到集信息之前
            episode_info = episode_match[0]
            p_index = target_str.find(episode_info)
            # 仅处理不在开头的情况
            if p_index > 0:
                return target_str[0:p_index]  + '.' + first_season + '.' + target_str[p_index:]
        
        t = PTN.parse(target_str)
        t_title = t.get('title')
        if t_title:
            insert_pos = target_str.find(t_title) + len(t_title)
            return target_str[0:insert_pos] + '.' + first_season + '.' + target_str[insert_pos:]
        
        return target_str + '.' + first_season

    @staticmethod
    def insert_episode_to_sw(first_episode:str, target_str:str):
        """
        把集信息插入合适的位置
        """
        if not target_str.startswith(first_episode):
            return target_str
        
        target_str = target_str[len(first_episode):].strip(".-")

        episode_pattern = r"(E\d{1,3})"
        episode_match = re.findall(episode_pattern, target_str)
        if episode_match:
            second_episode = episode_match[0]
            e_index = target_str.find(second_episode)
            # 第二个集信息必须不在开头
            if e_index > 0:
                sep = int(second_episode[1:])
                fep = int(first_episode[1:])
                if fep != sep:
                    if sep > fep:
                        insert_pos = e_index
                        insert_str = first_episode + '-'
                    else:
                        insert_pos = e_index + len(second_episode)
                        insert_str = '-' + first_episode
                    target_str = target_str[0:insert_pos] + insert_str + target_str[insert_pos:]
                return target_str

        season_pattern = r"(S\d{1,2})"
        season_match = re.findall(season_pattern, target_str)
        if season_match:
            if len(season_match) > 1:
                return target_str
            p_index = target_str.find(season_match[0]) + len(season_match[0])
            return target_str[0:p_index]  + '.' + first_episode + '.' + target_str[p_index:]
        
        t = PTN.parse(target_str)
        t_title = t.get('title')
        if t_title:
            insert_pos = target_str.find(t_title) + len(t_title)
            return target_str[0:insert_pos] + '.' + first_episode + '.' + target_str[insert_pos:]

        return target_str + '.' + first_episode

