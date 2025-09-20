from functools import wraps
import os

from fastapi import APIRouter, Request, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

import log

from app.brushtask import BrushTask
from app.conf.moduleconf import ModuleConf
from app.conf.systemconfig import SystemConfig
from app.downloader.downloader import Downloader
from app.filter import Filter
from app.helper.meta_helper import MetaHelper
from app.indexer.indexer import Indexer
from app.mediaserver.media_server import MediaServer
from app.message import Message
from app.plugins.plugin_manager import PluginManager
from app.rsschecker import RssChecker
from app.sites.site_manager import SitesManager
from app.sync import Sync
from app.torrentremover import TorrentRemover
from app.utils.system_utils import SystemUtils
from app.utils.types import *

from config import PT_TRANSFER_INTERVAL, TMDB_API_DOMAINS, Config

from web.action import WebAction
from web.backend.security import get_current_user
from web.backend.user import User
from web.backend.wallpaper import get_login_wallpaper
from web.backend.web_utils import WebUtils


# API路由
data_router = APIRouter(prefix="/data")


# 异常捕获器
def router_exception_handler(router: APIRouter):
    """
    给整个 APIRouter 加统一异常捕获
    """
    for route in router.routes:
        original_endpoint = route.endpoint

        # 每条路由生成独立包装函数
        def make_wrapped(endpoint):
            @wraps(endpoint)
            async def wrapped(*args, **kwargs):
                try:
                    return await endpoint(*args, **kwargs)
                except Exception as e:
                    return JSONResponse(
                        status_code=500,
                        content=str(e)
                    )
            return wrapped

        route.endpoint = make_wrapped(original_endpoint)


# 统一的返回函数
def response(code: int = 0, msg: str = "success", data=None, status_code: int = 200):
    return JSONResponse(
        content=jsonable_encoder({
            "code": code,
            "msg": msg,
            "data": data
        }),
        status_code=status_code
    )


# bing
@data_router.post("/bing")
async def bing(request: Request):

    image_code, img_title, img_link = get_login_wallpaper()

    return response(data=
        {
            "image_code" : image_code,
            "img_title" : img_title,
            "img_link" : img_link
        }
    )


# sysinfo
@data_router.post("/sysinfo")
async def sysinfo(request: Request, current_user: User = Depends(get_current_user)):

    # 判断当前的运营环境
    system_flag = SystemUtils.get_system()
    tmdb_flag = 1 if Config().get_config('app').get('rmt_tmdbkey') else 0
    default_path = Config().get_config('media').get('media_default_path')
    sync_mod = Config().get_config('media').get('default_rmt_mode')
    if not sync_mod:
        sync_mod = "link"

    webAction = WebAction(current_user)

    commands = webAction.get_commands()
    username = current_user.username

    restype_dict = ModuleConf.TORRENT_SEARCH_PARAMS.get("restype")
    pix_dict = ModuleConf.TORRENT_SEARCH_PARAMS.get("pix")

    rmt_mode_dict = webAction.get_rmt_modes()

    return response(data=
        {
            "username" : username,
            "admin" : 1 if username == 'admin' else 0,
            "search" : current_user.search,
            "SystemFlag": system_flag.value,
            "TMDBFlag": tmdb_flag,
            "AppVersion": WebUtils.get_current_version(),
            "SyncMod": sync_mod,
            "DefaultPath": default_path,
            "Commands": commands,
            "restype_dict": restype_dict,
            "pix_dict": pix_dict,
            "rmt_mode_dict": rmt_mode_dict,
        }
    )


# 基础设置页面
@data_router.post("/basic")
async def basic(request: Request, current_user: User = Depends(get_current_user)):
    proxy = Config().get_config('app').get("proxies", {}).get("http")
    if proxy:
        proxy = proxy.replace("http://", "")
        
    RmtModeDict = WebAction(current_user).get_rmt_modes()
    CustomScriptCfg = SystemConfig().get(SystemConfigKey.CustomScript)
    ScraperConf = SystemConfig().get(SystemConfigKey.UserScraperConf) or {}
    return response(data=
        {
            "Config": Config().get_config(),
            "Proxy": proxy,
            "RmtModeDict": RmtModeDict,
            "CustomScriptCfg": CustomScriptCfg,
            "ScraperNfo": ScraperConf.get("scraper_nfo") or {},
            "ScraperPic": ScraperConf.get("scraper_pic") or {},
            "MediaServerConf": ModuleConf.MEDIASERVER_CONF,
            "TmdbDomains": TMDB_API_DOMAINS,
        }
    )


