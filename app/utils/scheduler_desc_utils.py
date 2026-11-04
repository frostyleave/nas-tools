from datetime import timedelta
from itertools import pairwise
from typing import ClassVar

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger


class SchedulerDescUtils:
    """
    APScheduler 触发器描述工具
    """

    # APScheduler 的 day_of_week：0 为周一，6 为周日
    _WEEKDAY_NAMES: ClassVar[dict[str, str]] = {
        "0": "周一",
        "1": "周二",
        "2": "周三",
        "3": "周四",
        "4": "周五",
        "5": "周六",
        "6": "周日",
        "mon": "周一",
        "tue": "周二",
        "wed": "周三",
        "thu": "周四",
        "fri": "周五",
        "sat": "周六",
        "sun": "周日",
    }

    @classmethod
    def describe(cls, trigger) -> str:
        """
        生成任务的执行频率描述，无法识别时返回空串
        """
        if isinstance(trigger, IntervalTrigger):
            return cls._describe_interval(trigger.interval)
        if isinstance(trigger, CronTrigger):
            return cls._describe_cron(trigger)
        if isinstance(trigger, DateTrigger):
            return "仅执行一次"
        return ""

    @classmethod
    def _describe_interval(cls, interval: timedelta) -> str:
        """
        将时间间隔转换为「每X天X小时X分钟X秒」
        """
        total_seconds = int(interval.total_seconds())
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)

        parts = []
        if days:
            parts.append(f"{days}天")
        if hours:
            parts.append(f"{hours}小时")
        if minutes:
            parts.append(f"{minutes}分钟")
        if seconds:
            parts.append(f"{seconds}秒")
        return f"每{''.join(parts)}" if parts else "立即执行"

    @classmethod
    def _describe_cron(cls, trigger: CronTrigger) -> str:
        """
        将常见的 cron 规则转换为中文描述，无法识别时返回空串
        """
        values = {
            field.name: ",".join(str(expression) for expression in field.expressions)
            for field in trigger.fields
        }
        year = values.get("year", "*")
        month = values.get("month", "*")
        day = values.get("day", "*")
        weekday = values.get("day_of_week", "*")
        hour = values.get("hour", "*")
        minute = values.get("minute", "*")

        # 秒级、年份、周序号等复杂规则不做展开，避免描述过长或产生歧义
        if values.get("second", "0") not in ("0", "*") or year != "*" or values.get("week", "*") != "*":
            return ""

        day_text = cls._describe_cron_day(month, day, weekday)
        if day_text is None:
            return ""

        # 每小时内的执行规则
        if hour == "*":
            if minute == "*":
                return cls._decorate_day(day_text, "每分钟")
            if minute.startswith("*/") and minute[2:].isdigit():
                return cls._decorate_day(day_text, f"每{minute[2:]}分钟")

            minutes = cls._parse_cron_numbers(minute, 0, 59)
            if not minutes:
                return ""
            if minutes == [0]:
                return cls._decorate_day(day_text, "每小时整点")
            return cls._decorate_day(day_text, f"每小时第{cls._format_minutes(minutes)}分钟")

        # 每 N 小时
        if hour.startswith("*/") and hour[2:].isdigit():
            if minute == "*":
                return cls._decorate_day(day_text, f"每{hour[2:]}小时内的每分钟")
            minutes = cls._parse_cron_numbers(minute, 0, 59)
            if not minutes:
                return ""
            if minutes == [0]:
                return cls._decorate_day(day_text, f"每{hour[2:]}小时")
            return cls._decorate_day(day_text, f"每{hour[2:]}小时的第{cls._format_minutes(minutes)}分钟")

        hours = cls._parse_cron_numbers(hour, 0, 23)
        minutes = cls._parse_cron_numbers(minute, 0, 59)
        if not hours or not minutes:
            return ""

        # 固定小时 + 每分钟
        if minute == "*":
            if len(hours) == 1:
                return f"{day_text} {hours[0]:02d}:00 至 {hours[0]:02d}:59 每分钟"
            return ""

        # 连续多个小时：归纳为时间段，避免罗列大量时间点
        if len(hours) >= 3 and cls._is_contiguous(hours):
            if len(minutes) == 1:
                return (
                    f"{day_text} {hours[0]:02d}:{minutes[0]:02d} 至 "
                    f"{hours[-1]:02d}:{minutes[0]:02d}（每小时）"
                )
            return (
                f"{day_text} {hours[0]:02d}:00 至 {hours[-1]:02d}:59，"
                f"每小时第{cls._format_minutes(minutes)}分钟"
            )

        # 具体时间点（小时/分钟均支持列表、范围）
        times = [f"{hour_value:02d}:{minute_value:02d}" for hour_value in hours for minute_value in minutes]
        if len(times) > 12:
            return ""
        return f"{day_text} {'、'.join(times)}"

    @classmethod
    def _describe_weekday(cls, value: str) -> str:
        """
        将 day_of_week 字段（如 1、1-5、mon,wed）转换为中文
        """
        parts = []
        for item in value.split(","):
            if "-" in item:
                start, end = item.split("-", 1)
                parts.append(
                    f"{cls._WEEKDAY_NAMES.get(start.lower(), start)}至"
                    f"{cls._WEEKDAY_NAMES.get(end.lower(), end)}"
                )
            else:
                parts.append(cls._WEEKDAY_NAMES.get(item.lower(), item))
        return "、".join(parts)

    @staticmethod
    def _parse_cron_numbers(value: str, min_value: int, max_value: int) -> list[int] | None:
        """
        解析 cron 数字字段（如 1,2、9-18、*/2），无法解析时返回 None
        """
        numbers: list[int] = []
        for item in value.split(","):
            item = item.strip()
            if not item:
                return None

            step = 1
            if "/" in item:
                base, step_text = item.split("/", 1)
                if not step_text.isdigit() or int(step_text) <= 0:
                    return None
                step = int(step_text)
            else:
                base = item

            if base == "*":
                start, end = min_value, max_value
            elif "-" in base:
                start_text, end_text = base.split("-", 1)
                if not start_text.isdigit() or not end_text.isdigit():
                    return None
                start, end = int(start_text), int(end_text)
            elif base.isdigit():
                start = end = int(base)
            else:
                return None

            if start < min_value or end > max_value or start > end:
                return None
            numbers.extend(range(start, end + 1, step))

        # 去重并保持顺序
        return list(dict.fromkeys(numbers))

    @staticmethod
    def _is_contiguous(numbers: list[int]) -> bool:
        """
        判断数字列表是否连续
        """
        return all(current - previous == 1 for previous, current in pairwise(numbers))

    @staticmethod
    def _format_minutes(minutes: list[int]) -> str:
        """
        将分钟列表格式化为「0、30」或「10至20」
        """
        if len(minutes) > 1 and SchedulerDescUtils._is_contiguous(minutes):
            return f"{minutes[0]}至{minutes[-1]}"
        return "、".join(str(minute) for minute in minutes)

    @staticmethod
    def _decorate_day(day_text: str, text: str) -> str:
        """
        为频率描述补充日期前缀，「每天」时省略
        """
        return text if day_text == "每天" else f"{day_text}{text}"

    @classmethod
    def _describe_cron_day(cls, month: str, day: str, weekday: str) -> str | None:
        """
        生成 cron 的日期部分描述，无法识别时返回 None
        """
        if weekday != "*" and day == "*" and month == "*":
            return cls._describe_weekday(weekday)
        if day != "*" and weekday == "*" and month == "*":
            return f"每月{day}日"
        if month != "*" and day != "*" and weekday == "*":
            return f"{month}月{day}日"
        if month == "*" and day == "*" and weekday == "*":
            return "每天"
        return None
