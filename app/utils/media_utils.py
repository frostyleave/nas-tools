import cn2an
import PTN
import re

from app.utils.string_utils import StringUtils

import log


class MediaUtils:
    
    @staticmethod
    def format_tv_file_name(title, subtitle):
        """
        格式化剧集文件名
        """
        # 1. 基础清理
        clean_title = title.replace("【", "[").replace("】", "]").strip()

        # 2. 一次性调用完成所有季、集的格式化
        clean_title = MediaUtils._format_media_numbers(clean_title)

        # 3. 最终清理
        clean_title = re.sub(r'\|\s+\|', '|', clean_title)
        clean_title = re.sub(r'\s{2,}', ' ', clean_title).strip()

        return MediaUtils._adjust_tv_se_position(clean_title, subtitle)


    @staticmethod
    def resolve_douban_season_tag(title: str):
        """
        解析豆瓣剧集名称中的季信息
        """
        season_match = re.findall(r'([第][^第]+[季|期|卷])', title)
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
        return MediaUtils._adjust_tv_se_position(clean_title, subtitle)        


    @staticmethod
    def _move_last_char_to_front(text: str, char: str) -> str:
        """
        辅助函数。如果 `text` 以 `char` 结尾，则将其移动到开头。
        示例: "40集全" -> "全40集"
        """
        if text.endswith(char):
            return char + text[:-1]
        return text

    @staticmethod
    def _parse_and_format_numbers(number_section: str, format_str: str, tag: str) -> str:
        """
        解析包含中文或阿拉伯数字的字符串并进行格式化。
        此函数能正确格式化范围 (例如 E01-E40)，使得原代码中最后的 re.sub 不再需要。
        """
        # 查找所有数字部分 (阿拉伯数字或中文数字)
        number_matches = re.findall(r'(\d+|[\u4e00-\u9fa5]+)', number_section)
        
        digits = []
        for num_str in number_matches:
            try:
                digits.append(cn2an.cn2an(num_str, "smart"))
            except (ValueError, KeyError) as e:
                log.error(f"无法将 '{num_str}' 转换为数字: {e}")
                continue
        
        if not digits:
            return ""

        # --- 格式化逻辑 ---
        # 情况1: 处理总集数 (例如, "全40集" -> "E01-E40")
        if tag in ('全', '共') and len(digits) == 1:
            total = digits[0]
            if total > 1:
                # 正确格式化为完整范围
                return f"{format_str}01-{format_str}{total:02d}"
            else:
                return f"{format_str}{total:02d}"
        
        # 情况2: 处理单个数字 (例如, "第21集" -> "E21")
        if len(digits) == 1:
            return f"{format_str}{digits[0]:02d}"
        
        # 情况3: 处理范围或列表 (例如, "21-22" -> "E21-E22")
        if len(digits) >= 2:
            min_num, max_num = min(digits), max(digits)
            if min_num == max_num:
                return f"{format_str}{min_num:02d}"
            # 正确格式化范围，确保前后都有前缀
            return f"{format_str}{min_num:02d}-{format_str}{max_num:02d}"

        return ""

    @staticmethod
    def _format_media_numbers(title: str) -> str:
        """
        在一个函数内，一次性查找并格式化标题中所有的季、集编号
        """
        # 这个统一的正则表达式可以一次性匹配所有需要处理的格式。
        # 它覆盖了：第..季, 第..集, X集全, 以及像 21集 这样的独立数字。
        # 它还允许数字之间有空格、连字符、逗号等多种分隔符

        unified_reg_pattern = r'(' + '|'.join([
            r'[第全共][^第全共]+[季期卷]',  # 季、期模式
            r'[第全共][^第全共]+[集话話]',  # 集数模式  
            r'\d+[集话話]全',               # 数字+集全模式
            r'(?<!第)(?<!全)(?<!共)(?<!\d)\b\d+[集话話]'  # 单独数字+集模式
        ]) + ')'

        matches = list(re.finditer(unified_reg_pattern, title, flags=re.IGNORECASE))
        
        if not matches:
            return title

        try:
            # 从后向前遍历，这样在替换字符串时不会影响前面未处理部分的索引位置
            for match in reversed(matches):
                original_match_str = match.group(0).strip()

                # 1. 根据后缀（季/集）判断是季(S)还是集(E)
                format_str = 'S' if re.search(r'[季期卷]', original_match_str) else 'E'

                # 2. 预处理匹配到的字符串以便解析 (例如, "40集全" -> "全40集")
                processed_match = MediaUtils._move_last_char_to_front(original_match_str, '全')

                # 3. 识别前缀标签 ('第', '全', '共')
                tag = ''
                if processed_match.startswith(('第', '全', '共')):
                    tag = processed_match[0]

                # 4. 用一个通用正则提取出核心的数字部分 (位于前缀和后缀之间)
                number_part_match = re.search(r"[第全共]?(.*?)[季期卷集话話]", processed_match, re.IGNORECASE)
                if not number_part_match:
                    continue
                number_section = number_part_match.group(1).strip()
                
                # 5. 解析数字并创建新的格式化字符串
                new_part = MediaUtils._parse_and_format_numbers(number_section, format_str, tag)
                
                # 6. 在标题中，用新生成的字符串替换原始匹配项
                if new_part:
                    start, end = match.span()
                    title = title[:start] + new_part + title[end:]
                    
        except Exception as e:
            log.exception("格式化标题中的季集编号出错: ")
                
        return title

    @staticmethod
    def _adjust_tv_se_position(filename:str, subtitle:str):
        """
        调整剧集文件的季、集信息所在位置
        """
        # 正则表达式匹配季和集信息
        season_pattern = r"(S\d{1,2})"
        episode_pattern = r"(E\d{1,3})"

        if not subtitle:
            subtitle = ''

        try:
            season_rindex = -1
            episode_rindex = -1
            cleaned_filename = filename
            # 提取集信息
            episode_match = list(re.finditer(episode_pattern, filename, flags=re.IGNORECASE))
            if episode_match:
                # 清除集信息
                cleaned_filename = filename[:episode_match[0].start()] + filename[episode_match[-1].end():]
                episode_rindex = episode_match[0].start()

            season_match = list(re.finditer(season_pattern, cleaned_filename, flags=re.IGNORECASE))        
            if len(season_match) == 1:
                season_name = season_match[0].group()
                cleaned_filename = MediaUtils._insert_season_to_sw(season_name, cleaned_filename, episode_rindex)
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
                            cleaned_filename = MediaUtils._insert_season_to_sw(season_name, cleaned_filename, episode_rindex)
                            season_rindex = cleaned_filename.find(season_name) + len(season_name) + 1
                        else:
                            # 连续剧集范围：不包含符号
                            multi_season = re.findall(r'S\d{1,2}\d{1,2}', cleaned_filename, re.IGNORECASE)
                            if multi_season:
                                season_name = multi_season[0]
                                cleaned_filename = MediaUtils._insert_season_to_sw(season_name, cleaned_filename, episode_rindex)
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

        except Exception as e:
            log.exception("调整剧集文件的季集信息所在位置出错: ")

        return re.sub(r"\s+", " ", cleaned_filename).strip(), subtitle.strip()

    @staticmethod
    def _insert_season_to_sw(first_season:str, target_str:str, episode_rindex:int):
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