# 开始页面
@data_router.post("/index")
async def index(request: Request, current_user: User = Depends(get_current_user)):

    webAction = WebAction(current_user)

    # 媒体服务器类型
    MSType = Config().get_config('media').get('media_server')
    # 获取媒体数量
    MediaCounts = webAction.get_library_mediacount()
    if MediaCounts.get("code") == 0:
        ServerSucess = True
    else:
        ServerSucess = False

    # 获得活动日志
    Activity = webAction.get_library_playhistory().get("result")

    # 磁盘空间
    LibrarySpaces = webAction.get_library_spacesize()

    # 媒体库
    Librarys = MediaServer().get_libraries()
    LibrarySyncConf = SystemConfig().get(SystemConfigKey.SyncLibrary) or []

    # 继续观看
    Resumes = MediaServer().get_resume()

    # 最近添加
    Latests = MediaServer().get_latest()

    return response(data=
        {
             "ServerSucess": ServerSucess,
             "MediaCount": {'MovieCount': MediaCounts.get("Movie"),
                     'SeriesCount': MediaCounts.get("Series"),
                     'SongCount': MediaCounts.get("Music"),
                     "EpisodeCount": MediaCounts.get("Episodes")
                     },
             "Activitys": Activity,
             "UserCount": MediaCounts.get("User"),
             "FreeSpace": LibrarySpaces.get("FreeSpace"),
             "TotalSpace": LibrarySpaces.get("TotalSpace"),
             "UsedSapce": LibrarySpaces.get("UsedSapce"),
             "UsedPercent": LibrarySpaces.get("UsedPercent"),
             "MediaServerType": MSType,
             "Librarys": Librarys,
             "LibrarySyncConf": LibrarySyncConf,
             "Resumes": Resumes,
             "Latests": Latests,
        }
    )


# 资源搜索页面
@data_router.post("/search")
async def search(request: Request, current_user: User = Depends(get_current_user)):

    # 结果
    res = WebAction(current_user).get_search_result()
    SearchResults = res.get("result")
    Count = res.get("total")

    return response(data=
        {
            "Count": Count,
            "Results": SearchResults,
            "SiteDict": Indexer().get_indexer_hash_dict()
        })


# 订阅页面
@data_router.post("/rss")
async def rss(request: Request, current_user: User = Depends(get_current_user), t: str = "MOV"):

    webAction = WebAction(current_user)

    RuleGroups = {str(group["id"]): group["name"] for group in Filter().get_rule_groups()}
    DownloadSettings = Downloader().get_download_setting()

    RssItems = []
    Type = 'MOV'
    TypeName = '电影'
    if t == 'TV':
        RssItems = webAction.get_tv_rss_list().get("result")
        Type = 'TV'
        TypeName = '电视剧'
    else:
        RssItems = webAction.get_movie_rss_list().get("result")

    return response(data=
        {
            "Count": len(RssItems),
            "RuleGroups": RuleGroups,
            "DownloadSettings": dict(DownloadSettings) if DownloadSettings else {},
            "Items": RssItems,
            "Type": Type,
            "TypeName": TypeName,
        })


# 订阅历史页面
@data_router.post("/rss_history")
async def rss_history(request: Request, current_user: User = Depends(get_current_user), t: str = ""):

    RssHistory = WebAction(current_user).get_rss_history({"type": t}).get("result")

    return response(data=
        {
            "Count": len(RssHistory),
            "Items": RssHistory,
            "Type": t,
        })


# 订阅日历页面
@data_router.post("/rss_calendar")
async def rss_calendar(request: Request, current_user: User = Depends(get_current_user)):

    webAction = WebAction(current_user)
    # 电影订阅
    RssMovieItems = webAction.get_movie_rss_items().get("result")
    # 电视剧订阅
    RssTvItems = webAction.get_tv_rss_items().get("result")

    return response(data=
        {
            "RssMovieItems": RssMovieItems,
            "RssTvItems": RssTvItems,
        })


