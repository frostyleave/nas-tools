import shutil
import os

from dataclasses import dataclass, field
from threading import Lock
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler

import log

from app.conf import SystemConfig
from app.downloader.client._base import _IDownloadClient
from app.downloader.config import DownloadConfig, PT_TAG
from app.downloader.torrent import TorrentDownloader
from app.downloader.media_check import MediaExistenceChecker
from app.downloader.transfer import TransferManager
from app.downloader.batch import BatchDownloader
from app.modules.filetransfer import FileTransfer
from app.models.model import UserSiteConf, IndexerInfo
from app.helper import DbHelper, ThreadHelper, SubmoduleHelper
from app.core.jobcenter import JobCenter
from app.media import Media
from app.media.meta import MetaInfo
from app.mediaserver import MediaServer
from app.message import Message
from app.plugins import EventManager
from app.sites import SitesManager, SiteSubtitle
from app.utils import TorrentUtils, StringUtils
from app.utils.torrent import TorrentDownloadResult
from app.utils.commons import singleton
from app.utils.constants import Constants
from app.utils.types import DownloaderType, SearchType

from config import Config

client_lock = Lock()

@dataclass
class _DownloadContentInfo:
    """
    _resolve_download_content 的返回结果（内部使用）
    """
    url: str = ""
    torrent_file: str | None = None
    content: str | bytes | None = None
    dl_files_folder: str = ""
    dl_files: list = field(default_factory=list)
    retmsg: str = ""
    site_info: Optional[UserSiteConf] = None

    @property
    def success(self) -> bool:
        return bool(self.content or self.torrent_file)

