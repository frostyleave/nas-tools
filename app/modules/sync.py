import os
import threading
from typing import ClassVar

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

import log
from app.conf import ModuleConf
from app.core.jobcenter import JobCenter
from app.helper import DbHelper
from app.modules.filetransfer import FileTransfer
from app.utils import PathUtils
from app.utils.commons import singleton
from app.utils.constants import Constants
from app.utils.types import SyncType

# 批量转移文件任务ID
SYNC_TRANSFER_JOB_ID = "sync_transfer_mon_files"
# 监控文件聚合转移时间（秒）
SYNC_TRANSFER_INTERVAL = 60

lock = threading.Lock()


class FileMonitorHandler(FileSystemEventHandler):
    """
    目录监控响应类
    """

    def __init__(self, monpath, sync, **kwargs):
        super().__init__(**kwargs)
        self._watch_path = monpath
        self.sync = sync

    def on_created(self, event):
        self.sync.file_change_handler(event, "创建", event.src_path)

    def on_moved(self, event):
        self.sync.file_change_handler(event, "移动", event.dest_path)

    """
    def on_modified(self, event):
        self.sync.file_change_handler(event, "修改", event.src_path)
    """


@singleton
class Sync:
    filetransfer = None
    dbhelper = None

    _sync_path_confs: dict
    _monitor_sync_path_ids: list
    _observer: list
    _sync_paths: ClassVar[list] = []
    _synced_files: ClassVar[list] = []
    _need_sync_paths: ClassVar[dict] = {}

    def __init__(self):
        self._observer = []
        self.init_config(is_init=True)

    def init_config(self, is_init=False):
        self.dbhelper = DbHelper()
        self.filetransfer = FileTransfer()
        self._sync_path_confs = {}
        self._monitor_sync_path_ids = []
        for sync_conf in self.dbhelper.get_config_sync_paths():
            if not sync_conf:
                continue
            # ID
            sid = sync_conf.ID
            # 启用标志
            enabled = bool(sync_conf.ENABLED)
            # 仅硬链接标志
            rename = bool(sync_conf.RENAME)
            # 兼容模式
            compatibility = bool(sync_conf.COMPATIBILITY)
            # 转移方式
            syncmode = sync_conf.MODE
            syncmode_enum = ModuleConf.RMT_MODES.get(syncmode)
            # 源目录|目的目录|未知目录
            monpath = sync_conf.SOURCE
            target_path = sync_conf.DEST
            unknown_path = sync_conf.UNKNOWN

            if enabled:
                # 输出日志
                log_content1, log_content2 = "", ""
                if target_path:
                    log_content1 += f"目的目录：{target_path}，"
                if unknown_path:
                    log_content1 += f"未识别目录：{unknown_path}，"
                if rename:
                    log_content2 += "，启用识别和重命名"
                if compatibility:
                    log_content2 += "，启用兼容模式"
                log.info(f"【Sync】读取到监控目录: {monpath}, {log_content1}转移方式：{syncmode_enum.value}{log_content2} ✔️")
            else:
                log.info(f"【Sync】读取到监控目录: {monpath} 不进行监控和同步：手动关闭")

            if target_path and not os.path.exists(target_path) and syncmode_enum not in ModuleConf.REMOTE_RMT_MODES:
                log.info(f"【Sync】目的目录不存在，正在创建：{target_path}")
                os.makedirs(target_path)
            if unknown_path and not os.path.exists(unknown_path):
                log.info(f"【Sync】未识别目录不存在，正在创建：{unknown_path}")
                os.makedirs(unknown_path)
            # 登记关系
            self._sync_path_confs[str(sid)] = {
                'id': sid,
                'from': monpath,
                'to': target_path or "",
                'unknown': unknown_path or "",
                'syncmod': syncmode,
                'syncmod_name': syncmode_enum.value,
                "compatibility": compatibility,
                'rename': rename,
                'enabled': enabled
            }
            if monpath and os.path.exists(monpath):
                if enabled:
                    self._monitor_sync_path_ids.append(sid)
            else:
                log.error(f"【Sync】{monpath} 目录不存在！")
        # 启动监控服务
        self.run_service()
        # 根据监控目录注册或解除批量转移任务
        self.__init_transfer_job(is_init=is_init)

    def __init_transfer_job(self, is_init=False):
        """
        存在启用的监控目录时注册批量转移任务，否则解除注册
        """
        scheduler = JobCenter().get_sys_scheduler()
        job = scheduler.get_job(SYNC_TRANSFER_JOB_ID)

        if self._monitor_sync_path_ids:
            if job:
                log.debug("【Sync】批量转移文件定时任务已存在，无需重复注册")
                return
            scheduler.add_job(
                self.transfer_mon_files,
                "interval",
                seconds=SYNC_TRANSFER_INTERVAL,
                id=SYNC_TRANSFER_JOB_ID,
                name="批量转移文件",
                replace_existing=True
            )
            if is_init:
                log.info("【Sync】初始化时检测到启用的监控目录，已注册批量转移文件定时任务")
            else:
                log.info("【Sync】检测到启用的监控目录，已注册批量转移文件定时任务")
        elif job:
            scheduler.remove_job(SYNC_TRANSFER_JOB_ID)
            log.info("【Sync】未检测到启用的监控目录，已解除批量转移文件定时任务")
        elif is_init:
            log.info("【Sync】初始化时未检测到启用的监控目录，不注册批量转移文件定时任务")

    @property
    def monitor_sync_path_ids(self):
        """
        监控目录同步配置id
        """
        return self._monitor_sync_path_ids

    def get_sync_path_conf(self, sid=None):
        """
        获取目录同步配置
        """
        if sid:
            return self._sync_path_confs.get(str(sid)) or {}
        return self._sync_path_confs

    def check_source(self, source=None, sid=None):
        """
        检查关闭其他源目录相同或为父目录或为子目录的同步目录
        """
        if source:
            check_monpath = source
        elif sid:
            check_monpath = self.get_sync_path_conf(sid).get("from")
        else:
            return
        check_monpath = os.path.normpath(check_monpath)
        for sid, config in self._sync_path_confs.items():
            monpath = os.path.normpath(config.get("from"))
            if PathUtils.is_path_in_path(monpath, check_monpath) \
                    or PathUtils.is_path_in_path(check_monpath, monpath) \
                    and config.get("enabled"):
                self.dbhelper.check_config_sync_paths(sid=sid, enabled=0)

    def file_change_handler(self, event, text, event_path):
        """
        处理文件变化
        :param event: 事件
        :param text: 事件描述
        :param event_path: 事件文件路径
        """
        if not event.is_directory:
            # 文件发生变化
            try:
                if not os.path.exists(event_path):
                    return
                log.debug(f"【Sync】文件{text}：{event_path}")
                # 判断是否处理过了
                need_handler_flag = False
                try:
                    lock.acquire()
                    if event_path not in self._synced_files:
                        self._synced_files.append(event_path)
                        need_handler_flag = True
                finally:
                    lock.release()
                if not need_handler_flag:
                    log.debug(f"【Sync】文件已处理过：{event_path}")
                    return

                # 上级目录
                from_dir = os.path.dirname(event_path)
                # 判断是否在监控目录下
                sync_id = None
                is_root_path = False
                for sid in self._monitor_sync_path_ids:
                    sync_path_conf = self.get_sync_path_conf(sid)
                    mon_path = sync_path_conf.get('from')
                    target_path = sync_path_conf.get('to')
                    unknown_path = sync_path_conf.get('unknown')
                    # 判断是否在监控目录下
                    if PathUtils.is_path_in_path(mon_path, event_path):
                        if os.path.normpath(mon_path) == os.path.normpath(from_dir):
                            is_root_path = True
                        sync_id = sid

                # 不在监控目录下，不处理
                if not sync_id:
                    log.debug(f"【Sync】{event_path} 不在监控目录下，不处理 ...")
                    return
                # 回收站及隐藏的文件不处理
                if PathUtils.is_invalid_path(event_path):
                    log.debug(f"【Sync】{event_path} 是回收站或隐藏的文件，不处理 ...")
                    return

                # 应用的同步配置
                sync_path_conf = self.get_sync_path_conf(sync_id)
                mon_path = sync_path_conf.get('from')
                target_path = sync_path_conf.get('to')
                unknown_path = sync_path_conf.get('unknown')
                rename = sync_path_conf.get('rename')
                sync_mode = ModuleConf.RMT_MODES.get(sync_path_conf.get('syncmod'))

                # 不做识别重命名
                if not rename:
                    self.__link(event_path, mon_path, target_path, sync_mode)
                # 识别转移
                else:
                    # 媒体库目录及子目录不处理
                    if self.filetransfer.is_target_dir_path(event_path):
                        log.error(f"【Sync】{event_path} 是媒体库子目录，无法同步！")
                        return
                    # 目的目录下不处理
                    if PathUtils.is_path_in_path(target_path, event_path):
                        log.error(f"【Sync】{event_path} -> {target_path} 目的目录存在嵌套，无法同步！")
                        return
                    # 未识别目录下不处理
                    if PathUtils.is_path_in_path(unknown_path, event_path):
                        log.error(f"【Sync】{event_path} -> {unknown_path} 未识别目录存在嵌套，无法同步！")
                        return
                    # 不是媒体文件不处理
                    name = os.path.basename(event_path)
                    if not name:
                        return
                    if name.lower() != "index.bdmv":
                        ext = os.path.splitext(name)[-1]
                        if ext.lower() not in Constants.RMT_MEDIAEXT:
                            return
                    # 监控根目录下的文件发生变化时直接发走
                    if is_root_path:
                        ret, ret_msg = self.filetransfer.transfer_media(in_from=SyncType.MON,
                                                                        in_path=event_path,
                                                                        target_dir=target_path,
                                                                        unknown_dir=unknown_path,
                                                                        rmt_mode=sync_mode)
                        if not ret:
                            log.warn(f"【Sync】{event_path} 转移失败：{ret_msg}")
                    else:
                        try:
                            lock.acquire()
                            if self._need_sync_paths.get(from_dir):
                                files = self._need_sync_paths[from_dir].get('files')
                                if not files:
                                    files = [event_path]
                                else:
                                    if event_path not in files:
                                        files.append(event_path)
                                    else:
                                        return
                                self._need_sync_paths[from_dir].update({'files': files})
                            else:
                                self._need_sync_paths[from_dir] = {'target': target_path,
                                                                   'unknown': unknown_path,
                                                                   'syncmod': sync_mode,
                                                                   'files': [event_path]}
                        finally:
                            lock.release()
            except Exception as e:
                log.exception("【Sync】发生错误: ")

    def transfer_mon_files(self):
        """
        批量转移文件，由定时服务定期调用执行
        """
        try:
            lock.acquire()
            finished_paths = []
            for path in list(self._need_sync_paths):
                if not PathUtils.is_invalid_path(path) and os.path.exists(path):
                    log.info("【Sync】开始转移监控目录文件...")
                    target_info = self._need_sync_paths.get(path)
                    bluray_dir = PathUtils.get_bluray_dir(path)
                    if not bluray_dir:
                        src_path = path
                        files = target_info.get('files')
                    else:
                        src_path = bluray_dir
                        files = []
                    if src_path not in finished_paths:
                        finished_paths.append(src_path)
                    else:
                        continue
                    target_path = target_info.get('target')
                    unknown_path = target_info.get('unknown')
                    sync_mode = target_info.get('syncmod')
                    # 判断是否根目录
                    is_root_path = False
                    for sid in self._monitor_sync_path_ids:
                        if os.path.normpath(self.get_sync_path_conf(sid).get("from")) == os.path.normpath(src_path):
                            is_root_path = True
                    ret, ret_msg = self.filetransfer.transfer_media(in_from=SyncType.MON,
                                                                    in_path=src_path,
                                                                    files=files,
                                                                    target_dir=target_path,
                                                                    unknown_dir=unknown_path,
                                                                    rmt_mode=sync_mode,
                                                                    root_path=is_root_path)
                    if not ret:
                        log.warn(f"【Sync】{path}转移失败：{ret_msg}")
                self._need_sync_paths.pop(path)
        finally:
            lock.release()

    def run_service(self):
        """
        启动监控服务
        """
        self.stop_service()
        for sid in self._monitor_sync_path_ids:
            sync_path_conf = self.get_sync_path_conf(sid)
            if not sync_path_conf:
                continue
            mon_path = sync_path_conf.get("from")
            try:
                if sync_path_conf.get("compatibility"):
                    # 兼容模式，目录同步性能降低且NAS不能休眠，但可以兼容挂载的远程共享目录如SMB
                    observer = PollingObserver(timeout=10)
                else:
                    # 内部处理系统操作类型选择最优解
                    observer = Observer(timeout=10)
                self._observer.append(observer)
                observer.schedule(FileMonitorHandler(mon_path, self), path=mon_path, recursive=True)
                observer.daemon = True
                observer.start()
                log.info(f"{mon_path} 的监控服务启动")
            except Exception as e:
                log.exception("【Sync】启动监控 发生错误: ")
                err_msg = str(e)
                if "inotify" in err_msg and "reached" in err_msg:
                    log.warn(f"目录监控服务启动出现异常：{err_msg}，请在宿主机上（不是docker容器内）执行以下命令并重启："
                             + """
                             echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf
                             echo fs.inotify.max_user_instances=524288 | sudo tee -a /etc/sysctl.conf
                             sudo sysctl -p
                             """)
                else:
                    log.error(f"{mon_path} 启动目录监控失败：{err_msg}")

    def stop_service(self):
        """
        关闭监控服务
        """
        if self._observer:
            for observer in self._observer:
                try:
                    observer.stop()
                    observer.join()
                except Exception as e:
                    print(str(e))
        self._observer = []

    def transfer_sync(self, sid=None):
        """
        全量转移Sync目录下的文件，WEB界面点击目录同步时获发
        """
        if not sid:
            sids = self._monitor_sync_path_ids
        elif isinstance(sid, list):
            sids = sid
        else:
            sids = [sid]

        for id_item in sids:
            sync_path_conf = self.get_sync_path_conf(id_item)
            mon_path = sync_path_conf.get("from")
            target_path = sync_path_conf.get("to")
            unknown_path = sync_path_conf.get("unknown")
            rename = sync_path_conf.get("rename")
            sync_mode = ModuleConf.RMT_MODES.get(sync_path_conf.get("syncmod"))
            # 不做识别重命名
            if not rename:
                for link_file in PathUtils.get_dir_files(mon_path):
                    self.__link(link_file, mon_path, target_path, sync_mode)
            else:
                for path in PathUtils.get_dir_level1_medias(mon_path, Constants.RMT_MEDIAEXT):
                    if PathUtils.is_invalid_path(path):
                        continue
                    ret, ret_msg = self.filetransfer.transfer_media(in_from=SyncType.MON,
                                                                    in_path=path,
                                                                    target_dir=target_path,
                                                                    unknown_dir=unknown_path,
                                                                    rmt_mode=sync_mode)
                    if not ret:
                        log.error(f"【Sync】{mon_path} 处理失败：{ret_msg}")

    def __link(self, event_path, mon_path, target_path, sync_mode):
        """
        只转移不识别
        """
        if self.dbhelper.is_sync_in_history(event_path, target_path):
            return
        log.info("【Sync】开始同步 %s", event_path)
        try:
            ret, msg = self.filetransfer.link_sync_file(src_path=mon_path,
                                                        in_file=event_path,
                                                        target_dir=target_path,
                                                        sync_transfer_mode=sync_mode)
            if ret != 0:
                log.warn("【Sync】%s 同步失败，错误码：%s", (event_path, ret))
            elif not msg:
                self.dbhelper.insert_sync_history(event_path, mon_path, target_path)
                log.info("【Sync】%s 同步完成", event_path)
        except Exception as err:
            log.exception("【Sync】%s 同步失败：" , event_path)

    def delete_sync_path(self, sid):
        """
        删除配置的同步目录
        """
        ret = self.dbhelper.delete_config_sync_path(sid=sid)
        self.init_config()
        return ret

    def insert_sync_path(self, source, dest, unknown, mode, compatibility, rename, enabled, note=None):
        """
        添加同步目录配置
        """
        ret = self.dbhelper.insert_config_sync_path(source=source,
                                                    dest=dest,
                                                    unknown=unknown,
                                                    mode=mode,
                                                    compatibility=compatibility,
                                                    rename=rename,
                                                    enabled=enabled,
                                                    note=note)
        self.init_config()
        return ret

    def check_sync_paths(self, sid=None, compatibility=None, rename=None, enabled=None):
        """
        检查配置的同步目录
        """
        ret = self.dbhelper.check_config_sync_paths(
            sid=sid,
            compatibility=compatibility,
            rename=rename,
            enabled=enabled
        )
        self.init_config()
        return ret