# 索引站点页面
@data_router.post("/indexer")
async def indexer(request: Request, current_user: User = Depends(get_current_user), p: int = 1):

    indexers = Indexer().get_indexers(check=False)
    indexer_sites = SystemConfig().get(SystemConfigKey.UserIndexerSites)
    if not indexer_sites:
        indexer_sites = []

    DownloadSettings = {did: attr["name"] for did, attr in Downloader().get_download_setting().items()}
    SourceTypes = { "MOVIE":'电影', "TV":'剧集', "ANIME":'动漫' }
    SearchTypes = { "title":'关键字', "en_name":'英文名', "douban_id":'豆瓣id', "imdb":'imdb id' }

    front_indexers = []
    check_sites = []

    is_public = p == 1

    for idx_site in indexers:
        checked = idx_site.id in indexer_sites
        if checked:
            check_sites.append(idx_site.id)

        if idx_site.public != is_public:
            continue
        site_info = {
            "id": idx_site.id,
            "name": idx_site.name,
            "domain": idx_site.domain,
            "render": idx_site.render,
            "source_type": idx_site.source_type,
            "search_type": SearchTypes.get(idx_site.search_type, '关键字'),
            "downloader": idx_site.downloader,
            "public": idx_site.public,
            "proxy": idx_site.proxy,
            "en_expand": idx_site.en_expand,
            "checked": checked
        }
        front_indexers.append(site_info)

    return response(data=
        {
            "Config": Config().get_config(),
            "IsPublic": p,
            "Indexers": front_indexers,
            "DownloadSettings": DownloadSettings,
            "CheckSites": check_sites,
            "SourceTypes": SourceTypes,
        })


# 站点维护页面
@data_router.post("/site")
async def sites_page(request: Request, current_user = Depends(get_current_user)):
    cfg_sites = SitesManager().get_sites()
    rule_groups = {str(group["id"]): group["name"] for group in Filter().get_rule_groups()}
    download_settings = {did: attr["name"] for did, attr in Downloader().get_download_setting().items()}
    cookie_cloud_cfg = SystemConfig().get(SystemConfigKey.CookieCloud)
    cookie_user_info_cfg = SystemConfig().get(SystemConfigKey.CookieUserInfo)

    return response(data=
        {
            "Sites": cfg_sites,
            "RuleGroups": rule_groups,
            "DownloadSettings": download_settings,
            "ChromeOk": True,
            "CookieCloudCfg": cookie_cloud_cfg,
            "CookieUserInfoCfg": cookie_user_info_cfg,
        }
    )


# 站点资源页面
@data_router.post("/sitelist")
async def sitelist_page(request: Request, current_user = Depends(get_current_user)):
    indexer_sites = Indexer().get_indexers(check=False)
    return response(data=
        {
            "Sites": indexer_sites,
            "Count": len(indexer_sites),
        }
    )


# 媒体库页面
@data_router.post("/library")
async def library(request: Request, current_user = Depends(get_current_user)):
    return response(data=
        {
            "Config": Config().get_config(),
            "MediaServerConf": ModuleConf.MEDIASERVER_CONF,
        })


# 通知消息页面
@data_router.post("/notification")
async def notification(request: Request, current_user = Depends(get_current_user)):
    MessageClients = Message().get_message_client_info()
    Switchs = ModuleConf.MESSAGE_CONF.get("switch")

    Channels = ModuleConf.MESSAGE_CONF.get("client")
    ChannelsTpyes = []
    # 遍历修改
    for key, conf in Channels.items():
        if "search_type" in conf:
            conf["search_type"] = str(conf["search_type"])
        ChannelsTpyes.append(key)

    return response(data=
        {
            "Channels": Channels,
            "Switchs": Switchs,
            "ChannelsTpyes": ChannelsTpyes,
            "ClientCount": len(MessageClients) if MessageClients else 0,
            "MessageClients": dict(MessageClients) if MessageClients else {},
        })


# 用户管理页面
@data_router.post("/users")
async def users(request: Request, current_user = Depends(get_current_user)):
    Users = WebAction(current_user).get_users().get("result")
    TopMenus = WebAction(current_user).get_top_menus().get("menus")

    return response(data=
        {
            "Users": Users,
            "UserCount": len(Users),
            "TopMenus": TopMenus,
        })


