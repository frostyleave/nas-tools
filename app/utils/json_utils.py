import json
from enum import Enum

import log


class JsonUtils:

    @staticmethod
    def loads(text, default=None, silent=False):
        """
        安全解析 JSON 字符串，解析失败时返回默认值而不是抛出异常

        :param text: JSON 字符串、bytes，或已解析的 dict/list（原样返回）
        :param default: 解析失败或内容为空时返回的默认值
        :param silent: 解析失败时是否不输出错误日志
        :return: 解析结果或默认值
        """
        if isinstance(text, (dict, list)):
            return text
        if not text:
            return default
        try:
            return json.loads(text)
        except (TypeError, ValueError) as e:
            if not silent:
                log.error(f"【Json】解析 JSON 失败：{e!s}")
            return default

    @staticmethod
    def json_serializable(obj):
        """
        将普通对象转化为支持json序列化的对象
        @param obj: 待转化的对象
        @return: 支持json序列化的对象
        """

        def _try(o):
            if isinstance(o, Enum):
                return o.value
            try:
                return o.__dict__
            except Exception as err:
                print(str(err))
                return str(o)

        return json.loads(json.dumps(obj, default=lambda o: _try(o)))
