import ssl

from requests.adapters import HTTPAdapter

# 创建一个自定义的 SSL 上下文，忽略 EOF 错误
class SSLAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context()
        # 核心设置：允许非预期的 EOF
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        kwargs['ssl_context'] = context
        return super().init_poolmanager(*args, **kwargs)
