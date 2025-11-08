from typing import Any, Dict, List, Optional

from apscheduler.job import Job
from apscheduler.jobstores.base import JobLookupError
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
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

    _scheduler : Optional[BackgroundScheduler] = None

    def __init__(self):
        self._scheduler = BackgroundScheduler(
            timezone=Config().get_timezone(),
            executors={"default": ThreadPoolExecutor(50)},
        )
        self.init_config()

    def init_config(self):
        self.stop_service()
        self.run_service()

    def run_service(self):
        """
        读取配置，启动定时服务
        """
        if not self._scheduler:
            return
        
        # 注册事件监听器
        self._scheduler.add_listener(
            self._job_start_listener, 
            EVENT_JOB_SUBMITTED
        )
        self._scheduler.add_listener(
            self._job_end_listener,
            EVENT_JOB_EXECUTED | EVENT_JOB_ERROR
        )

        self._scheduler.start()

    def stop_service(self):
        """
        停止定时服务
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
        except Exception as e:
            log.exception('[Sys]停止定时服务出错: ', e)

    def get_scheduler(self) -> BackgroundScheduler:
        """获取任务管理器"""
        return self._scheduler

    def get_job(self, job_id: str) -> Optional[Job]:
        """获取单个 job 实例"""
        return self._scheduler.get_job(job_id)
    
    def get_jobs(self) -> List[Dict[str, Any]]:
        """
        获取所有已注册的任务，并将其格式化为适合 API 返回的列表。
        """
        jobs_list = []
        
        # 1. 调用底层的 get_jobs()
        all_jobs = self._scheduler.get_jobs()
        
        if not all_jobs:
            return []
            
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
                job_data["next_run_time"] = job.next_run_time.isoformat() 
            else:
                job_data["next_run_time"] = None
                
            jobs_list.append(job_data)
            
        return jobs_list

    def remove_job(self, job_id: str):
        """
        移除一个任务
        :param job_id: 任务ID
        """
        try:
            self._scheduler.remove_job(job_id)
            log.info(f"[Job]任务[{job_id}] 已移除")
        except JobLookupError:
            log.info(f"[Job]任务[{job_id}] 未找到，可能已被移除")    
        except Exception as e:
            log.exception(f"[Job]任务[{job_id}] 移除时发生错误: ", e)

    def _job_start_listener(self, event):
        """监听 job 开始执行"""
        job = self.get_job(event.job_id)
        if job:
            job_name = job.name or job.id
            log.info(f"--- [Job 开始] --- 任务: '{job_name}' (id={event.job_id}) 准备执行...")
        else:
            log.info(f"--- [Job 开始] --- 无法查询到id={event.job_id} 的任务")

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
                log.info(f"--- [Job 成功] --- 任务: '{job_name}' (id={event.job_id}) 执行成功, 下次执行时间: {job.next_run_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            else:
                log.info(f"--- [Job 成功] --- 任务: '{job_name}' (id={event.job_id}) 已执行完毕")
                
        elif event.code == EVENT_JOB_ERROR:
            # 失败
            log.exception(f"[Job]{job_name} 失败, 错误信息: {event.exception}")
            next_run = job.next_run_time
            if next_run:
                log.warn(f"--- [Job 失败] --- 任务: '{job_name}' (id={event.job_id}) 执行失败, 下次执行时间 {job.next_run_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            else:
                log.warn(f"--- [Job 失败] --- 任务: '{job_name}' (id={event.job_id}) 执行失败")