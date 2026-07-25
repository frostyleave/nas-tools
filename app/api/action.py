import base64
import datetime
import importlib
import inspect
import json
import os.path
import re
import shutil
import threading
import time

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Body, Depends

import log

from app.conf import SystemConfig, ModuleConf
from app.helper import ProgressHelper, ThreadHelper, MetaHelper, WordsHelper, RssHelper, FileHelper
from app.utils import StringUtils, EpisodeFormat, RequestUtils, PathUtils, SystemUtils, MediaUtils

from app.core.cmd_handler import CommandHandler
from app.core.jobcenter import JobCenter
from app.core.services import ServiceManager
from app.core.task_manager import GlobalTaskManager
from app.downloader import Downloader
from app.indexer import Indexer
from app.indexer.manager import IndexerManager
from app.media import Media, Bangumi, DouBan, Scraper
from app.media.meta import MetaInfo
from app.mediaserver import MediaServer
from app.message import Message
from app.models.user import User, UserManager
from app.middleware.security import get_current_user
from app.modules.filetransfer import FileTransfer
from app.modules.filter import Filter
from app.modules.brushtaskv2 import BrushTaskV2 as BrushTask
from app.modules.rss import Rss
from app.modules.rsschecker import RssChecker
from app.modules.search import SearchProxy
from app.modules.searcher import Searcher
from app.modules.subscribe import Subscribe
from app.modules.media_status import MediaStatusChecker
from app.modules.sync import Sync
from app.modules.torrentremover import TorrentRemover
from app.plugins import PluginManager, EventManager
from app.sites import SitesManager, SitesDataStatisticsCenter, CookieManager, SiteConf
from app.utils.constants import Constants
from app.utils.types import MediaType, SyncType, SearchType, EventType, SystemConfigKey, RssType
from app.utils.password_hash import generate_password_hash

from config import Config

# action接口路由
action_router = APIRouter(dependencies=[Depends(get_current_user)])

# 事件响应
@action_router.post("/do")
def do(content: dict = Body(...), current_user: User = Depends(get_current_user)):
    
    start_time = time.time()
    try:
        cmd = content.get("cmd")
        data = content.get("data") or {}
        log.debug("处理/do请求: cmd={%s}, data={%s}", cmd, data)
        return WebAction(current_user).action(cmd, data)
    except Exception as e:
        log.exception("处理/do请求出错, cmd=" + content.get("cmd"))
        return {"code": -1, "msg": str(e)}
    finally:
        cost_time = time.time()
        process_time = (cost_time - start_time) * 1000  # 转换为毫秒
        log.debug("[%s] %s, 耗时: %s ms", str(threading.get_ident()), json.dumps(content), format(process_time, ".2f"))

# search
@action_router.post("/search")
def search(background_tasks: BackgroundTasks, data: dict = Body(...)):
    
    start_time = time.time()
    try:
        search_word = data.get("search_word")
        if not search_word:
            return {"code": -1, "msg": '缺少搜索关键词'}

        ident_flag = False if data.get("unident") else True
        filters = data.get("filters")
        tmdbid = data.get("tmdbid")
        media_type = data.get("media_type")

        if media_type:
            if media_type in Constants.MOVIE_TYPES:
                media_type = MediaType.MOVIE
            else:
                media_type = MediaType.TV

        task_id = GlobalTaskManager().create_task()

        background_tasks.add_task(SearchProxy().search_torrents_from_web,
                                  content=search_word,
                                  ident_flag=ident_flag,
                                  filters=filters,
                                  tmdbid=tmdbid,
                                  media_type=media_type,
                                  task_id=task_id)
        
        return {"code": 0, "task_id": task_id}
    
    except Exception as e:
        log.exception("处理/search请求出错")
        return {"code": -1, "msg": str(e)}
    finally:
        cost_time = time.time()
        process_time = (cost_time - start_time) * 1000  # 转换为毫秒
        log.debug("[%s] %s, 耗时: %s ms", str(threading.get_ident()), json.dumps(data), format(process_time, ".2f"))

