import os

from functools import wraps
from math import floor

from fastapi import APIRouter, Request, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

import log

from app.core.cmd_registry import CommandRegistry
from app.conf.moduleconf import ModuleConf
from app.conf.systemconfig import SystemConfig
from app.downloader.config import PT_TRANSFER_INTERVAL
from app.downloader.downloader import Downloader
from app.helper.meta_helper import MetaHelper
from app.helper.words_helper import WordsHelper
from app.indexer.indexer import Indexer
from app.media.category import Category
from app.mediaserver.media_server import MediaServer
from app.message import Message
from app.middleware.security import get_current_user
from app.modules.brushtaskv2 import BrushTaskV2 as BrushTask
from app.modules.filter import Filter
from app.modules.rsschecker import RssChecker
from app.modules.sync import Sync
from app.modules.torrentremover import TorrentRemover
from app.modules.filetransfer import FileTransfer
from app.modules.rss import Rss
from app.modules.search import SearchProxy
from app.modules.subscribe import Subscribe
from app.models.user import User, UserManager
from app.plugins.plugin_manager import PluginManager
from app.sites.site_manager import SitesManager
from app.sites.site_statistics import SitesDataStatisticsCenter
from app.utils.constants import Constants
from app.utils.system_utils import SystemUtils
from app.utils.types import Spider, SystemConfigKey

from config import Config

# 页面数据路由
data_router = APIRouter(
    prefix="/data",
    dependencies=[Depends(get_current_user)]
)

SOURCE_TYPES = { 
    "MOVIE":'电影', 
    "TV":'剧集', 
    "ANIME":'动漫' 
}

SEARCH_PARAMS = { 
    "kw": '关键字', 
    "en": '英文名', 
    "douban": '豆瓣id', 
    "imdb": 'imdb id'
}


