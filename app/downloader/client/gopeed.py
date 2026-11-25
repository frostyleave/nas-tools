import os
from urllib.parse import urlparse, urlunparse

import log
from app.downloader.client._base import _IDownloadClient
from app.downloader.client._pygopeed import PyGopeed
from app.utils import AsyncRequestUtils, StringUtils
from app.utils.types import DownloaderType


class Gopeed(_IDownloadClient):
    schema = "gopeed"
    # 下载器ID
    client_id = "gopeed"
    client_type = DownloaderType.Gopeed
    client_name = DownloaderType.Gopeed.value
    _client = None
    host = None
    port = None
    secret = None
    name = "gopeed"

    magnet_prefix = 'magnet:?xt=urn:btih:'
    magnet_prefix_len = 20
    magnet_hash_dn = '&dn='
    magnet_hash_tr = '&tr='

    def __init__(self, config=None):
        self._client_config = config or {}
        self.download_dir = []
        self.init_config()
        self.connect()

    def init_config(self):
        if self._client_config:
            self.host = self._client_config.get("host")
            if self.host:
                if not self.host.startswith('http'):
                    self.host = "http://" + self.host
                self.host = self.host.removesuffix('/')
            self.port = self._client_config.get("port")
            self.secret = self._client_config.get("secret")
            self.download_dir = self._client_config.get('download_dir') or []
            self.name = self._client_config.get('name') or ""
            if self.host and self.port:
                self._client = PyGopeed(secret=self.secret, host=self.host, port=self.port)

    @classmethod
    def match(cls, ctype):
        return ctype in [cls.client_id, cls.client_type, cls.client_name]

    def get_status(self):
        if not self._client:
            return False
        try:
            return self._client.getAllTask('ready') is not None
        except Exception:
            log.exception(f"【{self.client_name}】{self.name} 获取状态出错：")
            return False

    def get_torrents(self, ids=None, status=None, tag=None):
        """
        获取种子列表
        :return: 种子列表, 是否发生错误
        """
        if not self._client:
            return [], True
        try:
            ret_torrents = self._client.getAllTask(status)
        except Exception:
            log.exception(f"【{self.client_name}】{self.name} 获取种子列表出错：")
            return [], True
        if ids:
            id_set = {str(item) for item in (ids if isinstance(ids, list) else [ids])}
            ret_torrents = [item for item in (ret_torrents or [])
                            if str(item.get("id")) in id_set]
        if ret_torrents and tag:
            tag_list = tag if isinstance(tag, list) else [tag]
            ret_torrents = [item for item in ret_torrents
                            if self.get_tag_in_torrent_label(item) in tag_list]
        return ret_torrents or [], False

    def get_tag_in_torrent_label(self, torrent_item):
        if not torrent_item:
            return None
        res_meta = torrent_item.get('meta')
        if not res_meta:
            return None
        req_info = res_meta.get('req')
        if not req_info:
            return None
        labels = req_info.get('labels')
        if not labels:
            return None
        file_tag = labels.get('tag')
        if file_tag:
            return file_tag
        file_tag = labels.get('TAG')
        if file_tag:
            return file_tag
        return None

    def get_downloading_torrents(self, ids=None, tag=None, **kwargs):
        torrents, error = self.get_torrents(ids=ids,
                                            status=["running", "pause", "wait", "ready"],
                                            tag=tag)
        return None if error else torrents

    def _async_base_url(self):
        """
        拼接 API 基地址，port 未包含在 host 中时补上
        """
        host = (self.host or "").strip().rstrip("/")
        if not host:
            return ""
        if not host.startswith(("http://", "https://")):
            host = "http://" + host
        parsed = urlparse(host)
        netloc = parsed.netloc
        if self.port and not parsed.port:
            netloc = f"{netloc}:{self.port}"
        return urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))

    def _async_tasks_url(self, status=None):
        """
        拼接任务查询地址
        """
        base_url = self._async_base_url()
        if not base_url:
            return ""
        url = f"{base_url}/api/v1/tasks"
        if not status:
            return url
        if isinstance(status, list):
            return url + "?" + "&".join(f"status={item}" for item in status)
        return f"{url}?status={status}"

    def _async_headers(self):
        """
        构造请求头
        """
        headers = {"Content-Type": "application/json"}
        if self.secret:
            headers["x-api-token"] = self.secret
        return headers

    async def get_torrents_async(self, ids=None, status=None, tag=None):
        """
        异步获取种子列表
        :return: 种子列表, 是否发生错误
        """
        if not self.host or not self.port:
            return [], True
        try:
            res = await AsyncRequestUtils(headers=self._async_headers()).get_res(
                self._async_tasks_url(status))
            if res is None or res.status_code != 200:
                return [], True
            data = res.json()
            if data.get("code", -1) != 0:
                return [], True
            ret_torrents = data.get("data") or []
        except Exception:
            log.exception(f"【{self.client_name}】{self.name} 异步获取种子列表出错：")
            return [], True
        if ids:
            id_set = {str(item) for item in (ids if isinstance(ids, list) else [ids])}
            ret_torrents = [item for item in ret_torrents
                            if str(item.get("id")) in id_set]
        if ret_torrents and tag:
            tag_list = tag if isinstance(tag, list) else [tag]
            ret_torrents = [item for item in ret_torrents
                            if self.get_tag_in_torrent_label(item) in tag_list]
        return ret_torrents, False

    def get_completed_torrents(self, ids=None, tag=None, **kwargs):
        torrents, error = self.get_torrents(ids=ids, status="done", tag=tag)
        return None if error else torrents

    def get_transfer_task(self, tag=None, match_path=False):
        if not self._client:
            return []
        torrents = self.get_completed_torrents(tag=tag) or []
        trans_tasks = []
        for torrent in torrents:
            torrent_id = torrent.get("id")
            res_meta = torrent.get('meta')
            if not res_meta:
                log.warn(f"【{self.client_name}】id={torrent_id} 文件信息解析失败")
                continue
            opts_info = res_meta.get('opts')
            if not opts_info:
                log.warn(f"【{self.client_name}】id={torrent_id} 文件信息解析失败")
                continue
            name = opts_info.get("name")
            if not name:
                log.warn(f"【{self.client_name}】id={torrent_id} 文件信息解析失败：无法获取文件名称")
                continue
            path = opts_info.get("path")
            if not path:
                log.warn(f"【{self.client_name}】id={torrent_id} 文件信息解析失败：无法获取文件下载路径")
                continue
            true_path, replace_flag = self.get_replace_path(path.replace("\\", "/"), self.download_dir)
            # 开启目录隔离，未进行目录替换的不处理
            if match_path and not replace_flag:
                log.debug(f"【{self.client_name}】{self.name} 开启目录隔离，但 {name} 未匹配下载目录范围")
                continue

            trans_path = os.path.join(true_path, name).replace("\\", "/")
            if os.path.exists(trans_path):
                trans_tasks.append({'path': trans_path, 'id': torrent.get("id")})
                continue

            # 1.59版本后移除顶级目录, 需要取资源目录
            res_info = res_meta.get('res')
            if res_info:
                name = res_info.get("name")
                if name:
                    trans_path = os.path.join(true_path, name).replace("\\", "/")
                    if os.path.exists(trans_path):
                        trans_tasks.append({'path': trans_path, 'id': torrent.get("id")})
                    continue
                # 单文件
                files = res_info.get("files", [])
                for file_info in files:
                    file_name = file_info.get("name")
                    if file_name:
                        file_path = os.path.join(true_path, file_name).replace("\\", "/")
                        if os.path.exists(file_path):
                            trans_tasks.append({'path': file_path, 'id': torrent.get("id")})
                        continue

        return trans_tasks

    def add_torrent(self, content, name, download_dir=None, **kwargs):
        if not self._client:
            return None
        if isinstance(content, str):
            save_name = self.join_name_with_hash(name, content)
            return self._client.addTask(url=content, name=save_name, path=download_dir, **kwargs)
        log.warn(f"【{self.client_name}】{self.name} 无法识别的下载内容类型: {type(content)!r}")
        return None
    
    def join_name_with_hash(self, name, input_link):

        if not input_link or not input_link.startswith(self.magnet_prefix):
            return name

        left = input_link[self.magnet_prefix_len:]
        dn_index = left.find(self.magnet_hash_dn)
        if dn_index > 0:
            left = left[:dn_index]
        
        tr_index = left.find(self.magnet_hash_tr)
        if tr_index > 0:
            left = left[:tr_index]        
        
        return f'{name}-{left}'


    def start_torrents(self, ids):
        if not self._client:
            return False
        return self._client.continueOne(gid=ids)

    def stop_torrents(self, ids):
        if not self._client:
            return False
        return self._client.pause(gid=ids)

    def delete_torrents(self, delete_file, ids):
        if not self._client:
            return False
        
        if delete_file:
            return self._client.forceRemove(gid=ids)

        return self._client.remove(gid=ids)

    def get_downloading_progress(self, tag=None, **kwargs):
        """
        获取正在下载的种子进度
        """
        return self.__format_progress(self.get_downloading_torrents(tag=tag) or [])

    async def get_downloading_progress_async(self, tag=None, ids=None):
        """
        异步获取正在下载的种子进度
        """
        torrents, _ = await self.get_torrents_async(
            status=["running", "pause", "wait", "ready"], tag=tag)
        return self.__format_progress(torrents or [])

    def __format_progress(self, Torrents):
        """
        格式化下载进度
        """
        DispTorrents = []
        for torrent in Torrents:
            res_info = torrent.get("meta", {}).get("res")
            opts_info = torrent.get("meta", {}).get("opts")

            # 进度
            progress_info = torrent.get("progress")
            if res_info and progress_info:
                name = res_info.get("name")
                if not name and opts_info:
                    name = opts_info.get("name")
                    if not name:
                        continue

                total_size = res_info.get("size", 1)
                downloaded = progress_info.get("downloaded", 0)
                _dlspeed = '0'
                _upspeed = '0'
                try:
                    total_size_value = int(total_size)
                    progress = round(int(downloaded) / total_size_value * 100, 1) if total_size_value else 0.0
                except (TypeError, ValueError):
                    progress = 0.0

                if torrent.get("status") in ["pause"]:
                    state = "Stoped"
                    speed = "已暂停"
                else:
                    state = "Downloading"
                    speed = progress_info.get("speed")
                    if isinstance(speed, str):
                        speed = int(speed)
                    if speed < 0:
                        speed = abs(speed)

                    _dlspeed = StringUtils.str_filesize(speed)
                    _upspeed = StringUtils.str_filesize(
                        progress_info.get("uploadSpeed")
                    )
                    speed = (f"{chr(8595)} {_dlspeed}B/s {chr(8593)} {_upspeed}B/s").replace('BB', 'B')

                DispTorrents.append(
                    {
                        "id": torrent.get("id"),
                        "name": name,
                        "speed": speed,
                        'dlspeed': _dlspeed,
                        'upspeed': _upspeed,
                        "state": state,
                        "progress": progress,
                        "sizeprogress": (f"{StringUtils.str_filesize(downloaded)}B / {StringUtils.str_filesize(total_size)}B").replace('BB', 'B')
                    }
                )

        return DispTorrents

    def get_type(self):
        return self.client_type

    def get_download_dirs(self):
        return []

    def get_remove_torrents(self, **kwargs):
        return []

    def connect(self):
        pass

    def change_torrent(self, **kwargs):
        pass

    def set_speed_limit(self, download_limit=None, upload_limit=None):
        pass
 
    def set_torrents_status(self, ids, **kwargs):
        pass
    
    def get_files(self, tid):
        pass

    def recheck_torrents(self, ids):
        pass

    def set_torrents_tag(self, ids, tags):
        pass
