import copy
import os
import shutil
import time
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Body, Depends

import log
from app.conf import SystemConfig
from app.core.initializer import diff_config, reload_config
from app.core.security_center import SecurityCenter
from app.core.services import ServiceManager
from app.core.system_update import check_system_update, get_git_info, run_system_update
from app.core.task_manager import TaskStore
from app.helper import FileHelper
from app.middleware.security import CurrentUser, auth_check, get_current_user
from app.models.user import LEVEL_OPERATOR, LEVEL_SYSADMIN, LEVEL_USER, UserManager
from app.plugins import PluginManager
from app.utils import PathUtils, SystemUtils
from app.utils.password_hash import generate_password_hash, normalize_password_hash
from app.utils.types import SystemConfigKey
from config import Config

# 系统管理路由
sys_router = APIRouter(dependencies=[Depends(get_current_user)])


@sys_router.post("/sys/git_info")
@auth_check(LEVEL_SYSADMIN)
def git_info():
    """获取当前 Git 仓库信息"""
    return get_git_info()


@sys_router.post("/sys/git_check")
@auth_check(LEVEL_SYSADMIN)
def git_check():
    """检查远程是否有可用更新（只 fetch，不修改本地代码）"""
    return check_system_update()


@sys_router.post("/sys/restart")
@auth_check(LEVEL_SYSADMIN)
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
@auth_check(LEVEL_SYSADMIN)
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


# ---------------------------------------------------------------------------
# 系统安全相关的写操作
# 这些接口原先挂在 /do 上，任何登录用户都能调用；统一收拢到 /sys 并做等级校验。
# ---------------------------------------------------------------------------

