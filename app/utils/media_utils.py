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

        sort_str = ''

        # 标题统一处理为简体中文，简体资源优先
        if re.match(ZHTW_SUB_RE, download_info.title):
            sort_str = '0' + zhconv.convert(download_info.title, 'zh-hans')
        else:
            sort_str = '1' + download_info.title

        # 季集
        se_list = download_info.get_season_list()
        if se_list:
            sort_str += str(se_list[-1]).rjust(4, '0') + str(len(se_list)).rjust(2, '0')

        ep_list = download_info.get_episode_list()
        if ep_list:
            sort_str += str(ep_list[-1]).rjust(4, '0') + str(len(ep_list)).rjust(4, '0')

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
            sort_str += str(download_info.seeders).rjust(5, '0')
        
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
    def format_tv_file_name(title, subtitle):
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

        return MediaUtils.adjust_tv_se_position(clean_title, subtitle)
    
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
    def clean_episode_range_from_file_name(filename: str, subtitle: str):
        """
        清除文件名中的集数范围信息
        """
        episode_pattern = r"([全|共][^全|共]+[集|话|話])|(\d+)(集|话|話)全|(?<!全)(?<!共)(?<!\d)\b\d+[集话話]"
        clean_title = re.sub(episode_pattern, '', filename)
        return MediaUtils.adjust_tv_se_position(clean_title, subtitle)        

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
    def adjust_tv_se_position(filename:str, subtitle:str):
        """
        调整剧集文件的季、集信息所在位置
        """
        # 正则表达式匹配季和集信息
        season_pattern = r"(S\d{1,2})"
        episode_pattern = r"(E\d{1,3})"

        if not subtitle:
            subtitle = ''

        season_rindex = -1
        episode_rindex = -1
        cleaned_filename = filename
        # 提取集信息
        episode_match = list(re.finditer(episode_pattern, filename, flags=re.IGNORECASE))
        if episode_match:
            # 清除集信息
            cleaned_filename = re.sub(episode_pattern, '', filename).strip('.')
            last_one = episode_match[-1].group()
            episode_rindex = (episode_match[-1]).regs[0][0] - sum(len(s.group()) for s in episode_match) + len(last_one)

        season_match = list(re.finditer(season_pattern, cleaned_filename, flags=re.IGNORECASE))        
        if len(season_match) == 1:
            season_name = season_match[0].group()
            cleaned_filename = MediaUtils.insert_season_to_sw(season_name, cleaned_filename, episode_rindex)
            season_rindex = cleaned_filename.find(season_name) + len(season_name) + 1
        elif len(season_match) > 1:
            # 去重后检查真是季数
            real_season = sorted(list(set(list(map(lambda x: x.group().upper().strip('S'), season_match)))))
            if len(real_season) == 1:
                # 移除第一个
                cleaned_filename = cleaned_filename.replace(season_match[0].group(), "", 1)
                season_name = season_match[1].group()
                season_rindex = cleaned_filename.find(season_name) + len(season_name) + 1
            else:
                first_season = season_match[0].group()
                # 仅在开头时做特殊处理
                if cleaned_filename.startswith(first_season):
                    # 连续剧集范围：包含符号
                    multi_season = re.findall(r'S\d{1,2}[-.]\d{1,2}', cleaned_filename, re.IGNORECASE)
                    if multi_season:
                        season_name = multi_season[0]
                        cleaned_filename = MediaUtils.insert_season_to_sw(season_name, cleaned_filename, episode_rindex)
                        season_rindex = cleaned_filename.find(season_name) + len(season_name) + 1
                    else:
                        # 连续剧集范围：不包含符号
                        multi_season = re.findall(r'S\d{1,2}\d{1,2}', cleaned_filename, re.IGNORECASE)
                        if multi_season:
                            season_name = multi_season[0]
                            cleaned_filename = MediaUtils.insert_season_to_sw(season_name, cleaned_filename, episode_rindex)
                            season_rindex = cleaned_filename.find(season_name) + len(season_name) + 1
                        else:
                            # 主标题中移除所有季信息，把季信息移动到副标题
                            last_season_reg = season_match[-1]
                            last_season_name = last_season_reg.group()
                            # 清空季信息
                            cleaned_filename = re.sub(season_pattern, '', cleaned_filename)
                            # 有集信息
                            if episode_rindex > 0:
                                # 检查集数下标是否在季之前
                                behind_seasons = list(filter(lambda x: x.regs[0][0] > episode_rindex, season_match))
                                if len(behind_seasons) == 0:
                                    # 季、集 混着的情况: 插入最后一个季信息所在位置
                                    episode_rindex = (season_match[-1]).regs[0][0] - sum(len(s.group()) for s in season_match) + len(last_season_name)
                                season_name = ' {}-{} '.format(first_season, last_season_name)     
                                cleaned_filename = StringUtils.insert_char_at_index(cleaned_filename, season_name, episode_rindex)
                                season_rindex = cleaned_filename.find(season_name) + len(season_name) + 1
                            else:
                                season_name = ' 第{}-{}季'.format(first_season, last_season_name).replace('S', '').replace('s', '')
                                subtitle += season_name

        # 集
        if episode_match:
            # 去重后排序
            real_ep = sorted(list(set(list(map(lambda x: int(x.group().upper().strip('E')), episode_match)))))
            if len(real_ep) == 1:
                ep_name = ' E{} '.format(real_ep[0])
            else:
                real_ep = list(filter(lambda x: x > 0, real_ep))
                if len(real_ep) == 0:
                    ep_name = ' E00 '
                elif len(real_ep) == 1:
                    ep_name = ' E{} '.format(str(real_ep[0]).rjust(2, '0'))
                else:
                    ep_name = ' E{}-{} '.format(str(real_ep[0]).rjust(2, '0'), str(real_ep[-1]).rjust(2, '0'))

            if season_rindex > 0:
                cleaned_filename = StringUtils.insert_char_at_index(cleaned_filename, ep_name, season_rindex)
            elif episode_rindex > 0:
                cleaned_filename = StringUtils.insert_char_at_index(cleaned_filename, ep_name, episode_rindex)
            else:
                subtitle += ' 第{}集'.format(ep_name).replace('E', '')
                
        return re.sub(r"\s+", " ", cleaned_filename).strip(), subtitle.strip()

    @staticmethod
    def insert_season_to_sw(first_season:str, target_str:str, episode_rindex:int):
        """
        把季信息插入合适的位置
        """
        if not target_str.startswith(first_season):
            return target_str
        
        target_str = target_str[len(first_season):].strip(".-")

        if episode_rindex > 0:
            return StringUtils.insert_char_at_index(target_str, ' {} '.format(first_season), episode_rindex)                
        
        t = PTN.parse(target_str)
        t_title = t.get('title')
        if t_title:
            insert_pos = target_str.find(t_title) + len(t_title)
            return StringUtils.insert_char_at_index(target_str, ' {} '.format(first_season), insert_pos)
        
        return target_str + ' ' + first_season

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