# 异常捕获器
def router_exception_handler(router: APIRouter):
    """
    统一异常捕获器
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

# userinfo
@data_router.post("/userinfo")
async def sysinfo(current_user: User = Depends(get_current_user)):

    return response(data=
        {
            "username" : current_user.username
        }
    )


# sysinfo
@data_router.post("/sysinfo")
async def sysinfo(current_user: User = Depends(get_current_user)):

    # 判断当前的运营环境
    system_flag = SystemUtils.get_system()
    tmdb_flag = 1 if Config().get_config('app').get('rmt_tmdbkey') else 0
    default_path = Config().get_config('media').get('media_default_path')
    sync_mod = Config().get_config('media').get('default_rmt_mode')
    if not sync_mod:
        sync_mod = "link"

    username = current_user.username
    
    commands = CommandRegistry().list_commands()
    pulgins = [{"id": item.get("cmd"), "name": item.get("desc")} for item in PluginManager().get_plugin_commands()]
    commands = commands + pulgins

    restype_dict = ModuleConf.TORRENT_SEARCH_PARAMS.get("restype")
    pix_dict = ModuleConf.TORRENT_SEARCH_PARAMS.get("pix")
    rmt_mode_dict = _get_rmt_modes_dict()

    download_settings = {did: attr["name"] for did, attr in Downloader().get_download_setting().items()}
    spider_types = { member.value: member.name for member in Spider }

    return response(data=
        {
            "username" : username,
            "admin" : 1 if current_user.admin else 0,
            "search" : current_user.search,
            "menus": current_user.get_usermenus(),
            "systemFlag": system_flag.value,
            "tmdbFlag": tmdb_flag,
            "appVersion": SystemUtils.get_current_version(),
            "syncMod": sync_mod,
            "defaultPath": default_path,
            "commands": commands,
            "restypeDict": restype_dict,
            "pixDict": pix_dict,
            "rmtDodeDict": rmt_mode_dict,
            "downloadSettings": download_settings,
            "spiderTypes": spider_types,
            "sourceTypes": SOURCE_TYPES,
            "searchParams": SEARCH_PARAMS,
        }
    )


# 基础设置页面
@data_router.post("/basic")
async def basic():

    proxy = Config().get_config('app').get("proxies", {}).get("http")
    if proxy:
        proxy = proxy.replace("http://", "")
        
    custom_script_cfg = SystemConfig().get(SystemConfigKey.CustomScript)
    return response(data=
        {
            "Config": Config().get_config(),
            "Proxy": proxy,
            "CustomScriptCfg": custom_script_cfg,
            "MediaServerConf": ModuleConf.MEDIASERVER_CONF,
            "TmdbDomains": Constants.TMDB_API_DOMAINS,
        }
    )


# 开始页面
@data_router.post("/index")
async def index():

    # 磁盘空间
    library_spaces = _get_library_spacesize()
    # 媒体库配置
    library_sync_conf = SystemConfig().get(SystemConfigKey.SyncLibrary) or []
    # 媒体服务器类型
    server_type = Config().get_config('media').get('media_server')

    # 媒体库
    media_server = MediaServer()

    media_librarys = media_server.get_libraries()
    activity_logs = media_server.get_activity_log(30)
    latest_adds = media_server.get_latest()

    # 获取媒体数量
    media_counts = media_server.get_medias_count()
    if media_counts:
        server_sucess = True
        movie_count = "{:,}".format(media_counts.get('MovieCount'))
        series_count = "{:,}".format(media_counts.get('SeriesCount'))
        song_count = "{:,}".format(media_counts.get('SongCount'))
        episode_count = "{:,}".format(media_counts.get('EpisodeCount')) if media_counts.get('EpisodeCount') else ""
    else:
        server_sucess = False
        movie_count = 0
        series_count = 0
        song_count = 0
        episode_count = 0

    return response(data=
        {
             "serverSucess": server_sucess,
             "mediaCount": {
                 'movieCount': movie_count,
                 'seriesCount': series_count,
                 'songCount': song_count,
                 "episodeCount": episode_count
                },
             "activitys": activity_logs,
             "totalSpace": library_spaces.get("TotalSpace"),
             "usedPercent": library_spaces.get("UsedPercent"),
             "mediaServerType": server_type,
             "librarys": media_librarys,
             "librarySyncConf": library_sync_conf,
             "latests": latest_adds,
        }
    )


# 资源搜索页面
@data_router.post("/search")
async def search():

    res = SearchProxy().get_torrent_search_result()
    return response(data=
        {
            "Count": res.get("total"),
            "Results": res.get("result"),
            "SiteDict": Indexer().get_indexer_hash_dict()
        })


# 订阅页面
@data_router.post("/rss")
async def rss(t: str = "MOV"):

    rule_groups = {str(group["id"]): group["name"] for group in Filter().get_rule_groups()}
    download_settings = Downloader().get_download_setting()

    rss_items = []
    rss_type = 'MOV'
    type_name = '电影'

    if t == 'TV':
        rss_items = Subscribe().get_subscribe_tvs()
        rss_type = 'TV'
        type_name = '电视剧'
    else:
        rss_items = Subscribe().get_subscribe_movies()

    return response(data=
        {
            "RuleGroups": rule_groups,
            "DownloadSettings": dict(download_settings) if download_settings else {},
            "Items": rss_items,
            "Type": rss_type,
            "TypeName": type_name,
        })


# 订阅历史页面
@data_router.post("/rss_history")
async def rss_history(t: str = ""):

    rss_history = [rec.as_dict() for rec in Rss().get_rss_history(rtype=t)]

    return response(data=
        {
            "Items": rss_history,
            "Type": t,
        })


# 订阅日历页面
@data_router.post("/rss_calendar")
async def rss_calendar():

    subscriber = Subscribe()

    # 电影订阅
    rss_movies = [
            {
                "id": movie.get("tmdbid"),
                "rssid": movie.get("id")
            } for movie in subscriber.get_subscribe_movies().values() if movie.get("tmdbid")
        ]
    
    rss_tvs = []

    # 电视剧订阅
    rss_tv_items = [
        {
            "id": tv.get("tmdbid"),
            "rssid": tv.get("id"),
            "season": int(str(tv.get('season')).replace("S", "")),
            "name": tv.get("name"),
        } for tv in subscriber.get_subscribe_tvs().values() if tv.get('season') and tv.get("tmdbid")
    ]

    # 自定义订阅
    rss_tv_items += RssChecker().get_userrss_mediainfos()

    # 电视剧订阅去重
    Uniques = set()
    for item in rss_tv_items:
        unique = f"{item.get('id')}_{item.get('season')}"
        if unique not in Uniques:
            Uniques.add(unique)
            rss_tvs.append(item)

    return response(data=
        {
            "RssMovieItems": rss_movies,
            "RssTvItems": rss_tvs,
        })


# 索引站点页面
@data_router.post("/indexer")
async def indexer(p: int = 1):

    # 启用的索引站点
    indexer_sites = SystemConfig().get(SystemConfigKey.UserIndexerSites)
    if not indexer_sites:
        indexer_sites = []

    is_public = p == 1
    front_indexers = []

    indexers = Indexer().get_indexers(check=False)
    for idx_site in indexers:

        if idx_site.public != is_public:
            continue

        checked = idx_site.id in indexer_sites
        site_info = {
            "id": idx_site.id,
            "name": idx_site.name,
            "domain": idx_site.domain,
            "render": idx_site.render,
            "source_type": idx_site.source_type,
            "search_param": idx_site.search_param,
            "search_param_name": SEARCH_PARAMS.get(idx_site.search_param, '关键字'),
            "public": idx_site.public,
            "proxy": idx_site.proxy,
            "en_expand": idx_site.en_expand,
            "checked": checked
        }
        front_indexers.append(site_info)

    # 根据选中情况排序
    sorted_list = sorted(front_indexers, key=lambda x: x.get("id", "") not in indexer_sites)

    return response(data=
        {
            "indexers": sorted_list,
            "sourceTypes": SOURCE_TYPES
        })


# 站点维护页面
@data_router.post("/site")
async def sites_page():

    indexer_sites = SystemConfig().get(SystemConfigKey.UserIndexerSites)
    if not indexer_sites:
        indexer_sites = []

    cfg_sites = SitesManager().get_sites()
    rule_groups = {str(group["id"]): group["name"] for group in Filter().get_rule_groups()}
    download_settings = {did: attr["name"] for did, attr in Downloader().get_download_setting().items()}
    cookie_cloud_cfg = SystemConfig().get(SystemConfigKey.CookieCloud)
    cookie_user_info_cfg = SystemConfig().get(SystemConfigKey.CookieUserInfo)

    sorted_list = sorted(cfg_sites, key=lambda x: x.indexer_id not in indexer_sites)

    return response(data=
        {
            "Sites": sorted_list,
            "RuleGroups": rule_groups,
            "DownloadSettings": download_settings,
            "ChromeOk": True,
            "CookieCloudCfg": cookie_cloud_cfg,
            "CookieUserInfoCfg": cookie_user_info_cfg,
            "indexerSites": indexer_sites,
            "sourceTypes": SOURCE_TYPES,
        }
    )


# 站点资源页面
@data_router.post("/sitelist")
async def sitelist_page():
    indexer_sites = Indexer().get_indexers(check=False)
    return response(data=
        {
            "Sites": indexer_sites,
        }
    )


# 媒体库页面
@data_router.post("/library")
async def library():
    rmt_mode_dict = _get_rmt_modes_dict()
    scraper_conf = SystemConfig().get(SystemConfigKey.UserScraperConf) or {}
    return response(data=
        {
            "Config": Config().get_config(),
            "RmtModeDict": rmt_mode_dict,
            "ScraperNfo": scraper_conf.get("scraper_nfo") or {},
            "ScraperPic": scraper_conf.get("scraper_pic") or {},
        })


# 通知消息页面
@data_router.post("/notification")
async def notification():

    message_clients = Message().get_message_client_info()
    switchs = ModuleConf.MESSAGE_CONF.get("switch")

    channels = ModuleConf.MESSAGE_CONF.get("client")
    channels_tpyes = []

    # 遍历修改
    for key, conf in channels.items():
        if "search_type" in conf:
            conf["search_type"] = str(conf["search_type"])
        channels_tpyes.append(key)

    return response(data=
        {
            "Channels": channels,
            "Switchs": switchs,
            "ChannelsTpyes": channels_tpyes,
            "MessageClients": dict(message_clients) if message_clients else {},
        })


# 用户管理页面
@data_router.post("/users")
async def users(current_user: User = Depends(get_current_user)):

    users = []
    top_menus = []
    
    if current_user.admin:
        users = []
        user_list = UserManager().get_users()
        for user in user_list:
            pris = str(user.pris).split(",")
            users.append({"id": user.id, "name": user.username, "pris": pris})
        top_menus = current_user.get_topmenus()

    return response(data=
        {
            "Users": users,
            "TopMenus": top_menus,
        })


# 过滤规则设置页面
@data_router.post("/filterrule")
async def filterrule():

    _filter = Filter()
    rule_groups = _filter.get_rule_infos()
    init_rule_groups = _filter.get_init_filterrules()

    return response(data=
        {
            "RuleGroups": rule_groups,
            "InitRuleGroups": init_rule_groups,
        })


# 目录同步页面
@data_router.post("/directorysync")
async def directorysync():
    rmt_mode_dict = _get_rmt_modes_dict()
    sync_paths = Sync().get_sync_path_conf()
    return response(data=
        {
            "SyncPaths": sync_paths,
            "RmtModeDict": rmt_mode_dict,
        })


# 自定义识别词设置页面
@data_router.post("/customwords")
async def customwords():
    groups = WordsHelper().get_customwords_groups()
    return response(data=
        {
            "Groups": groups,
            "GroupsCount": len(groups),
        })


# 插件页面
@data_router.post("/plugin")
async def plugin(current_user: User = Depends(get_current_user)):

    # 插件
    plugins = PluginManager().get_plugins_conf(current_user.level)

    return response(data=
        {
            "Plugins": plugins
        })


# 用户RSS页面
@data_router.post("/user_rss")
async def user_rss():
    """
    用户RSS页面
    """
    _rss_checker = RssChecker()
    rss_tasks = _rss_checker.get_rsstask_info()
    rss_parsers = _rss_checker.get_userrss_parser()

    rule_groups = {str(group["id"]): group["name"] for group in Filter().get_rule_groups()}
    download_settings = {did: attr["name"] for did, attr in Downloader().get_download_setting().items()}
    restype_dict = ModuleConf.TORRENT_SEARCH_PARAMS.get("restype")
    pix_dict = ModuleConf.TORRENT_SEARCH_PARAMS.get("pix")

    return response(data=
        {
            "Tasks": rss_tasks,
            "Count": len(rss_tasks),
            "RssParsers": rss_parsers,
            "RuleGroups": rule_groups,
            "RestypeDict": restype_dict,
            "PixDict": pix_dict,
            "DownloadSettings": download_settings,
        }
    )


# 服务页面
@data_router.post("/service")
async def service(current_user: User = Depends(get_current_user)):
    """
    服务页面
    """

    # 获取用户服务
    service_list = current_user.get_services()
    pt_config = Config().get_config('pt')

    # RSS订阅
    if "rssdownload" in service_list:
        pt_check_interval = pt_config.get('pt_check_interval')
        if str(pt_check_interval).isdigit():
            tim_rssdownload = str(round(int(pt_check_interval) / 60)) + " 分钟"
            rss_state = 'ON'
        else:
            tim_rssdownload = ""
            rss_state = 'OFF'
        service_list['rssdownload'].update({
            'time': tim_rssdownload,
            'state': rss_state,
        })

    # RSS搜索
    if "subscribe_search_all" in service_list:
        search_rss_interval = pt_config.get('search_rss_interval')
        if str(search_rss_interval).isdigit():
            if int(search_rss_interval) < 3:
                search_rss_interval = 3
            tim_rsssearch = str(int(search_rss_interval)) + " 小时"
            rss_search_state = 'ON'
        else:
            tim_rsssearch = ""
            rss_search_state = 'OFF'
        service_list['subscribe_search_all'].update({
            'time': tim_rsssearch,
            'state': rss_search_state,
        })

    # 下载文件转移
    if "pttransfer" in service_list:
        pt_monitor = Downloader().monitor_downloader_ids
        if pt_monitor:
            tim_pttransfer = str(round(PT_TRANSFER_INTERVAL / 60)) + " 分钟"
            sta_pttransfer = 'ON'
        else:
            tim_pttransfer = ""
            sta_pttransfer = 'OFF'
        service_list['pttransfer'].update({
            'time': tim_pttransfer,
            'state': sta_pttransfer,
        })

    # 目录同步
    if "sync" in service_list:
        if Sync().monitor_sync_path_ids:
            service_list['sync'].update({'state': 'ON'})

    # 系统进程
    if "processes" in service_list:
        if not SystemUtils.is_docker() or not SystemUtils.get_all_processes():
            service_list.pop('processes')

    # 所有规则组
    rule_groups = Filter().get_rule_groups()
    # 所有同步目录
    sync_paths = Sync().get_sync_path_conf()

    return response(data=
        {
            "ruleGroups": rule_groups,
            "syncPaths": sync_paths,
            "schedulerTasks": service_list,
        }
    )


# 下载器
@data_router.post("/downloaders")
async def downloading():
    """
    正在下载页面
    """

    # 下载器
    download_manager = Downloader()
    default_downloader = download_manager.default_downloader_id
    downloader_confs = download_manager.get_downloader_conf()

    # 目录配置
    category_manager = Category()
    categories = {
        "电影" : list(category_manager.movie_categorys),
        "电视剧": list(category_manager.tv_categorys),
        "动漫": list(category_manager.anime_categorys)
    }

    rmt_mode_dict = _get_rmt_modes_dict()

    return response(data=
        {
            "downloaders": downloader_confs,
            "defaultDownloader": default_downloader,
            "categories": categories,
            "downloaderConf": ModuleConf.DOWNLOADER_CONF,
            "rmtModeDict": rmt_mode_dict,
        }
    )


# 正在下载页面
@data_router.post("/downloading")
async def downloading():
    """
    正在下载页面
    """
    download_manager = Downloader()

    active_downloaders = []
    for key, value in download_manager.get_downloader_conf().items():
        if not value.get('enabled'):
            continue
        if key == download_manager.default_downloader_id:
            active_downloaders.insert(0, value) # 默认下载器放到列表头部
        else:
            active_downloaders.append(value)

    return response(data=
        {
            "downloaders": active_downloaders
        }
    )


# 媒体文件管理页面
@data_router.post("/mediafile")
async def mediafile():
    """
    媒体文件管理页面
    """
    media_default_path = Config().get_config('media').get('media_default_path')
    if media_default_path:
        root_dir = media_default_path
    else:
        download_dirs = Downloader().get_download_visit_dirs()
        if download_dirs:
            try:
                root_dir = os.path.commonpath(download_dirs).replace("\\", "/")
            except Exception as err:
                log.exception(f'管理目录转换异常: {download_dirs}')
                root_dir = "/"
        else:
            root_dir = "/"
    
    return response(data=
        {
            "Dir": root_dir,
        }
    )


# 数据统计页面
@data_router.post("/statistics")
async def statistics(current_user: User = Depends(get_current_user)):
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
    site_user_statistics = SitesDataStatisticsCenter().get_site_user_statistics(encoding= "DICT")
    
    # 站点上传下载总量
    for site_item in site_user_statistics:

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
            "SiteUserStatistics": site_user_statistics,
        }
    )


# 刷流任务页面
@data_router.post("/brushtask")
async def brushtask():
    """
    刷流任务页面
    """
    # 站点列表
    config_sites = SitesManager().get_sites(brush=True)
    # 下载器列表
    downloaders = Downloader().get_downloader_conf_simple()
    # 任务列表
    brush_tasks = BrushTask().get_brushtask_info()

    return response(data=
        {
            "Count": len(brush_tasks),
            "Sites": config_sites,
            "Tasks": list(brush_tasks) if brush_tasks else [],
            "Downloaders": dict(downloaders) if downloaders else {},
        }
    )


# RSS解析器页面
@data_router.post("/rss_parser")
async def rss_parser():
    """
    RSS解析器页面
    """
    rss_parsers = RssChecker().get_userrss_parser()

    return response(data=
        {
            "RssParsers": rss_parsers,
            "Count": len(rss_parsers),
        }
    )


# 自动删种页面
@data_router.post("/torrent_remove")
async def torrent_remove():
    """
    自动删种页面
    """
    downloaders = Downloader().get_downloader_conf_simple()
    torrent_remove_tasks = TorrentRemover().get_torrent_remove_tasks()

    return response(data=
        {
            "Downloaders": dict(downloaders) if downloaders else {},
            "DownloaderConfig": ModuleConf.TORRENTREMOVER_DICT,
            "Count": len(torrent_remove_tasks) if torrent_remove_tasks else 0,
            "TorrentRemoveTasks": dict(torrent_remove_tasks) if torrent_remove_tasks else {},
        }
    )


# 下载设置页面
@data_router.post("/download_setting")
async def download_setting():
    """
    下载设置页面
    """
    default_download_setting_id = Downloader().default_download_setting_id
    downloaders = Downloader().get_downloader_conf_simple()
    download_setting = Downloader().get_download_setting()

    return response(data=
        {
            "DownloadSetting": dict(download_setting) if download_setting else {},
            "DefaultDownloadSetting": default_download_setting_id,
            "Downloaders": dict(downloaders) if downloaders else {},
            "Count": len(download_setting) if download_setting else 0,
        }
    )

# TMDB缓存页面
@data_router.post("/tmdbcache")
async def tmdbcache(request: Request):
    """
    TMDB缓存页面
    """
    data = await request.json()
    
    page_num = data.get("pagenum")
    if not page_num:
        page_num = 20
    search_str = data.get("s")
    if not search_str:
        search_str = ""
    current_page = data.get("page")
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


# 历史记录页面
@data_router.post("/history")
async def history(request: Request):
    """
    历史记录页面
    """
    data = await request.json()

    page_size = data.get("pagenum")
    if not page_size:
        page_size = 20

    search_str = data.get("s")
    if not search_str:
        search_str = ""

    current_page = data.get("page")
    if not current_page:
        current_page = 1
    else:
        current_page = int(current_page)

    # 查询
    total_count, historys = FileTransfer().get_transfer_history(search_str, current_page, page_size)
    # 结果转换
    historys_list = []
    for history in historys:
        history = history.as_dict()
        sync_mode = history.get("MODE")
        rmt_mode = ModuleConf.get_dictenum_key(
            ModuleConf.RMT_MODES, sync_mode) if sync_mode else ""
        history.update({
            "SYNC_MODE": sync_mode,
            "RMT_MODE": rmt_mode
        })
        historys_list.append(history)

    total_page = floor(total_count / page_size) + 1

    return response(data=
        {
            "Search": search_str,
            "TotalCount": total_count,
            "Count": len(historys_list),
            "Historys": historys_list,
            "CurrentPage": current_page,
            "TotalPage": total_page,
            "PageNum": current_page,
        }
    )


# 手工识别页面
@data_router.post("/unidentification")
async def unidentification(request: Request):
    """
    手工识别页面
    """
    data = await request.json()

    page_num = data.get("pagenum")
    if not page_num:
        page_num = 20

    search_str = data.get("s")
    if not search_str:
        search_str = ""

    current_page = data.get("page")
    if not current_page:
        current_page = 1
    else:
        current_page = int(current_page)

    # 查询
    total_count, db_records = FileTransfer().get_transfer_unknown_paths_by_page(search_str, current_page, page_num)
    # 结果转换
    unknown_items = []
    for rec in db_records:
        if not rec.PATH:
            continue
        path = rec.PATH.replace("\\", "/") if rec.PATH else ""
        path_to = rec.DEST.replace("\\", "/") if rec.DEST else ""
        sync_mode = rec.MODE or ""
        rmt_mode = ModuleConf.get_dictenum_key(ModuleConf.RMT_MODES,
                                               sync_mode) if sync_mode else ""
        unknown_items.append({
            "id": rec.ID,
            "path": path,
            "to": path_to,
            "name": path,
            "sync_mode": sync_mode,
            "rmt_mode": rmt_mode,
        })

    total_page = floor(total_count / page_num) + 1

    return response(data=
        {
            "TotalCount": total_count,
            "Count": len(unknown_items),
            "Items": unknown_items,
            "Search": search_str,
            "CurrentPage": current_page,
            "TotalPage": total_page,
            "PageNum": current_page,
        }
    )


# 查询转移模式字典
def _get_rmt_modes_dict():
    rmt_modes = ModuleConf.RMT_MODES
    return [{
        "value": value,
        "name": name.value
    } for value, name in rmt_modes.items()]


def _get_library_spacesize():
    """
    查询媒体库存储空间
    """
    # 磁盘空间
    used_sapce = 0
    used_percent = 0

    media_config = Config().get_config('media')
    # 电影目录
    movie_paths = media_config.get('movie_path')
    if not isinstance(movie_paths, list):
        movie_paths = [movie_paths]

    # 电视目录
    tv_paths = media_config.get('tv_path')
    if not isinstance(tv_paths, list):
        tv_paths = [tv_paths]

    # 动漫目录
    anime_paths = media_config.get('anime_path')
    if not isinstance(anime_paths, list):
        anime_paths = [anime_paths]

    # 总空间、剩余空间
    total_space, free_space = SystemUtils.calculate_space_usage(movie_paths + tv_paths + anime_paths)
    if total_space:
        # 已使用空间
        used_sapce = total_space - free_space
        # 百分比格式化
        used_percent = "%0.1f" % ((used_sapce / total_space) * 100)
        # 总剩余空间 格式化
        if free_space > 1024:
            free_space = "{:,} TB".format(round(free_space / 1024, 2))
        else:
            free_space = "{:,} GB".format(round(free_space, 2))
        # 总使用空间 格式化
        if used_sapce > 1024:
            used_sapce = "{:,} TB".format(round(used_sapce / 1024, 2))
        else:
            used_sapce = "{:,} GB".format(round(used_sapce, 2))
        # 总空间 格式化
        if total_space > 1024:
            total_space = "{:,} TB".format(round(total_space / 1024, 2))
        else:
            total_space = "{:,} GB".format(round(total_space, 2))

    return {
        "TotalSpace": total_space,
        "UsedPercent": used_percent,
        "FreeSpace": free_space,
        "UsedSapce": used_sapce
    }



# 下载历史页面
@data_router.post("/download_history")
async def download_history(request: Request):
    """
    下载历史页面
    """
    data = await request.json()

    search_type = data.get("type") or ""
    search_tmdbid = data.get("tmdbid") or ""
    search_site = data.get("site") or ""

    page_size = data.get("pagenum")
    if not page_size:
        page_size = 30

    current_page = data.get("page")
    if not current_page:
        current_page = 1
    else:
        current_page = int(current_page)

    from app.db.models import DOWNLOADHISTORY
    from app.helper.db_helper import DbHelper

    db = DbHelper()
    query = db._db.query(DOWNLOADHISTORY)

    if search_type:
        query = query.filter(DOWNLOADHISTORY.TYPE == search_type)
    if search_tmdbid:
        query = query.filter(DOWNLOADHISTORY.TMDBID == search_tmdbid)
    if search_site:
        query = query.filter(DOWNLOADHISTORY.SITE.like(f"%{search_site}%"))

    total_count = query.count()
    offset = (current_page - 1) * page_size
    results = query.order_by(DOWNLOADHISTORY.ID.desc()).limit(page_size).offset(offset).all()

    items = [rec.as_dict() for rec in results]

    total_page = floor(total_count / page_size) + 1 if total_count > 0 else 0

    return response(data={
        "Items": items,
        "TotalCount": total_count,
        "TotalPage": total_page,
        "CurrentPage": current_page,
        "PageNum": page_size,
        "Type": search_type,
        "Tmdbid": search_tmdbid,
        "Site": search_site,
    })


# 给这个 router 加异常捕获
router_exception_handler(data_router)