def _set_config_value(cfg: dict, cfg_key: str, cfg_value):
    """
    根据 Key 原地设置配置值
    """
    if not cfg_key:
        return

    # 用户名
    if cfg_key == "app.login_user":
        cfg['app']['login_user'] = str(cfg_value).strip() if cfg_value else ''
        return
    # 密码
    if cfg_key == "app.login_password":
        if cfg_value and not str(cfg_value).startswith("[hash]"):
            cfg['app']['login_password'] = f"[hash]{generate_password_hash(str(cfg_value))}"
        elif cfg_value:
            cfg['app']['login_password'] = cfg_value
        else:
            cfg['app']['login_password'] = f"[hash]{generate_password_hash('password')}"
        return
    # 代理
    if cfg_key == "app.proxies":
        if cfg_value:
            if not cfg_value.startswith("http") and not cfg_value.startswith("sock"):
                cfg['app']['proxies'] = {
                    "https": f"http://{cfg_value}", "http": f"http://{cfg_value}"}
            else:
                cfg['app']['proxies'] = {"https": f"{cfg_value}", "http": f"{cfg_value}"}
        else:
            cfg['app']['proxies'] = {"https": None, "http": None}
        return

    # 按点号逐层定位，自动创建缺失的字典节点
    keys = cfg_key.split(".")
    node = cfg
    for key in keys[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    node[keys[-1]] = cfg_value


@sys_router.post("/sys/update_config")
@auth_check(LEVEL_SYSADMIN)
def update_config(current_user: CurrentUser, data: Annotated[dict, Body(...)]):
    """
    更新系统配置（原 /do → update_config）
    """
    data = dict(data)

    # 使用副本修改，校验失败时不污染内存中的配置
    old_cfg = copy.deepcopy(Config().get_config())
    cfg = copy.deepcopy(old_cfg)
    old_login_user = str((cfg.get('app') or {}).get('login_user') or '').strip()

    # 仅测试不保存
    config_test = False
    # 是否修改了管理员密码
    password_changed = False
    # 修改配置
    for key, value in data.items():
        if key == "test" and value:
            config_test = True
            continue
        if key == "app.login_password":
            password_changed = True
        # 生效配置
        _set_config_value(cfg, key, value)

    # 管理员用户名变更校验
    new_login_user = str((cfg.get('app') or {}).get('login_user') or '').strip()
    if "app.login_user" in data and not new_login_user:
        return {"code": -1, "msg": "WEB管理用户不能为空"}

    rename_admin = bool(old_login_user and new_login_user
                        and old_login_user != new_login_user)
    admin_user = None
    if rename_admin:
        if UserManager().get_user_by_name(new_login_user):
            return {"code": -1, "msg": f"用户 {new_login_user} 已存在"}
        # 优先匹配原配置名对应的管理员，其次当前管理员，最后取最早创建的管理员
        admin_user = UserManager().get_user_by_name(old_login_user)
        if not admin_user or admin_user.level < LEVEL_SYSADMIN:
            if current_user and current_user.level >= LEVEL_SYSADMIN:
                admin_user = current_user
            else:
                admin_user = UserManager().get_admin_user()
        if not admin_user:
            # 数据库中没有管理员时仅保存配置，下次启动会自动创建
            rename_admin = False

    relogin = False
    reloaded = []
    # 保存配置
    if not config_test:
        # 用户名以数据库为准，先同步数据库再保存配置
        if rename_admin:
            if not UserManager().rename_user(admin_user.username, new_login_user):
                return {"code": -1, "msg": "修改管理员用户名失败"}
            relogin = bool(current_user and current_user.username == admin_user.username)
            log.info(f"系统管理员用户名已修改：{admin_user.username} -> {new_login_user}")

        Config().save_config(cfg)

        # 管理员账号以数据库为准，同步密码到数据库
        if password_changed:
            password_hash = normalize_password_hash(
                cfg.get('app', {}).get('login_password'))
            if not UserManager().update_admin_password(password_hash):
                log.warn("【Config】未找到系统管理员账号，密码仅保存到配置文件")

        # 按变更内容重新初始化受影响的服务
        reloaded = reload_config(diff_config(old_cfg, cfg))

    return {"code": 0, "relogin": relogin, "reloaded": reloaded}


@sys_router.post("/sys/user_manager")
@auth_check(LEVEL_SYSADMIN)
def user_manager(current_user: CurrentUser, data: Annotated[dict, Body(...)]):
    """
    用户管理（原 /do → user_manager）
    """
    oper = data.get("oper")
    name = data.get("name")
    if not name:
        return {"code": -1, "success": False, "message": "用户名不能为空"}

    if oper == "add":
        raw_password = str(data.get("password") or "")
        if not raw_password:
            return {"code": -1, "success": False, "message": "密码不能为空"}
        password = generate_password_hash(raw_password)
        pris = data.get("pris")
        if isinstance(pris, list):
            pris = ",".join(pris)
        ret = UserManager().add_user(name, password, pris, LEVEL_USER)
    else:
        if current_user.username == name:
            return {"code": -1, "success": False, "message": "不能删除自己"}
        target = UserManager().get_user_by_name(name)
        if not target:
            return {"code": -1, "success": False, "message": "用户不存在"}
        if target.level >= current_user.level:
            return {"code": -1, "success": False, "message": "无权删除该用户"}
        ret = UserManager().delete_user(name)

    if ret:
        return {"code": 0, "success": True}
    return {"code": -1, "success": False, 'message': '操作失败'}


@sys_router.post("/sys/apikey_manager")
@auth_check(LEVEL_SYSADMIN)
def apikey_manager(data: Annotated[dict, Body(...)]):
    """
    API密钥管理：新增、删除、重新生成
    """
    oper = data.get("oper")
    if oper == "add":
        ok, msg, api_key = SecurityCenter().add_api_key(data.get("name"))
        if not ok:
            return {"code": -1, "msg": msg}
        return {"code": 0, "msg": msg, "data": {"api_key": api_key}}
    if oper == "del":
        if not SecurityCenter().delete_api_key(data.get("id")):
            return {"code": -1, "msg": "删除失败：密钥不存在或系统默认密钥不可删除"}
        return {"code": 0, "msg": "删除成功"}
    if oper == "regen":
        ok, msg, api_key = SecurityCenter().regenerate_api_key(data.get("id"))
        if not ok:
            return {"code": -1, "msg": msg}
        return {"code": 0, "msg": msg, "data": {"api_key": api_key}}
    return {"code": -1, "msg": "不支持的操作"}


@sys_router.post("/sys/restory_backup")
@auth_check(LEVEL_SYSADMIN)
def restory_backup(data: Annotated[dict, Body(...)]):
    """
    解压恢复备份文件（原 /do → restory_backup）
    """
    raw_name = str(data.get("file_name") or "")
    # 只取文件名，禁止路径穿越
    filename = PathUtils.safe_filename(raw_name)
    if not filename:
        return {"code": 1, "msg": "文件不存在"}

    config_path = Config().get_config_path()
    temp_path = Config().get_temp_path()
    file_path = os.path.join(temp_path, filename)
    if not PathUtils.is_within_dir(file_path, temp_path):
        log.warn(f"【Security】非法的备份文件名: {raw_name}")
        return {"code": 1, "msg": "文件不存在"}

    try:
        shutil.unpack_archive(file_path, config_path, format='zip')
        return {"code": 0, "msg": ""}
    except Exception as e:
        log.exception("[act]解压恢复备份文件出错:")
        return {"code": 1, "msg": str(e)}
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@sys_router.post("/sys/rename_file")
@auth_check(LEVEL_OPERATOR)
def rename_file(data: Annotated[dict, Body(...)]):
    """
    文件重命名（原 /do → rename_file）
    """
    path = data.get("path")
    name = data.get("name")
    if path and name:
        # 目标名只允许文件名，不允许携带目录
        name = PathUtils.safe_filename(name)
        if not name:
            return {"code": -1, "msg": "文件名无效"}
        try:
            shutil.move(path, os.path.join(os.path.dirname(path), name))
        except Exception as e:
            log.exception("[act]文件重命名 异常:")
            return {"code": -1, "msg": str(e)}
    return {"code": 0}


@sys_router.post("/sys/delete_files")
@auth_check(LEVEL_OPERATOR)
def delete_files(data: Annotated[dict, Body(...)]):
    """
    删除文件（原 /do → delete_files）
    """
    files = data.get("files")
    if files:
        for file in files:
            del_flag, del_msg = FileHelper.delete_media_file(
                filedir=os.path.dirname(file),
                filename=os.path.basename(file)
            )
            if not del_flag:
                log.error(del_msg)
            else:
                log.info(del_msg)
    return {"code": 0}


def _set_plugin_installed(module_id: str, installed: bool):
    """更新已安装插件列表，仅在状态变化时重载插件"""
    plugins = list(SystemConfig().get(SystemConfigKey.UserInstalledPlugins) or [])
    if installed:
        if module_id in plugins:
            return
        plugins.append(module_id)
    else:
        if module_id not in plugins:
            return
        plugins.remove(module_id)
    SystemConfig().set(SystemConfigKey.UserInstalledPlugins, plugins)
    PluginManager().init_config()


@sys_router.post("/sys/install_plugin")
@auth_check(LEVEL_OPERATOR)
def install_plugin(data: Annotated[dict, Body(...)]):
    """
    安装插件（原 /do → install_plugin）
    """
    module_id = data.get("id")
    if not module_id:
        return {"code": -1, "msg": "参数错误"}
    _set_plugin_installed(module_id, True)
    return {"code": 0, "msg": "插件安装成功"}


@sys_router.post("/sys/uninstall_plugin")
@auth_check(LEVEL_OPERATOR)
def uninstall_plugin(data: Annotated[dict, Body(...)]):
    """
    卸载插件（原 /do → uninstall_plugin）
    """
    module_id = data.get("id")
    if not module_id:
        return {"code": -1, "msg": "参数错误"}
    _set_plugin_installed(module_id, False)
    return {"code": 0, "msg": "插件卸载成功"}


@sys_router.post("/sys/update_plugin_config")
@auth_check(LEVEL_OPERATOR)
def update_plugin_config(data: Annotated[dict, Body(...)]):
    """
    保存插件配置（原 /do → update_plugin_config）
    """
    plugin_id = data.get("plugin")
    config = data.get("config")
    if not plugin_id:
        return {"code": 1, "msg": "数据错误"}
    PluginManager().save_plugin_config(pid=plugin_id, conf=config)
    if PluginManager().reload_plugin(plugin_id) is False:
        return {"code": 1, "msg": "插件配置已保存，但初始化失败，请检查日志"}
    return {"code": 0, "msg": "保存成功"}


@sys_router.post("/sys/run_plugin_method")
@auth_check(LEVEL_OPERATOR)
def run_plugin_method(data: Annotated[dict, Body(...)]):
    """
    运行插件方法（原 /do → run_plugin_method）
    """
    plugin_id = data.get("plugin_id")
    method = data.get("method")
    if not plugin_id or not method:
        return {"code": 1, "msg": "参数错误"}
    data = dict(data)
    data.pop("plugin_id")
    data.pop("method")
    result = PluginManager().run_plugin_method(pid=plugin_id, method=method, **data)
    return {"code": 0, "result": result}
