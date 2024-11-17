import cn2an
import PTN
import re
import zhconv

from app.utils.string_utils import StringUtils
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

        # 英文集数范围格式化
        clean_title = re.sub(r'(E)(\d{2,3})-(\d{2,3})', r'\1\2-E\3', clean_title)

        return MediaUtils.adjust_tv_se_position(clean_title)
    
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
            numbers = list(re.finditer(r'[\d\u4e00-\u9fa5]+', info))
            trans_num_list = []
            position_list = []
            for ep in numbers[::-1]:
                try:
                    digit = cn2an.cn2an(ep.group(), "smart")
                    format_ep = format_str + str(int(digit)).rjust(2, '0')
                    trans_num_list.append(format_ep)
                    position_list.append(ep.regs)
                except Exception as err:
                    log.error(f"季集信息转换出错出错：{str(err)}")
            
            if len(numbers) == 1 and (tag =='全' or tag =='共'):
                position = position_list[0]
                info = format_str + '01-' + info[0: position[0][0]] + trans_num_list[0] + info[position[0][1]:]
            else:
                sorted_list = sorted(trans_num_list)
                list_len = len(sorted_list)
                for i in range(list_len):
                    position_item = position_list[i]
                    se_item = sorted_list[list_len - i - 1]
                    info = info[0: position_item[0][0]] + se_item + info[position_item[0][1]:]

            new_list.add(info)

        list_len = len(new_list)
        if list_len == 0:
            return title
        elif list_len > 1:
            new_list = list(set(new_list))

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

        def standardizing_se(source_str, reg_pattern):
            """
            剧集名标准化
            """
            match_reg = list(re.finditer(reg_pattern, source_str, flags=re.IGNORECASE))

            if not match_reg:
                return source_str, []

            result_match = []
            cleaned_filename = source_str

            # 超过2个匹配项时, 倒序标准化处理
            if len(match_reg) > 1:
                for match_raw in match_reg[::-1]:
                    info = match_raw.group()
                    if len(info) == 2:
                        info = StringUtils.insert_char_at_index(info, '0', 1)
                        cleaned_filename = StringUtils.insert_char_at_index(cleaned_filename, '0', match_raw.regs[0][0] + 1)
                    result_match.append(info)
                return cleaned_filename, result_match[::-1]
                
            return cleaned_filename, list(map(lambda x: x.group(), match_reg))

        # 季
        cleaned_filename, season_match = standardizing_se(filename, season_pattern)
        if season_match:        
            if len(season_match) > 2:
                return filename
            first_season = season_match[0]
            cleaned_filename = MediaUtils.insert_season_to_sw(first_season, cleaned_filename)
            
            if len(season_match) == 2:
                second_season = season_match[1]
                cleaned_filename = MediaUtils.insert_season_to_sw(second_season, cleaned_filename)
                # 如果两个季信息相同，则去掉第一个
                if second_season == first_season:
                    cleaned_filename = cleaned_filename.replace(first_season, "", 1)

        # 集
        cleaned_filename, episode_match = standardizing_se(cleaned_filename, episode_pattern)
        if episode_match:
            # 真实季数大于1的, 不保留集信息
            season_match = re.findall(season_pattern, cleaned_filename)
            if len(season_match) > 1 and len(list({s.upper() for s in season_match})) > 1:
                return re.sub(episode_pattern, '', cleaned_filename)

            # 去重后排序
            real_episode = sorted(list(set(list(map(lambda x: 'E' + x.upper().strip('E'), episode_match)))))
            if len(real_episode) > 2:
                return cleaned_filename
            
            first_episode = real_episode[0]
            cleaned_filename, pos = MediaUtils.insert_episode_to_sw(first_episode, cleaned_filename)
            
            if len(real_episode) == 2:
                second_episode = real_episode[1]
                if pos <= 0:
                    pos = cleaned_filename.find(first_episode)
                # 移除second_episode
                cleaned_filename = cleaned_filename.replace(second_episode, "", 1)
                # 调整插入下标位置
                pos = pos + len(first_episode) - len(second_episode)
                cleaned_filename = StringUtils.insert_char_at_index(cleaned_filename, '.{}.'.format(second_episode), pos)

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
                    target_str = StringUtils.insert_char_at_index(target_str, insert_str, insert_pos)
                return target_str

        episode_pattern = r"(E\d{1,3})"
        episode_match = re.findall(episode_pattern, target_str)
        if episode_match:
            # 放到集信息之前
            episode_info = episode_match[0]
            p_index = target_str.find(episode_info)
            # 仅处理不在开头的情况
            if p_index > 0:
                return StringUtils.insert_char_at_index(target_str, '.{}.'.format(first_season), p_index)
        
        t = PTN.parse(target_str)
        t_title = t.get('title')
        if t_title:
            insert_pos = target_str.find(t_title) + len(t_title)
            return StringUtils.insert_char_at_index(target_str, '.{}.'.format(first_season), insert_pos)
        
        return target_str + '.' + first_season

    @staticmethod
    def insert_episode_to_sw(first_episode:str, target_str:str):
        """
        把集信息插入合适的位置
        :return: 调整后的字符串、first_episode 下标
        """
        if not target_str.startswith(first_episode):
            return MediaUtils.move_episode_after_season(first_episode, target_str)

        target_str = target_str[len(first_episode):].strip(".-")

        episode_pattern = r"(E\d{1,3})"
        episode_match = re.findall(episode_pattern, target_str)
        if episode_match:
            second_episode = episode_match[0]
            e_index = target_str.find(second_episode)
            # 第二个集信息必须不在开头
            if e_index > 0:
                fep = int(first_episode[1:])
                sep = int(second_episode[1:])
                insert_idx = fep
                if fep != sep:
                    if sep > fep:
                        insert_idx = e_index
                        insert_str = first_episode + '-'
                    else:
                        insert_idx = e_index + len(second_episode)
                        insert_str = '-' + first_episode
                    target_str = target_str[0:insert_idx] + insert_str + target_str[insert_idx:]
                return target_str, insert_idx + 1

        move_result, pos = MediaUtils.move_episode_after_season(first_episode, target_str)
        if pos > -1:
            return move_result, pos
        
        t = PTN.parse(target_str)
        t_title = t.get('title')
        if t_title:
            insert_idx = target_str.find(t_title) + len(t_title)
            splicing = StringUtils.insert_char_at_index(target_str, '.{}.'.format(first_episode), insert_idx)
            return splicing, insert_idx + 1

        splicing = target_str + '.' + first_episode
        return splicing, len(splicing)


    @staticmethod
    def move_episode_after_season(first_episode:str, target_str:str):
        """
        把集信息插入季信息之后
        """
        season_pattern = r"(S\d{1,2})"
        season_match = re.findall(season_pattern, target_str)
        if not season_match:
            return target_str, -1
        
        if len(season_match) > 1:
            return target_str, -1
        
        # 移除first_episode
        target_str = target_str.replace(first_episode, "", 1)
        
        p_index = target_str.find(season_match[0]) + len(season_match[0])
        # 拼接到季信息之后
        splicing = StringUtils.insert_char_at_index(target_str, '.{}.'.format(first_episode), p_index)
        return splicing, p_index + 1