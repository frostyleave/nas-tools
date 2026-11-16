from threading import Lock
from typing import Any, ClassVar

from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MISSED,
    EVENT_JOB_SUBMITTED,
)
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.job import Job
from apscheduler.schedulers import (
    SchedulerAlreadyRunningError,
    SchedulerNotRunningError,
)
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import STATE_STOPPED

import log
from app.utils.commons import singleton
from app.utils.scheduler_desc_utils import SchedulerDescUtils
from config import Config


@singleton
class JobCenter:

    _timezone = Config().get_timezone()

    # 系统任务管理器
    _sys_scheduler : BackgroundScheduler = BackgroundScheduler(timezone=_timezone, executors={"default": ThreadPoolExecutor(5)})
    _sys_scheduler.name = '系统任务管理器'

    # 插件任务管理器
    _plg_scheduler : BackgroundScheduler = BackgroundScheduler(timezone=_timezone, executors={"default": ThreadPoolExecutor(5)})
    _plg_scheduler.name = '插件任务管理器'

    _scheduler_list : ClassVar[list] = (_sys_scheduler, _plg_scheduler)

    def __init__(self):

        # 正在执行的任务计数：job_id -> 尚未结束的执行实例数
        # 不用集合的原因：APScheduler 的 EVENT_JOB_SUBMITTED 是在整批到期任务全部提交后
        # 才统一派发的，而 EVENT_JOB_EXECUTED/ERROR 由工作线程在任务跑完后立即派发。
        # 执行极快的任务（如“清理未识别缓存”）可能结束事件先到，用集合会出现
        # “结束丢弃空转、开始又加回去”的永久卡“执行中”；改计数后 -1 与 +1 仍能配平归零。
        self._running_counts: dict[str, int] = {}
        self._running_lock = Lock()

        # BackgroundScheduler init
        for _scheduler in self._scheduler_list:
            # 注册事件监听器（MISSED 也要监听，否则错过的执行永远不会从计数中扣除）
            _scheduler.add_listener(self._job_start_listener, EVENT_JOB_SUBMITTED)
            _scheduler.add_listener(
                self._job_end_listener,
                EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED
            )

        self.init_config()

    def init_config(self):
        """
        配置变更后重建定时任务

        注意：APScheduler 的 executor 在 shutdown() 后不可复用，再次 start() 后提交任务会报
        “cannot schedule new futures after shutdown”。因此重载配置时只清空任务，不关闭调度器。
        """
        self._clear_jobs()
        self.run_service()

    def run_service(self):
        """
        启动定时服务（已在运行则跳过）
        """
        if not self._scheduler_list:
            return

        for _scheduler in self._scheduler_list:
            if _scheduler.state != STATE_STOPPED:
                log.debug(f'【System】定时服务({_scheduler.name})已在运行中')
                continue
            try:
                _scheduler.start()
                log.info(f'【System】定时服务({_scheduler.name})已启动')
            except SchedulerAlreadyRunningError:
                log.info(f'【System】定时服务({_scheduler.name})已在运行中..')
            except Exception as e:
                log.exception(f'【System】启动定时服务({_scheduler.name})出错: ')

    def _clear_jobs(self):
        """清空所有已注册任务，但保持调度器及其 executor 可用"""
        for _scheduler in self._scheduler_list:
            try:
                _scheduler.remove_all_jobs()
            except Exception as e:
                log.exception(f'【System】清理定时任务({_scheduler.name})出错: ')
        self._clear_running_counts()

    def stop_service(self):
        """
        停止定时服务
        """
        if not self._scheduler_list:
            return
        
        for _scheduler in self._scheduler_list:
            try:
                if _scheduler:
                    _scheduler.remove_all_jobs()
                    if _scheduler.state != STATE_STOPPED:
                        _scheduler.shutdown()
            except SchedulerNotRunningError as ex:
                log.debug(f'【System】定时服务({_scheduler.name})不在运行中')
            except Exception as e:
                log.exception(f'【System】停止定时服务({_scheduler.name})出错: ')

        self._clear_running_counts()

    def get_sys_scheduler(self) -> BackgroundScheduler:
        """获取系统任务管理器"""
        return self._sys_scheduler

    def get_plugin_scheduler(self) -> BackgroundScheduler:
        """获取插件任务管理器"""
        return self._plg_scheduler
    
    def get_job(self, job_id: str) -> Job | None:
        """获取单个 job 实例"""
        job = self._sys_scheduler.get_job(job_id)
        if job:
            return job
        return self._plg_scheduler.get_job(job_id)
    
    def get_jobs(self) -> list[dict[str, Any]]:
        """
        获取所有已注册的任务，并将其格式化为适合 API 返回的列表。
        """
        jobs_list = []

        for _scheduler in self._scheduler_list:

            # 1. 调用底层的 get_jobs()
            all_jobs = _scheduler.get_jobs()

            if not all_jobs:
                continue

            # 是否插件任务
            from_plugin = _scheduler is self._plg_scheduler

            # 2. 遍历 Job 对象，将其转换为字典
            for job in all_jobs:
                job_data = {
                    "id": job.id,
                    "name": job.name or job.id, # 如果 name 为空，则使用 id
                    "func_ref": str(job.func_ref), # 运行的函数
                    "trigger_type": str(job.trigger.__class__.__name__), # 'IntervalTrigger', 'CronTrigger', 'DateTrigger'
                    "trigger_details": str(job.trigger), # 触发器的详细信息 (例如 "interval[0:00:10]")
                    "trigger_text": SchedulerDescUtils.describe(job.trigger), # 执行频率的文字描述
                    "pending": job.pending, # 是否待处理
                    "running": self._is_job_running(job.id), # 是否正在执行
                    "from_plugin": from_plugin, # 是否来自插件
                }
                
                # 3. 安全地处理 next_run_time (它可能为 None)
                if job.next_run_time:
                    # 转换为 ISO 8601 字符串格式，这是 JSON 标准
                    job_data["next_run_time"] = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    job_data["next_run_time"] = None
                    
                jobs_list.append(job_data)
                
        return jobs_list

    def print_jobs(self):
        if not self._scheduler_list:
            return
        for _scheduler in self._scheduler_list:
            _scheduler.print_jobs()

    def _change_running_count(self, job_id, delta):
        """调整任务执行计数；归零时删除，负值保留用于配平先到的结束事件"""
        with self._running_lock:
            count = self._running_counts.get(job_id, 0) + delta
            if count == 0:
                self._running_counts.pop(job_id, None)
            else:
                self._running_counts[job_id] = count

    def _is_job_running(self, job_id):
        """任务是否正在执行"""
        with self._running_lock:
            return self._running_counts.get(job_id, 0) > 0

    def _clear_running_counts(self):
        """清空任务执行计数"""
        with self._running_lock:
            self._running_counts.clear()

    def _job_start_listener(self, event):
        """监听 job 开始执行"""
        # 一次提交可能包含多个执行时间点，需要按实际执行次数计数
        self._change_running_count(event.job_id, len(event.scheduled_run_times) or 1)
        job = self.get_job(event.job_id)
        if job:
            job_name = job.name or job.id
            log.debug("--- [Job 开始] --- 任务: %s (id=%s) 准备执行...", job_name, str(job.id))
        else:
            log.debug("--- [Job 开始] --- 无法查询到id=%s 的任务", str(event.job_id))

    def _job_end_listener(self, event):
        """监听 job 执行完毕（成功、失败或错过执行时间）"""
        self._change_running_count(event.job_id, -1)
        job = self.get_job(event.job_id)
        if not job:
            return
            
        job_name = job.name or job.id
        
        if event.code == EVENT_JOB_EXECUTED:
            # 成功
            next_run = job.next_run_time
            if next_run:
                log.debug("--- [Job 成功] --- 任务 %s (id=%s) 执行成功, 下次执行时间 %s", job_name, str(job.id), job.next_run_time.strftime('%Y-%m-%d %H:%M:%S %Z'))
            else:
                log.debug("--- [Job 成功] --- 任务 %s (id=%s) 已执行完毕", job_name, str(job.id))
                
        elif event.code == EVENT_JOB_ERROR:
            # 失败
            log.exception("[Job]%s 失败, 错误信息: %s", job_name, event.exception)
            next_run = job.next_run_time
            if next_run:
                log.warn("--- [Job 失败] --- 任务: %s (id=%s) 执行失败, 下次执行时间 %s", job_name, str(job.id), job.next_run_time.strftime('%Y-%m-%d %H:%M:%S %Z'))
            else:
                log.warn("--- [Job 失败] --- 任务: %s (id=%s) 执行失败", job_name, str(job.id))