# 过滤规则设置页面
@data_router.post("/filterrule")
async def filterrule(request: Request, current_user = Depends(get_current_user)):

    ruleGroups = Filter().get_rule_infos()
    initRuleGroups = WebAction(current_user).get_init_filterrules()

    return response(data=
        {
            "RuleGroups": ruleGroups,
            "InitRuleGroups": initRuleGroups,
        })


# 目录同步页面
@data_router.post("/directorysync")
async def directorysync(request: Request, current_user = Depends(get_current_user)):
    RmtModeDict = WebAction(current_user).get_rmt_modes()
    SyncPaths = Sync().get_sync_path_conf()
    return response(data=
        {
            "SyncPaths": SyncPaths,
            "SyncCount": len(SyncPaths),
            "RmtModeDict": RmtModeDict,
        })


# 自定义识别词设置页面
@data_router.post("/customwords")
async def customwords(request: Request, current_user = Depends(get_current_user)):
    groups = WebAction(current_user).get_customwords().get("result")
    return response(data=
        {
            "Groups": groups,
            "GroupsCount": len(groups),
        })


# 插件页面
@data_router.post("/plugin")
async def plugin(request: Request, current_user = Depends(get_current_user)):

    webAction = WebAction(current_user)

    # 下载器
    DefaultDownloader = Downloader().default_downloader_id
    Downloaders = Downloader().get_downloader_conf()
    Categories = {
        x: webAction.get_categories({
            "type": x
        }).get("category") for x in ["电影", "电视剧", "动漫"]
    }
    RmtModeDict = webAction.get_rmt_modes()
    # 插件
    Plugins = PluginManager().get_plugins_conf(current_user.level)

    Settings = '\n'.join(SystemConfig().get(SystemConfigKey.ExternalPluginsSource) or [])
    return response(data=
        {
            "Downloaders": Downloaders,
            "DefaultDownloader": DefaultDownloader,
            "Categories": Categories,
            "RmtModeDict": RmtModeDict,
            "DownloaderConf": ModuleConf.DOWNLOADER_CONF,
            "Plugins": Plugins,
            "Settings": Settings
        })


# 用户RSS页面
@data_router.post("/user_rss")
async def user_rss(request: Request, current_user: User = Depends(get_current_user)):
    """
    用户RSS页面
    """
    Tasks = RssChecker().get_rsstask_info()
    RssParsers = RssChecker().get_userrss_parser()
    RuleGroups = {str(group["id"]): group["name"] for group in Filter().get_rule_groups()}
    DownloadSettings = {did: attr["name"] for did, attr in Downloader().get_download_setting().items()}
    RestypeDict = ModuleConf.TORRENT_SEARCH_PARAMS.get("restype")
    PixDict = ModuleConf.TORRENT_SEARCH_PARAMS.get("pix")

    return response(data=
        {
            "Tasks": Tasks,
            "Count": len(Tasks),
            "RssParsers": RssParsers,
            "RuleGroups": RuleGroups,
            "RestypeDict": RestypeDict,
            "PixDict": PixDict,
            "DownloadSettings": DownloadSettings,
        }
    )


