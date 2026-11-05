import threading
import time
import urllib.parse
from collections import OrderedDict

# 线程锁
lock = threading.RLock()

# ------------------------
# 日志脱敏
# ------------------------
# 掩码文本
MASK_TEXT = "******"
# 命中以下关键字的字段（忽略大小写、下划线、连字符）视为敏感信息
SENSITIVE_KEYWORDS = (
    "password", "passwd", "pwd", "secret", "token", "cookie",
    "apikey", "authorization", "credential", "privatekey",
)


def is_sensitive_key(key) -> bool:
    """
    判断字段名是否为敏感字段
    """
    if not key:
        return False
    name = str(key).strip().lower().replace("_", "").replace("-", "")
    return any(keyword in name for keyword in SENSITIVE_KEYWORDS)


def mask_value(value):
    """
    对敏感值做掩码，保留少量首尾字符便于排查
    """
    if value is None:
        return value
    text = str(value)
    if not text:
        return text
    if len(text) <= 8:
        return MASK_TEXT
    return f"{text[:4]}{MASK_TEXT}{text[-2:]}"


def mask_sensitive(data, depth: int = 0):
    """
    递归脱敏字典/列表中的敏感字段，其余字段原样返回
    """
    if depth > 10:
        return MASK_TEXT
    if isinstance(data, dict):
        return {
            key: mask_value(value) if is_sensitive_key(key) else mask_sensitive(value, depth + 1)
            for key, value in data.items()
        }
    if isinstance(data, (list, tuple)):
        return [mask_sensitive(item, depth + 1) for item in data]
    return data


def mask_url(url):
    """
    隐藏 URL 查询参数中的敏感值（如 api_key/token/corpsecret）
    """
    if not url:
        return url
    try:
        parts = urllib.parse.urlsplit(str(url))
        if not parts.query:
            return str(url)
        query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        masked = [
            (key, mask_value(value) if is_sensitive_key(key) else value)
            for key, value in query
        ]
        return urllib.parse.urlunsplit(
            parts._replace(query=urllib.parse.urlencode(masked, safe="*")))
    except Exception:
        return MASK_TEXT

# 全局实例
INSTANCES = OrderedDict()


# 单例模式注解
def singleton(cls):
    # 创建字典用来保存类的实例对象
    global INSTANCES

    def _singleton(*args, **kwargs):
        # 先判断这个类有没有对象
        if cls not in INSTANCES:
            with lock:
                if cls not in INSTANCES:
                    INSTANCES[cls] = cls(*args, **kwargs)
        # 将实例对象返回
        return INSTANCES[cls]

    return _singleton


# 重试装饰器
def retry(ExceptionToCheck, tries=3, delay=3, backoff=2, logger=None):
    """
    :param ExceptionToCheck: 需要捕获的异常
    :param tries: 重试次数
    :param delay: 延迟时间
    :param backoff: 延迟倍数
    :param logger: 日志对象
    """

    def deco_retry(f):
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    return f(*args, **kwargs)
                except ExceptionToCheck as e:
                    msg = f"{e!s}, {mdelay} 秒后重试 ..."
                    if logger:
                        logger.warning(msg)
                    else:
                        print(msg)
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            return f(*args, **kwargs)

        return f_retry

    return deco_retry
