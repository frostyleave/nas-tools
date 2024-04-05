import base64
import json

import log


class JsonObject(object):
    def __init__(self, d):
        self.__dict__ = d


class JsonHelper:

    @staticmethod
    def de_json(json_str):
        """
        json字符串转python对象(dict)
        """
        try:
            return json.loads(json_str)
        except Exception as e:
            log.error(f"【JsonHelper】对象序列化出错：{str(e)}")
            return None

    @staticmethod
    def base64_de_json(base64_str):
        """
        base64转换后的json字符串转python对象(dict)
        """
        try:
            json_str = base64.b64decode(base64_str).decode('utf-8')
            return json.loads(json_str)
        except Exception as e:
            log.error(f"【JsonHelper】对象序列化出错：{str(e)}")
            return None