# 服务页面
@data_router.post("/service")
async def service(request: Request, current_user: User = Depends(get_current_user)):
    """
    服务页面
    """
    # 所有规则组
    RuleGroups = Filter().get_rule_groups()
    # 所有同步目录
    SyncPaths = Sync().get_sync_path_conf()

    # 获取用户服务（get_current_user_required已经保证current_user不为空）
    Services = current_user.get_services()
    pt = Config().get_config('pt')
    # RSS订阅
    if "rssdownload" in Services:
        pt_check_interval = pt.get('pt_check_interval')
        if str(pt_check_interval).isdigit():
            tim_rssdownload = str(round(int(pt_check_interval) / 60)) + " 分钟"
            rss_state = 'ON'
        else:
            tim_rssdownload = ""
            rss_state = 'OFF'
        Services['rssdownload'].update({
            'time': tim_rssdownload,
            'state': rss_state,
        })

    # RSS搜索
    if "subscribe_search_all" in Services:
        search_rss_interval = pt.get('search_rss_interval')
        if str(search_rss_interval).isdigit():
            if int(search_rss_interval) < 3:
                search_rss_interval = 3
            tim_rsssearch = str(int(search_rss_interval)) + " 小时"
            rss_search_state = 'ON'
        else:
            tim_rsssearch = ""
            rss_search_state = 'OFF'
        Services['subscribe_search_all'].update({
            'time': tim_rsssearch,
            'state': rss_search_state,
        })

    # 下载文件转移
    if "pttransfer" in Services:
        pt_monitor = Downloader().monitor_downloader_ids
        if pt_monitor:
            tim_pttransfer = str(round(PT_TRANSFER_INTERVAL / 60)) + " 分钟"
            sta_pttransfer = 'ON'
        else:
            tim_pttransfer = ""
            sta_pttransfer = 'OFF'
        Services['pttransfer'].update({
            'time': tim_pttransfer,
            'state': sta_pttransfer,
        })

    # 目录同步
    if "sync" in Services:
        if Sync().monitor_sync_path_ids:
            Services['sync'].update({'state': 'ON'})

    # 系统进程
    if "processes" in Services:
        if not SystemUtils.is_docker() or not SystemUtils.get_all_processes():
            Services.pop('processes')

    return response(data=
        {
            "Count": len(Services),
            "RuleGroups": RuleGroups,
            "SyncPaths": SyncPaths,
            "SchedulerTasks": Services,
        }
    )


# 正在下载页面
@data_router.post("/downloading")
async def downloading(request: Request, current_user: User = Depends(get_current_user)):
    """
    正在下载页面
    """
    downloader_proxy = Downloader()
    Downloaders = []
    for key, value in downloader_proxy.get_downloader_conf().items():
        if value.get('enabled'):
            Downloaders.append(value)

    return response(data=
        {
            "Downloaders": Downloaders
        }
    )


# 媒体文件管理页面
@data_router.post("/mediafile")
async def mediafile(request: Request, current_user: User = Depends(get_current_user)):
    """
    媒体文件管理页面
    """
    media_default_path = Config().get_config('media').get('media_default_path')
    if media_default_path:
        rootDir = media_default_path
    else:
        download_dirs = Downloader().get_download_visit_dirs()
        if download_dirs:
            try:
                rootDir = os.path.commonpath(download_dirs).replace("\\", "/")
            except Exception as err:
                log.exception(f'管理目录转换异常: {download_dirs}', err)
                rootDir = "/"
        else:
            rootDir = "/"
    
    form = await request.form()

    return response(data=
        {
            "Dir": rootDir,
        }
    )


# 数据统计页面
@data_router.post("/statistics")
async def statistics(request: Request, current_user: User = Depends(get_current_user)):
    """
    数据统计页面
    """
    # 总上传下载
    TotalUpload = 0
    TotalDownload = 0
    TotalSeedingSize = 0
    TotalSeeding = 0
    # 站点标签及上传下载
    SiteNames = []
    SiteUploads = []
    SiteDownloads = []
    SiteRatios = []
    SiteErrs = {}

    # 站点用户数据
    SiteUserStatistics = WebAction(current_user).get_site_user_statistics({"encoding": "DICT"}).get("data")
    
    # 站点上传下载总量
    for site_item in SiteUserStatistics:

        name = site_item.get('site')
        if not name:
            continue

        up = site_item.get("upload", 0)
        dl = site_item.get("download", 0)
        ratio = site_item.get("ratio", 0)
        seeding = site_item.get("seeding", 0)
        seeding_size = site_item.get("seeding_size", 0)

        if not up and not dl and not ratio:
            continue
        if not str(up).isdigit() or not str(dl).isdigit():
            continue
        if name not in SiteNames:
            SiteNames.append(name)
            TotalUpload += int(up)
            TotalDownload += int(dl)
            TotalSeeding += int(seeding)
            TotalSeedingSize += int(seeding_size)
            SiteUploads.append(int(up))
            SiteDownloads.append(int(dl))
            SiteRatios.append(round(float(ratio), 1))

    return response(data=
        {
            "TotalDownload": TotalDownload,
            "TotalUpload": TotalUpload,
            "TotalSeedingSize": TotalSeedingSize,
            "TotalSeeding": TotalSeeding,
            "SiteDownloads": SiteDownloads,
            "SiteUploads": SiteUploads,
            "SiteRatios": SiteRatios,
            "SiteNames": SiteNames,
            "SiteErr": SiteErrs,
            "SiteUserStatistics": SiteUserStatistics,
        }
    )


