"""
zhconv 兼容层

项目内只使用 ``convert(text, 'zh-hans')`` 和 ``issimp(text)``，
底层改为维护更活跃、无 pkg_resources 依赖的 OpenCC。

OpenCC 的转换器实例不是线程安全的，这里用单例 + 锁串行调用；
转换本身是微秒级操作，锁开销可以忽略。
"""

import threading

from opencc import OpenCC

_lock = threading.Lock()
_converter = None


def _get_converter() -> OpenCC:
    global _converter
    if _converter is None:
        _converter = OpenCC("t2s")
    return _converter


def convert(text: str, locale: str = "zh-hans") -> str:
    """
    繁体转简体，保持与 zhconv.convert 一致的调用方式

    :param text: 待转换文本
    :param locale: 目前仅支持 zh-hans / zh-cn
    :return: 转换后的文本
    """
    if not text:
        return text
    if locale not in ("zh-hans", "zh-cn"):
        raise ValueError(f"zhconv_compat: unsupported locale: {locale}")

    with _lock:
        return _get_converter().convert(text)


def issimp(text: str) -> bool:
    """
    判断文本是否为简体

    :param text: 待判断文本
    :return: 是否全部为简体
    """
    return convert(text) == text
