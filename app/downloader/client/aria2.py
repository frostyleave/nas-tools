import asyncio
import base64
import os
import re
from urllib.parse import urlparse, urlunparse

import log
from app.downloader.client._base import _IDownloadClient
from app.downloader.client._pyaria2 import PyAria2
from app.utils import AsyncRequestUtils, RequestUtils, StringUtils
from app.utils.types import DownloaderType


class Aria2(_IDownloadClient):
    schema = "aria2"
    # 下载器ID
    client_id = "aria2"
    client_type = DownloaderType.ARIA2
    client_name = DownloaderType.ARIA2.value
    _client = None
    host = None
    port = None
    secret = None
    name = "aria2"

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
                self._client = PyAria2(secret=self.secret, host=self.host, port=self.port)

    @classmethod
    def match(cls, ctype):
        return ctype in [cls.client_id, cls.client_type, cls.client_name]

    def connect(self):
        pass

    def get_status(self):
        if not self._client:
            return False
        try:
            return bool(self._client.getVersion())
        except Exception:
            log.exception("【%s】%s 获取状态出错：", self.client_name, self.name)
            return False

    def get_torrents(self, ids=None, status=None, **kwargs):
        """
        获取种子列表
        :return: 种子列表, 是否发生错误
        """
        if not self._client:
            return [], True
        try:
            ret_torrents = []
            if ids:
                gids = ids if isinstance(ids, list) else [ids]
                for gid in gids:
                    result = self._client.tellStatus(gid=gid)
                    if result:
                        ret_torrents.append(result)
            elif status == "downloading":
                ret_torrents = (self._client.tellActive() or []) \
                    + (self._client.tellWaiting(offset=-1, num=100) or [])
            else:
                ret_torrents = self._client.tellStopped(offset=-1, num=1000) or []
            return ret_torrents, False
        except Exception:
            log.exception("【%s】%s 获取种子列表出错：", self.client_name, self.name)
            return [], True

    def get_downloading_torrents(self, ids=None, tag=None, **kwargs):
        torrents, error = self.get_torrents(ids=ids, status="downloading")
        return None if error else torrents

    def get_completed_torrents(self, ids=None, tag=None, **kwargs):
        torrents, error = self.get_torrents(ids=ids, status="completed")
        if error:
            return None
        return [torrent for torrent in torrents if torrent.get("status") == "complete"]

    def _async_rpc_headers(self):
        """
        构造 JSON-RPC 请求头
        """
        secret = "token:%s" % (self.secret or "")
        token = base64.b64encode(f"{secret}:".encode()).decode()
        return {
            "Content-Type": "application/json",
            "Authorization": f"Basic {token}"
        }

    def _async_rpc_url(self):
        """
        拼接 JSON-RPC 地址，port 未包含在 host 中时补上
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
        return urlunparse((parsed.scheme, netloc, parsed.path, "", "", "")) + "/jsonrpc"

    async def _async_rpc(self, method, params=None):
        """
        异步调用 JSON-RPC
        """
        url = self._async_rpc_url()
        if not url:
            return None
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": ["token:%s" % (self.secret or "")] + list(params or [])
        }
        try:
            res = await AsyncRequestUtils(headers=self._async_rpc_headers()).request(
                "post", url, json=payload)
            if res is None or res.status_code != 200:
                return None
            data = res.json()
            if "error" in data:
                return None
            return data.get("result")
        except Exception:
            log.exception("【%s】%s 异步RPC调用出错：", self.client_name, self.name)
            return None

    async def get_torrents_async(self, ids=None, status=None, tag=None):
        """
        异步获取种子列表
        :return: 种子列表, 是否发生错误
        """
        if ids:
            gids = ids if isinstance(ids, list) else [ids]
            results = await asyncio.gather(
                *[self._async_rpc("aria2.tellStatus", [gid]) for gid in gids])
            return [item for item in results if item], False
        if status == "downloading":
            active, waiting = await asyncio.gather(
                self._async_rpc("aria2.tellActive"),
                self._async_rpc("aria2.tellWaiting", [-1, 100]))
            return (active or []) + (waiting or []), False
        return await self._async_rpc("aria2.tellStopped", [-1, 1000]) or [], False

    def set_torrents_status(self, ids, **kwargs):
        return self.delete_torrents(ids=ids, delete_file=False)

    def get_transfer_task(self, tag=None, match_path=False):
        if not self._client:
            return []
        torrents = self.get_completed_torrents() or []
        trans_tasks = []
        for torrent in torrents:
            name = torrent.get('bittorrent', {}).get('info', {}).get("name")
            if not name:
                continue
            path = torrent.get("dir")
            if not path:
                continue
            true_path, replace_flag = self.get_replace_path(path, self.download_dir)
            # 开启目录隔离，未进行目录替换的不处理
            if match_path and not replace_flag:
                log.debug(f"【{self.client_name}】{self.name} 开启目录隔离，但 {torrent.get('name')} 未匹配下载目录范围")
                continue
            trans_tasks.append({'path': os.path.join(true_path, name).replace("\\", "/"), 'id': torrent.get("gid")})
        return trans_tasks

    def get_remove_torrents(self, **kwargs):
        return []

    def add_torrent(self, content, download_dir=None, **kwargs):
        if not self._client:
            return None
        options = {"dir": download_dir} if download_dir else {}
        if isinstance(content, str):
            # 种子文件路径：按二进制读取，避免文本模式改写字节破坏种子
            if content.endswith('.torrent'):
                with open(content, 'rb') as file:
                    file_content = file.read()
                torrent_bin = base64.b64encode(file_content).decode('ascii')
                return self._client.addTorrentFile(torrent=torrent_bin, options=options)
            # 处理重定向
            if re.match("^https*://", content):
                try:
                    p = RequestUtils().get_res(url=content, allow_redirects=False)
                    if p and p.headers.get("Location"):
                        content = p.headers.get("Location")
                except Exception as ex:
                    log.exception("【%s】%s 处理重定向出错：", self.client_name, self.name)
            # 直接添加url
            return self._client.addUri(uris=[content], options=options)
        elif isinstance(content, bytes):
            # aria2 的 addTorrent 需要 base64 后的种子内容
            torrent_bin = base64.b64encode(content).decode('ascii')
            return self._client.addTorrentFile(torrent=torrent_bin, options=options)
        log.warn(f"【{self.client_name}】{self.name} 无法识别的下载内容类型: {type(content)!r}")
        return None

    def start_torrents(self, ids):
        if not self._client:
            return False
        return self._run_torrent_action("unpause", ids)

    def stop_torrents(self, ids):
        if not self._client:
            return False
        return self._run_torrent_action("pause", ids)

    def delete_torrents(self, delete_file, ids):
        if not self._client:
            return False
        return self._run_torrent_action("remove", ids)

    def _run_torrent_action(self, action, ids):
        """
        aria2 的 pause/unpause/remove 只接受单个 GID，需要逐个调用
        """
        gids = ids if isinstance(ids, list) else [ids]
        try:
            for gid in gids:
                getattr(self._client, action)(gid=gid)
            return True
        except Exception:
            log.exception("【%s】%s 执行 %s 出错：", self.client_name, self.name, action)
            return False

    def get_download_dirs(self):
        return []

    def change_torrent(self, **kwargs):
        pass

    def get_downloading_progress(self, **kwargs):
        """
        获取正在下载的种子进度
        """
        return self.__format_progress(self.get_downloading_torrents() or [])

    async def get_downloading_progress_async(self, tag=None, ids=None):
        """
        异步获取正在下载的种子进度
        """
        torrents, _ = await self.get_torrents_async(status="downloading")
        return self.__format_progress(torrents or [])

    def __format_progress(self, Torrents):
        """
        格式化下载进度
        """
        DispTorrents = []
        for torrent in Torrents:
            # 进度
            try:
                downloaded = int(torrent.get('completedLength') or 0)
                total_size = int(torrent.get("totalLength") or 0)
                progress = round(downloaded / total_size * 100, 1) if total_size else 0.0
            except (TypeError, ValueError):
                downloaded = total_size = 0
                progress = 0.0
            if torrent.get('status') in ['paused']:
                state = "Stoped"
                speed = "已暂停"
                _dlspeed = '0'
                _upspeed = '0'
            else:
                state = "Downloading"
                _dlspeed = StringUtils.str_filesize(torrent.get('downloadSpeed'))
                _upspeed = StringUtils.str_filesize(torrent.get('uploadSpeed'))
                speed = (f"{chr(8595)}{_dlspeed}B/s {chr(8593)}{_upspeed}B/s").replace('BB', 'B')

            DispTorrents.append({
                'id': torrent.get('gid'),
                'name': torrent.get('bittorrent', {}).get('info', {}).get("name"),
                'speed': speed,
                'dlspeed': _dlspeed,
                'upspeed': _upspeed,
                'state': state,
                'progress': progress,
                 "sizeprogress": (f"{StringUtils.str_filesize(downloaded)}B / {StringUtils.str_filesize(total_size)}B").replace('BB', 'B')
            })

        return DispTorrents

    def set_speed_limit(self, download_limit=None, upload_limit=None):
        """
        设置速度限制
        :param download_limit: 下载速度限制，单位KB/s
        :param upload_limit: 上传速度限制，单位kB/s
        """
        if not self._client:
            return
        download_limit = int(download_limit or 0) * 1024
        upload_limit = int(upload_limit or 0) * 1024
        try:
            speed_opt = self._client.getGlobalOption()

            def _to_int(value):
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return 0

            options = {}
            if _to_int(speed_opt.get('max-overall-upload-limit')) != upload_limit:
                options['max-overall-upload-limit'] = str(upload_limit)
            if _to_int(speed_opt.get('max-overall-download-limit')) != download_limit:
                options['max-overall-download-limit'] = str(download_limit)
            if not options:
                return True
            return self._client.changeGlobalOption(options)
        except Exception as err:
            log.exception("【%s】%s 设置速度限制 出错：", self.client_name, self.name)
            return False

    def get_type(self):
        return self.client_type

    def get_files(self, tid):
        try:
            return self._client.getFiles(gid=tid)
        except Exception as err:
            log.exception("【%s】%s 获取种子文件 出错：", self.client_name, self.name)
            return None

    def recheck_torrents(self, ids):
        pass

    def set_torrents_tag(self, ids, tags):
        pass
