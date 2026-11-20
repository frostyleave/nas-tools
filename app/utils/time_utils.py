import time
from datetime import datetime
from zoneinfo import ZoneInfo

from config import Config

# 默认时区，与 config.py 中保持一致
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class TimeUtils:
    """
    统一的时间工具：所有时间均按应用配置的时区生成/转换，
    不依赖进程自身时区，避免容器时区与本地时区不一致时显示错误。
    """

    @staticmethod
    def get_timezone():
        """
        获取配置的时区对象，无效时返回 None
        """
        tz_name = Config().get_timezone() or DEFAULT_TIMEZONE
        try:
            return ZoneInfo(tz_name)
        except Exception:
            return None

    @staticmethod
    def now() -> datetime:
        """
        配置时区下的当前本地时间（不带 tzinfo，可直接替代 datetime.now()）
        """
        timezone = TimeUtils.get_timezone()
        if timezone is None:
            return datetime.now()
        return datetime.now(timezone).replace(tzinfo=None)

    @staticmethod
    def now_str(date_format: str = DEFAULT_TIME_FORMAT) -> str:
        """
        配置时区下的当前时间字符串
        """
        return TimeUtils.now().strftime(date_format)

    @staticmethod
    def timestamp_to_datetime(timestamp) -> datetime:
        """
        时间戳转配置时区下的本地时间（不带 tzinfo）
        """
        timezone = TimeUtils.get_timezone()
        if timezone is None:
            return datetime.fromtimestamp(timestamp)
        return datetime.fromtimestamp(timestamp, timezone).replace(tzinfo=None)

    @staticmethod
    def timestamp_to_str(timestamp, date_format: str = DEFAULT_TIME_FORMAT) -> str:
        """
        时间戳转配置时区下的时间字符串
        """
        try:
            return TimeUtils.timestamp_to_datetime(timestamp).strftime(date_format)
        except Exception:
            return ""

    @staticmethod
    def localtime(timestamp=None):
        """
        获取配置时区下的 struct_time，供 logging.Formatter 等使用
        """
        if timestamp is None:
            timestamp = time.time()
        timezone = TimeUtils.get_timezone()
        if timezone is None:
            return time.localtime(timestamp)
        return datetime.fromtimestamp(timestamp, timezone).timetuple()
