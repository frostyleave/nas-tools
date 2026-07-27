from typing import Any, Dict, List, Optional

from apscheduler.job import Job
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers import SchedulerNotRunningError, SchedulerAlreadyRunningError
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import STATE_STOPPED
from apscheduler.events import (
    EVENT_JOB_SUBMITTED,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_ERROR
)

import log

from app.utils.commons import singleton
from config import Config


@singleton
class JobCenter:

    _timezone = Config().get_timezone()

    # 系统任务管理器
    _sys_scheduler : BackgroundScheduler = BackgroundScheduler(timezone=_timezone, executors={"default": ThreadPoolExecutor(5)})
    setattr(_sys_scheduler, 'name', '系统任务管理器')

    # 插件任务管理器
    _plg_scheduler : BackgroundScheduler = BackgroundScheduler(timezone=_timezone, executors={"default": ThreadPoolExecutor(5)})
    setattr(_plg_scheduler, 'name', '插件任务管理器')

    _scheduler_list = [
        _sys_scheduler,
        _plg_scheduler
    ]

    def __init__(self):

        # BackgroundScheduler init
        for _scheduler in self._scheduler_list:
            # 注册事件监听器
            _scheduler.add_listener(self._job_start_listener, EVENT_JOB_SUBMITTED)
            _scheduler.add_listener(self._job_end_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

        self.init_config()

    def init_config(self):
        self.stop_service()
        self.run_service()

    def run_service(self):
        """
        读取配置，启动定时服务
        """
        if not self._scheduler_list:
            return
        
        for _scheduler in self._scheduler_list:
            try:
                _scheduler.start()
                log.info(f'[System]定时服务({_scheduler.name})已启动')
            except SchedulerAlreadyRunningError as ex:
                log.info(f'[System]定时服务({_scheduler.name})已在运行中..')
            except Exception as e:
                log.exception(f'[System]启动定时服务({_scheduler.name})出错: ')    

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
                log.debug(f'[System]定时服务({_scheduler.name})不在运行中')
            except Exception as e:
                log.exception(f'[System]停止定时服务({_scheduler.name})出错: ')
   
    def get_sys_scheduler(self) -> BackgroundScheduler:
        """获取系统任务管理器"""
        return self._sys_scheduler

    def get_plugin_scheduler(self) -> BackgroundScheduler:
        """获取插件任务管理器"""
        return self._plg_scheduler
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """获取单个 job 实例"""
        job = self._sys_scheduler.get_job(job_id)
        if job:
            return job
        return self._plg_scheduler.get_job(job_id)
    
    def get_jobs(self) -> List[Dict[str, Any]]:
        """
        获取所有已注册的任务，并将其格式化为适合 API 返回的列表。
        """
        jobs_list = []

        for _scheduler in self._scheduler_list:
        
            # 1. 调用底层的 get_jobs()
            all_jobs = _scheduler.get_jobs()
            
            if not all_jobs:
                continue
                
            # 2. 遍历 Job 对象，将其转换为字典
            for job in all_jobs:
                job_data = {
                    "id": job.id,
                    "name": job.name or job.id, # 如果 name 为空，则使用 id
                    "func_ref": str(job.func_ref), # 运行的函数
                    "trigger_type": str(job.trigger.__class__.__name__), # 'IntervalTrigger', 'CronTrigger', 'DateTrigger'
                    "trigger_details": str(job.trigger), # 触发器的详细信息 (例如 "interval[0:00:10]")
                    "pending": job.pending, # 是否待处理
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

    def _job_start_listener(self, event):
        """监听 job 开始执行"""
        job = self.get_job(event.job_id)
        if job:
            job_name = job.name or job.id
            log.debug("--- [Job 开始] --- 任务: %s (id=%s) 准备执行...", job_name, str(job.id))
        else:
            log.debug("--- [Job 开始] --- 无法查询到id=%s 的任务", str(event.job_id))

    def _job_end_listener(self, event):
        """监听 job 执行完毕（无论成功还是失败）"""
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