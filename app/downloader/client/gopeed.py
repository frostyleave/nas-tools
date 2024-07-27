import os
import log

from app.utils import StringUtils
from app.utils.types import DownloaderType
from app.downloader.client._base import _IDownloadClient
from app.downloader.client._pygopeed import PyGopeed


class Gopeed(_IDownloadClient):
    schema = "gopeed"
    # 下载器ID
    client_id = "gopeed"
    client_type = DownloaderType.Gopeed
    client_name = DownloaderType.Gopeed.value
    _client_config = {}

    _client = None
    host = None
    port = None
    secret = None
    download_dir = []
    name = "gopeed"

    magnet_prefix = 'magnet:?xt=urn:btih:'
    magnet_prefix_len = 20
    magnet_hash_split = '&dn='

    def __init__(self, config=None):
        if config:
            self._client_config = config
        self.init_config()
        self.connect()

    def init_config(self):
        if self._client_config:
            self.host = self._client_config.get("host")
            if self.host:
                if not self.host.startswith('http'):
                    self.host = "http://" + self.host
                if self.host.endswith('/'):
                    self.host = self.host[:-1]
            self.port = self._client_config.get("port")
            self.secret = self._client_config.get("secret")
            self.download_dir = self._client_config.get('download_dir') or []
            self.name = self._client_config.get('name') or ""
            if self.host and self.port:
                self._client = PyGopeed(secret=self.secret, host=self.host, port=self.port)

    @classmethod
    def match(cls, ctype):
        return True if ctype in [cls.client_id, cls.client_type, cls.client_name] else False

    def get_status(self):
        if not self._client:
            return False
        ready_data = self._client.getAllTask('ready')
        return True if ready_data is not None else False

    def get_torrents(self, ids=None, status=None, tag=None):
        if not self._client:
            return []
        ret_torrents = self._client.getAllTask(status)
        if ret_torrents and tag:
            tag_ret = []
            for torrent_item in ret_torrents:
                file_tag = self.get_tag_in_torrent_label(torrent_item)
                if file_tag and file_tag in tag:
                    tag_ret.append(torrent_item)
            return tag_ret

        return ret_torrents
    
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

    def get_downloading_torrents(self, tag=None):
        return self.get_torrents(status=["running","pause","wait","ready"], tag=tag)

    def get_completed_torrents(self, tag=None):
        return self.get_torrents(status="done", tag=tag)

    def get_transfer_task(self, tag=None, match_path=False):
        if not self._client:
            return []
        torrents = self.get_completed_torrents(tag)
        trans_tasks = []
        for torrent in torrents:
            res_meta = torrent.get('meta')
            opts_info = res_meta.get('opts')
            if not opts_info:
                log.warn(f"【{self.client_name}】id={self.id} 文件信息解析失败")
                continue
            name = opts_info.get("name")
            if not name:
                log.warn(f"【{self.client_name}】id={self.id} 文件信息解析失败：无法获取文件名称")
                continue
            path = opts_info.get("path")
            if not path:
                log.warn(f"【{self.client_name}】id={self.id} 文件信息解析失败：无法获取文件下载路径")
                continue
            true_path, replace_flag = self.get_replace_path(path.replace("\\", "/"), self.download_dir)
            # 开启目录隔离，未进行目录替换的不处理
            if match_path and not replace_flag:
                log.debug(f"【{self.client_name}】{self.name} 开启目录隔离，但 {name} 未匹配下载目录范围")
                continue
            trans_tasks.append({'path': os.path.join(true_path, name).replace("\\", "/"), 'id': torrent.get("id")})
        return trans_tasks

    def add_torrent(self, content, name=name, download_dir=None, **kwargs):
        if not self._client:
            return None
        if isinstance(content, str):         
            save_name = self.join_name_with_hash(name, content)
            return self._client.addTask(url=content, name=save_name, path=download_dir, **kwargs)
        else:
            return "无法提交下载任务"
    
    def join_name_with_hash(self, name, input_link):
        if not input_link or not input_link.startswith(self.magnet_prefix):
            return name

        s_index = input_link.find(self.magnet_hash_split)
        if s_index < 0:
            return '{0}-{1}'.format(name, input_link[self.magnet_prefix_len:])
        
        return '{0}-{1}'.format(name, input_link[self.magnet_prefix_len:s_index])


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
        Torrents = self.get_downloading_torrents(tag)
        DispTorrents = []
        for torrent in Torrents:
            # 进度
            progress_info = torrent.get('progress')
            try:
                progress = round(int(progress_info.get('downloaded')) / int(progress_info.get("used")), 1) * 100
            except ZeroDivisionError:
                progress = 0.0
            if torrent.get('status') in ['pause']:
                state = "Stoped"
                speed = "已暂停"
            else:
                state = "Downloading"
                _dlspeed = StringUtils.str_filesize(progress_info.get('speed'))
                speed = "%s%sB/s %s%sB/s" % (chr(8595), _dlspeed, chr(8593), '')

            name = ''
            res_meta = torrent.get('meta')
            if res_meta:
                res_info = res_meta.get('res')
                if res_info:
                    name = res_info.get("name")
                if not name:
                    opts_info = res_meta.get('opts')
                    if opts_info:
                        name = opts_info.get("name")
            
            if not name:
                continue

            DispTorrents.append({
                'id': torrent.get('id'),
                'name': name,
                'speed': speed,
                'state': state,
                'progress': progress
            })

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
