import time

from fastapi import APIRouter, BackgroundTasks, Depends

import log
from app.core.services import ServiceManager
from app.core.system_update import check_system_update, get_git_info, run_system_update
from app.core.task_manager import TaskStore
from app.middleware.security import get_current_user
from app.utils import SystemUtils

# 系统管理路由
sys_router = APIRouter(dependencies=[Depends(get_current_user)])


@sys_router.post("/sys/git_info")
def git_info():
    """获取当前 Git 仓库信息"""
    return get_git_info()


@sys_router.post("/sys/git_check")
def git_check():
    """检查远程是否有可用更新（只 fetch，不修改本地代码）"""
    return check_system_update()


@sys_router.post("/sys/restart")
def restart(background_tasks: BackgroundTasks):
    """重启系统"""
    background_tasks.add_task(_delayed_restart)
    return {"code": 0, "msg": "系统即将重启"}


def _delayed_restart():
    time.sleep(1)
    ServiceManager.restart_server()


def _update_system_job(task_id: str):
    """后台执行系统更新，通过 TaskStore 刷新进度"""
    token = log.bind_task_log(task_id)
    try:
        try:
            result = run_system_update(
                progress_cb=lambda progress, message: TaskStore().update_task(
                    task_id=task_id, progress=progress, message=message
                )
            )
        except Exception as e:
            log.exception("执行系统更新任务出错, task_id=%s", task_id)
            result = {"code": 1, "updated": False,
                      "msg": f"更新失败：{e!s}", "output": ""}
        # 记录本任务最后一条日志的序号，供旧的进度接口使用
        result["log_seq"] = log.get_last_task_seq(task_id)
        TaskStore().finish_task(task_id=task_id,
                                message=result.get("msg"),
                                result=result)
    finally:
        log.unbind_task_log(token)


@sys_router.post("/sys/update_system")
def update_system(background_tasks: BackgroundTasks):
    """
    兼容旧的任务模式：创建后台更新任务并返回 task_id。

    新版前端面板使用 /stream-update-system 直接流式获取日志和结果。
    """
    if not SystemUtils.is_docker():
        log.warn('【UpdateSystem】当前环境不支持在线更新，仅支持Docker环境')
        return {
            "code": 1,
            "updated": False,
            "msg": "仅支持在Docker环境中执行系统更新",
            "output": "",
        }

    task_id = TaskStore().create_task()
    background_tasks.add_task(_update_system_job, task_id)
    return {"code": 0, "task_id": task_id}
