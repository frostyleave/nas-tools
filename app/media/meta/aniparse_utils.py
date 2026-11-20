"""
aniparse 解析结果读取工具

aniparse 的输出是嵌套结构：名称/季/集/年份位于 series[0] 中，
分辨率、编码等为对象或列表。这里集中做兼容处理，供 MetaAnime / MetaInfo 使用。
"""
import aniparse

import log

# aniparse 将 4K/8K 这类写法记为宽度（4000/8000），这里转换回常见的高度写法
_K_RESOLUTION_HEIGHT = {1: 1080, 2: 1440, 4: 2160, 8: 4320}


def parse(filename: str) -> dict | None:
    """
    调用 aniparse 解析名称，空字符串或解析失败时返回 None
    """
    if not filename or not filename.strip():
        return None
    try:
        return aniparse.parse(filename)
    except Exception:
        log.debug(f"【Meta】aniparse 解析[{filename}]出错")
        return None


def get_series(info: dict | None, index: int = 0) -> dict:
    """
    获取 series 列表中的指定项，不存在时返回空字典
    """
    if not info:
        return {}
    series = info.get("series") or []
    if index >= len(series):
        return {}
    return series[index] or {}


def get_first(info: dict | None, key: str):
    """
    获取列表型字段的第一个值
    """
    if not info:
        return None
    value = info.get(key)
    if isinstance(value, list):
        return value[0] if value else None
    return value


def get_title(info: dict | None) -> str | None:
    """
    获取识别出的名称
    """
    return get_series(info).get("title")


def get_release_group(info: dict | None) -> str | None:
    """
    获取制作组/字幕组
    """
    return get_first(info, "release_group")


def _sequence_numbers(sequences: list | None) -> list:
    """
    将 aniparse 的序列展开为数字列表，支持单值、区间及多值
    """
    numbers = []
    for sequence in sequences or []:
        if not isinstance(sequence, dict):
            numbers.append(sequence)
        elif "number" in sequence:
            numbers.append(sequence.get("number"))
        elif "start" in sequence or "end" in sequence:
            start = sequence.get("start") or {}
            end = sequence.get("end") or {}
            numbers.extend([start.get("number"), end.get("number")])
    return [number for number in numbers if number is not None]


def get_year(info: dict | None) -> int | float | None:
    """
    获取年份
    """
    years = _sequence_numbers(get_series(info).get("year"))
    return years[0] if years else None


def get_season_range(info: dict | None) -> tuple:
    """
    获取季号范围，(开始季, 结束季)，无季号时返回 (None, None)
    """
    return _get_range(get_series(info).get("season"))


def get_episode_range(info: dict | None) -> tuple:
    """
    获取集号范围，(开始集, 结束集)，无集号时返回 (None, None)
    """
    return _get_range(get_series(info).get("episode"))


def _get_range(sequences: list | None) -> tuple:
    numbers = _sequence_numbers(sequences)
    if not numbers:
        return None, None
    begin = numbers[0]
    end = numbers[-1] if numbers[-1] != begin else None
    return begin, end


def get_type(info: dict | None) -> str | None:
    """
    获取类型关键字（TV/Movie/OVA 等）
    """
    return get_series(info).get("type")


def get_resolution(info: dict | None) -> str | None:
    """
    获取分辨率，统一为 1080p 这种格式
    """
    if not info:
        return None
    resolutions = info.get("video_resolution")
    if not resolutions:
        return None
    resolution = resolutions[0]
    if not isinstance(resolution, dict):
        return str(resolution)
    height = resolution.get("video_height")
    if height:
        return f"{height}p"
    width = resolution.get("video_width")
    if width:
        if width % 1000 == 0 and width // 1000 in _K_RESOLUTION_HEIGHT:
            return f"{_K_RESOLUTION_HEIGHT[width // 1000]}p"
        return f"{width}p"
    return None


def get_video_term(info: dict | None) -> str | None:
    """
    获取视频编码
    """
    return get_first(info, "video_term")


def get_audio_term(info: dict | None) -> str | None:
    """
    获取音频编码
    """
    return get_first(info, "audio_term")
