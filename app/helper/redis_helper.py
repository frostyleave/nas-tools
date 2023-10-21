import re

from config import Config

REG_IP_PORT = r'^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?::(\d{1,5}))$'

class RedisHelper:

    @staticmethod
    def is_valid():
        """
        判斷redis是否有效
        """
        config = Config().get_config()
        app = config.get('app')
        if not app:
            return False
        # 配置开启  且 有填写ip信息
        if not app.get('redis_enable') or not app.get('redis_addr'):
            return False
        # ip+端口号是否合法
        return True if re.match(REG_IP_PORT, app.get('redis_addr')) else False
