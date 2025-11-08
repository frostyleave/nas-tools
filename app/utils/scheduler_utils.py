import datetime
import math
import random

from typing import Optional

from apscheduler.job import Job
from apscheduler.triggers.cron import CronTrigger
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.util import undefined

import log


class SchedulerUtils:

    @staticmethod
    def add_job(scheduler:BackgroundScheduler, func, func_desc:str, cron:str, next_run_time=undefined) -> Optional[Job]:
        """
        解析任务的定时规则,启动定时服务
        :param func: 可调用的一个函数,在指定时间运行
        :param func_desc: 函数的描述,在日志中提现
        :param cron 时间表达式 三种配置方法：
        :param next_run_time: 下次运行时间
          1、配置cron表达式, 只支持5位的cron表达式
          2、配置时间范围, 如08:00-09:00, 表示在该时间范围内随机执行一次
          3、配置固定时间, 如08:00
          4、配置间隔, 单位小时, 比如23.5
        """
        if not cron:
            log.warn(f"[计划任务]%s 缺少cron表达式 ", func_desc)
            return None

        cron = cron.strip()
        if cron.count(" ") == 4:
            try:
                return scheduler.add_job(func=func,
                                         name=func_desc,
                                         trigger=CronTrigger.from_crontab(cron),
                                         next_run_time=next_run_time)
            except Exception as e:
                log.exception(f'[计划任务]{func_desc}创建失败, 时间cron表达式配置格式错误', e)
                return None
            
        if '-' in cron:
            try:
                time_range = cron.split("-")
                start_time_range_str = time_range[0]
                end_time_range_str = time_range[1]
                start_time_range_array = start_time_range_str.split(":")
                end_time_range_array = end_time_range_str.split(":")
                start_hour = int(start_time_range_array[0])
                start_minute = int(start_time_range_array[1])
                end_hour = int(end_time_range_array[0])
                end_minute = int(end_time_range_array[1])

                def start_random_job():
                    task_time_count = random.randint(start_hour * 60 + start_minute, end_hour * 60 + end_minute)
                    SchedulerUtils.start_range_job(scheduler=scheduler,
                                                   func=func,
                                                   func_desc=func_desc,
                                                   hour=math.floor(task_time_count / 60),
                                                   minute=task_time_count % 60,
                                                   next_run_time=next_run_time)

                random_job = scheduler.add_job(start_random_job,
                                               "cron",
                                               name=func_desc,
                                               hour=start_hour,
                                               minute=start_minute,
                                               next_run_time=next_run_time)
                return random_job
            except Exception as e:
                log.exception(f'[计划任务]{func_desc}创建失败, 时间范围随机模式 配置格式错误：', e)
                return None
            
        if cron.find(':') != -1:
            try:
                hour = int(cron.split(":")[0])
                minute = int(cron.split(":")[1])
            except Exception as e:
                log.exception(f'[计划任务]{func_desc}时间 配置格式错误, 调整为0时0分执行: ', e)
                hour = minute = 0

            time_job = scheduler.add_job(func,
                                         "cron",
                                         name=func_desc,
                                         hour=hour,
                                         minute=minute,
                                         next_run_time=next_run_time)
            return time_job
        # 小时间隔任务
        try:
            hours = float(cron)
        except Exception as e:
            log.exception(f'[计划任务]{func_desc}时间 配置格式错误：', e)
            return None
        
        interval_job = scheduler.add_job(func,
                                         "interval",
                                         name=func_desc,
                                         hours=hours,
                                         next_run_time=next_run_time)
        return interval_job

    @staticmethod
    def start_range_job(scheduler:BackgroundScheduler, func, func_desc, hour, minute, next_run_time=None) -> Optional[Job]:
        year = datetime.datetime.now().year
        month = datetime.datetime.now().month
        day = datetime.datetime.now().day
        # 随机数从1秒开始, 不在整点签到
        second = random.randint(1, 59)
        log.info("%s到时间 即将在%s-%s-%s,%s:%s:%s签到" % (
            func_desc, str(year), str(month), str(day), str(hour), str(minute), str(second)))
        if hour < 0 or hour > 24:
            hour = -1
        if minute < 0 or minute > 60:
            minute = -1
        if hour < 0 or minute < 0:
            log.warn("%s时间 配置格式错误：不启动任务" % func_desc)
            return None
        return scheduler.add_job(func,
                                 "date",
                                 name=func_desc,
                                 run_date=datetime.datetime(year, month, day, hour, minute, second),
                                 next_run_time=next_run_time)

    @staticmethod
    def quartz_cron_compatible(cron_expr):
        if not cron_expr:
            return cron_expr
        
        values = cron_expr.split()
        if len(values) != 6:
            return cron_expr
        # 移除最左边的“秒”部分
        return ' '.join(values[1:])