class WebAction:
    
    _actions = {}
    _commands = {}
    _current_user : Optional[User] = None
    _douBan : Optional[DouBan] =  None

    def __init__(self, current_user:Optional[User]=None):
        # WEB请求响应
        self._actions = {
            "sch": self.__sch,
            "search": self.__search,
            "download": self.__download,
            "download_link": self.__download_link,
            "download_torrent": self.__download_torrent,
            "pt_start": self.__pt_start,
            "pt_stop": self.__pt_stop,
            "pt_remove": self.__pt_remove,
            "pt_info": self.__pt_info,
            "del_unknown_path": self.__del_unknown_path,
            "rename": self.__rename,
            "rename_udf": self.__rename_udf,
            "delete_history": self.delete_history,
            "version": self.__version,
            "update_site": self.__update_site,
            "get_site": self.__get_site,
            "del_site": self.__del_site,
            "restart": self.__restart,
            "update_system": self.update_system,
            "logout": self.__logout,
            "update_config": self.__update_config,
            "update_directory": self.__update_directory,
            "add_or_edit_sync_path": self.__add_or_edit_sync_path,
            "get_sync_path": self.get_sync_path,
            "delete_sync_path": self.__delete_sync_path,
            "check_sync_path": self.__check_sync_path,
            "remove_rss_media": self.__remove_rss_media,
            "add_rss_media": self.__add_rss_media,
            "re_identification": self.__re_identification,
            "media_info": self.__media_info,
            "test_connection": self.__test_connection,
            "user_manager": self.__user_manager,
            "refresh_rss": self.__refresh_rss,
            "delete_tmdb_cache": self.__delete_tmdb_cache,
            "movie_calendar_data": self.__movie_calendar_data,
            "tv_calendar_data": self.__tv_calendar_data,
            "modify_tmdb_cache": self.__modify_tmdb_cache,
            "rss_detail": self.__rss_detail,
            "truncate_blacklist": self.truncate_blacklist,
            "truncate_rsshistory": self.truncate_rsshistory,
            "add_brushtask": self.__add_brushtask,
            "del_brushtask": self.__del_brushtask,
            "brushtask_detail": self.__brushtask_detail,
            "update_brushtask_state": self.__update_brushtask_state,
            "name_test": self.__name_test,
            "rule_test": self.__rule_test,
            "net_test": self.__net_test,
            "add_filtergroup": self.__add_filtergroup,
            "restore_filtergroup": self.__restore_filtergroup,
            "set_default_filtergroup": self.__set_default_filtergroup,
            "del_filtergroup": self.__del_filtergroup,
            "add_filterrule": self.__add_filterrule,
            "del_filterrule": self.__del_filterrule,
            "filterrule_detail": self.__filterrule_detail,
            "get_site_activity": self.__get_site_activity,
            "get_site_history": self.__get_site_history,
            "get_recommend": self.get_recommend,
            "batch_get_media_exists_info": self.batch_get_media_exists_info,
            "get_downloaded": self.get_downloaded,
            "get_site_seeding_info": self.__get_site_seeding_info,
            "clear_tmdb_cache": self.__clear_tmdb_cache,
            "check_site_attr": self.__check_site_attr,
            "refresh_process": self.refresh_process,
            "restory_backup": self.__restory_backup,
            "start_mediasync": self.__start_mediasync,
            "mediasync_state": self.__mediasync_state,
            "get_tvseason_list": self.__get_tvseason_list,
            "get_userrss_task": self.__get_userrss_task,
            "delete_userrss_task": self.__delete_userrss_task,
            "update_userrss_task": self.__update_userrss_task,
            "check_userrss_task": self.__check_userrss_task,
            "get_rssparser": self.__get_rssparser,
            "delete_rssparser": self.__delete_rssparser,
            "update_rssparser": self.__update_rssparser,
            "run_userrss": self.__run_userrss,
            "run_brushtask": self.__run_brushtask,
            "list_site_resources": self.list_site_resources,
            "list_rss_articles": self.__list_rss_articles,
            "rss_article_test": self.__rss_article_test,
            "list_rss_history": self.__list_rss_history,
            "rss_articles_check": self.__rss_articles_check,
            "rss_articles_download": self.__rss_articles_download,
            "add_custom_word_group": self.__add_custom_word_group,
            "delete_custom_word_group": self.__delete_custom_word_group,
            "add_or_edit_custom_word": self.__add_or_edit_custom_word,
            "get_custom_word": self.__get_custom_word,
            "delete_custom_words": self.__delete_custom_words,
            "check_custom_words": self.__check_custom_words,
            "export_custom_words": self.__export_custom_words,
            "analyse_import_custom_words_code": self.__analyse_import_custom_words_code,
            "import_custom_words": self.__import_custom_words,
            "re_rss_history": self.__re_rss_history,
            "delete_rss_history": self.__delete_rss_history,
            "share_filtergroup": self.__share_filtergroup,
            "import_filtergroup": self.__import_filtergroup,
            "get_transfer_statistics": self.get_transfer_statistics,
            "search_media_infos": self._search_media_infos,
            "get_filterrules": self.get_filterrules,
            "get_downloading": self.get_downloading,
            "test_site": self.__test_site,
            "get_sub_path": self.__get_sub_path,
            "rename_file": self.__rename_file,
            "delete_files": self.__delete_files,
            "download_subtitle": self.__download_subtitle,
            "get_download_setting": self.__get_download_setting,
            "update_download_setting": self.__update_download_setting,
            "delete_download_setting": self.__delete_download_setting,
            "update_message_client": self.__update_message_client,
            "delete_message_client": self.__delete_message_client,
            "check_message_client": self.__check_message_client,
            "get_message_client": self.__get_message_client,
            "test_message_client": self.__test_message_client,
            "get_sites": self.__get_sites,
            "get_indexers": self.__get_indexers,
            "get_download_dirs": self.__get_download_dirs,
            "find_hardlinks": self.__find_hardlinks,
            "update_sites_cookie_ua": self.__update_sites_cookie_ua,
            "update_site_cookie_ua": self.__update_site_cookie_ua,
            "set_site_captcha_code": self.__set_site_captcha_code,
            "update_torrent_remove_task": self.__update_torrent_remove_task,
            "get_torrent_remove_task": self.__get_torrent_remove_task,
            "delete_torrent_remove_task": self.__delete_torrent_remove_task,
            "get_remove_torrents": self.__get_remove_torrents,
            "auto_remove_torrents": self.__auto_remove_torrents,
            "list_brushtask_torrents": self.__list_brushtask_torrents,
            "set_system_config": self.__set_system_config,
            "set_user_indexer_sites": self.__set_user_indexer_sites,
            "get_site_user_statistics": self.get_site_user_statistics,
            "send_custom_message": self.send_custom_message,
            "media_detail": self.media_detail,
            "media_brief_info": self.media_brief_info,
            "media_extra_info": self.media_extra_info,
            "media_person": self.__media_person,
            "person_medias": self.__person_medias,
            "run_directory_sync": self.__run_directory_sync,
            "update_plugin_config": self.__update_plugin_config,
            "get_season_episodes": self.__get_season_episodes,
            "update_downloader": self.__update_downloader,
            "del_downloader": self.__del_downloader,
            "check_downloader": self.__check_downloader,
            "get_downloaders": self.__get_downloaders,
            "test_downloader": self.__test_downloader,
            "get_indexer": self.__get_indexer,
            "add_indexer": self.__add_indexer,
            "update_indexer": self.__update_indexer,
            "delete_indexer": self.__delete_indexer,
            "media_path_scrap": self.__media_path_scrap,
            "get_default_rss_setting": self.get_default_rss_setting,
            "install_plugin": self.install_plugin,
            "uninstall_plugin": self.uninstall_plugin,
            "get_plugin_apps": self.get_plugin_apps,
            "get_plugin_page": self.get_plugin_page,
            "update_category_config": self.update_category_config,
            "get_category_config": self.get_category_config,
            "get_system_processes": self.get_system_processes,
            "run_plugin_method": self.run_plugin_method,
            "refresh_pt_statistics": self.refresh_pt_statistics,
            "get_jobs": self.get_jobs
        }
        # 用户绑定
        self._current_user = current_user
        # 豆瓣实例
        self._douBan = DouBan()

    def action(self, cmd, data):
        """
        执行WEB请求
        """
        func = self._actions.get(cmd)
        if not func:
            return {"code": -1, "msg": "无效请求！"}
        elif inspect.signature(func).parameters:
            return func(data)
        else:
            return func(**{})

    def api_action(self, cmd, data=None):
        """
        执行API请求
        """
        result = self.action(cmd, data)
        if not result:
            return {
                "code": -1,
                "success": False,
                "message": "服务异常，未获取到返回结果"
            }
        code = result.get("code", result.get("retcode", 0))
        if not code or str(code) == "0":
            success = True
        else:
            success = False
        message = result.get("msg", result.get("retmsg", ""))
        for key in ['code', 'retcode', 'msg', 'retmsg']:
            if key in result:
                result.pop(key)
        return {
            "code": code,
            "success": success,
            "message": message,
            "data": result
        }

    def set_config_value(self, cfg, cfg_key, cfg_value):
        """
        根据Key设置配置值
        """
        # 密码
        if cfg_key == "app.login_password":
            if cfg_value and not cfg_value.startswith("[hash]"):
                password_hash = "[hash]%s" % generate_password_hash(cfg_value)
                cfg['app']['login_password'] = "[hash]%s" % password_hash
            else:
                cfg['app']['login_password'] = cfg_value or "password"
            return cfg
        # 代理
        if cfg_key == "app.proxies":
            if cfg_value:
                if not cfg_value.startswith("http") and not cfg_value.startswith("sock"):
                    cfg['app']['proxies'] = {
                        "https": "http://%s" % cfg_value, "http": "http://%s" % cfg_value}
                else:
                    cfg['app']['proxies'] = {"https": "%s" %
                                                      cfg_value, "http": "%s" % cfg_value}
            else:
                cfg['app']['proxies'] = {"https": None, "http": None}
            return cfg
        # 最大支持三层赋值
        keys = cfg_key.split(".")
        if keys:
            if len(keys) == 1:
                cfg[keys[0]] = cfg_value
            elif len(keys) == 2:
                if not cfg.get(keys[0]):
                    cfg[keys[0]] = {}
                cfg[keys[0]][keys[1]] = cfg_value
            elif len(keys) == 3:
                if cfg.get(keys[0]):
                    if not cfg[keys[0]].get(keys[1]) or isinstance(cfg[keys[0]][keys[1]], str):
                        cfg[keys[0]][keys[1]] = {}
                    cfg[keys[0]][keys[1]][keys[2]] = cfg_value
                else:
                    cfg[keys[0]] = {}
                    cfg[keys[0]][keys[1]] = {}
                    cfg[keys[0]][keys[1]][keys[2]] = cfg_value

        return cfg

    def set_config_directory(self, cfg, oper, cfg_key, cfg_value, update_value=None):
        """
        更新目录数据
        """

        def remove_sync_path(obj, key):
            if not isinstance(obj, list):
                return []
            ret_obj = []
            for item in obj:
                if item.split("@")[0].replace("\\", "/") != key.split("@")[0].replace("\\", "/"):
                    ret_obj.append(item)
            return ret_obj

        # 最大支持二层赋值
        keys = cfg_key.split(".")
        if keys:
            if len(keys) == 1:
                if cfg.get(keys[0]):
                    if not isinstance(cfg[keys[0]], list):
                        cfg[keys[0]] = [cfg[keys[0]]]
                    if oper == "add":
                        cfg[keys[0]].append(cfg_value)
                    elif oper == "sub":
                        cfg[keys[0]].remove(cfg_value)
                        if not cfg[keys[0]]:
                            cfg[keys[0]] = None
                    elif oper == "set":
                        cfg[keys[0]].remove(cfg_value)
                        if update_value:
                            cfg[keys[0]].append(update_value)
                else:
                    cfg[keys[0]] = cfg_value
            elif len(keys) == 2:
                if cfg.get(keys[0]):
                    if not cfg[keys[0]].get(keys[1]):
                        cfg[keys[0]][keys[1]] = []
                    if not isinstance(cfg[keys[0]][keys[1]], list):
                        cfg[keys[0]][keys[1]] = [cfg[keys[0]][keys[1]]]
                    if oper == "add":
                        cfg[keys[0]][keys[1]].append(
                            cfg_value.replace("\\", "/"))
                    elif oper == "sub":
                        cfg[keys[0]][keys[1]] = remove_sync_path(
                            cfg[keys[0]][keys[1]], cfg_value)
                        if not cfg[keys[0]][keys[1]]:
                            cfg[keys[0]][keys[1]] = None
                    elif oper == "set":
                        cfg[keys[0]][keys[1]] = remove_sync_path(
                            cfg[keys[0]][keys[1]], cfg_value)
                        if update_value:
                            cfg[keys[0]][keys[1]].append(
                                update_value.replace("\\", "/"))
                else:
                    cfg[keys[0]] = {}
                    cfg[keys[0]][keys[1]] = cfg_value.replace("\\", "/")
        return cfg

    def __sch(self, data):
        """
        启动服务
        """
        commands = {
            "pttransfer": Downloader().transfer,
            "sync": Sync().transfer_sync,
            "rssdownload": Rss().rssdownload,
            "subscribe_search_all": Subscribe().subscribe_search_all,
        }
        sch_item = data.get("item")
        if sch_item and commands.get(sch_item):
            ThreadHelper().start_thread(commands.get(sch_item), ())
        return {"retmsg": "服务已启动", "item": sch_item}

    def __search(self, data):
        """
        WEB搜索资源
        """
        search_word = data.get("search_word")
        ident_flag = False if data.get("unident") else True
        filters = data.get("filters")
        tmdbid = data.get("tmdbid")
        media_type = data.get("media_type")

        if media_type:
            if media_type in Constants.MOVIE_TYPES:
                media_type = MediaType.MOVIE
            else:
                media_type = MediaType.TV

        if search_word:
            ret, ret_msg = SearchProxy().search_torrents_from_web(content=search_word,
                                                                  ident_flag=ident_flag,
                                                                  filters=filters,
                                                                  tmdbid=tmdbid,
                                                                  media_type=media_type,
                                                                  task_id=data.get("task_id"))
            if ret != 0:
                return {"code": ret, "msg": ret_msg}
        return {"code": 0}

    def __download(self, data):
        """
        从WEB添加下载
        """

        media_info, msg = Searcher().get_search_result_info_by_id(data.get("id"))

        if not media_info:
            return {"retcode": -1, "retmsg": msg }

        dl_dir = data.get("dir")
        dl_setting = data.get("setting")

        # 添加下载
        _, ret, ret_msg = Downloader().download(media_info=media_info,
                                                download_dir=dl_dir,
                                                download_setting=dl_setting,
                                                in_from=SearchType.WEB,
                                                user_name=self._current_user.username)
        if not ret:
            return {"retcode": -1, "retmsg": ret_msg}
        
        return {"retcode": 0, "retmsg": ""}

    def __download_link(self, data):
        """
        从WEB添加下载链接
        """
        site = data.get("site")
        enclosure = data.get("enclosure")
        title = data.get("title")
        description = data.get("description")
        page_url = data.get("page_url")
        size = data.get("size")
        seeders = data.get("seeders")
        uploadvolumefactor = data.get("uploadvolumefactor")
        downloadvolumefactor = data.get("downloadvolumefactor")
        dl_dir = data.get("dl_dir")
        dl_setting = data.get("dl_setting")
        if not title or not enclosure:
            return {"code": -1, "msg": "种子信息有误"}
        media = Media().get_media_info(title=title, subtitle=description)
        media.site = site
        media.enclosure = enclosure
        media.page_url = page_url
        media.size = size
        media.upload_volume_factor = float(uploadvolumefactor)
        media.download_volume_factor = float(downloadvolumefactor)
        media.seeders = seeders
        # 添加下载
        _, ret, ret_msg = Downloader().download(media_info=media,
                                                download_dir=dl_dir,
                                                download_setting=dl_setting,
                                                in_from=SearchType.WEB,
                                                user_name="admin")
        if not ret:
            return {"code": 1, "msg": ret_msg or "如连接正常，请检查下载任务是否存在"}
        return {"code": 0, "msg": "下载成功"}

    def __download_torrent(self, data):
        """
        从种子文件或者URL链接添加下载
        files：文件地址的列表，urls：种子链接地址列表或者单个链接地址
        """
        dl_dir = data.get("dl_dir")
        dl_setting = data.get("dl_setting")
        files = data.get("files") or []
        urls = data.get("urls") or []
        if not files and not urls:
            return {"code": -1, "msg": "没有种子文件或者种子链接"}
        # 下载种子
        for file_item in files:
            if not file_item:
                continue
            file_name = file_item.get("upload", {}).get("filename")
            file_path = os.path.join(Config().get_temp_path(), file_name)
            media_info = Media().get_media_info(title=file_name)
            if media_info:
                media_info.site = "WEB"
            # 添加下载
            Downloader().download(media_info=media_info,
                                  download_dir=dl_dir,
                                  download_setting=dl_setting,
                                  torrent_file=file_path,
                                  in_from=SearchType.WEB,
                                  user_name="admin")
        # 下载链接
        if urls and not isinstance(urls, list):
            urls = [urls]
        for url in urls:
            if not url:
                continue
            # 查询站点
            site_info = SitesManager().get_site(siteurl=url)
            if not site_info:
                return {"code": -1, "msg": "根据链接地址未匹配到站点"}
            # 下载种子文件，并读取信息
            result = Downloader().get_torrent_info(
                url=url,
                cookie=site_info.cookie,
                ua=site_info.ua,
                proxy=site_info.proxy
            )
            file_path = result.file_path
            retmsg = result.ret_msg
            if not file_path:
                return {"code": -1, "msg": f"下载种子文件失败： {retmsg}"}
            media_info = Media().get_media_info(title=os.path.basename(file_path))
            if media_info:
                media_info.site = "WEB"
            # 添加下载
            Downloader().download(media_info=media_info,
                                  download_dir=dl_dir,
                                  download_setting=dl_setting,
                                  torrent_file=file_path,
                                  in_from=SearchType.WEB,
                                  user_name="admin")

        return {"code": 0, "msg": "添加下载完成！"}

    def __pt_start(self, data):
        """
        开始下载
        """
        tid = data.get("id")
        if id:
            Downloader().start_torrents(ids=tid)
        return {"retcode": 0, "id": tid}

    def __pt_stop(self, data):
        """
        停止下载
        """
        tid = data.get("id")
        if id:
            Downloader().stop_torrents(ids=tid)
        return {"retcode": 0, "id": tid}

    def __pt_remove(self, data):
        """
        删除下载
        """
        tid = data.get("id")
        if id:
            Downloader().delete_torrents(ids=tid, delete_file=True)
        return {"retcode": 0, "id": tid}

    def __pt_info(self, data):
        """
        查询具体种子的信息
        """
        ids = data.get("ids")
        downloader_id = data.get("downloaderId")
        torrents = Downloader().get_downloading_progress(downloader_id=downloader_id,ids=ids)
        return {"retcode": 0, "torrents": torrents}

    def __del_unknown_path(self, data):
        """
        删除路径
        """
        tids = data.get("id")
        if isinstance(tids, list):
            for tid in tids:
                if not tid:
                    continue
                FileTransfer().delete_transfer_unknown(tid)
            return {"retcode": 0}
        else:
            retcode = FileTransfer().delete_transfer_unknown(tids)
            return {"retcode": retcode}

    def __rename(self, data):
        """
        手工转移
        """
        path = dest_dir = None
        syncmod = ModuleConf.RMT_MODES.get(data.get("syncmod"))
        logid = data.get("logid")
        if logid:
            transinfo = FileTransfer().get_transfer_info_by_id(logid)
            if transinfo:
                path = os.path.join(
                    transinfo.SOURCE_PATH, transinfo.SOURCE_FILENAME)
                dest_dir = transinfo.DEST
            else:
                return {"retcode": -1, "retmsg": "未查询到转移日志记录"}
        else:
            unknown_id = data.get("unknown_id")
            if unknown_id:
                inknowninfo = FileTransfer().get_unknown_info_by_id(unknown_id)
                if inknowninfo:
                    path = inknowninfo.PATH
                    dest_dir = inknowninfo.DEST
                else:
                    return {"retcode": -1, "retmsg": "未查询到未识别记录"}
                
        if not dest_dir:
            dest_dir = ""
        if not path:
            return {"retcode": -1, "retmsg": "输入路径有误"}
        
        tmdbid = data.get("tmdb")
        mtype = data.get("type")
        season = data.get("season")
        episode_format = data.get("episode_format")
        episode_details = data.get("episode_details")
        episode_part = data.get("episode_part")
        episode_offset = data.get("episode_offset")
        min_filesize = data.get("min_filesize")

        if mtype in Constants.MOVIE_TYPES:
            media_type = MediaType.MOVIE
        elif mtype in Constants.TVT_YPES:
            media_type = MediaType.TV
        else:
            media_type = MediaType.ANIME
        # 如果改次手动修复时一个单文件，自动修复改目录下同名文件，需要配合episode_format生效
        need_fix_all = False
        if os.path.splitext(path)[-1].lower() in Constants.RMT_MEDIAEXT and episode_format:
            path = os.path.dirname(path)
            need_fix_all = True
        # 开始转移
        succ_flag, ret_msg = self.__manual_transfer(inpath=path,
                                                    syncmod=syncmod,
                                                    outpath=dest_dir,
                                                    media_type=media_type,
                                                    episode_format=episode_format,
                                                    episode_details=episode_details,
                                                    episode_part=episode_part,
                                                    episode_offset=episode_offset,
                                                    need_fix_all=need_fix_all,
                                                    min_filesize=min_filesize,
                                                    tmdbid=tmdbid,
                                                    season=season)
        if succ_flag:
            if not need_fix_all and not logid:
                # 更新记录状态
                FileTransfer().update_transfer_unknown_state(path)
            return {"retcode": 0, "retmsg": "转移成功"}
        else:
            return {"retcode": 2, "retmsg": ret_msg}

    def __rename_udf(self, data):
        """
        自定义识别
        """
        inpath = data.get("inpath")
        if not os.path.exists(inpath):
            return {"retcode": -1, "retmsg": f"输入路径{inpath}不存在"}
        
        outpath = data.get("outpath")
        syncmod = ModuleConf.RMT_MODES.get(data.get("syncmod"))
        tmdbid = data.get("tmdb")
        mtype = data.get("type")
        season = data.get("season")
        episode_format = data.get("episode_format")
        episode_details = data.get("episode_details")
        episode_part = data.get("episode_part")
        episode_offset = data.get("episode_offset")
        min_filesize = data.get("min_filesize")
        if mtype in Constants.MOVIE_TYPES:
            media_type = MediaType.MOVIE
        elif mtype in Constants.TVT_YPES:
            media_type = MediaType.TV
        else:
            media_type = MediaType.ANIME

        # 开始转移
        succ_flag, ret_msg = self.__manual_transfer(inpath=inpath,
                                                    syncmod=syncmod,
                                                    outpath=outpath,
                                                    media_type=media_type,
                                                    episode_format=episode_format,
                                                    episode_details=episode_details,
                                                    episode_part=episode_part,
                                                    episode_offset=episode_offset,
                                                    min_filesize=min_filesize,
                                                    tmdbid=tmdbid,
                                                    season=season)
        if succ_flag:
            return {"retcode": 0, "retmsg": "转移成功"}
        else:
            return {"retcode": 2, "retmsg": ret_msg}

    def __manual_transfer(self, 
                          inpath,
                          syncmod,
                          outpath=None,
                          media_type=None,
                          episode_format=None,
                          episode_details=None,
                          episode_part=None,
                          episode_offset=None,
                          min_filesize=None,
                          tmdbid=None,
                          season=None,
                          need_fix_all=False):
        """
        开始手工转移文件
        """
        inpath = os.path.normpath(inpath)
        if not os.path.exists(inpath):
            return False, "输入路径不存在"
        
        outpath = os.path.normpath(outpath) if outpath else None
        is_dir_specified = True if outpath else False
        episode_conf = (EpisodeFormat(episode_format, episode_details, episode_part, episode_offset), need_fix_all)
        
        if tmdbid:
            # 有输入TMDBID
            tmdb_info = Media().get_tmdb_info(mtype=media_type, tmdbid=tmdbid)
            if not tmdb_info:
                return False, "识别失败, 无法查询到TMDB信息"
            
            # 按识别的信息转移
            succ_flag, ret_msg = FileTransfer().transfer_media(in_from=SyncType.MAN,
                                                               in_path=inpath,
                                                               rmt_mode=syncmod,
                                                               target_dir=outpath,
                                                               tmdb_info=tmdb_info,
                                                               media_type=media_type,
                                                               season=season,
                                                               episode=episode_conf,
                                                               min_filesize=min_filesize,
                                                               udf_flag=True,
                                                               is_dir_specified=is_dir_specified)
        else:
            # 按识别的信息转移
            succ_flag, ret_msg = FileTransfer().transfer_media(in_from=SyncType.MAN,
                                                               in_path=inpath,
                                                               rmt_mode=syncmod,
                                                               target_dir=outpath,
                                                               media_type=media_type,
                                                               episode=episode_conf,
                                                               min_filesize=min_filesize,
                                                               udf_flag=True,
                                                               is_dir_specified=is_dir_specified)
        return succ_flag, ret_msg

    def delete_history(self, data):
        """
        删除识别记录及文件
        """
        return FileTransfer().delete_history(data)

    def __version(self):
        """
        检查新版本
        """
        version, url = SystemUtils.get_latest_version()
        if version:
            return {"code": 0, "version": version, "url": url}
        return {"code": -1, "version": "", "url": ""}

    def __update_site(self, data):
        """
        维护站点信息
        """

        _sites = SitesManager()

        def __is_site_duplicate(query_name, query_tid):
            # 检查是否重名
            for site in _sites.get_sites_by_name(name=query_name):
                if str(site.id) != str(query_tid):
                    return True
            return False

        tid = data.get('site_id')
        name = data.get('site_name')
        site_pri = data.get('site_pri')
        rssurl = data.get('site_rssurl')
        signurl = data.get('site_signurl')
        cookie = data.get('site_cookie')
        token = data.get('site_token')
        apikey = data.get('site_apikey')
        note = data.get('site_note')
        if isinstance(note, dict):
            note = json.dumps(note)
        rss_uses = data.get('site_include')

        if __is_site_duplicate(name, tid):
            return {"code": 400, "msg": "站点名称重复"}

        if tid:
            site_data = _sites.get_site(siteid=tid)
            # 站点不存在
            if not site_data:
                return {"code": 400, "msg": "站点不存在"}
            old_name = site_data.name
            ret = _sites.update_site(tid=tid,
                                     name=name,
                                     site_pri=site_pri,
                                     rssurl=rssurl,
                                     signurl=signurl,
                                     cookie=cookie,
                                     token=token,
                                     apikey=apikey,
                                     note=note,
                                     rss_uses=rss_uses)
            if ret and (name != old_name):
                # 更新历史站点数据信息
                SitesDataStatisticsCenter().update_site_name(name, old_name)

        else:
            ret = _sites.add_site(name=name,
                                  site_pri=site_pri,
                                  rssurl=rssurl,
                                  signurl=signurl,
                                  cookie=cookie,
                                  token=token,
                                  apikey=apikey,
                                  note=note,
                                  rss_uses=rss_uses)

        return {"code": ret}

    def __get_site(self, data):
        """
        查询单个站点信息
        """
        tid = data.get("id")
        site_free = False
        site_2xfree = False
        site_hr = False
        if tid:
            ret = SitesManager().get_site(siteid=tid)
            if ret.rssurl:
                site_attr = SiteConf().get_grap_conf(ret.rssurl)
                if site_attr.get("FREE"):
                    site_free = True
                if site_attr.get("2XFREE"):
                    site_2xfree = True
                if site_attr.get("HR"):
                    site_hr = True
        else:
            ret = []
        return {"code": 0, "site": ret, "site_free": site_free, "site_2xfree": site_2xfree, "site_hr": site_hr}

    def __get_sites(self, data):
        """
        查询多个站点信息
        """
        rss = True if data.get("rss") else False
        brush = True if data.get("brush") else False
        statistic = True if data.get("statistic") else False
        basic = True if data.get("basic") else False
        if basic:
            sites = SitesManager().get_site_dict(rss=rss,
                                                 brush=brush,
                                                 statistic=statistic)
        else:
            sites = SitesManager().get_sites(rss=rss,
                                             brush=brush,
                                             statistic=statistic)
        return {"code": 0, "sites": sites}

    def __del_site(self, data):
        """
        删除单个站点信息
        """
        tid = data.get("id")
        if tid:
            ret = SitesManager().delete_site(tid)
            return {"code": ret}
        
        return {"code": 0}

    def __restart(self):
        """
        重启
        """
        # 退出主进程
        ServiceManager.restart_server()
        return {"code": 0}

    def update_system(self):
        """
        更新
        """
        third_version = Config().get_config("app").get("third_version")
        log.info(f'【UpdateSystem】检查是否开启第三方更新源: {third_version}')
        if third_version:
            log.info("【UpdateSystem】开始第三方源更新流程")
            # 获取当前系统根目录
            root_path = Config().get_root_path()
            log.info(f'【UpdateSystem】获取系统根目录: {root_path}')

            # 下载文件临时目录
            tmp_path = "/tmp/nas-tools"
            # 文件不存在则创建
            if not os.path.exists(tmp_path):
                log.info(f'【UpdateSystem】创建临时目录: {tmp_path}')
                os.makedirs(tmp_path)

            tmp_path_file = os.path.join(tmp_path, "nas-tools.zip")

            # 获取版本下载地址
            version, download_url = SystemUtils.get_latest_version()
            log.info(f'【UpdateSystem】获取最新系统版本: {version}')
            log.info(f'【UpdateSystem】获取最新系统下载地址: {download_url}')

            # 开始下载文件
            log.info("【UpdateSystem】正在下载最新系统")
            result = RequestUtils(timeout=5, proxies=Config().get_proxies()).get_res(download_url)
            if result.status_code != 200:
                log.error("【UpdateSystem】系统下载失败，停止更新")
                return {"code": 1, "msg": "系统下载失败"}
            log.info(f'【UpdateSystem】保存系统文件：{tmp_path_file}')
            open(tmp_path_file, "wb").write(result.content)

            # 解压文件
            log.info('【UpdateSystem】正在解压文件...')
            shutil.unpack_archive(tmp_path_file, tmp_path, format='zip')
            tmp_path_root = os.path.join(tmp_path, f"nas-tools-{version.split()[0]}")
            log.info(f'【UpdateSystem】文件解压成功：{tmp_path_root}')

            # 删除不需要的文件
            PathUtils.del_files(os.path.join(tmp_path_root, ".github"))
            PathUtils.del_files(os.path.join(tmp_path_root, "config"))

            # 拷贝文件
            log.info('【UpdateSystem】正在升级系统版本...')
            os.system(f"cp -R {tmp_path_root}/* {root_path}/")

            # 安装依赖
            log.info('【UpdateSystem】正在安装系统依赖...')
            os.system(f'sudo pip install -r {root_path}/requirements.txt')
            # 修复权限
            user_auth = os.stat(root_path)
            os.chown(f"{root_path}", user_auth.st_uid, user_auth.st_gid)

            # 清理临时目录
            PathUtils.del_files(tmp_path)
            log.info('【UpdateSystem】清理临时目录...')

            # 重启
            log.info('【UpdateSystem】系统升级完成，正在重启...')
            log.info("【UpdateSystem】请手动刷新页面！")
            time.sleep(3)
            ServiceManager.restart_server()
        # 升级
        elif SystemUtils.is_synology():
            if SystemUtils.execute('/bin/ps -w -x | grep -v grep | grep -w "nastool update" | wc -l') == '0':
                # 调用群晖套件内置命令升级
                os.system('【UpdateSystem】nastool update')
                # 重启
                ServiceManager.restart_server()
        else:
            # 清除git代理
            os.system("sudo git config --global --unset http.proxy")
            os.system("sudo git config --global --unset https.proxy")
            # 设置git代理
            proxy = Config().get_proxies() or {}
            http_proxy = proxy.get("http")
            https_proxy = proxy.get("https")
            if http_proxy or https_proxy:
                os.system(
                    f"sudo git config --global http.proxy {http_proxy or https_proxy}")
                os.system(
                    f"sudo git config --global https.proxy {https_proxy or http_proxy}")
            # 清理
            os.system("sudo git clean -dffx")
            # 升级
            branch = os.getenv("NASTOOL_VERSION", "master")
            os.system(f"sudo git fetch --depth 1 origin {branch}")
            os.system(f"sudo git reset --hard origin/{branch}")
            os.system("sudo git submodule update --init --recursive")
            # 安装依赖
            os.system('sudo pip install -r /nas-tools/requirements.txt')
            # 修复权限
            os.system('sudo chown -R nt:nt /nas-tools')
            # 重启
            ServiceManager.restart_server()
        return {"code": 0}

    def __logout(self):
        """
        注销
        """
        return {"code": 0}

    def __update_config(self, data):
        """
        更新配置信息
        """
        cfg = Config().get_config()
        cfgs = dict(data).items()
        # 仅测试不保存
        config_test = False
        # 修改配置
        for key, value in cfgs:
            if key == "test" and value:
                config_test = True
                continue
            # 生效配置
            cfg = self.set_config_value(cfg, key, value)

        # 保存配置
        if not config_test:
            Config().save_config(cfg)

        return {"code": 0}

    def __add_or_edit_sync_path(self, data):
        """
        维护同步目录
        """
        sid = data.get("sid")
        source = data.get("from")
        dest = data.get("to")
        unknown = data.get("unknown")
        mode = data.get("syncmod")
        compatibility = data.get("compatibility")
        rename = data.get("rename")
        enabled = data.get("enabled")

        _sync = Sync()

        # 源目录检查
        if not source:
            return {"code": 1, "msg": '源目录不能为空'}
        if not os.path.exists(source):
            return {"code": 1, "msg": f'{source}目录不存在'}
        # windows目录用\，linux目录用/
        source = os.path.normpath(source)
        # 目的目录检查，目的目录可为空
        if dest:
            dest = os.path.normpath(dest)
            if PathUtils.is_path_in_path(source, dest):
                return {"code": 1, "msg": "目的目录不可包含在源目录中"}
        if unknown:
            unknown = os.path.normpath(unknown)

        # 硬链接不能跨盘
        if mode == "link" and dest:
            common_path = os.path.commonprefix([source, dest])
            if not common_path or common_path == "/":
                return {"code": 1, "msg": "硬链接不能跨盘"}

        # 编辑先删再增
        if sid:
            _sync.delete_sync_path(sid)
        # 若启用，则关闭其他相同源目录的同步目录
        if enabled == 1:
            _sync.check_source(source=source)
        # 插入数据库
        _sync.insert_sync_path(source=source,
                               dest=dest,
                               unknown=unknown,
                               mode=mode,
                               compatibility=compatibility,
                               rename=rename,
                               enabled=enabled)
        return {"code": 0, "msg": ""}

    def get_sync_path(self, data=None):
        """
        查询同步目录
        """
        if data:
            sync_path = Sync().get_sync_path_conf(sid=data.get("sid"))
        else:
            sync_path = Sync().get_sync_path_conf()
        return {"code": 0, "result": sync_path}

    def __delete_sync_path(self, data):
        """
        移出同步目录
        """
        sid = data.get("sid")
        Sync().delete_sync_path(sid)
        return {"code": 0}

    def __check_sync_path(self, data):
        """
        维护同步目录
        """
        flag = data.get("flag")
        sid = data.get("sid")
        checked = data.get("checked")

        _sync = Sync()

        if flag == "compatibility":
            _sync.check_sync_paths(sid=sid, compatibility=1 if checked else 0)
            return {"code": 0}
        elif flag == "rename":
            _sync.check_sync_paths(sid=sid, rename=1 if checked else 0)
            return {"code": 0}
        elif flag == "enable":
            # 若启用，则关闭其他相同源目录的同步目录
            if checked:
                _sync.check_source(sid=sid)
            _sync.check_sync_paths(sid=sid, enabled=1 if checked else 0)
            return {"code": 0}
        else:
            return {"code": 1}

    def __remove_rss_media(self, data):
        """
        移除RSS订阅
        """
        name = data.get("name")
        mtype = data.get("type")
        year = data.get("year")
        season = data.get("season")
        rssid = data.get("rssid")
        page = data.get("page")
        tmdbid = data.get("tmdbid")
        if not str(tmdbid).isdigit():
            tmdbid = None
        if name:
            name = MetaInfo(title=name).get_name()
        if mtype:
            if mtype in Constants.MOVIE_TYPES:
                Subscribe().delete_subscribe(mtype=MediaType.MOVIE,
                                             title=name,
                                             year=year,
                                             rssid=rssid,
                                             tmdbid=tmdbid)
            else:
                Subscribe().delete_subscribe(mtype=MediaType.TV,
                                             title=name,
                                             season=season,
                                             rssid=rssid,
                                             tmdbid=tmdbid)
        return {"code": 0, "page": page, "name": name}

    def __add_rss_media(self, data):
        """
        添加RSS订阅
        """
        _subscribe = Subscribe()
        channel = RssType.Manual if data.get("in_form") == "manual" else RssType.Auto
        name = data.get("name")
        year = data.get("year")
        keyword = data.get("keyword")
        season = data.get("season")
        fuzzy_match = data.get("fuzzy_match")
        mediaid = data.get("mediaid")
        rss_sites = data.get("rss_sites")
        search_sites = data.get("search_sites")
        over_edition = data.get("over_edition")
        filter_restype = data.get("filter_restype")
        filter_pix = data.get("filter_pix")
        filter_team = data.get("filter_team")
        filter_rule = data.get("filter_rule")
        filter_include = data.get("filter_include")
        filter_exclude = data.get("filter_exclude")
        save_path = data.get("save_path")
        download_setting = data.get("download_setting")
        total_ep = data.get("total_ep")
        current_ep = data.get("current_ep")
        rssid = data.get("rssid")
        page = data.get("page")
        mtype = MediaType.MOVIE if data.get(
            "type") in Constants.MOVIE_TYPES else MediaType.TV

        media_info = None
        if isinstance(season, list):
            code = 0
            msg = ""
            for sea in season:
                code, msg, media_info = _subscribe.add_rss_subscribe(mtype=mtype,
                                                                     name=name,
                                                                     year=year,
                                                                     channel=channel,
                                                                     keyword=keyword,
                                                                     season=sea,
                                                                     fuzzy_match=fuzzy_match,
                                                                     mediaid=mediaid,
                                                                     rss_sites=rss_sites,
                                                                     search_sites=search_sites,
                                                                     over_edition=over_edition,
                                                                     filter_restype=filter_restype,
                                                                     filter_pix=filter_pix,
                                                                     filter_team=filter_team,
                                                                     filter_rule=filter_rule,
                                                                     filter_include=filter_include,
                                                                     filter_exclude=filter_exclude,
                                                                     save_path=save_path,
                                                                     download_setting=download_setting,
                                                                     rssid=rssid)
                if code != 0:
                    break
        else:
            code, msg, media_info = _subscribe.add_rss_subscribe(mtype=mtype,
                                                                 name=name,
                                                                 year=year,
                                                                 channel=channel,
                                                                 keyword=keyword,
                                                                 season=season,
                                                                 fuzzy_match=fuzzy_match,
                                                                 mediaid=mediaid,
                                                                 rss_sites=rss_sites,
                                                                 search_sites=search_sites,
                                                                 over_edition=over_edition,
                                                                 filter_restype=filter_restype,
                                                                 filter_pix=filter_pix,
                                                                 filter_team=filter_team,
                                                                 filter_rule=filter_rule,
                                                                 filter_include=filter_include,
                                                                 filter_exclude=filter_exclude,
                                                                 save_path=save_path,
                                                                 download_setting=download_setting,
                                                                 total_ep=total_ep,
                                                                 current_ep=current_ep,
                                                                 rssid=rssid)
        if not rssid and media_info:
            rssid = _subscribe.get_subscribe_id(mtype=mtype,
                                                title=name,
                                                tmdbid=media_info.tmdb_id)
        return {"code": code, "msg": msg, "page": page, "name": name, "rssid": rssid}

    def __re_identification(self, data):
        """
        未识别的重新识别
        """
        flag = data.get("flag")
        ids = data.get("ids")

        return FileTransfer().re_identification(flag, ids)

    def __media_info(self, data):
        """
        查询媒体信息
        """
        mediaid = data.get("id")
        mtype = data.get("type")
        title = data.get("title")
        year = data.get("year")
        page = data.get("page")
        rssid = data.get("rssid")
        seasons = []
        link_url = ""
        vote_average = 0
        poster_path = ""
        release_date = ""
        overview = ""
        # 类型
        if mtype in Constants.MOVIE_TYPES:
            media_type = MediaType.MOVIE
        else:
            media_type = MediaType.TV

        # 先取订阅信息
        _subcribe = Subscribe()
        _media = Media()
        rssid_ok = False
        if rssid:
            rssid = str(rssid)
            if media_type == MediaType.MOVIE:
                rssinfo = _subcribe.get_subscribe_movies(rid=rssid)
            else:
                rssinfo = _subcribe.get_subscribe_tvs(rid=rssid)
            if not rssinfo:
                return {
                    "code": 1,
                    "retmsg": "无法查询到订阅信息",
                    "rssid": rssid,
                    "type_str": media_type.value
                }
            overview = rssinfo[rssid].get("overview")
            poster_path = rssinfo[rssid].get("poster")
            title = rssinfo[rssid].get("name")
            vote_average = rssinfo[rssid].get("vote")
            year = rssinfo[rssid].get("year")
            release_date = rssinfo[rssid].get("release_date")
            link_url = _media.get_detail_url(mtype=media_type,
                                             tmdbid=rssinfo[rssid].get("tmdbid"))
            if overview and poster_path:
                rssid_ok = True

        # 订阅信息不足
        if not rssid_ok:
            if mediaid:
                media = _media.get_mediainfo_from_id(mediaid=mediaid, mtype=media_type)
            else:
                media = _media.get_media_info(
                    title=f"{title} {year}", mtype=media_type)
            if not media or not media.tmdb_info:
                return {
                    "code": 1,
                    "retmsg": "无法查询到TMDB信息",
                    "rssid": rssid,
                    "type_str": media_type.value
                }
            if not mediaid:
                mediaid = media.tmdb_id
            link_url = media.get_detail_url()
            overview = media.overview
            poster_path = media.get_poster_image()
            title = media.title
            vote_average = round(float(media.vote_average or 0), 1)
            year = media.year
            if media_type != MediaType.MOVIE:
                release_date = media.tmdb_info.get('first_air_date')
                seasons = MediaUtils.batch_convert_ch_season_info(_media.get_tmdb_tv_seasons(tv_info=media.tmdb_info))
            else:
                release_date = media.tmdb_info.get('release_date')

            # 查订阅信息
            if not rssid:
                rssid = _subcribe.get_subscribe_id(mtype=media_type,
                                                   title=title,
                                                   tmdbid=mediaid)

        return {
            "code": 0,
            "type": mtype,
            "type_str": media_type.value,
            "page": page,
            "title": title,
            "vote_average": vote_average,
            "poster_path": poster_path,
            "release_date": release_date,
            "year": year,
            "overview": overview,
            "link_url": link_url,
            "tmdbid": mediaid,
            "rssid": rssid,
            "seasons": seasons
        }

    def __test_connection(self, data):
        """
        测试连通性
        """
        # 支持两种传入方式：命令数组或单个命令，单个命令时xx|xx模式解析为模块和类，进行动态引入
        command = data.get("command")
        ret = None
        if command:
            try:
                module_obj = None
                if isinstance(command, list):
                    for cmd_str in command:
                        ret = eval(cmd_str)
                        if not ret:
                            break
                else:
                    if command.find("|") != -1:
                        module = command.split("|")[0]
                        class_name = command.split("|")[1]
                        module_obj = getattr(
                            importlib.import_module(module), class_name)()
                        if hasattr(module_obj, "init_config"):
                            module_obj.init_config()
                        ret = module_obj.get_status()
                    else:
                        ret = eval(command)
                # 重载配置
                Config().init_config()
                if module_obj:
                    if hasattr(module_obj, "init_config"):
                        module_obj.init_config()
            except Exception as e:
                ret = None
                log.exception("[act]测试连通性出错:")
            return {"code": 0 if ret else 1}
        return {"code": 0}

    def __user_manager(self, data):
        """
        用户管理
        """
        oper = data.get("oper")
        name = data.get("name")
        if oper == "add":
            password = generate_password_hash(str(data.get("password")))
            pris = data.get("pris")
            if isinstance(pris, list):
                pris = ",".join(pris)
            ret = UserManager().add_user(name, password, pris)
        else:
            ret = UserManager().delete_user(name)

        if ret == 1 or ret:
            return {"code": 0, "success": False}
        return {"code": -1, "success": False, 'message': '操作失败'}

    def __refresh_rss(self, data):
        """
        重新搜索RSS
        """
        mtype = data.get("type")
        rssid = data.get("rssid")
        page = data.get("page")
        if mtype == "MOV":
            ThreadHelper().start_thread(Subscribe().subscribe_search_movie, (rssid,))
        else:
            ThreadHelper().start_thread(Subscribe().subscribe_search_tv, (rssid,))
        return {"code": 0, "page": page}

    def __delete_tmdb_cache(self, data):
        """
        删除tmdb缓存
        """
        if MetaHelper().delete_meta_data(data.get("cache_key")):
            MetaHelper().save_meta_data()
        return {"code": 0}

    def __movie_calendar_data(self, data):
        """
        查询电影上映日期
        """
        tid = data.get("id")
        rssid = data.get("rssid")
        if tid and tid.startswith("DB:"):
            doubanid = tid.replace("DB:", "")
            douban_info = self._douBan.get_douban_detail(doubanid=doubanid, mtype=MediaType.MOVIE)
            if not douban_info:
                return {"code": 1, "retmsg": "无法查询到豆瓣信息"}

            poster_path = douban_info.get("images", {}).get('large') or ""
            title = douban_info.get("title")
            vote_average = douban_info.get("rating", {}).get("average") or "无"
            release_date = douban_info.get("pubdate")
            if not release_date:
                return {"code": 1, "retmsg": "上映日期不正确"}
            else:
                return {"code": 0,
                        "type": "电影",
                        "title": title,
                        "start": release_date,
                        "id": tid,
                        "year": release_date[0:4] if release_date else "",
                        "poster": poster_path,
                        "vote_average": vote_average,
                        "rssid": rssid
                        }
        else:
            if tid:
                tmdb_info = Media().get_tmdb_info(mtype=MediaType.MOVIE, tmdbid=tid)
            else:
                return {"code": 1, "retmsg": "没有TMDBID信息"}
            if not tmdb_info:
                return {"code": 1, "retmsg": "无法查询到TMDB信息"}
            poster_path = Config().get_tmdbimage_url(tmdb_info.get('poster_path')) \
                if tmdb_info.get('poster_path') else ""
            title = tmdb_info.get('title')
            vote_average = tmdb_info.get("vote_average")
            release_date = tmdb_info.get('release_date')
            if not release_date:
                return {"code": 1, "retmsg": "上映日期不正确"}
            else:
                return {"code": 0,
                        "type": "电影",
                        "title": title,
                        "start": release_date,
                        "id": tid,
                        "year": release_date[0:4] if release_date else "",
                        "poster": poster_path,
                        "vote_average": vote_average,
                        "rssid": rssid
                        }

    def __tv_calendar_data(self, data):
        """
        查询电视剧上映日期
        """
        tid = data.get("id")
        season = data.get("season")
        name = data.get("name")
        rssid = data.get("rssid")
        if tid and tid.startswith("DB:"):
            doubanid = tid.replace("DB:", "")
            douban_info = self._douBan.get_douban_detail(doubanid=doubanid, mtype=MediaType.TV)
            if not douban_info:
                return {"code": 1, "retmsg": "无法查询到豆瓣信息"}

            poster_path = douban_info.get("images", {}).get('large') or ""
            title = douban_info.get("title")
            vote_average = douban_info.get("rating", {}).get("average") or "无"
            release_date = douban_info.get("pubdate")
            if not release_date:
                return {"code": 1, "retmsg": "上映日期不正确"}
            else:
                return {
                    "code": 0,
                    "events": [{
                        "type": "电视剧",
                        "title": title,
                        "start": release_date,
                        "id": tid,
                        "year": release_date[0:4] if release_date else "",
                        "poster": poster_path,
                        "vote_average": vote_average,
                        "rssid": rssid
                    }]
                }
        else:
            if tid:
                tmdb_info = Media().get_tmdb_tv_season_detail(tmdbid=tid, season=season)
            else:
                return {"code": 1, "retmsg": "没有TMDBID信息"}
            if not tmdb_info:
                return {"code": 1, "retmsg": "无法查询到TMDB信息"}
            episode_events = []
            air_date = tmdb_info.get("air_date")
            if not tmdb_info.get("poster_path"):
                tv_tmdb_info = Media().get_tmdb_info(mtype=MediaType.TV, tmdbid=tid)
                if tv_tmdb_info:
                    poster_path = Config().get_tmdbimage_url(tv_tmdb_info.get('poster_path'))
                else:
                    poster_path = ""
            else:
                poster_path = Config().get_tmdbimage_url(tmdb_info.get('poster_path'))
            year = air_date[0:4] if air_date else ""
            for episode in tmdb_info.get("episodes"):
                episode_events.append({
                    "type": "剧集",
                    "title": "%s 第%s季第%s集" % (
                        name,
                        season,
                        episode.get("episode_number")
                    ) if season != 1 else "%s 第%s集" % (
                        name,
                        episode.get("episode_number")
                    ),
                    "start": episode.get("air_date"),
                    "id": tid,
                    "year": year,
                    "poster": poster_path,
                    "vote_average": episode.get("vote_average") or "无",
                    "rssid": rssid
                })
            return {"code": 0, "events": episode_events}

    def __rss_detail(self, data):
        rid = data.get("rssid")
        mtype = data.get("rsstype")
        if mtype in Constants.MOVIE_TYPES:
            rssdetail = Subscribe().get_subscribe_movies(rid=rid)
            if not rssdetail:
                return {"code": 1}
            rssdetail = list(rssdetail.values())[0]
            rssdetail["type"] = "MOV"
        else:
            rssdetail = Subscribe().get_subscribe_tvs(rid=rid)
            if not rssdetail:
                return {"code": 1}
            rssdetail = list(rssdetail.values())[0]
            rssdetail["type"] = "TV"
        return {"code": 0, "detail": rssdetail}

    def __modify_tmdb_cache(self, data):
        """
        修改TMDB缓存的标题
        """
        if MetaHelper().modify_meta_data(data.get("key"), data.get("title")):
            MetaHelper().save_meta_data(force=True)
        return {"code": 0}

    def truncate_blacklist(self):
        """
        清空文件转移黑名单记录
        """
        FileTransfer().truncate_transfer_blacklist()
        return {"code": 0}

    def truncate_rsshistory(self):
        """
        清空RSS历史记录
        """
        RssHelper().truncate_rss_history()
        Subscribe().truncate_rss_episodes()
        return {"code": 0}

    def __add_brushtask(self, data):
        """
        新增刷流任务
        """
        # 输入值
        brushtask_id = data.get("brushtask_id")
        brushtask_name = data.get("brushtask_name")
        brushtask_site = data.get("brushtask_site")
        brushtask_interval = data.get("brushtask_interval")
        brushtask_downloader = data.get("brushtask_downloader")
        brushtask_totalsize = data.get("brushtask_totalsize")
        brushtask_state = data.get("brushtask_state")
        brushtask_rssurl = data.get("brushtask_rssurl")
        brushtask_label = data.get("brushtask_label")
        brushtask_savepath = data.get("brushtask_savepath")
        brushtask_transfer = 'Y' if data.get("brushtask_transfer") else 'N'
        brushtask_sendmessage = 'Y' if data.get(
            "brushtask_sendmessage") else 'N'
        brushtask_free = data.get("brushtask_free")
        brushtask_hr = data.get("brushtask_hr")
        brushtask_torrent_size = data.get("brushtask_torrent_size")
        brushtask_include = data.get("brushtask_include")
        brushtask_exclude = data.get("brushtask_exclude")
        brushtask_dlcount = data.get("brushtask_dlcount")
        brushtask_peercount = data.get("brushtask_peercount")
        brushtask_seedtime = data.get("brushtask_seedtime")
        brushtask_seedratio = data.get("brushtask_seedratio")
        brushtask_seedsize = data.get("brushtask_seedsize")
        brushtask_dltime = data.get("brushtask_dltime")
        brushtask_avg_upspeed = data.get("brushtask_avg_upspeed")
        brushtask_iatime = data.get("brushtask_iatime")
        brushtask_pubdate = data.get("brushtask_pubdate")
        brushtask_upspeed = data.get("brushtask_upspeed")
        brushtask_downspeed = data.get("brushtask_downspeed")
        # 选种规则
        rss_rule = {
            "free": brushtask_free,
            "hr": brushtask_hr,
            "size": brushtask_torrent_size,
            "include": brushtask_include,
            "exclude": brushtask_exclude,
            "dlcount": brushtask_dlcount,
            "peercount": brushtask_peercount,
            "pubdate": brushtask_pubdate,
            "upspeed": brushtask_upspeed,
            "downspeed": brushtask_downspeed
        }
        # 删除规则
        remove_rule = {
            "time": brushtask_seedtime,
            "ratio": brushtask_seedratio,
            "uploadsize": brushtask_seedsize,
            "dltime": brushtask_dltime,
            "avg_upspeed": brushtask_avg_upspeed,
            "iatime": brushtask_iatime
        }
        # 添加记录
        item = {
            "name": brushtask_name,
            "site": brushtask_site,
            "free": brushtask_free,
            "rssurl": brushtask_rssurl,
            "interval": brushtask_interval,
            "downloader": brushtask_downloader,
            "seed_size": brushtask_totalsize,
            "label": brushtask_label,
            "savepath": brushtask_savepath,
            "transfer": brushtask_transfer,
            "state": brushtask_state,
            "rss_rule": rss_rule,
            "remove_rule": remove_rule,
            "sendmessage": brushtask_sendmessage
        }
        BrushTask().update_brushtask(brushtask_id, item)
        return {"code": 0}

    def __del_brushtask(self, data):
        """
        删除刷流任务
        """
        brush_id = data.get("id")
        if brush_id:
            BrushTask().delete_brushtask(brush_id)
            return {"code": 0}
        return {"code": 1}

    def __brushtask_detail(self, data):
        """
        查询刷流任务详情
        """
        brush_id = data.get("id")
        brushtask = BrushTask().get_brushtask_info(brush_id)
        if not brushtask:
            return {"code": 1, "task": {}}

        return {"code": 0, "task": brushtask}

    def __update_brushtask_state(self, data):
        """
        批量暂停/开始刷流任务
        """
        try:
            state = data.get("state")
            task_ids = data.get("ids")
            _brushtask = BrushTask()
            if state is not None:
                if task_ids:
                    for tid in task_ids:
                        _brushtask.update_brushtask_state(state=state, brushtask_id=tid)
                else:
                    _brushtask.update_brushtask_state(state=state)
            return {"code": 0, "msg": ""}
        except Exception as e:
            log.exception("[act]刷流任务设置失败:")
            return {"code": 1, "msg": "刷流任务设置失败"}

    def __name_test(self, data):
        """
        名称识别测试
        """
        name = data.get("name")
        subtitle = data.get("subtitle")
        if not name:
            return {"code": -1}
        media_info = Media().get_media_info(title=name, subtitle=subtitle)
        if not media_info:
            return {"code": 0, "data": {"name": "无法识别"}}
        return {"code": 0, "data": MediaUtils.mediainfo_dict(media_info)}

    def __rule_test(self, data):
        title = data.get("title")
        subtitle = data.get("subtitle")
        size = data.get("size")
        rulegroup = data.get("rulegroup")
        if not title:
            return {"code": -1}
        meta_info = MetaInfo(title=title, subtitle=subtitle)
        meta_info.size = float(size) * 1024 ** 3 if size else 0
        match_flag, res_order, match_msg = \
            Filter().check_torrent_filter(meta_info=meta_info,
                                          filter_args={"rule": rulegroup})
        return {
            "code": 0,
            "flag": match_flag,
            "text": "匹配" if match_flag else "未匹配",
            "order": 100 - res_order if res_order else 0
        }

    def __net_test(self, data):
        target = data
        if target == "image.tmdb.org":
            target = target + "/t/p/w500/wwemzKWzjKYJFfCeiB57q3r4Bcm.png"
        if target == "qyapi.weixin.qq.com":
            target = target + "/cgi-bin/message/send"
        target = "https://" + target
        start_time = datetime.datetime.now()
        if target.find("themoviedb") != -1 \
                or target.find("telegram") != -1 \
                or target.find("fanart") != -1 \
                or target.find("tmdb") != -1:
            res = RequestUtils(proxies=Config().get_proxies(),
                               timeout=5).get_res(target)
        else:
            res = RequestUtils(timeout=5).get_res(target)
        seconds = int((datetime.datetime.now() -
                       start_time).microseconds / 1000)
        if not res:
            return {"res": False, "time": "%s 毫秒" % seconds}
        elif res.ok:
            return {"res": True, "time": "%s 毫秒" % seconds}
        else:
            return {"res": False, "time": "%s 毫秒" % seconds}

    def __get_site_activity(self, data):
        """
        查询site活动[上传，下载，魔力值]
        :param data: {"name":site_name}
        :return:
        """
        if not data or "name" not in data:
            return {"code": 1, "msg": "查询参数错误"}

        resp = {"code": 0}

        resp.update(
            {"dataset": SitesDataStatisticsCenter().get_pt_site_activity_history(data["name"])})
        return resp

    def __get_site_history(self, data):
        """
        查询site 历史[上传，下载]
        :param data: {"days":累计时间}
        :return:
        """
        if not data or "days" not in data or not isinstance(data["days"], int):
            return {"code": 1, "msg": "查询参数错误"}

        resp = {"code": 0}
        _, _, site, upload, download = SitesDataStatisticsCenter().get_pt_site_statistics_history(
            data["days"] + 1, data.get("end_day", None)
        )

        # 调整为dataset组织数据
        dataset = [["site", "upload", "download"]]
        dataset.extend([[site, upload, download]
                        for site, upload, download in zip(site, upload, download)])
        resp.update({"dataset": dataset})
        return resp

    def __get_site_seeding_info(self, data):
        """
        查询site 做种分布信息 大小，做种数
        :param data: {"name":site_name}
        :return:
        """
        if not data or "name" not in data:
            return {"code": 1, "msg": "查询参数错误"}

        resp = {"code": 0}

        seeding_info = SitesDataStatisticsCenter().get_pt_site_seeding_info(
            data["name"]).get("seeding_info", [])
        # 调整为dataset组织数据
        dataset = [["seeders", "size"]]
        dataset.extend(seeding_info)

        resp.update({"dataset": dataset})
        return resp

    def __add_filtergroup(self, data):
        """
        新增规则组
        """
        name = data.get("name")
        default = data.get("default")
        if not name:
            return {"code": -1}
        Filter().add_group(name, default)
        return {"code": 0}

    def __restore_filtergroup(self, data):
        """
        恢复初始规则组
        """
        groupids = data.get("groupids")
        if groupids:
            Filter().restore_filtergroup()
        return {"code": 0}

    def __set_default_filtergroup(self, data):
        groupid = data.get("id")
        if not groupid:
            return {"code": -1}
        Filter().set_default_filtergroup(groupid)
        return {"code": 0}

    def __del_filtergroup(self, data):
        groupid = data.get("id")
        Filter().delete_filtergroup(groupid)
        return {"code": 0}

    def __add_filterrule(self, data):
        rule_id = data.get("rule_id")
        item = {
            "group": data.get("group_id"),
            "name": data.get("rule_name"),
            "pri": data.get("rule_pri"),
            "include": data.get("rule_include"),
            "exclude": data.get("rule_exclude"),
            "size": data.get("rule_sizelimit"),
            "free": data.get("rule_free")
        }
        Filter().add_filter_rule(ruleid=rule_id, item=item)
        return {"code": 0}

    def __del_filterrule(self, data):
        ruleid = data.get("id")
        Filter().delete_filterrule(ruleid)
        return {"code": 0}

    def __filterrule_detail(self, data):
        rid = data.get("ruleid")
        groupid = data.get("groupid")
        ruleinfo = Filter().get_rules(groupid=groupid, ruleid=rid)
        if ruleinfo:
            ruleinfo['include'] = "\n".join(ruleinfo.get("include"))
            ruleinfo['exclude'] = "\n".join(ruleinfo.get("exclude"))
        return {"code": 0, "info": ruleinfo}

    def get_recommend(self, data):
        Type = data.get("type")
        SubType = data.get("subtype")
        CurrentPage = data.get("page")
        if not CurrentPage:
            CurrentPage = 1
        else:
            CurrentPage = int(CurrentPage)

        res_list = []
        if Type in ['MOV', 'TV', 'ALL']:
            res_list = self.get_randking_data(data, Type, SubType, CurrentPage)
        elif Type == "SEARCH":
            # 搜索词条
            Keyword = data.get("keyword")
            Source = data.get("source")
            mtype = Constants.MEDIA_TYPE_MAP.get(data.get("subtype"), None)
            medias = SearchProxy().search_media_by_keyword(keyword=Keyword, source=Source, page=CurrentPage, media_type=mtype)
            res_list = [media.to_dict() for media in medias]
            # 相关性排序
            res_list = self.sort_search_results(res_list, Keyword)
        elif Type == "DOWNLOADED":
            # 近期下载
            res_list = self.get_downloaded({"page": CurrentPage}).get("Items")
        elif Type == "TRENDING":
            # TMDB流行趋势
            if SubType == "trendingmv":
                res_list = Media().get_tmdb_trending_movie_week(page=CurrentPage)
            elif SubType == "trendingtv":
                res_list = Media().get_tmdb_trending_tv_week(page=CurrentPage)
            else:
                res_list = Media().get_tmdb_trending_all_week(page=CurrentPage)
        elif Type == "DISCOVER":
            # TMDB发现
            mtype = MediaType.MOVIE if SubType in Constants.MOVIE_TYPES else MediaType.TV
            # 过滤参数 with_genres with_original_language
            params = data.get("params") or {}

            res_list = Media().get_tmdb_discover(mtype=mtype, page=CurrentPage, params=params)
        elif Type == "DOUBANTAG":
            # 豆瓣发现
            mtype = MediaType.MOVIE if SubType in Constants.MOVIE_TYPES else MediaType.TV
            # 参数
            params = data.get("params") or {}
            # 排序
            sort = params.get("sort") or "R"
            # 选中的分类
            tags = params.get("tags") or ""
            # 过滤参数
            res_list = self._douBan.get_douban_disover(mtype=mtype,
                                                   sort=sort,
                                                   tags=tags,
                                                   page=CurrentPage)

        fav = data.get("fav", 1)
        # 不检查存在与订阅状态
        if not fav:
            return {"code": 0, "Items": res_list}

        # 补充存在与订阅状态
        for res in res_list:
            fav, rssid, item_url = MediaStatusChecker().get_media_exists_info(mtype=res.get("type"),
                                                              title=res.get("title"),
                                                              year=res.get("year"),
                                                              mediaid=res.get("id"))
            res.update({
                'fav': fav,
                'rssid': rssid,
                'item_url': item_url
            })
        return {"code": 0, "Items": res_list}
    
    def batch_get_media_exists_info(self, data):
        """
        批量获取媒体存在标记：是否存在、是否订阅
        """
        media_list = data.get("list")
        if not media_list:
            return {"code": 0, "Items": []} 

        for item in media_list:
            fav, rssid, item_url = MediaStatusChecker().get_media_exists_info(mtype=item.get("type"),
                                                              title=item.get("title"),
                                                              year=item.get("year"),
                                                              mediaid=item.get("tmdbid"))
            item.update({
                'fav': fav,
                'rssid': rssid,
                'item_url': item_url
            })
        return {"code": 0, "items": media_list}


    def get_randking_data(self, data, Type, SubType, CurrentPage):
        
        if SubType == "hm":
            # TMDB热门电影
            return Media().get_tmdb_hot_movies(CurrentPage)
        
        if SubType == "ht":
            # TMDB热门电视剧
            return Media().get_tmdb_hot_tvs(CurrentPage)
        
        if SubType == "nm":
            # TMDB最新电影
            return Media().get_tmdb_new_movies(CurrentPage)
        
        if SubType == "nt":
            # TMDB最新电视剧
            return Media().get_tmdb_new_tvs(CurrentPage)
        
        if SubType == "dbom":
                # 豆瓣正在上映
            return self._douBan.get_douban_online_movie(CurrentPage)
        
        if SubType == "dbhm":
            # 豆瓣热门电影
            return self._douBan.get_douban_hot_movie(CurrentPage)
        
        if SubType == "dbht":
            # 豆瓣热门电视剧
            return self._douBan.get_douban_hot_tv(CurrentPage)
        
        if SubType == "dbdh":
            # 豆瓣热门动画
            return self._douBan.get_douban_hot_anime(CurrentPage)
        
        if SubType == "dbnm":
            # 豆瓣最新电影
            return self._douBan.get_douban_new_movie(CurrentPage)
        
        if SubType == "dbtop":
            # 豆瓣TOP250电影
            return self._douBan.get_douban_top250_movie(CurrentPage)
        
        if SubType == "dbzy":
            # 豆瓣热门综艺
            return self._douBan.get_douban_hot_show(CurrentPage)
        
        if SubType == "dbct":
            # 华语口碑剧集榜
            return self._douBan.get_douban_chinese_weekly_tv(CurrentPage)
        
        if SubType == "dbgt":
            # 全球口碑剧集榜
            return self._douBan.get_douban_weekly_tv_global(CurrentPage)
        
        if SubType == "sim":
            # 相似推荐
            TmdbId = data.get("tmdbid")
            return self.__media_similar({
                    "tmdbid": TmdbId,
                    "page": CurrentPage,
                    "type": Type
                }).get("data")
        
        if SubType == "more":
            # 更多推荐
            TmdbId = data.get("tmdbid")
            return self.__media_recommendations({
                    "tmdbid": TmdbId,
                    "page": CurrentPage,
                    "type": Type
                }).get("data")
        
        if SubType == "person":
            # 人物作品
            PersonId = data.get("personid")
            return self.__person_medias({
                    "personid": PersonId,
                    "type": None if Type == 'ALL' else Type,
                    "page": CurrentPage
                }).get("data")
        
        if SubType == "bangumi":
            # Bangumi每日放送
            Week = data.get("week")
            return Bangumi().get_bangumi_calendar(page=CurrentPage, week=Week)
        
        return []
    
    def sort_search_results(self, results, kw):
        # 计算相关性级别
        def compute_relevance_level(title):
            title_lower = title.lower()
            kw_lower = kw.lower()
            
            # 完全匹配（标题等于关键词）
            if title_lower == kw_lower:
                return 3  # 最高优先级
            # 前缀匹配（标题以关键词开头）
            elif title_lower.startswith(kw_lower):
                return 2  # 次高优先级
            # 包含关键词
            elif kw_lower in title_lower:
                return 1  # 基础优先级
            # 不相关
            else:
                return 0  # 最低优先级
        
        # 排序处理
        sorted_results = sorted(
            results,
            key=lambda x: (
                compute_relevance_level(x['title']),  # 相关性级别（降序）
                x['release_date']  # 发布日期（降序）
            ),
            reverse=True
        )
        return sorted_results

    def get_downloaded(self, data):
        page = data.get("page")
        Items = Downloader().get_download_history(page=page)
        if Items:
            return {"code": 0, "Items": [{
                'id': item.TMDBID,
                'orgid': item.TMDBID,
                'tmdbid': item.TMDBID,
                'title': item.TITLE,
                'type': 'MOV' if item.TYPE == "电影" else "TV",
                'media_type': item.TYPE,
                'year': item.YEAR,
                'vote': item.VOTE,
                'image': item.POSTER,
                'backdrop': item.BACKDROP,
                'overview': item.OVERVIEW,
                "date": item.DATE,
                "site": item.SITE
            } for item in Items]}
        else:
            return {"code": 0, "Items": []}

    def __clear_tmdb_cache(self):
        """
        清空TMDB缓存
        """
        try:
            MetaHelper().clear_meta_data()
            os.remove(MetaHelper().get_meta_data_path())
        except Exception as e:
            log.exception("[act]清空TMDB缓存出错:")
            return {"code": 0, "msg": str(e)}
        return {"code": 0}

    def __check_site_attr(self, data):
        """
        检查站点标识
        """
        site_attr = SiteConf().get_grap_conf(data.get("url"))
        site_free = site_2xfree = site_hr = False
        if site_attr.get("FREE"):
            site_free = True
        if site_attr.get("2XFREE"):
            site_2xfree = True
        if site_attr.get("HR"):
            site_hr = True
        return {"code": 0, "site_free": site_free, "site_2xfree": site_2xfree, "site_hr": site_hr}
       
    def refresh_process(self, data):
        """
        刷新进度条
        """
        detail = ProgressHelper().get_process(data.get("type"))
        if detail:
            return {"code": 0, "value": detail.get("value"), "text": detail.get("text")}
        else:
            return {"code": 1, "value": 0, "text": "正在处理..."}

    def __restory_backup(self, data):
        """
        解压恢复备份文件
        """
        filename = data.get("file_name")
        if filename:
            config_path = Config().get_config_path()
            temp_path = Config().get_temp_path()
            file_path = os.path.join(temp_path, filename)
            try:
                shutil.unpack_archive(file_path, config_path, format='zip')
                return {"code": 0, "msg": ""}
            except Exception as e:
                log.exception("[act]解压恢复备份文件出错:")
                return {"code": 1, "msg": str(e)}
            finally:
                if os.path.exists(file_path):
                    os.remove(file_path)

        return {"code": 1, "msg": "文件不存在"}

    def __start_mediasync(self, data):
        """
        开始媒体库同步
        """
        librarys = data.get("librarys") or []
        SystemConfig().set(key=SystemConfigKey.SyncLibrary, value=librarys)
        ThreadHelper().start_thread(MediaServer().sync_mediaserver, ())
        return {"code": 0}

    def __mediasync_state(self):
        """
        获取媒体库同步数据情况
        """
        status = MediaServer().get_mediasync_status()
        if not status:
            return {"code": 0, "text": "未同步"}
        else:
            return {"code": 0, "text": "电影：%s，电视剧：%s，同步时间：%s" %
                                       (status.get("movie_count"),
                                        status.get("tv_count"),
                                        status.get("time"))}

    def __get_tvseason_list(self, data):
        """
        获取剧集季列表
        """
        tmdbid = data.get("tmdbid")
        title = data.get("title")
        if title:
            title_season = MetaInfo(title=title).begin_season
        else:
            title_season = None
        
        _media = Media()
        if not str(tmdbid).isdigit():
            media_info = _media.get_mediainfo_from_id(mediaid=tmdbid, mtype=MediaType.TV)
            season_infos = _media.get_tmdb_tv_seasons(media_info.tmdb_info)
        else:
            season_infos = _media.get_tmdb_tv_seasons_byid(tmdbid=tmdbid)

        if title_season:
            seasons = [
                {
                    "text": "第%s季" % title_season,
                    "num": title_season
                }
            ]
        else:
            seasons = MediaUtils.batch_convert_ch_season_info(season_infos)
        return {"code": 0, "seasons": seasons}

    def __get_userrss_task(self, data):
        """
        获取自定义订阅详情
        """
        taskid = data.get("id")
        return {"code": 0, "detail": RssChecker().get_rsstask_info(taskid=taskid)}

    def __delete_userrss_task(self, data):
        """
        删除自定义订阅
        """
        if RssChecker().delete_userrss_task(data.get("id")):
            return {"code": 0}
        else:
            return {"code": 1}

    def __update_userrss_task(self, data):
        """
        新增或修改自定义订阅
        """
        uses = data.get("uses")
        address_parser = data.get("address_parser")
        if not address_parser:
            return {"code": 1}
        address = list(dict(sorted(
            {k.replace("address_", ""): y for k, y in address_parser.items() if k.startswith("address_")}.items(),
            key=lambda x: int(x[0])
        )).values())
        parser = list(dict(sorted(
            {k.replace("parser_", ""): y for k, y in address_parser.items() if k.startswith("parser_")}.items(),
            key=lambda x: int(x[0])
        )).values())
        params = {
            "id": data.get("id"),
            "name": data.get("name"),
            "address": address,
            "parser": parser,
            "interval": data.get("interval"),
            "uses": uses,
            "include": data.get("include"),
            "exclude": data.get("exclude"),
            "filter_rule": data.get("rule"),
            "state": data.get("state"),
            "save_path": data.get("save_path"),
            "download_setting": data.get("download_setting"),
            "note": {"proxy": data.get("proxy")},
        }
        if uses == "D":
            params.update({
                "recognization": data.get("recognization")
            })
        elif uses == "R":
            params.update({
                "over_edition": data.get("over_edition"),
                "sites": data.get("sites"),
                "filter_args": {
                    "restype": data.get("restype"),
                    "pix": data.get("pix"),
                    "team": data.get("team")
                }
            })
        else:
            return {"code": 1}
        if RssChecker().update_userrss_task(params):
            return {"code": 0}
        else:
            return {"code": 1}

    def __check_userrss_task(self, data):
        """
        检测自定义订阅
        """
        try:
            flag_dict = {"enable": True, "disable": False}
            taskids = data.get("ids")
            state = flag_dict.get(data.get("flag"))
            _rsschecker = RssChecker()
            if state is not None:
                if taskids:
                    for taskid in taskids:
                        _rsschecker.check_userrss_task(tid=taskid, state=state)
                else:
                    _rsschecker.check_userrss_task(state=state)
            return {"code": 0, "msg": ""}
        except Exception as e:
            log.exception("[act]自定义订阅状态设置出错:")
            return {"code": 1, "msg": "自定义订阅状态设置失败"}

    def __get_rssparser(self, data):
        """
        获取订阅解析器详情
        """
        pid = data.get("id")
        return {"code": 0, "detail": RssChecker().get_userrss_parser(pid=pid)}

    def __delete_rssparser(self, data):
        """
        删除订阅解析器
        """
        if RssChecker().delete_userrss_parser(data.get("id")):
            return {"code": 0}
        else:
            return {"code": 1}

    def __update_rssparser(self, data):
        """
        新增或更新订阅解析器
        """
        params = {
            "id": data.get("id"),
            "name": data.get("name"),
            "type": data.get("type"),
            "format": data.get("format"),
            "params": data.get("params")
        }
        if RssChecker().update_userrss_parser(params):
            return {"code": 0}
        else:
            return {"code": 1}

    def __run_userrss(self, data):
        RssChecker().check_task_rss(data.get("id"))
        return {"code": 0}

    def __run_brushtask(self, data):
        BrushTask().check_task_rss(data.get("id"))
        return {"code": 0}

    def list_site_resources(self, data):
        resources = Indexer().list_resources(index_id=data.get("id"),
                                             page=data.get("page"),
                                             keyword=data.get("keyword"))
        if not resources:
            return {"code": 1, "msg": "获取站点资源出现错误，无法连接到站点！"}
        else:
            return {"code": 0, "data": resources}

    def __list_rss_articles(self, data):
        task_info = RssChecker().get_rsstask_info(taskid=data.get("id"))
        uses = task_info.get("uses")
        address_count = len(task_info.get("address"))
        articles = RssChecker().get_rss_articles(data.get("id"))
        count = len(articles)
        if articles:
            return {"code": 0, "data": articles, "count": count, "uses": uses, "address_count": address_count}
        else:
            return {"code": 1, "msg": "未获取到报文"}

    def __rss_article_test(self, data):
        taskid = data.get("taskid")
        title = data.get("title")
        if not taskid:
            return {"code": -1}
        if not title:
            return {"code": -1}
        media_info, match_flag, exist_flag = RssChecker(
        ).test_rss_articles(taskid=taskid, title=title)
        if not media_info:
            return {"code": 0, "data": {"name": "无法识别"}}
        media_dict = MediaUtils.mediainfo_dict(media_info)
        media_dict.update({"match_flag": match_flag, "exist_flag": exist_flag})
        return {"code": 0, "data": media_dict}

    def __list_rss_history(self, data):
        downloads = []
        historys = RssChecker().get_userrss_task_history(data.get("id"))
        count = len(historys)
        for history in historys:
            params = {
                "title": history.TITLE,
                "downloader": history.DOWNLOADER,
                "date": history.DATE
            }
            downloads.append(params)
        if downloads:
            return {"code": 0, "data": downloads, "count": count}
        else:
            return {"code": 1, "msg": "无下载记录"}

    def __rss_articles_check(self, data):
        if not data.get("articles"):
            return {"code": 2}
        res = RssChecker().check_rss_articles(
            taskid=data.get("taskid"),
            flag=data.get("flag"),
            articles=data.get("articles")
        )
        if res:
            return {"code": 0}
        else:
            return {"code": 1}

    def __rss_articles_download(self, data):
        if not data.get("articles"):
            return {"code": 2}
        res = RssChecker().download_rss_articles(
            taskid=data.get("taskid"), articles=data.get("articles"))
        if res:
            return {"code": 0}
        else:
            return {"code": 1}

    def __add_custom_word_group(self, data):
        try:
            tmdb_id = data.get("tmdb_id")
            tmdb_type = data.get("tmdb_type")
            _wordshelper = WordsHelper()
            _media = Media()
            if tmdb_type == "tv":
                if not _wordshelper.is_custom_word_group_existed(tmdbid=tmdb_id, gtype=2):
                    tmdb_info = _media.get_tmdb_info(mtype=MediaType.TV, tmdbid=tmdb_id)
                    if not tmdb_info:
                        return {"code": 1, "msg": "添加失败，无法查询到TMDB信息"}
                    _wordshelper.insert_custom_word_groups(title=tmdb_info.get("name"),
                                                           year=tmdb_info.get(
                                                               "first_air_date")[0:4],
                                                           gtype=2,
                                                           tmdbid=tmdb_id,
                                                           season_count=tmdb_info.get("number_of_seasons"))
                    return {"code": 0, "msg": ""}
                else:
                    return {"code": 1, "msg": "识别词组（TMDB ID）已存在"}
            elif tmdb_type == "movie":
                if not _wordshelper.is_custom_word_group_existed(tmdbid=tmdb_id, gtype=1):
                    tmdb_info = _media.get_tmdb_info(mtype=MediaType.MOVIE, tmdbid=tmdb_id)
                    if not tmdb_info:
                        return {"code": 1, "msg": "添加失败，无法查询到TMDB信息"}
                    _wordshelper.insert_custom_word_groups(title=tmdb_info.get("title"),
                                                           year=tmdb_info.get(
                                                               "release_date")[0:4],
                                                           gtype=1,
                                                           tmdbid=tmdb_id,
                                                           season_count=0)
                    return {"code": 0, "msg": ""}
                else:
                    return {"code": 1, "msg": "识别词组（TMDB ID）已存在"}
            else:
                return {"code": 1, "msg": "无法识别媒体类型"}
        except Exception as e:
            log.exception("[act]增加自定义识别词组 出错:")
            return {"code": 1, "msg": str(e)}

    def __delete_custom_word_group(self, data):
        try:
            gid = data.get("gid")
            WordsHelper().delete_custom_word_group(gid=gid)
            return {"code": 0, "msg": ""}
        except Exception as e:
            log.exception("[act]删除自定义识别词组 出错:")
            return {"code": 1, "msg": str(e)}

    def __add_or_edit_custom_word(self, data):
        try:
            wid = data.get("id")
            gid = data.get("gid")
            group_type = data.get("group_type")
            replaced = data.get("new_replaced")
            replace = data.get("new_replace")
            front = data.get("new_front")
            back = data.get("new_back")
            offset = data.get("new_offset")
            whelp = data.get("new_help")
            wtype = data.get("type")
            season = data.get("season")
            enabled = data.get("enabled")
            regex = data.get("regex")

            _wordshelper = WordsHelper()

            # 集数偏移格式检查
            if wtype in ["3", "4"]:
                if not re.findall(r'EP', offset):
                    return {"code": 1, "msg": "偏移集数格式有误"}
                if re.findall(r'(?!-|\+|\*|/|[0-9]).', re.sub(r'EP', "", offset)):
                    return {"code": 1, "msg": "偏移集数格式有误"}
            if wid:
                _wordshelper.delete_custom_word(wid=wid)
            # 电影
            if group_type == "1":
                season = -2
            # 屏蔽
            if wtype == "1":
                if not _wordshelper.is_custom_words_existed(replaced=replaced):
                    _wordshelper.insert_custom_word(replaced=replaced,
                                                    replace="",
                                                    front="",
                                                    back="",
                                                    offset="",
                                                    wtype=wtype,
                                                    gid=gid,
                                                    season=season,
                                                    enabled=enabled,
                                                    regex=regex,
                                                    whelp=whelp if whelp else "")
                    return {"code": 0, "msg": ""}
                else:
                    return {"code": 1, "msg": "识别词已存在\n（被替换词：%s）" % replaced}
            # 替换
            elif wtype == "2":
                if not _wordshelper.is_custom_words_existed(replaced=replaced):
                    _wordshelper.insert_custom_word(replaced=replaced,
                                                    replace=replace,
                                                    front="",
                                                    back="",
                                                    offset="",
                                                    wtype=wtype,
                                                    gid=gid,
                                                    season=season,
                                                    enabled=enabled,
                                                    regex=regex,
                                                    whelp=whelp if whelp else "")
                    return {"code": 0, "msg": ""}
                else:
                    return {"code": 1, "msg": "识别词已存在\n（被替换词：%s）" % replaced}
            # 集偏移
            elif wtype == "4":
                if not _wordshelper.is_custom_words_existed(front=front, back=back):
                    _wordshelper.insert_custom_word(replaced="",
                                                    replace="",
                                                    front=front,
                                                    back=back,
                                                    offset=offset,
                                                    wtype=wtype,
                                                    gid=gid,
                                                    season=season,
                                                    enabled=enabled,
                                                    regex=regex,
                                                    whelp=whelp if whelp else "")
                    return {"code": 0, "msg": ""}
                else:
                    return {"code": 1, "msg": "识别词已存在\n（前后定位词：%s@%s）" % (front, back)}
            # 替换+集偏移
            elif wtype == "3":
                if not _wordshelper.is_custom_words_existed(replaced=replaced):
                    _wordshelper.insert_custom_word(replaced=replaced,
                                                    replace=replace,
                                                    front=front,
                                                    back=back,
                                                    offset=offset,
                                                    wtype=wtype,
                                                    gid=gid,
                                                    season=season,
                                                    enabled=enabled,
                                                    regex=regex,
                                                    whelp=whelp if whelp else "")
                    return {"code": 0, "msg": ""}
                else:
                    return {"code": 1, "msg": "识别词已存在\n（被替换词：%s）" % replaced}
            else:
                return {"code": 1, "msg": ""}
        except Exception as e:
            log.exception("[act]新增或修改自定义识别词 出错:")
            return {"code": 1, "msg": str(e)}

    def __get_custom_word(self, data):
        try:
            wid = data.get("wid")
            word_info = WordsHelper().get_custom_words(wid=wid)
            if word_info:
                word_info = word_info[0]
                word = {"id": word_info.ID,
                        "replaced": word_info.REPLACED,
                        "replace": word_info.REPLACE,
                        "front": word_info.FRONT,
                        "back": word_info.BACK,
                        "offset": word_info.OFFSET,
                        "type": word_info.TYPE,
                        "group_id": word_info.GROUP_ID,
                        "season": word_info.SEASON,
                        "enabled": word_info.ENABLED,
                        "regex": word_info.REGEX,
                        "help": word_info.HELP, }
            else:
                word = {}
            return {"code": 0, "data": word}
        except Exception as e:
            log.exception("[act]查询识别词 出错:")
            return {"code": 1, "msg": "查询识别词失败"}

    def __delete_custom_words(self, data):
        try:
            _wordshelper = WordsHelper()
            ids_info = data.get("ids_info")
            if not ids_info:
                _wordshelper.delete_custom_word()
            else:
                ids = [id_info.split("_")[1] for id_info in ids_info]
                for wid in ids:
                    _wordshelper.delete_custom_word(wid=wid)
            return {"code": 0, "msg": ""}
        except Exception as e:
            log.exception("[act]自定义识别词 出错:")
            return {"code": 1, "msg": str(e)}

    def __check_custom_words(self, data):
        try:
            flag_dict = {"enable": 1, "disable": 0}
            ids_info = data.get("ids_info")
            enabled = flag_dict.get(data.get("flag"))
            _wordshelper = WordsHelper()
            if not ids_info:
                _wordshelper.check_custom_word(enabled=enabled)
            else:
                ids = [id_info.split("_")[1] for id_info in ids_info]
                for wid in ids:
                    _wordshelper.check_custom_word(wid=wid, enabled=enabled)
            return {"code": 0, "msg": ""}
        except Exception as e:
            log.exception("[act]识别词状态设置 出错:")
            return {"code": 1, "msg": "识别词状态设置失败"}

    def __export_custom_words(self, data):
        try:
            note = data.get("note")
            ids_info = data.get("ids_info")
            group_ids = []
            word_ids = []
            group_infos = []
            word_infos = []

            _wordshelper = WordsHelper()

            if ids_info:
                ids_info = ids_info.split("@")
                for id_info in ids_info:
                    wid = id_info.split("_")
                    group_ids.append(wid[0])
                    word_ids.append(wid[1])
                for group_id in group_ids:
                    if group_id != "-1":
                        group_info = _wordshelper.get_custom_word_groups(gid=group_id)
                        if group_info:
                            group_infos.append(group_info[0])
                for word_id in word_ids:
                    word_info = _wordshelper.get_custom_words(wid=word_id)
                    if word_info:
                        word_infos.append(word_info[0])
            else:
                group_infos = _wordshelper.get_custom_word_groups()
                word_infos = _wordshelper.get_custom_words()
            export_dict = {}
            if not group_ids or "-1" in group_ids:
                export_dict["-1"] = {"id": -1,
                                     "title": "通用",
                                     "type": 1,
                                     "words": {}, }
            for group_info in group_infos:
                export_dict[str(group_info.ID)] = {"id": group_info.ID,
                                                   "title": group_info.TITLE,
                                                   "year": group_info.YEAR,
                                                   "type": group_info.TYPE,
                                                   "tmdbid": group_info.TMDBID,
                                                   "season_count": group_info.SEASON_COUNT,
                                                   "words": {}, }
            for word_info in word_infos:
                export_dict[str(word_info.GROUP_ID)]["words"][str(word_info.ID)] = {"id": word_info.ID,
                                                                                    "replaced": word_info.REPLACED,
                                                                                    "replace": word_info.REPLACE,
                                                                                    "front": word_info.FRONT,
                                                                                    "back": word_info.BACK,
                                                                                    "offset": word_info.OFFSET,
                                                                                    "type": word_info.TYPE,
                                                                                    "season": word_info.SEASON,
                                                                                    "regex": word_info.REGEX,
                                                                                    "help": word_info.HELP, }
            export_string = json.dumps(export_dict) + "@@@@@@" + str(note)
            string = base64.b64encode(
                export_string.encode("utf-8")).decode('utf-8')
            return {"code": 0, "string": string}
        except Exception as e:
            log.exception("[act]导出自定义识别词 出错:")
            return {"code": 1, "msg": str(e)}

    def __analyse_import_custom_words_code(self, data):
        try:
            import_code = data.get('import_code')
            string = base64.b64decode(import_code.encode(
                "utf-8")).decode('utf-8').split("@@@@@@")
            note_string = string[1]
            import_dict = json.loads(string[0])
            groups = []
            for group in import_dict.values():
                wid = group.get('id')
                title = group.get("title")
                year = group.get("year")
                wtype = group.get("type")
                tmdbid = group.get("tmdbid")
                season_count = group.get("season_count") or ""
                words = group.get("words")
                if tmdbid:
                    link = "https://www.themoviedb.org/%s/%s" % (
                        "movie" if int(wtype) == 1 else "tv", tmdbid)
                else:
                    link = ""
                groups.append({"id": wid,
                               "name": "%s（%s）" % (title, year) if year else title,
                               "link": link,
                               "type": wtype,
                               "seasons": season_count,
                               "words": words})
            return {"code": 0, "groups": groups, "note_string": note_string}
        except Exception as e:
            log.exception("[act]分析识别词导入Code 出错:")
            return {"code": 1, "msg": str(e)}

    def __import_custom_words(self, data):
        try:
            _wordshelper = WordsHelper()
            import_code = data.get('import_code')
            ids_info = data.get('ids_info')
            string = base64.b64decode(import_code.encode(
                "utf-8")).decode('utf-8').split("@@@@@@")
            import_dict = json.loads(string[0])
            import_group_ids = [id_info.split("_")[0] for id_info in ids_info]
            group_id_dict = {}
            for import_group_id in import_group_ids:
                import_group_info = import_dict.get(import_group_id)
                if int(import_group_info.get("id")) == -1:
                    group_id_dict["-1"] = -1
                    continue
                title = import_group_info.get("title")
                year = import_group_info.get("year")
                gtype = import_group_info.get("type")
                tmdbid = import_group_info.get("tmdbid")
                season_count = import_group_info.get("season_count")
                if not _wordshelper.is_custom_word_group_existed(tmdbid=tmdbid, gtype=gtype):
                    _wordshelper.insert_custom_word_groups(title=title,
                                                           year=year,
                                                           gtype=gtype,
                                                           tmdbid=tmdbid,
                                                           season_count=season_count)
                group_info = _wordshelper.get_custom_word_groups(
                    tmdbid=tmdbid, gtype=gtype)
                if group_info:
                    group_id_dict[import_group_id] = group_info[0].ID
            for id_info in ids_info:
                id_info = id_info.split('_')
                import_group_id = id_info[0]
                import_word_id = id_info[1]
                import_word_info = import_dict.get(
                    import_group_id).get("words").get(import_word_id)
                gid = group_id_dict.get(import_group_id)
                replaced = import_word_info.get("replaced")
                replace = import_word_info.get("replace")
                front = import_word_info.get("front")
                back = import_word_info.get("back")
                offset = import_word_info.get("offset")
                whelp = import_word_info.get("help")
                wtype = int(import_word_info.get("type"))
                season = import_word_info.get("season")
                regex = import_word_info.get("regex")
                # 屏蔽, 替换, 替换+集偏移
                if wtype in [1, 2, 3]:
                    if _wordshelper.is_custom_words_existed(replaced=replaced):
                        return {"code": 1, "msg": "识别词已存在\n（被替换词：%s）" % replaced}
                # 集偏移
                elif wtype == 4:
                    if _wordshelper.is_custom_words_existed(front=front, back=back):
                        return {"code": 1, "msg": "识别词已存在\n（前后定位词：%s@%s）" % (front, back)}
                _wordshelper.insert_custom_word(replaced=replaced,
                                                replace=replace,
                                                front=front,
                                                back=back,
                                                offset=offset,
                                                wtype=wtype,
                                                gid=gid,
                                                season=season,
                                                enabled=1,
                                                regex=regex,
                                                whelp=whelp if whelp else "")
            return {"code": 0, "msg": ""}
        except Exception as e:
            log.exception("[act]自定义识别词导入 出错:")
            return {"code": 1, "msg": str(e)}

    def __delete_rss_history(self, data):
        rssid = data.get("rssid")
        Rss().delete_rss_history(rssid=rssid)
        return {"code": 0}

    def __re_rss_history(self, data):
        rssid = data.get("rssid")
        rtype = data.get("type")
        rssinfo = Rss().get_rss_history(rtype=rtype, rid=rssid)
        if rssinfo:
            if rtype == "MOV":
                mtype = MediaType.MOVIE
            else:
                mtype = MediaType.TV
            if rssinfo[0].SEASON:
                season = int(str(rssinfo[0].SEASON).replace("S", ""))
            else:
                season = None
            code, msg, _ = Subscribe().add_rss_subscribe(mtype=mtype,
                                                         name=rssinfo[0].NAME,
                                                         year=rssinfo[0].YEAR,
                                                         channel=RssType.Auto,
                                                         season=season,
                                                         mediaid=rssinfo[0].TMDBID,
                                                         total_ep=rssinfo[0].TOTAL,
                                                         current_ep=rssinfo[0].START)
            return {"code": code, "msg": msg}
        else:
            return {"code": 1, "msg": "订阅历史记录不存在"}

    def __share_filtergroup(self, data):
        gid = data.get("id")
        _filter = Filter()
        group_info = _filter.get_filter_group(gid=gid)
        if not group_info:
            return {"code": 1, "msg": "规则组不存在"}
        group_rules = _filter.get_filter_rule(groupid=gid)
        if not group_rules:
            return {"code": 1, "msg": "规则组没有对应规则"}
        rules = []
        for rule in group_rules:
            rules.append({
                "name": rule.ROLE_NAME,
                "pri": rule.PRIORITY,
                "include": rule.INCLUDE,
                "exclude": rule.EXCLUDE,
                "size": rule.SIZE_LIMIT,
                "free": rule.NOTE
            })
        rule_json = {
            "name": group_info[0].GROUP_NAME,
            "rules": rules
        }
        json_string = base64.b64encode(json.dumps(
            rule_json).encode("utf-8")).decode('utf-8')
        return {"code": 0, "string": json_string}

    def __import_filtergroup(self, data):
        content = data.get("content")
        try:
            _filter = Filter()

            json_str = base64.b64decode(
                str(content).encode("utf-8")).decode('utf-8')
            json_obj = json.loads(json_str)
            if json_obj:
                if not json_obj.get("name"):
                    return {"code": 1, "msg": "数据格式不正确"}
                _filter.add_group(name=json_obj.get("name"))
                group_id = _filter.get_filter_groupid_by_name(
                    json_obj.get("name"))
                if not group_id:
                    return {"code": 1, "msg": "数据内容不正确"}
                if json_obj.get("rules"):
                    for rule in json_obj.get("rules"):
                        _filter.add_filter_rule(item={
                            "group": group_id,
                            "name": rule.get("name"),
                            "pri": rule.get("pri"),
                            "include": rule.get("include"),
                            "exclude": rule.get("exclude"),
                            "size": rule.get("size"),
                            "free": rule.get("free")
                        })
            return {"code": 0, "msg": ""}
        except Exception as err:
            log.exception("[act]导入过滤规则失败:")
            return {"code": 1, "msg": "数据格式不正确，%s" % str(err)}


    def get_transfer_statistics(self):
        """
        查询转移历史统计数据
        """
        Labels = []
        MovieNums = []
        TvNums = []
        AnimeNums = []
        for statistic in FileTransfer().get_transfer_statistics(90):
            if not statistic[2]:
                continue
            if statistic[1] not in Labels:
                Labels.append(statistic[1])
            if statistic[0] == "电影":
                MovieNums.append(statistic[2])
                TvNums.append(0)
                AnimeNums.append(0)
            elif statistic[0] == "电视剧":
                TvNums.append(statistic[2])
                MovieNums.append(0)
                AnimeNums.append(0)
            else:
                AnimeNums.append(statistic[2])
                MovieNums.append(0)
                TvNums.append(0)
        return {
            "code": 0,
            "Labels": Labels,
            "MovieNums": MovieNums,
            "TvNums": TvNums,
            "AnimeNums": AnimeNums
        }

    def _search_media_infos(self, data):
        """
        根据关键字搜索相似词条
        """
        SearchWord = data.get("keyword")
        if not SearchWord:
            return []
        SearchSourceType = data.get("searchtype")
        medias = SearchProxy().search_media_by_keyword(keyword=SearchWord, source=SearchSourceType)

        return {"code": 0, "result": [media.to_dict() for media in medias]}

    def get_downloading(self, data):
        """
        查询正在下载的任务
        """
        downloader_id = data.get("downloader_id")

        DownloaderHandler = Downloader()
        torrents = DownloaderHandler.get_downloading_progress(downloader_id=downloader_id)
        for torrent in torrents:
            # 先查询下载记录，没有再识别
            name = torrent.get("name")
            download_info = DownloaderHandler.get_download_history_by_downloader(
                downloader=downloader_id,
                download_id=torrent.get("id")
            )
            if download_info:
                name = download_info.TITLE
                year = download_info.YEAR
                poster_path = download_info.POSTER
                backdrop = download_info.BACKDROP
                se = download_info.SE
                title = "%s(%s)" % (name, year) if year and download_info.TYPE == '电影' else name
                tpye_str = 'MOV' if download_info.TYPE == '电影' else 'TV'
                vote = download_info.VOTE

                torrent.update({
                    "tmdbid": download_info.TMDBID,
                    "title": title,
                    "se": se,
                    "image": poster_path or "",
                    "backdrop" : backdrop or "",
                    "type": tpye_str,
                    "vote": vote,
                    "site": download_info.SITE
                })

        return {"code": 0, "result": torrents}

    def get_filterrules(self):
        """
        查询所有过滤规则
        """
        RuleGroups = Filter().get_rule_infos()

        return {
            "code": 0,
            "ruleGroups": RuleGroups
        }

    def __update_directory(self, data):
        """
        维护媒体库目录
        """
        cfg = self.set_config_directory(Config().get_config(),
                                        data.get("oper"),
                                        data.get("key"),
                                        data.get("value"),
                                        data.get("replace_value"))
        # 保存配置
        Config().save_config(cfg)
        return {"code": 0}

    def __test_site(self, data):
        """
        测试站点连通性
        """
        flag, msg, times = SitesManager().test_connection(data.get("id"))
        code = 0 if flag else -1
        return {"code": code, "msg": msg, "time": times}

    def __get_sub_path(self, data):
        """
        查询下级子目录
        """
        r = FileHelper.get_sub_path(data.get("filter"), data.get("dir"))
        return {
            "code": 0,
            "count": len(r),
            "data": r
        }

    def __rename_file(self, data):
        """
        文件重命名
        """
        path = data.get("path")
        name = data.get("name")
        if path and name:
            try:
                shutil.move(path, os.path.join(os.path.dirname(path), name))
            except Exception as e:
                log.exception("[act]文件重命名 异常:")
                return {"code": -1, "msg": str(e)}
        return {"code": 0}

    def __delete_files(self, data):
        """
        删除文件
        """
        files = data.get("files")
        if files:
            # 删除文件
            for file in files:
                del_flag, del_msg = FileHelper.delete_media_file(filedir=os.path.dirname(file),
                                                           filename=os.path.basename(file))
                if not del_flag:
                    log.error(del_msg)
                else:
                    log.info(del_msg)
        return {"code": 0}

    def __download_subtitle(self, data):
        """
        从配置的字幕服务下载单个文件的字幕
        """
        path = data.get("path")
        name = data.get("name")
        media = Media().get_media_info(title=name)
        if not media or not media.tmdb_info:
            return {"code": -1, "msg": f"{name} 无法从TMDB查询到媒体信息"}
        if not media.imdb_id:
            media.set_tmdb_info(Media().get_tmdb_info(mtype=media.type,
                                                      tmdbid=media.tmdb_id))
        # 触发字幕下载事件
        EventManager().send_event(EventType.SubtitleDownload, {
            "media_info": media.to_dict(),
            "file": os.path.splitext(path)[0],
            "file_ext": os.path.splitext(name)[-1],
            "bluray": False
        })
        return {"code": 0, "msg": "字幕下载任务已提交，正在后台运行。"}

    def __media_path_scrap(self, data):
        """
        刮削媒体文件夹或文件
        """
        path = data.get("path")
        if not path:
            return {"code": -1, "msg": "请指定刮削路径"}
        ThreadHelper().start_thread(Scraper().folder_scraper, (path, None, 'force_all'))
        return {"code": 0, "msg": "刮削任务已提交，正在后台运行。"}

    def __get_download_setting(self, data):
        sid = data.get("sid")
        if sid:
            download_setting = Downloader().get_download_setting(sid=sid)
        else:
            download_setting = list(
                Downloader().get_download_setting().values())
        return {"code": 0, "data": download_setting}

    def __update_download_setting(self, data):
        sid = data.get("sid")
        name = data.get("name")
        category = data.get("category")
        tags = data.get("tags")
        is_paused = data.get("is_paused")
        upload_limit = data.get("upload_limit")
        download_limit = data.get("download_limit")
        ratio_limit = data.get("ratio_limit")
        seeding_time_limit = data.get("seeding_time_limit")
        downloader = data.get("downloader")
        Downloader().update_download_setting(sid=sid,
                                             name=name,
                                             category=category,
                                             tags=tags,
                                             is_paused=is_paused,
                                             upload_limit=upload_limit or 0,
                                             download_limit=download_limit or 0,
                                             ratio_limit=ratio_limit or 0,
                                             seeding_time_limit=seeding_time_limit or 0,
                                             downloader=downloader)
        return {"code": 0}

    def __delete_download_setting(self, data):
        sid = data.get("sid")
        Downloader().delete_download_setting(sid=sid)
        return {"code": 0}

    def __update_message_client(self, data):
        """
        更新消息设置
        """
        _message = Message()
        name = data.get("name")
        cid = data.get("cid")
        ctype = data.get("type")
        config = data.get("config")
        switchs = data.get("switchs")
        interactive = data.get("interactive")
        enabled = data.get("enabled")
        if cid:
            _message.delete_message_client(cid=cid)
        # if int(interactive) == 1:
        #     _message.check_message_client(interactive=0, ctype=ctype)
        _message.insert_message_client(name=name,
                                       ctype=ctype,
                                       config=config,
                                       switchs=switchs,
                                       interactive=interactive,
                                       enabled=enabled)
        return {"code": 0}

    def __delete_message_client(self, data):
        """
        删除消息设置
        """
        if Message().delete_message_client(cid=data.get("cid")):
            return {"code": 0}
        else:
            return {"code": 1}

    def __check_message_client(self, data):
        """
        维护消息设置
        """
        flag = data.get("flag")
        cid = data.get("cid")
        ctype = data.get("type")
        checked = data.get("checked")
        _message = Message()
        if flag == "interactive":
            # TG/WX只能开启一个交互
            if checked:
                _message.check_message_client(interactive=0, ctype=ctype)
            _message.check_message_client(cid=cid,
                                          interactive=1 if checked else 0)
            return {"code": 0}
        elif flag == "enable":
            _message.check_message_client(cid=cid,
                                          enabled=1 if checked else 0)
            return {"code": 0}
        else:
            return {"code": 1}

    def __get_message_client(self, data):
        """
        获取消息设置
        """
        cid = data.get("cid")
        return {"code": 0, "detail": Message().get_message_client_info(cid=cid)}

    def __test_message_client(self, data):
        """
        测试消息设置
        """
        ctype = data.get("type")
        config = json.loads(data.get("config"))
        res = Message().get_status(ctype=ctype, config=config)
        if res:
            return {"code": 0}
        else:
            return {"code": 1}

    def __get_indexers(self):
        """
        获取索引器
        """
        return {"code": 0, "indexers": Indexer().get_user_indexer_dict()}

    def __get_download_dirs(self, data):
        """
        获取下载目录
        """
        sid = data.get("sid")
        site = data.get("site")
        if not sid and site:
            sid = SitesManager().get_site_download_setting(site_name=site)
        dirs = Downloader().get_download_dirs(setting=sid)
        return {"code": 0, "paths": dirs}

    def __find_hardlinks(self, data):
        files = data.get("files")
        file_dir = data.get("dir")
        if not files:
            return []
        if not file_dir and os.name != "nt":
            # 取根目录下一级为查找目录
            file_dir = os.path.commonpath(files).replace("\\", "/")
            if file_dir != "/":
                file_dir = "/" + str(file_dir).split("/")[1]
            else:
                return []
        hardlinks = {}
        if files:
            try:
                for file in files:
                    hardlinks[os.path.basename(file)] = SystemUtils(
                    ).find_hardlinks(file=file, fdir=file_dir)
            except Exception as e:
                log.exception("[act]硬链接查找 异常:")
                return {"code": 1}
        return {"code": 0, "data": hardlinks}

    def __update_sites_cookie_ua(self, data):
        """
        更新所有站点的Cookie和UA
        """
        siteid = data.get("siteid")
        username = data.get("username")
        password = data.get("password")
        twostepcode = data.get("two_step_code")
        ocrflag = data.get("ocrflag")
        # 保存设置
        SystemConfig().set(key=SystemConfigKey.CookieUserInfo,
                           value={
                               "username": username,
                               "password": password,
                               "two_step_code": twostepcode
                           })
        retcode, messages = CookieManager().update_sites_cookie_ua(siteid=siteid,
                                                                username=username,
                                                                password=password,
                                                                twostepcode=twostepcode,
                                                                ocrflag=ocrflag)
        return {"code": retcode, "messages": messages}

    def __update_site_cookie_ua(self, data):
        """
        更新单个站点的Cookie和UA
        """
        siteid = data.get("site_id")
        cookie = data.get("site_cookie")
        ua = data.get("site_ua")
        SitesManager().update_site_cookie(siteid=siteid, cookie=cookie, ua=ua)
        return {"code": 0, "messages": "请求发送成功"}

    def __set_site_captcha_code(self, data):
        """
        设置站点验证码
        """
        code = data.get("code")
        value = data.get("value")
        CookieManager().set_code(code=code, value=value)
        return {"code": 0}

    def __update_torrent_remove_task(self, data):
        """
        更新自动删种任务
        """
        flag, msg = TorrentRemover().update_torrent_remove_task(data=data)
        if not flag:
            return {"code": 1, "msg": msg}
        else:
            return {"code": 0}

    def __get_torrent_remove_task(self, data=None):
        """
        获取自动删种任务
        """
        if data:
            tid = data.get("tid")
        else:
            tid = None
        return {"code": 0, "detail": TorrentRemover().get_torrent_remove_tasks(taskid=tid)}

    def __delete_torrent_remove_task(self, data):
        """
        删除自动删种任务
        """
        tid = data.get("tid")
        flag = TorrentRemover().delete_torrent_remove_task(taskid=tid)
        if flag:
            return {"code": 0}
        else:
            return {"code": 1}

    def __get_remove_torrents(self, data):
        """
        获取满足自动删种任务的种子
        """
        tid = data.get("tid")
        flag, torrents = TorrentRemover().get_remove_torrents(taskid=tid)
        if not flag or not torrents:
            return {"code": 1, "msg": "未获取到符合处理条件种子"}
        return {"code": 0, "data": torrents}

    def __auto_remove_torrents(self, data):
        """
        执行自动删种任务
        """
        tid = data.get("tid")
        TorrentRemover().auto_remove_torrents(taskids=tid)
        return {"code": 0}

    def __list_brushtask_torrents(self, data):
        """
        获取刷流任务的种子明细
        """
        results = BrushTask().get_brushtask_torrents(brush_id=data.get("id"),
                                                     active=False)
        if not results:
            return {"code": 1, "msg": "未下载种子或未获取到种子明细"}
        return {"code": 0, "data": [item.as_dict() for item in results]}

    def __set_system_config(self, data):
        """
        设置系统设置（数据库）
        """
        key = data.get("key")
        value = data.get("value")
        if not key or not value:
            return {"code": 1}
        try:
            SystemConfig().set(key=key, value=value)
            return {"code": 0}
        except Exception as e:
            log.exception("[act]设置系统设置 异常:")
            return {"code": 1}
        
    def __set_user_indexer_sites(self, data):
        """
        设置索引站点（数据库）
        """
        site_id = data.get("site_id")
        if not site_id:
            return {"code": 1, "msg": "site_id为空, 请检查索引器是否匹配站点索引模板"}
        
        try:
            indexer_sites = SystemConfig().get(SystemConfigKey.UserIndexerSites) or []
            checked = data.get("checked")
            if checked:
                if site_id in indexer_sites:
                    return {"code": 0}
                indexer_sites.append(site_id)
            else:
                if site_id not in indexer_sites:
                    return {"code": 0}
                indexer_sites.remove(site_id)
            SystemConfig().set(key=SystemConfigKey.UserIndexerSites, value=indexer_sites)
            return {"code": 0}
        except Exception as e:
            log.exception("[act]设置索引站点 异常:")
            return {"code": 1}

    def get_site_user_statistics(self, data):
        """
        获取站点用户统计信息
        """
        sites = data.get("sites")
        encoding = data.get("encoding") or "RAW"
        sort_by = data.get("sort_by")
        sort_on = data.get("sort_on")
        site_hash = data.get("site_hash")

        statistics = SitesDataStatisticsCenter().get_site_user_statistics(sites=sites, encoding=encoding)
        if sort_by and sort_on in ["asc", "desc"]:
            if sort_on == "asc":
                statistics.sort(key=lambda x: x[sort_by])
            else:
                statistics.sort(key=lambda x: x[sort_by], reverse=True)
        if site_hash == "Y":
            for item in statistics:
                item["site_hash"] = StringUtils.md5_hash(item.get("site"))

        return {"code": 0, "data": statistics}

    def send_plugin_message(self, data):
        """
        发送插件消息
        """
        title = data.get("title")
        text = data.get("text") or ""
        image = data.get("image") or ""
        Message().send_plugin_message(title=title, text=text, image=image)
        return {"code": 0}

    def send_custom_message(self, data):
        """
        发送自定义消息
        """
        title = data.get("title")
        text = data.get("text") or ""
        image = data.get("image") or ""
        message_clients = data.get("message_clients")
        if not message_clients:
            return {"code": 1, "msg": "未选择消息服务"}
        Message().send_custom_message(clients=message_clients, title=title, text=text, image=image)
        return {"code": 0}

    def media_detail(self, data):
        """
        获取媒体详情
        """
        # TMDBID 或 DB:豆瓣ID
        tmdbid = data.get("tmdbid")
        if not tmdbid:
            return {"code": 1, "msg": "未指定媒体ID"}

        mtype = MediaType.MOVIE if data.get("type") in Constants.MOVIE_TYPES else MediaType.TV
        media_info = Media().get_mediainfo_from_id(mediaid=tmdbid, mtype=mtype)
        # 检查TMDB信息
        if not media_info or not media_info.tmdb_info:
            return {
                "code": 1,
                "msg": "无法查询到TMDB信息"
            }
        
        # 查询存在及订阅状态
        fav, rssid, item_url = MediaStatusChecker().get_media_exists_info(mtype=mtype,
                                                          title=media_info.title,
                                                          year=media_info.year,
                                                          mediaid=media_info.tmdb_id)
        media_handler = Media()
        # 演职人员信息整合
        crews = self.__get_crews_from_media_info(media_info, media_handler, mtype)
        # 解析季信息
        seasons = self.__resolve_season_info(media_info, media_handler, mtype)

        return {
            "code": 0,
            "data": {
                "tmdbid": str(media_info.tmdb_id),
                "douban_id": media_info.douban_id,
                "background": media_handler.get_tmdb_backdrops(tmdbinfo=media_info.tmdb_info),
                "image": media_info.get_poster_image(),
                "vote": media_info.vote_average,
                "year": media_info.year,
                "title": media_info.title,
                "genres": media_handler.get_tmdb_genres_names(tmdbinfo=media_info.tmdb_info),
                "overview": media_info.overview,
                "runtime": StringUtils.str_timehours(media_info.runtime),
                "crews": crews,
                # "actors": actors,
                "link": media_info.get_detail_url(),
                "fav": fav,
                "item_url": item_url,
                "rssid": rssid,
                "seasons": seasons
            }
        }


    def media_brief_info(self, data):
        """
        获取媒体概要信息
        :return: 不查询演职人员、季信息
        """
        # TMDBID 或 DB:豆瓣ID
        tmdbid = data.get("tmdbid")
        if not tmdbid:
            return {"code": 1, "msg": "未指定媒体ID"}
        
        mtype = MediaType.MOVIE if data.get("type") in Constants.MOVIE_TYPES else MediaType.TV
        # 从豆瓣接口查询
        if str(tmdbid).startswith("DB:"):

            doubanId = tmdbid[3:].split(',')[0]
            douban_info = self._douBan.get_douban_info_byId(doubanId, mtype)

            if douban_info:
                # 名称解析
                title = self.__try_get_ch_title_from_douban(doubanId, douban_info)
                # 根据媒体类型赋值
                if mtype != MediaType.MOVIE:
                    overview = douban_info.get('intro')
                    genres = douban_info.get('genres')
                    year = douban_info.get('year')
                    vote = douban_info.get('rating', {}).get('value'),
                    image = douban_info.get('cover_url')
                    duration = douban_info.get('durations')
                    duration_str = duration[0] if duration else ''
                else:
                    overview = douban_info.get('summary')
                    image = douban_info.get('image')
                    vote = douban_info.get('rating', {}).get('average'),
                    # 从attrs获取
                    info_attr = douban_info.get('attrs')
                    genres = info_attr.get('movie_type')
                    year_list = info_attr.get('year')
                    year = year_list[0] if year_list else ''
                    duration = info_attr.get('movie_duration')
                    duration_str = duration[0] if duration else ''

                # 查询存在及订阅状态
                fav, rssid, item_url = MediaStatusChecker().get_media_exists_info(mtype,title,year,tmdbid)

                return {
                    "code": 0,
                    "data": {
                        "tmdbid": tmdbid,
                        "douban_id": doubanId,
                        "title": title,
                        "year": year,
                        "image": image,
                        "vote": vote,
                        "overview": overview,
                        "link": douban_info.get('alt'),
                        "genres": genres,
                        "runtime": duration_str,
                        # "background": self._douBan.get_media_photo(doubanId, mtype),
                        "fav": fav,
                        "item_url": item_url,
                        "rssid": rssid,
                    }
                }
        
        if str(tmdbid).startswith("BG:"):

            title = data.get("title")
            if not title:
                return { "code": 1, "msg": "无法查询到BANGUMI信息" }

            year = data.get("year", '')           
            media_info = Media().get_media_info(title=f"{title} {year}",
                                                mtype=MediaType.ANIME,
                                                append_to_response="all")
            
            if not media_info or not media_info.tmdb_info:
                return { "code": 1, "msg": "无法查询到Bangumi资源的TMDB信息" }
            
        else:
            info = Media().get_tmdb_info(tmdbid=tmdbid, mtype=mtype, append_to_response="all")
            if not info:
                return { "code": 1, "msg": "无法查询到TMDB信息" }
            
            title = MediaUtils.get_tmdb_title(info)
            media_info = MetaInfo(title)
            media_info.set_tmdb_info(info)
               
        # 查询存在及订阅状态
        fav, rssid, item_url = MediaStatusChecker().get_media_exists_info(mtype=mtype,
                                                          title=media_info.title,
                                                          year=media_info.year,
                                                          mediaid=media_info.tmdb_id)
        MediaHandler = Media()
        return {
            "code": 0,
            "data": {
                "tmdbid": str(media_info.tmdb_id),
                "vote": media_info.vote_average,
                "year": media_info.year,
                "title": media_info.title,
                "overview": media_info.overview,
                "background": MediaHandler.get_tmdb_backdrops(tmdbinfo=media_info.tmdb_info),
                "genres": MediaHandler.get_tmdb_genres_names(tmdbinfo=media_info.tmdb_info),
                "runtime": StringUtils.str_timehours(media_info.runtime),
                "image": media_info.get_poster_image(),
                "link": media_info.get_detail_url(),
                "fav": fav,
                "item_url": item_url,
                "rssid": rssid,
            }
        }


    def media_extra_info(self, data):
        """
        获取媒体概要信息
        :return: 查询演职人员、季信息
        """
        # TMDBID 或 DB:豆瓣ID
        mediaid = data.get("mediaid")
        if not mediaid:
            return {"code": 1, "msg": "未指定媒体ID"}
        
        mtype = MediaType.MOVIE if data.get("type") in Constants.MOVIE_TYPES else MediaType.TV
        media_info = Media().get_mediainfo_from_id(mediaid=mediaid, mtype=mtype)

        if not media_info: 
            return {"code": 1, "msg": "媒体信息查询失败"}

        media_handler = Media()
        # 演职人员信息整合
        crews = self.__get_crews_from_media_info(media_info, media_handler, mtype)
        # 解析季信息
        seasons = self.__resolve_season_info(media_info, media_handler, mtype)
                
        return {
            "code": 0,
            "data": {
                "tmdbid": str(media_info.tmdb_id),
                "douban_id": media_info.douban_id,
                "background": media_handler.get_tmdb_backdrops(tmdbinfo=media_info.tmdb_info),
                "crews": crews,
                "seasons": seasons
            }
        }


    def __get_crews_from_media_info(self, media_info:MetaInfo, media_handler:Media, mtype:MediaType):
        """
        从媒体信息获取演职人员集合
        :return: 演职人员集合
        """
        crews = []
        actors = []
        if media_info.douban_id:
            crews, actors = self._douBan.get_media_celebrities(media_info.douban_id.split(',')[0])
        else:
            if media_info.tmdb_info:
                crews = media_info.tmdb_info.get("credits", {}).get("crew") or []
                if crews:
                    crews = crews[:6]
                actors = media_handler.get_tmdb_cats(mtype=mtype, tmdbid=media_info.tmdb_id)

        # 合并到一个集合
        crews.extend(actors)
        return crews
    
    def __resolve_season_info(self, media_info:MetaInfo, media_handler:Media, mtype:MediaType):

        if mtype == MediaType.MOVIE:
            return []

        # 解析季信息
        seasons = media_handler.get_tmdb_tv_seasons(media_info.tmdb_info)
        if not seasons:
            return []
        
        # 检查季是否入库
        media_server = MediaServer()

        for season in seasons:
            season.update({
                "state": True if media_server.check_item_exists(
                    mtype=mtype,
                    title=media_info.title,
                    year=media_info.year,
                    tmdbid=media_info.tmdb_id,
                    season=season.get("season_number")) else False
            })
        return seasons

    def __try_get_ch_title_from_douban(self, douban_id, douban_info):
        """
        尝试从豆瓣接口返回中获取中文名称
        :return: 名称
        """
        title = douban_info.get('title')
        if StringUtils.is_all_chinese_and_mark(title):
            return title
        
        if douban_info.get('alt_title'):
            alt_title = douban_info.get('alt_title').split('/')
            if len(alt_title) == 1:
                title = alt_title[0]
                if StringUtils.is_all_chinese_and_mark(title):
                    return title
            else:
                cn_title = next(filter(lambda t: StringUtils.is_all_chinese_and_mark(t), alt_title), None)
                if cn_title:
                    return cn_title.strip()
        
        douban_info = self._douBan.get_douban_detail(douban_id)
        return douban_info.get("title")

    def __media_similar(self, data):
        """
        查询TMDB相似媒体
        """
        tmdbid = data.get("tmdbid")
        page = data.get("page") or 1
        mtype = MediaType.MOVIE if data.get("type") in Constants.MOVIE_TYPES else MediaType.TV
        if not tmdbid:
            return {"code": 1, "msg": "未指定TMDBID"}
        if mtype == MediaType.MOVIE:
            result = Media().get_movie_similar(tmdbid=tmdbid, page=page)
        else:
            result = Media().get_tv_similar(tmdbid=tmdbid, page=page)
        return {"code": 0, "data": result}

    def __media_recommendations(self, data):
        """
        查询TMDB同类推荐媒体
        """
        tmdbid = data.get("tmdbid")
        page = data.get("page") or 1
        mtype = MediaType.MOVIE if data.get(
            "type") in Constants.MOVIE_TYPES else MediaType.TV
        if not tmdbid:
            return {"code": 1, "msg": "未指定TMDBID"}
        if mtype == MediaType.MOVIE:
            result = Media().get_movie_recommendations(tmdbid=tmdbid, page=page)
        else:
            result = Media().get_tv_recommendations(tmdbid=tmdbid, page=page)
        return {"code": 0, "data": result}

    def __media_person(self, data):
        """
        根据TMDBID或关键字查询TMDB演员
        """
        tmdbid = data.get("tmdbid")
        keyword = data.get("keyword")
        if not tmdbid and not keyword:
            return {"code": 1, "msg": "未指定TMDBID或关键字"}
        if tmdbid:
            mtype = MediaType.MOVIE if data.get("type") in Constants.MOVIE_TYPES else MediaType.TV
            result = Media().get_tmdb_cats(tmdbid=tmdbid, mtype=mtype)
        else:
            result = Media().search_tmdb_person(name=keyword)
        return {"code": 0, "data": result}

    def __person_medias(self, data):
        """
        查询演员参演作品
        """
        personid = data.get("personid")
        page = data.get("page") or 1
        if data.get("type"):
            mtype = MediaType.MOVIE if data.get("type") in Constants.MOVIE_TYPES else MediaType.TV
        else:
            mtype = None
        if not personid:
            return {"code": 1, "msg": "未指定演员ID"}
        return {"code": 0, "data": Media().get_person_medias(personid=personid,
                                                             mtype=mtype,
                                                             page=page)}

    def __run_directory_sync(self, data):
        """
        执行单个目录的目录同步
        """
        ThreadHelper().start_thread(Sync().transfer_sync, (data.get("sid"),))
        return {"code": 0, "msg": "执行成功"}

    def __update_plugin_config(self, data):
        """
        保存插件配置
        """
        plugin_id = data.get("plugin")
        config = data.get("config")
        if not plugin_id:
            return {"code": 1, "msg": "数据错误"}
        PluginManager().save_plugin_config(pid=plugin_id, conf=config)
        PluginManager().reload_plugin(plugin_id)
        return {"code": 0, "msg": "保存成功"}

    def __get_season_episodes(self, data=None):
        """
        查询TMDB剧集情况
        """
        tmdbid = data.get("tmdbid")
        title = data.get("title")
        year = data.get("year")
        season = 1 if data.get("season") is None else data.get("season")
        if not tmdbid:
            return {"code": 1, "msg": "TMDBID为空"}
        episodes = Media().get_tmdb_season_episodes(tmdbid=tmdbid,
                                                    season=season)
        MediaServerHandler = MediaServer()
        for episode in episodes:
            episode.update({
                "state": True if MediaServerHandler.check_item_exists(
                    mtype=MediaType.TV,
                    title=title,
                    year=year,
                    tmdbid=tmdbid,
                    season=season,
                    episode=episode.get("episode_number")) else False
            })
        return {
            "code": 0,
            "episodes": episodes
        }

    def __update_downloader(self, data):
        """
        更新下载器
        """
        did = data.get("did")
        name = data.get("name")
        dtype = data.get("type")
        enabled = data.get("enabled")
        transfer = data.get("transfer")
        only_nastool = data.get("only_nastool")
        match_path = data.get("match_path")
        rmt_mode = data.get("rmt_mode")
        config = data.get("config")
        if not isinstance(config, str):
            config = json.dumps(config)
        download_dir = data.get("download_dir")
        if not isinstance(download_dir, str):
            download_dir = json.dumps(download_dir)
        Downloader().update_downloader(did=did,
                                       name=name,
                                       dtype=dtype,
                                       enabled=enabled,
                                       transfer=transfer,
                                       only_nastool=only_nastool,
                                       match_path=match_path,
                                       rmt_mode=rmt_mode,
                                       config=config,
                                       download_dir=download_dir)
        return {"code": 0}

    def __del_downloader(self, data):
        """
        删除下载器
        """
        did = data.get("did")
        Downloader().delete_downloader(did=did)
        return {"code": 0}

    def __check_downloader(self, data):
        """
        检查下载器
        """
        did = data.get("did")
        if not did:
            return {"code": 1}
        checked = data.get("checked")
        flag = data.get("flag")
        enabled, transfer, only_nastool, match_path = None, None, None, None
        if flag == "enabled":
            enabled = 1 if checked else 0
        elif flag == "transfer":
            transfer = 1 if checked else 0
        elif flag == "only_nastool":
            only_nastool = 1 if checked else 0
        elif flag == "match_path":
            match_path = 1 if checked else 0
        Downloader().check_downloader(did=did,
                                      enabled=enabled,
                                      transfer=transfer,
                                      only_nastool=only_nastool,
                                      match_path=match_path)
        return {"code": 0}

    def __get_downloaders(self, data):
        """
        获取下载器
        """
        did = data.get("did")
        return {"code": 0, "detail": Downloader().get_downloader_conf(did=did)}

    def __test_downloader(self, data):
        """
        测试下载器
        """
        dtype = data.get("type")
        config = json.loads(data.get("config"))
        res = Downloader().get_status(dtype=dtype, config=config)
        if res:
            return {"code": 0}
        else:
            return {"code": 1}

    def __get_indexer(self, data):
        """
        查询索引站点数据
        """
        url = data.get('url')
        if not url:
            return {"code": 1, "msg": "站点url为空"}

        site = IndexerManager().build_indexer_conf(url=url)
        if not site:
            return {"code": 1, "msg": "索引站点查询失败"}

        return {
            "code": 0,
            "data": {
                "id": site.id,
                "name": site.name,
                "domain": site.domain,
                "search": json.dumps(site.search),
                "torrents": json.dumps(site.torrents),
                "parser": site.parser,
                "render": site.render,
                "browse": json.dumps(site.browse) if site.browse else '',
                "category": json.dumps(site.category) if site.category else '',
                "source_type": site.source_type,
                "search_type": site.search_type,
                "public": site.public,
                "proxy": site.proxy,
                "en_expand": site.en_expand
            }
        }

    def __add_indexer(self, data):
        IndexerManager().add_indexer(data)
        return {"code": 0, "msg": "已插入"}

    def __update_indexer(self, data):
        success = IndexerManager().update_indexer(data)
        if success:
            return {"code": 0, "msg": "更新成功"}
        return {"code": 1, "msg": "更新失败，请检查"}

    def __delete_indexer(self, data):
        indexer_id = data.get('id')
        if indexer_id is None:
             return {"code": 1, "msg": "索引id为空"}
        
        IndexerManager().delete_indexer(indexer_id)
        return {"code": 0, "msg": "更新成功"}

    def refresh_pt_statistics(self, data):
        """
        刷新站点数据
        """
        if not self._current_user:
            return {"code": 1, "msg": "未登录"}
        
         # 刷新站点数据
        if data.get('site'):
            SitesDataStatisticsCenter().refresh_site_data_now(specify_sites=data.get('site'))
        else:
            CommandHandler().handle_message_job("/sta", 
                                                in_from=SearchType.WEB, 
                                                user_id=self._current_user.id, 
                                                user_name=self._current_user.username)

        return {"code": 0, "msg": "已提交"}

    def get_default_rss_setting(self, data):
        """
        获取默认订阅设置
        """
        match data.get("mtype"):
            case "TV":
                default_rss_setting = Subscribe().default_rss_setting_tv
            case "MOV":
                default_rss_setting = Subscribe().default_rss_setting_mov
            case _:
                default_rss_setting = {}
        if default_rss_setting:
            return {"code": 0, "data": default_rss_setting}
        return {"code": 1}

    def install_plugin(self, data, reload=True):
        """
        安装插件
        """
        module_id = data.get("id")
        if not module_id:
            return {"code": -1, "msg": "参数错误"}
        # 用户已安装插件列表
        user_plugins = SystemConfig().get(SystemConfigKey.UserInstalledPlugins) or []
        if module_id not in user_plugins:
            user_plugins.append(module_id)
        # 保存配置
        SystemConfig().set(SystemConfigKey.UserInstalledPlugins, user_plugins)
        # 重新加载插件
        if reload:
            PluginManager().init_config()
        return {"code": 0, "msg": "插件安装成功"}

    def uninstall_plugin(self, data):
        """
        卸载插件
        """
        module_id = data.get("id")
        if not module_id:
            return {"code": -1, "msg": "参数错误"}
        # 用户已安装插件列表
        user_plugins = SystemConfig().get(SystemConfigKey.UserInstalledPlugins) or []
        if module_id in user_plugins:
            user_plugins.remove(module_id)
        # 保存配置
        SystemConfig().set(SystemConfigKey.UserInstalledPlugins, user_plugins)
        # 重新加载插件
        PluginManager().init_config()
        return {"code": 0, "msg": "插件卸载功"}

    def get_plugin_apps(self, data=None):
        """
        获取插件列表
        """
        # 使用默认admin用户级别
        user_level = 0

        # 如果传入了用户信息，则使用传入的用户级别
        if data and isinstance(data, dict) and "user" in data and hasattr(data["user"], "level"):
            user_level = data["user"].level
        # 如果获取不到，使用admin用户级别
        else:
            admin_user = UserManager().get_user_by_name("admin")
            if admin_user:
                user_level = admin_user.level

        plugins = PluginManager().get_plugin_apps(user_level)
        return {"code": 0, "result": plugins}

    def get_plugin_page(self, data):
        """
        查询插件的额外数据
        """
        plugin_id = data.get("id")
        if not plugin_id:
            return {"code": 1, "msg": "参数错误"}
        title, content, func = PluginManager().get_plugin_page(pid=plugin_id)
        return {"code": 0, "title": title, "content": content, "func": func}

    def get_plugins_conf(self, data=None):
        # 使用默认admin用户级别
        user_level = 0

        # 如果传入了用户信息，则使用传入的用户级别
        if data and isinstance(data, dict) and "user" in data and hasattr(data["user"], "level"):
            user_level = data["user"].level
        # 如果获取不到，使用admin用户级别
        else:
            admin_user = UserManager().get_user_by_name("admin")
            if admin_user:
                user_level = admin_user.level

        # 获取插件配置
        Plugins = PluginManager().get_plugins_conf(user_level)
        return {"code": 0, "result": Plugins}

    def update_category_config(self, data):
        """
        保存二级分类配置
        """
        text = data.get("config") or ''
        # 保存配置
        category_path = Config().category_path
        if category_path:
            with open(category_path, "w", encoding="utf-8") as f:
                f.write(text)
        return {"code": 0, "msg": "保存成功"}

    def get_category_config(self, data):
        """
        获取二级分类配置
        """
        category_name = data.get("category_name")
        if not category_name:
            return {"code": 1, "msg": "请输入二级分类策略名称"}
        if category_name == "config":
            return {"code": 1, "msg": "非法二级分类策略名称"}
        category_path = os.path.join(Config().get_config_path(), f"{category_name}.yaml")
        if not os.path.exists(category_path):
            return {"code": 1, "msg": "请保存生成配置文件"}
        # 读取category配置文件数据
        with open(category_path, "r", encoding="utf-8") as f:
            category_text = f.read()
        return {"code": 0, "text": category_text}

    def get_system_processes(self):
        """
        获取系统进程
        """
        return {"code": 0, "data": SystemUtils.get_all_processes()}

    def run_plugin_method(self, data):
        """
        运行插件方法
        """
        plugin_id = data.get("plugin_id")
        method = data.get("method")
        if not plugin_id or not method:
            return {"code": 1, "msg": "参数错误"}
        data.pop("plugin_id")
        data.pop("method")
        result = PluginManager().run_plugin_method(pid=plugin_id, method=method, **data)
        return {"code": 0, "result": result}

    def get_jobs(self):
        """
        获取所有已注册的定时任务
        """
        result = JobCenter().get_jobs()
        return {"code": 0, "result": result }