# 刷流任务页面
@data_router.post("/brushtask")
async def brushtask(request: Request, current_user: User = Depends(get_current_user)):
    """
    刷流任务页面
    """
    # 站点列表
    CfgSites = SitesManager().get_sites(brush=True)
    # 下载器列表
    Downloaders = Downloader().get_downloader_conf_simple()
    # 任务列表
    Tasks = BrushTask().get_brushtask_info()

    return response(data=
        {
            "Count": len(Tasks),
            "Sites": CfgSites,
            "Tasks": list(Tasks) if Tasks else [],
            "Downloaders": dict(Downloaders) if Downloaders else {},
        }
    )


# RSS解析器页面
@data_router.post("/rss_parser")
async def rss_parser(request: Request, current_user: User = Depends(get_current_user)):
    """
    RSS解析器页面
    """
    RssParsers = RssChecker().get_userrss_parser()

    return response(data=
        {
            "RssParsers": RssParsers,
            "Count": len(RssParsers),
        }
    )


# 自动删种页面
@data_router.post("/torrent_remove")
async def torrent_remove(request: Request, current_user: User = Depends(get_current_user)):
    """
    自动删种页面
    """
    Downloaders = Downloader().get_downloader_conf_simple()
    TorrentRemoveTasks = TorrentRemover().get_torrent_remove_tasks()

    return response(data=
        {
            "Downloaders": dict(Downloaders) if Downloaders else {},
            "DownloaderConfig": ModuleConf.TORRENTREMOVER_DICT,
            "Count": len(TorrentRemoveTasks) if TorrentRemoveTasks else 0,
            "TorrentRemoveTasks": dict(TorrentRemoveTasks) if TorrentRemoveTasks else {},
        }
    )


# 近期下载页面
@data_router.post("/downloaded")
async def downloaded(request: Request, current_user: User = Depends(get_current_user)):
    """
    近期下载页面
    """
    form = await request.form()
    CurrentPage = form.get("page") or 1

    return response(data=
        {
            "Type": 'DOWNLOADED',
            "Title": '近期下载',
            "CurrentPage": CurrentPage,
        }
    )


# 下载设置页面
@data_router.post("/download_setting")
async def download_setting(request: Request, current_user: User = Depends(get_current_user)):
    """
    下载设置页面
    """
    DefaultDownloadSetting = Downloader().default_download_setting_id
    Downloaders = Downloader().get_downloader_conf_simple()
    DownloadSetting = Downloader().get_download_setting()

    return response(data=
        {
            "DownloadSetting": dict(DownloadSetting) if DownloadSetting else {},
            "DefaultDownloadSetting": DefaultDownloadSetting,
            "Downloaders": dict(Downloaders) if Downloaders else {},
            "Count": len(DownloadSetting) if DownloadSetting else 0,
        }
    )


# 豆瓣电影
@data_router.post("/douban_movie")
async def douban_movie(request: Request, current_user: User = Depends(get_current_user)):
    """
    豆瓣电影页面
    """
    return response(data=
        {
            "Type": "DOUBANTAG",
            "SubType": "MOV",
            "Title": "豆瓣电影",
            "Filter": "douban_movie",
            "FilterConf": ModuleConf.DISCOVER_FILTER_CONF.get('douban_movie'),
        }
    )


# 豆瓣电视剧
@data_router.post("/douban_tv")
async def douban_tv(request: Request, current_user: User = Depends(get_current_user)):
    """
    豆瓣电视剧页面
    """
    return response(data=
        {
            "Type": "DOUBANTAG",
            "SubType": "TV",
            "Title": "豆瓣剧集",
            "Filter": "douban_tv",
            "FilterConf": ModuleConf.DISCOVER_FILTER_CONF.get('douban_tv'),
        }
    )