@singleton
class Downloader:
    # 客户端实例
    clients = {}

    _downloader_schema = []
    _scheduler = None
    _torrent_temp_path = None

    message = None
    mediaserver = None
    filetransfer = None
    media = None
    sites = None
    sitesubtitle = None
    dbhelper = None
    systemconfig = None
    eventmanager = None

    @property
    def transfer_job(self):
        return self._transfer_manager.transfer_job if hasattr(self, '_transfer_manager') else None

    def __init__(self):
        self._downloader_schema = SubmoduleHelper.import_submodules(
            'app.downloader.client',
            filter_func=lambda _, obj: hasattr(obj, 'client_id')
        )
        log.debug(f"【Downloader】加载下载器类型: {self._downloader_schema}")
        # 种子文件临时路径
        self._torrent_temp_path = Config().get_temp_path()
        if not os.path.exists(self._torrent_temp_path):
            os.makedirs(self._torrent_temp_path)
        # 配置管理器
        self._config = DownloadConfig()
        # 配置初始化
        self.init_config()

    def _get_client(self, did=None):
        """获取下载器客户端实例（供子模块调用）"""
        return self.__get_client(did)

    def init_config(self):
        self.dbhelper = DbHelper()
        self.message = Message()
        self.mediaserver = MediaServer()
        self.filetransfer = FileTransfer()
        self.media = Media()
        self.sites = SitesManager()
        self.systemconfig = SystemConfig()
        self.eventmanager = EventManager()
        self.sitesubtitle = SiteSubtitle()
        # 种子下载器
        self._torrent_downloader = TorrentDownloader(
            torrent_temp_path=self._torrent_temp_path,
            sites_manager=self.sites
        )
        # 清空已存在下载器实例
        self.clients = {}
        # 重新加载配置
        self._config._dbhelper = self.dbhelper
        self._config.reload()
        # 子模块（延迟初始化避免循环引用）
        self._transfer_manager = TransferManager(self)
        self._media_checker = MediaExistenceChecker(self.media, self.mediaserver, self.filetransfer)
        self._batch_downloader = BatchDownloader(self)
        # 启动下载器监控服务
        self._transfer_manager.start_service()

    def __build_class(self, ctype, conf=None):
        for downloader_schema in self._downloader_schema:
            try:
                if downloader_schema.match(ctype):
                    return downloader_schema(conf)
            except Exception as e:
                log.critical("【Downloader】下载器实例化异常: ")
        return None

    @property
    def default_downloader_id(self):
        """获取默认下载器id"""
        return self._config.default_downloader_id

    @property
    def default_download_setting_id(self):
        """获取默认下载设置id"""
        return self._config.default_download_setting_id

    def get_downloader_type(self, downloader_id=None):
        """
        获取下载器的类型
        """
        if not downloader_id:
            return self.default_client.get_type()
        return self.__get_client(downloader_id).get_type()

    @property
    def default_client(self):
        """
        获取默认下载器实例
        """
        return self.__get_client(self.default_downloader_id)

    @property
    def monitor_downloader_ids(self):
        """获取监控下载器ID列表"""
        return self._config.monitor_downloader_ids

    def start_service(self):
        """转移任务调度（委托给 TransferManager）"""
        self._transfer_manager.start_service()

    def get_scheduler(self) -> BackgroundScheduler:
        """获取任务管理器"""
        return JobCenter().get_sys_scheduler()
    
    def __get_client(self, did=None) -> _IDownloadClient:
        if not did:
            return None
        downloader_conf = self.get_downloader_conf(did)
        if not downloader_conf:
            log.info("【Downloader】下载器配置不存在")
            return None
        if not downloader_conf.enabled:
            log.info("【Downloader】下载器 %s 未启用", downloader_conf.name)
            return None
        ctype = downloader_conf.type
        config = downloader_conf.config
        config["download_dir"] = downloader_conf.download_dir
        config["name"] = downloader_conf.name
        with client_lock:
            did_key = str(did)
            if not self.clients.get(did_key):
                self.clients[did_key] = self.__build_class(ctype, config)
            return self.clients.get(did_key)

    def _download_fail_notify(self, in_from, media_info, msg):
        """
        发送下载失败消息
        """
        if in_from:
            self.message.send_download_fail_message(media_info, f"添加下载任务失败: {msg}")

    def download(self,
                 media_info,
                 is_paused=None,
                 tag=None,
                 download_dir=None,
                 download_setting=None,
                 downloader_id=None,
                 upload_limit=None,
                 download_limit=None,
                 torrent_file=None,
                 in_from=None,
                 user_name=None,
                 proxy=None):
        """
        添加下载任务, 根据当前使用的下载器分别调用不同的客户端处理
        :param media_info: 需下载的媒体信息, 含URL地址
        :param is_paused: 是否暂停下载
        :param tag: 种子标签
        :param download_dir: 指定下载目录
        :param download_setting: 下载设置id, 为None则使用-1默认设置, 为"-2"则不使用下载设置
        :param downloader_id: 指定下载器ID下载
        :param upload_limit: 上传速度限制
        :param download_limit: 下载速度限制
        :param torrent_file: 种子文件路径
        :param in_from: 来源
        :param user_name: 用户名
        :param proxy: 是否使用代理, 指定该选项为 True/False 会覆盖 site_info 的设置
        :return: 下载器类型, 种子ID, 错误信息
        """

        title = media_info.org_string
        page_url = media_info.page_url

        # 1. 解析下载内容
        content_info = self._resolve_download_content(media_info, torrent_file)
        url = content_info.url
        torrent_file = content_info.torrent_file
        content = content_info.content
        dl_files_folder = content_info.dl_files_folder
        dl_files = content_info.dl_files
        retmsg = content_info.retmsg
        site_info = content_info.site_info

        # 2. 验证解析结果
        if retmsg:
            log.warn("【Downloader】种子解析: %s" % retmsg)

        if not content and not torrent_file:
            self._download_fail_notify(in_from, media_info, retmsg)
            return None, None, retmsg

        # 3. 解析下载客户端
        download_attr, downloader_conf, downloader_client, download_setting_name, downloader_id = \
            self._resolve_download_client(download_setting, downloader_id, media_info)

        if not downloader_client or not downloader_conf:
            self._download_fail_notify(in_from, media_info, "请检查下载设置所选下载器是否有效且启用")
            return None, None, f"下载设置 {download_setting_name} 所选下载器失效"

        # 4. 执行下载
        try:

            # 暂停
            if is_paused is None:
                is_paused = StringUtils.to_bool(download_attr.get("is_paused"))
            else:
                is_paused = True if is_paused else False

            # 下载设置中的分类
            category = download_attr.get("category")
            download_info = self.__get_download_dir_info(media_info, downloader_conf.download_dir)
            if download_info:
                # 从下载目录中获取分类标签
                if not category:
                    category = download_info.get('category')
                # 下载目录设置
                if not download_dir:
                    download_dir = download_info.get('path')

            # 添加下载任务
            download_id = self.add_torrent(media_info, torrent_file, content, downloader_client, downloader_conf, download_dir, is_paused, upload_limit, download_limit, category, tag, download_attr, site_info)

            downloader_name = downloader_conf.name
            # 添加下载成功
            if download_id:
                self._log_add_download(downloader_name, title, download_dir, torrent_file, content, url, is_paused)
                # 计算数据文件保存的路径
                subtitle_dir, save_dir = self._calc_save_path(download_dir, dl_files_folder, dl_files)
                # 登记下载历史, 记录下载目录
                self.dbhelper.insert_download_history(media_info=media_info,
                                                      downloader=downloader_id,
                                                      download_id=download_id,
                                                      save_dir=save_dir)
                # 下载站点字幕文件
                if page_url and subtitle_dir and site_info and site_info.subtitle:
                    ThreadHelper().start_thread(self.sitesubtitle.download, (media_info, site_info.id, site_info.cookie, site_info.ua, subtitle_dir))

                # 发送下载消息
                if in_from:
                    media_info.user_name = user_name
                    self.message.send_download_message(in_from=in_from,
                                                       can_item=media_info,
                                                       download_setting_name=download_setting_name,
                                                       downloader_name=downloader_name)

                return downloader_id, download_id, ""
            else:
                self._download_fail_notify(in_from, media_info, "请检查下载任务是否已存在")
                return downloader_id, None, f"下载器 {downloader_name} 添加下载任务失败, 请检查下载任务是否已存在"
        except Exception as e:
            self._download_fail_notify(in_from, media_info, str(e))
            log.exception("【Downloader】下载器 %s 添加任务出错:", downloader_name)
            return None, None, str(e)


    def _resolve_download_content(self, media_info, torrent_file) -> _DownloadContentInfo:
        """
        解析下载内容: 从种子文件或URL中提取 torrent 内容和元信息
        """

        if torrent_file:
            log.debug("【Downloader】解析种子文件 %s ", torrent_file)
            read_result = TorrentUtils().read_torrent_content(torrent_file)
            return _DownloadContentInfo(
                url=os.path.basename(torrent_file),
                torrent_file=torrent_file,
                content=read_result.content,
                dl_files_folder=read_result.files_folder,
                dl_files=read_result.files,
                retmsg=read_result.ret_msg,
            )

        if not media_info.enclosure:
            return _DownloadContentInfo(retmsg="下载链接为空")

        url = media_info.enclosure
        if url.startswith("magnet:"):
            log.debug("【Downloader】磁力链不解析: %s ", url)
            return _DownloadContentInfo(url=url, content=url)

        # 下载种子文件, 解析
        page_url = media_info.page_url

        _xpath = ''
        _hash = ''
        if url.startswith("["):
            _xpath = url[1:-1]
            url = page_url
            log.debug("【Downloader】详情页面解析磁力链: %s ", url)
        elif url.startswith("#"):
            _xpath = url[1:-1]
            _hash = True
            url = page_url
            log.debug("【Downloader】从详情页面解析磁力Hash: %s ", url)

        if _xpath:
            # 从详情页面XPATH解析下载链接
            content = self.sites.parse_site_download_url(page_url=url, xpath=_xpath)
            if not content:
                return _DownloadContentInfo(
                    url=url,
                    retmsg="无法从详情页面: %s 解析出下载链接" % url,
                )

            # 解析出磁力链, 补充Trackers
            if content.startswith("magnet:"):
                content = content
            # 解析出来的是HASH值, 转换为磁力链
            elif _hash:
                content = TorrentUtils.convert_hash_to_magnet(hash_text=content, title=media_info.org_string)
                if not content:
                    return _DownloadContentInfo(
                        url=url,
                        retmsg="%s 转换磁力链失败" % content,
                    )
        else:
            site_info = self.sites.get_site(siteurl=url)
            # 下载种子文件, 并读取信息
            dl_result = self._download_torrent_from_site(url, page_url, site_info)
            return _DownloadContentInfo(
                url=url,
                torrent_file=dl_result.file_path,
                content=dl_result.content,
                dl_files_folder=dl_result.files_folder,
                dl_files=dl_result.files,
                retmsg=dl_result.ret_msg,
                site_info=site_info,
            )

        # xpath 解析成功, 只返回 url 和 content, 无 torrent 文件信息
        return _DownloadContentInfo(
            url=url,
            content=content,
        )

    def _resolve_download_client(self, download_setting, downloader_id, media_info):
        """
        解析下载客户端: 获取下载设置、下载器配置和客户端实例
        :param download_setting: 下载设置id
        :param downloader_id: 下载器id(可选)
        :param media_info: 媒体信息
        :return: (download_attr, downloader_conf, downloader_client, download_setting_name, downloader_id)
                 失败时 downloader_client 为 None
        """
        # 下载设置
        if not download_setting and media_info.site:
            download_setting = self.sites.get_site_download_setting(media_info.site)

        download_attr = self.get_download_attr(download_setting)

        # 下载器实例
        if not downloader_id:
            downloader_id = download_attr.get("downloader")

        downloader_conf = self.get_downloader_conf(downloader_id)
        downloader_client = self.__get_client(downloader_id)

        download_setting_name = download_attr.get('name')

        return download_attr, downloader_conf, downloader_client, download_setting_name, downloader_id

    def _calc_save_path(self, download_dir, dl_files_folder, dl_files):
        save_dir = subtitle_dir = None
        visit_dir = self.get_download_visit_dir(download_dir)
        if visit_dir:
            if dl_files_folder:
                # 种子文件带目录
                save_dir = os.path.join(visit_dir, dl_files_folder)
                subtitle_dir = save_dir
            elif dl_files:
                        # 种子文件为单独文件
                save_dir = os.path.join(visit_dir, dl_files[0])
                subtitle_dir = visit_dir
            else:
                save_dir = None
                subtitle_dir = visit_dir
        return subtitle_dir,save_dir

    def get_download_attr(self, download_setting):
        """获取下载设置属性（带回退逻辑）"""
        return self._config.get_download_attr(download_setting)

    def add_torrent(self,
                    media_info,
                    torrent_file,
                    content,
                    downloader_client,
                    downloader_conf,
                    download_dir,
                    is_paused,
                    upload_limit,
                    download_limit,
                    category,
                    tag,
                    download_attr,
                    site_info: Optional[UserSiteConf]):

        # 站点 cookie
        site_cookie = site_info.cookie if site_info else None
        # 上传/下载限速
        if not upload_limit:
            upload_limit = download_attr.get("upload_limit")
        if not download_limit:
            download_limit = download_attr.get("download_limit")
        # 分享率/做种时间
        ratio_limit = download_attr.get("ratio_limit")
        seeding_time_limit = download_attr.get("seeding_time_limit")
        # 合并TAG
        tags = self.merge_download_tags(tag, download_attr)

        downloader_type = downloader_client.get_type()

        # 按下载器类型分发
        if downloader_type == DownloaderType.TR:
            return self._add_torrent_tr(downloader_client, content, tags, is_paused,
                                        download_dir, site_cookie, upload_limit,
                                        download_limit, ratio_limit, seeding_time_limit)
        if downloader_type == DownloaderType.QB:
            return self._add_torrent_qb(downloader_client, downloader_conf, content, tags,
                                        is_paused, download_dir, category, site_cookie,
                                        upload_limit, download_limit, ratio_limit, seeding_time_limit)
        if downloader_type == DownloaderType.ARIA2:
            return self._add_torrent_aria2(downloader_client, content, torrent_file, tags,
                                            is_paused, download_dir, category)
        if downloader_type == DownloaderType.Gopeed:
            return self._add_torrent_gopeed(downloader_client, downloader_conf, media_info,
                                            torrent_file, content, download_dir)
        # 其它下载器默认处理
        return downloader_client.add_torrent(content,
                                            is_paused=is_paused,
                                            tag=tags,
                                            download_dir=download_dir,
                                            category=category)

    # ---- 各下载器类型的 add_torrent 私有实现 ----

    @staticmethod
    def _add_torrent_tr(client, content, tags, is_paused, download_dir,
                        site_cookie, upload_limit, download_limit,
                        ratio_limit, seeding_time_limit):
        """Transmission 添加下载"""
        ret = client.add_torrent(content, tag=tags, is_paused=is_paused,
                                 download_dir=download_dir, cookie=site_cookie)
        if ret:
            task_id = ret.hashString
            client.change_torrent(tid=task_id, tag=tags,
                                  upload_limit=upload_limit,
                                  download_limit=download_limit,
                                  ratio_limit=ratio_limit,
                                  seeding_time_limit=seeding_time_limit)
            return task_id
        return None

    @staticmethod
    def _add_torrent_qb(client, conf, content, tags, is_paused, download_dir,
                        category, site_cookie, upload_limit, download_limit,
                        ratio_limit, seeding_time_limit):
        """qBittorrent 添加下载"""
        ret, task_id = client.add_torrent(content,
                                          is_paused=is_paused,
                                          download_dir=download_dir,
                                          tag=tags,
                                          category=category,
                                          content_layout="Original",
                                          upload_limit=upload_limit,
                                          download_limit=download_limit,
                                          ratio_limit=ratio_limit,
                                          seeding_time_limit=seeding_time_limit,
                                          cookie=site_cookie)
        if ret:
            log.info(f"【Downloader】{conf.name} 已添加下载 {task_id}, 保存路径: {download_dir}")
        return task_id

    @staticmethod
    def _add_torrent_aria2(client, content, torrent_file, tags, is_paused,
                           download_dir, category):
        """Aria2 添加下载"""
        if content and (isinstance(content, bytes) or isinstance(content, str)):
            return client.add_torrent(content, is_paused=is_paused, tag=tags,
                                      download_dir=download_dir, category=category)
        elif torrent_file:
            return client.add_torrent(torrent_file, is_paused=is_paused, tag=tags,
                                      download_dir=download_dir, category=category)
        return None

    def _add_torrent_gopeed(self, client, conf, media_info, torrent_file,
                            content, download_dir):
        """Gopeed 添加下载"""
        # 构建标题
        if media_info.cn_name:
            title = media_info.cn_name
        elif media_info.en_name:
            title = media_info.en_name
        elif media_info.title:
            title = media_info.title
        else:
            title = ""
        se_info = media_info.get_season_string() + media_info.get_episode_string()
        title += se_info

        if torrent_file:
            mv_file = self.move_torrent_file_to_downloader_dir(torrent_file, conf)
            if mv_file == torrent_file:
                content = TorrentUtils.torrent_to_magnet(torrent_file)
                return client.add_torrent(content, name=title, download_dir=download_dir, tag=PT_TAG)
            else:
                task_name = os.path.basename(mv_file).strip('.torrent')
                if not task_name:
                    task_name = title
                elif title not in task_name:
                    task_name = title + task_name
                task_name += se_info
                log.info(f"【Downloader】下载器 {conf.name} 发起种子文件下载: %s" % (torrent_file))
                return client.add_torrent(mv_file, name=task_name, download_dir=download_dir, tag=PT_TAG)
        else:
            return client.add_torrent(content, name=title, download_dir=download_dir, tag=PT_TAG)

    def _download_torrent_from_site(self, url: str, page_url: str, site_info: Optional[UserSiteConf]):
        """从网站下载并解析种子信息（委托给 TorrentDownloader）"""
        return self._torrent_downloader.download_torrent_from_site(url, page_url, site_info)

    def merge_download_tags(self, tag, download_attr):
        tags = download_attr.get("tags")
        if tags:
            tags = str(tags).split(";")
            if tag:
                if isinstance(tag, list):
                    tags.extend(tag)
                else:
                    tags.append(tag)
        else:
            if tag:
                if isinstance(tag, list):
                    tags = tag
                else:
                    tags = [tag]
        return tags

    def move_torrent_file_to_downloader_dir(self, torrent_file, downloader_conf):
        """
        把种子文件移动到下载器目录
        :param torrent_file: 种子文件
        :param downloader_conf: 下载器配置
        :return: 移动后的文件路径
        """
        if not torrent_file or not downloader_conf or not downloader_conf.download_dir:
            return torrent_file

        # 把种子文件移动到下载器可访问的目录
        container_path = downloader_conf.download_dir[0].get('container_path')
        save_path = downloader_conf.download_dir[0].get('save_path')
        if container_path and save_path:
            file_name = os.path.basename(torrent_file)
            dst = os.path.join(container_path, file_name)
            if os.path.exists(dst):
                 os.remove(dst)
            shutil.move(torrent_file, container_path)
            torrent_file = os.path.join(save_path, file_name)
        return torrent_file

    def _log_add_download(self, downloader_name, title, download_dir, torrent_file, content, url, is_paused : bool):

        print_url = os.path.basename(torrent_file) if torrent_file else(content if isinstance(content, str) else url)
        if is_paused:
            log.info(f"【Downloader】下载器 {downloader_name} 添加任务并暂停: %s, 目录: %s, Url: %s" % (
                title, download_dir, print_url))
        else:
            log.info(f"【Downloader】下载器 {downloader_name} 添加任务: %s, 目录: %s, Url: %s" % (
                title, download_dir, print_url))

    def get_torrent_info_with_site(self, url: str, indexer_info: IndexerInfo, page_url: str) -> TorrentDownloadResult:
        """根据下载链接所属的站点信息下载种子（委托给 TorrentDownloader）"""
        return self._torrent_downloader.get_torrent_info_with_site(url, indexer_info, page_url)

    def get_torrent_info(self, url, cookie=None, ua=None, referer=None, proxy=False, render=False) -> TorrentDownloadResult:
        """把种子下载到本地（委托给 TorrentDownloader）"""
        return self._torrent_downloader.get_torrent_info(url, cookie, ua, referer, proxy, render)

    def save_torrent_file(self, url, cookie=None, ua=None, referer=None, proxy=False):
        """把种子下载到本地（委托给 TorrentDownloader）"""
        return self._torrent_downloader.save_torrent_file(url, cookie, ua, referer, proxy)

    def transfer(self, downloader_id=None):
        """转移下载完成的文件（委托给 TransferManager）"""
        self._transfer_manager.transfer(downloader_id)

    def get_torrents(self, downloader_id=None, ids=None, tag=None):
        """
        获取种子信息
        :param downloader_id: 下载器ID
        :param ids: 种子ID
        :param tag: 种子标签
        :return: 种子信息列表
        """
        if not downloader_id:
            downloader_id = self.default_downloader_id
        _client = self.__get_client(downloader_id)
        if not _client:
            return None
        try:
            torrents, error_flag = _client.get_torrents(tag=tag, ids=ids)
            if error_flag:
                return None
            return torrents
        except Exception as err:
            log.exception("【Downloader】下获取种子信息: ")
            return None

    def get_remove_torrents(self, downloader_id=None, config=None):
        """
        查询符合删种策略的种子信息
        :return: 符合删种策略的种子信息列表
        """
        if not config or not downloader_id:
            return []
        _client = self.__get_client(downloader_id)
        if not _client:
            return []
        config["filter_tags"] = []
        if config.get("onlynastool"):
            config["filter_tags"] = config["tags"] + [PT_TAG]
        else:
            config["filter_tags"] = config["tags"]
        torrents = _client.get_remove_torrents(config=config)
        torrents.sort(key=lambda x: x.get("name"))
        return torrents

    def get_downloading_torrents(self, downloader_id=None, ids=None, tag=None):
        """
        查询正在下载中的种子信息
        :return: 下载器名称, 发生错误时返回None
        """
        if not downloader_id:
            downloader_id = self.default_downloader_id
        _client = self.__get_client(downloader_id)
        if not _client:
            return None
        try:
            return _client.get_downloading_torrents(tag=tag, ids=ids)
        except Exception as err:
            log.exception("【Downloader】查询正在下载中的种子信息 异常: ")
            return None

    def get_downloading_progress(self, downloader_id=None, ids=None):
        """
        查询正在下载中的进度信息
        """
        if not downloader_id:
            downloader_id = self.default_downloader_id

        _client = self.__get_client(downloader_id)
        if not _client:
            return []
        
        # 查询配置
        downloader_conf = self.get_downloader_conf(downloader_id)
        if not downloader_conf:
            return []
        # 仅下载指定标签
        only_nastool = downloader_conf.only_nastool
        if only_nastool:
            tag = [PT_TAG]
        else:
            tag = None
        try:
            return _client.get_downloading_progress(tag=tag, ids=ids)
        except:  # noqa: E722
            return []


    def get_completed_torrents(self, downloader_id=None, ids=None, tag=None):
        """
        查询下载完成的种子列表
        :param downloader_id: 下载器ID
        :param ids: 种子ID列表
        :param tag: 种子标签
        :return: 种子信息列表, 发生错误时返回None
        """
        if not downloader_id:
            downloader_id = self.default_downloader_id
        _client = self.__get_client(downloader_id)
        if not _client:
            return None
        return _client.get_completed_torrents(ids=ids, tag=tag)

    def start_torrents(self, downloader_id=None, ids=None):
        """
        下载控制: 开始
        :param downloader_id: 下载器ID
        :param ids: 种子ID列表
        :return: 处理状态
        """
        if not ids:
            return False
        _client = self.__get_client(downloader_id) if downloader_id else self.default_client
        if not _client:
            return False
        return _client.start_torrents(ids)

    def stop_torrents(self, downloader_id=None, ids=None):
        """
        下载控制: 停止
        :param downloader_id: 下载器ID
        :param ids: 种子ID列表
        :return: 处理状态
        """
        if not ids:
            return False
        _client = self.__get_client(downloader_id) if downloader_id else self.default_client
        if not _client:
            return False
        return _client.stop_torrents(ids)

    def delete_torrents(self, downloader_id=None, ids=None, delete_file=False):
        """
        删除种子
        :param downloader_id: 下载器ID
        :param ids: 种子ID列表
        :param delete_file: 是否删除文件
        :return: 处理状态
        """
        if not ids:
            return False
        _client = self.__get_client(downloader_id) if downloader_id else self.default_client
        if not _client:
            return False
        return _client.delete_torrents(delete_file=delete_file, ids=ids)

    def batch_download(self,
                       in_from: SearchType,
                       media_list: list,
                       need_tvs: dict = None,
                       user_name=None):
        """根据命中的种子媒体信息批量添加下载（委托给 BatchDownloader）"""
        return self._batch_downloader.execute(in_from, media_list, need_tvs, user_name)

    def check_exists_medias(self, meta_info, no_exists=None, total_ep=None):
        """检查媒体库是否存在（委托给 MediaExistenceChecker）"""
        return self._media_checker.check(meta_info, no_exists, total_ep)

    def get_files(self, tid, downloader_id=None):
        """
        获取种子文件列表
        """
        # 客户端
        _client = self.__get_client(downloader_id) if downloader_id else self.default_client
        if not _client:
            return []
        # 种子文件
        torrent_files = _client.get_files(tid)
        if not torrent_files:
            return []

        ret_files = []
        if _client.get_type() == DownloaderType.TR:
            for file_id, torrent_file in enumerate(torrent_files):
                ret_files.append({
                    "id": file_id,
                    "name": torrent_file.name
                })
        elif _client.get_type() == DownloaderType.QB:
            for torrent_file in torrent_files:
                ret_files.append({
                    "id": torrent_file.get("index"),
                    "name": torrent_file.get("name")
                })

        return ret_files

    def set_files_status(self, tid, need_episodes, downloader_id=None):
        """
        设置文件下载状态, 选中需要下载的季集对应的文件下载, 其余不下载
        :param tid: 种子的hash或id
        :param need_episodes: 需要下载的文件的集信息
        :param downloader_id: 下载器ID
        :return: 返回选中的集的列表
        """
        sucess_epidised = []

        # 客户端
        if not downloader_id:
            downloader_id = self.default_downloader_id
        _client = self.__get_client(downloader_id)
        downloader_conf = self.get_downloader_conf(downloader_id)
        if not _client:
            return []
        # 种子文件
        torrent_files = self.get_files(tid=tid, downloader_id=downloader_id)
        if not torrent_files:
            return []
        
        if downloader_conf.type == "transmission":
            # 找出不需要下载的文件
            files_unwanted = []
            for torrent_file in torrent_files:
                file_id = torrent_file.get("id")
                file_name = torrent_file.get("name")
                meta_info = MetaInfo(file_name)
                if not meta_info.get_episode_list():
                    files_unwanted.append(file_id)
                else:
                    selected = set(meta_info.get_episode_list()).issubset(set(need_episodes))
                    if not selected:
                        files_unwanted.append(file_id)
                    else:
                        sucess_epidised = list(set(sucess_epidised).union(set(meta_info.get_episode_list())))
            if files_unwanted:
                _client.set_files(tid, files_unwanted)
        elif downloader_conf.type == "qbittorrent":
            file_ids = []
            for torrent_file in torrent_files:
                file_id = torrent_file.get("id")
                file_name = torrent_file.get("name")
                meta_info = MetaInfo(file_name)
                if not meta_info.get_episode_list() or not set(meta_info.get_episode_list()).issubset(
                        set(need_episodes)):
                    file_ids.append(file_id)
                else:
                    sucess_epidised = list(set(sucess_epidised).union(set(meta_info.get_episode_list())))
            if sucess_epidised and file_ids:
                _client.set_files(torrent_hash=tid, file_ids=file_ids, priority=0)
        return sucess_epidised

    def get_download_dirs(self, setting=None):
        """返回下载器中设置的保存目录"""
        return self._config.get_download_dirs(setting)

    def get_download_visit_dirs(self):
        """返回所有下载器中设置的访问目录"""
        return self._config.get_download_visit_dirs()

    def get_download_visit_dir(self, download_dir, downloader_id=None):
        """返回下载器中设置的访问目录"""
        if not downloader_id:
            downloader_id = self.default_downloader_id
        downloader_conf = self.get_downloader_conf(downloader_id)
        _client = self.__get_client(downloader_id)
        if not _client:
            return ""
        true_path, _ = _client.get_replace_path(download_dir, downloader_conf.download_dir)
        return true_path

    @staticmethod
    def __get_download_dir_info(media, downloaddir):
        """根据媒体信息读取一个下载目录的信息"""
        return DownloadConfig.get_download_dir_info(media, downloaddir)

    @staticmethod
    def __get_client_type(type_name):
        """根据名称返回下载器类型"""
        return DownloadConfig.get_client_type(type_name)

    def get_torrent_episodes(self, url, page_url=None):
        """
        解析种子文件, 获取集数
        :return: 集数列表、种子路径
        """
        site_info = self.sites.get_site(siteurl=url)
        if not site_info:
            log.warn(f"【Downloader】根据url获取站点数据失败:{url}")
            return [], None
        
        # 保存种子文件
        result = self.get_torrent_info(
            url=url,
            cookie=site_info.cookie,
            ua=site_info.ua,
            # referer=page_url if site_info.referer else None,
            proxy=site_info.proxy
        )
        file_path = result.file_path
        files = result.files
        retmsg = result.ret_msg
        if not files:
            log.error(f"【Downloader】读取种子文件集数出错: {retmsg}")
            return [], None
        episodes = []
        for file in files:
            if os.path.splitext(file)[-1] not in Constants.RMT_MEDIAEXT:
                continue
            meta = MetaInfo(file)
            if not meta.begin_episode:
                continue
            episodes = list(set(episodes).union(set(meta.get_episode_list())))
        return episodes, file_path

    def get_download_setting(self, sid=None):
        """获取下载设置"""
        return self._config.get_download_setting(sid)

    def set_speed_limit(self, downloader_id=None, download_limit=None, upload_limit=None):
        """
        设置速度限制
        :param downloader_id: 下载器ID
        :param download_limit: 下载速度限制, 单位KB/s
        :param upload_limit: 上传速度限制, 单位kB/s
        """
        if not downloader_id:
            return
        _client = self.__get_client(downloader_id)
        if not _client:
            return
        try:
            download_limit = int(download_limit) if download_limit else 0
        except Exception as err:
            log.exception("【Downloader】获取下载速度设置 异常: ")
            download_limit = 0
        try:
            upload_limit = int(upload_limit) if upload_limit else 0
        except Exception as err:
            log.exception("【Downloader】获取上传速度设置 异常: ")
            upload_limit = 0
        _client.set_speed_limit(download_limit=download_limit, upload_limit=upload_limit)

    def get_downloader_conf(self, did=None):
        """获取下载器配置"""
        return self._config.get_downloader_conf(did)

    def get_downloader_conf_simple(self):
        """获取简化下载器配置"""
        return self._config.get_downloader_conf_simple()

    def get_downloader(self, downloader_id=None):
        """
        获取下载器实例
        """
        if not downloader_id:
            return self.default_client
        return self.__get_client(downloader_id)

    def get_status(self, dtype=None, config=None):
        """
        测试下载器状态
        """
        if not config or not dtype:
            return False
        # 测试状态
        state = self.__build_class(ctype=dtype, conf=config).get_status()
        if not state:
            log.error("【Downloader】下载器连接测试失败")
        return state

    def recheck_torrents(self, downloader_id=None, ids=None):
        """
        下载控制: 重新校验种子
        :param downloader_id: 下载器ID
        :param ids: 种子ID列表
        :return: 处理状态
        """
        if not ids:
            return False
        _client = self.__get_client(downloader_id) if downloader_id else self.default_client
        if not _client:
            return False
        return _client.recheck_torrents(ids)

    def stop_service(self):
        """停止服务（委托给 TransferManager）"""
        self._transfer_manager.stop_service()

    def get_download_history(self, date=None, hid=None, num=30, page=1):
        """
        获取下载历史记录
        """
        return self.dbhelper.get_download_history(date=date, hid=hid, num=num, page=page)

    def get_download_history_by_title(self, title):
        """
        根据标题查询下载历史记录
        :return:
        """
        return self.dbhelper.get_download_history_by_title(title=title) or []

    def get_download_history_by_downloader(self, downloader, download_id):
        """
        根据下载器和下载ID查询下载历史记录
        :return:
        """
        return self.dbhelper.get_download_history_by_downloader(downloader=downloader,
                                                                download_id=download_id)

    def update_downloader(self,
                          did,
                          name,
                          enabled,
                          dtype,
                          transfer,
                          only_nastool,
                          match_path,
                          rmt_mode,
                          config,
                          download_dir):
        """
        更新下载器
        """
        ret = self.dbhelper.update_downloader(
            did=did,
            name=name,
            enabled=enabled,
            dtype=dtype,
            transfer=transfer,
            only_nastool=only_nastool,
            match_path=match_path,
            rmt_mode=rmt_mode,
            config=config,
            download_dir=download_dir
        )
        self.init_config()
        return ret

    def delete_downloader(self, did):
        """
        删除下载器
        """
        ret = self.dbhelper.delete_downloader(did=did)
        self.init_config()
        return ret

    def check_downloader(self, did=None, transfer=None, only_nastool=None, enabled=None, match_path=None):
        """
        检查下载器
        """
        ret = self.dbhelper.check_downloader(did=did,
                                             transfer=transfer,
                                             only_nastool=only_nastool,
                                             enabled=enabled,
                                             match_path=match_path)
        self.init_config()
        return ret

    def delete_download_setting(self, sid):
        """
        删除下载设置
        """
        ret = self.dbhelper.delete_download_setting(sid=sid)
        self.init_config()
        return ret

    def update_download_setting(self,
                                sid,
                                name,
                                category,
                                tags,
                                is_paused,
                                upload_limit,
                                download_limit,
                                ratio_limit,
                                seeding_time_limit,
                                downloader):
        """
        更新下载设置
        """
        ret = self.dbhelper.update_download_setting(
            sid=sid,
            name=name,
            category=category,
            tags=tags,
            is_paused=is_paused,
            upload_limit=upload_limit,
            download_limit=download_limit,
            ratio_limit=ratio_limit,
            seeding_time_limit=seeding_time_limit,
            downloader=downloader
        )
        self.init_config()
        return ret