# TMDB电影
@data_router.post("/tmdb_movie")
async def tmdb_movie(request: Request, current_user: User = Depends(get_current_user)):
    """
    TMDB电影页面
    """
    return response(data=
        {
            "Type": "DISCOVER",
            "SubType": "MOV",
            "Title": "TMDB电影",
            "Filter": "tmdb_movie",
            "FilterConf": ModuleConf.DISCOVER_FILTER_CONF.get('tmdb_movie'),
        }
    )


# TMDB电视剧
@data_router.post("/tmdb_tv")
async def tmdb_tv(request: Request, current_user: User = Depends(get_current_user)):
    """
    TMDB电视剧页面
    """
    return response(data=
        {
            "Type": "DISCOVER",
            "SubType": "TV",
            "Title": "TMDB剧集",
            "Filter": "tmdb_tv",
            "FilterConf": ModuleConf.DISCOVER_FILTER_CONF.get('tmdb_tv'),
        }
    )


# TMDB缓存页面
@data_router.post("/tmdbcache")
async def tmdbcache(request: Request, current_user: User = Depends(get_current_user)):
    """
    TMDB缓存页面
    """
    form = await request.form()
    page_num = form.get("pagenum")
    if not page_num:
        page_num = 20
    search_str = form.get("s")
    if not search_str:
        search_str = ""
    current_page = form.get("page")
    if not current_page:
        current_page = 1
    else:
        current_page = int(current_page)

    total_count, tmdb_caches = MetaHelper().dump_meta_data(search_str, current_page, page_num)

    return response(data=
        {
            "TmdbCaches": tmdb_caches,
            "Search": search_str,
            "CurrentPage": current_page,
            "TotalCount": total_count
        }
    )


# 系统设置页面
@data_router.post("/system")
async def system(request: Request, current_user: User = Depends(get_current_user)):
    """
    系统设置页面
    """
    SystemConfig = Config().get_config('system') or {}
    CurrentVersion = WebUtils.get_current_version()
    RestartFlag = SystemConfig.get("restart_flag") or ""
    return response(data=
        {
            "Config": Config().get_config(),
            "CurrentVersion": CurrentVersion,
            "RestartFlag": RestartFlag,
            "IndexerStatistics": WebAction(current_user).get_indexer_statistics().get("result"),
        }
    )


# 字幕页面
@data_router.post("/subtitle")
async def subtitle(request: Request, current_user: User = Depends(get_current_user)):
    """
    字幕页面
    """
    SubtitleSites = SystemConfig().get(SystemConfigKey.UserSubtitleSites) or []
    return response(data=
        {
            "SubtitleSites": SubtitleSites,
        }
    )


# 历史记录页面
@data_router.post("/history")
async def history(request: Request, current_user: User = Depends(get_current_user)):
    """
    历史记录页面
    """
    form = await request.form()

    page_num = form.get("pagenum")
    if not page_num:
        page_num = 20

    search_str = form.get("s")
    if not search_str:
        search_str = ""

    current_page = form.get("page")
    if not current_page:
        current_page = 1
    else:
        current_page = int(current_page)

    Result = WebAction(current_user).get_transfer_history(search_str, current_page, page_num)

    return response(data=
        {
            "TotalCount": Result.get("total"),
            "Count": len(Result.get("result")),
            "Historys": Result.get("result"),
            "Search": search_str,
            "CurrentPage": Result.get("currentPage"),
            "TotalPage": Result.get("totalPage"),
            "PageNum": Result.get("currentPage"),
        }
    )


# 手工识别页面
@data_router.post("/unidentification")
async def unidentification(request: Request, current_user: User = Depends(get_current_user)):
    """
    手工识别页面
    """
    form = await request.form()

    page_num = form.get("pagenum")
    if not page_num:
        page_num = 20

    search_str = form.get("s")
    if not search_str:
        search_str = ""

    current_page = form.get("page")
    if not current_page:
        current_page = 1
    else:
        current_page = int(current_page)

    Result = WebAction(current_user).get_unknown_list_by_page(search_str, current_page, page_num)

    return response(data=
        {
            "TotalCount": Result.get("total"),
            "Count": len(Result.get("items")),
            "Items": Result.get("items"),
            "Search": search_str,
            "CurrentPage": Result.get("currentPage"),
            "TotalPage": Result.get("totalPage"),
            "PageNum": Result.get("currentPage"),
        }
    )


# 给这个 router 加异常捕获
router_exception_handler(data_router)