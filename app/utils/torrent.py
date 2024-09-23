import hashlib
import os.path
import re
import bencodepy
import urllib

from app.utils.media_utils import MediaUtils
from app.utils.types import MediaType


class TorrentUtils:

    @staticmethod
    def convert_hash_to_magnet(hash_text, title):
        """
        根据hash值，转换为磁力链，自动添加tracker
        :param hash_text: 种子Hash值
        :param title: 种子标题
        """
        if not hash_text or not title:
            return None
        hash_text = re.search(r'[0-9a-z]+', hash_text, re.IGNORECASE)
        if not hash_text:
            return None
        hash_text = hash_text.group(0)
        ret_magnet = f'magnet:?xt=urn:btih:{hash_text}'
        return ret_magnet


    @staticmethod
    def resolve_torrent_files(content: str):
        """
        解析Torrent文件, 获取文件清单
        :return: 种子文件列表主目录、种子文件列表、错误信息
        """
        if not content:
            return "", [], "种子内容为空"
        
        file_names = []
        file_folder = ""
        try:
            torrent = bencodepy.decode(content)
            if torrent.get(b"info"):
                files = torrent.get(b"info", {}).get(b"files") or []
                if files:
                    for item in files:
                        if item.get(b"path"):
                            file_names.append(item[b"path"][0].decode('utf-8'))
                    file_folder = torrent.get(b"info", {}).get(b"name").decode('utf-8')
                else:
                    file_names.append(torrent.get(b"info", {}).get(b"name").decode('utf-8'))
        except Exception as err:
            return file_folder, file_names, "解析种子文件异常：%s" % str(err)
        return file_folder, file_names, ""
    

    @staticmethod
    def read_torrent_content(path):
        """
        读取本地种子文件的内容
        :return: 种子内容、种子文件列表主目录、种子文件列表、错误信息
        """
        if not path or not os.path.exists(path):
            return None, "", [], "种子文件不存在：%s" % path
        
        content, retmsg, file_folder, files = None, "", "", []
        
        try:
            # 读取种子文件内容
            with open(path, 'rb') as f:
                content = f.read()

            file_folder, files, retmsg = TorrentUtils.resolve_torrent_files(content)
        except Exception as e:
            retmsg = "读取种子文件出错：%s" % str(e)

        return content, file_folder, files, retmsg

    @staticmethod
    def torrent_to_magnet(torrent_file):
        """
        种子文件转磁力链接
        :return: 磁力链接
        """
        # 读取种子文件
        with open(torrent_file, 'rb') as f:
            torrent_data = bencodepy.decode(f.read())

        # 提取info部分并计算info hash
        info = torrent_data[b'info']
        info_hash = hashlib.sha1(bencodepy.encode(info)).hexdigest()

        # 获取种子文件中的文件名
        name = torrent_data[b'info'].get(b'name', b'').decode('utf-8')

        # 提取trackers
        trackers = []
        if b'announce' in torrent_data:
            trackers.append(torrent_data[b'announce'].decode('utf-8'))
        if b'announce-list' in torrent_data:
            for tracker_list in torrent_data[b'announce-list']:
                for tracker in tracker_list:
                    trackers.append(tracker.decode('utf-8'))

        # 去重
        trackers = list(set(trackers))

        # 构建磁力链接
        magnet_link = f"magnet:?xt=urn:btih:{info_hash}"
        if name:
            magnet_link += f"&dn={urllib.parse.quote(name)}"
        for tracker in trackers:
            magnet_link += f"&tr={urllib.parse.quote(tracker)}"

        return magnet_link

    @staticmethod
    def get_intersection_episodes(target, source, title):
        """
        对两个季集字典进行判重，有相同项目的取集的交集
        """
        if not source or not title:
            return target
        if not source.get(title):
            return target
        if not target.get(title):
            target[title] = source.get(title)
            return target
        index = -1
        for target_info in target.get(title):
            index += 1
            source_info = None
            for info in source.get(title):
                if info.get("season") == target_info.get("season"):
                    source_info = info
                    break
            if not source_info:
                continue
            if not source_info.get("episodes"):
                continue
            if not target_info.get("episodes"):
                target_episodes = source_info.get("episodes")
                target[title][index]["episodes"] = target_episodes
                continue
            target_episodes = list(set(target_info.get("episodes")).intersection(set(source_info.get("episodes"))))
            target[title][index]["episodes"] = target_episodes
        return target

    @staticmethod
    def get_download_list(media_list, download_order):
        """
        对媒体信息进行排序、去重
        """
        if not media_list:
            return []

        # 匹配的资源中排序分组选最好的一个下载
        # 按站点顺序、资源匹配顺序、做种人数下载数逆序排序
        media_list = sorted(media_list, key=lambda x: MediaUtils.get_sort_str(x), reverse=True)
        # 控重
        can_download_list_item = []
        can_download_list = []
        # 排序后重新加入数组，按真实名称控重，即只取每个名称的第一个
        for t_item in media_list:
            # 控重的主链是名称、年份、季、集
            if t_item.type != MediaType.MOVIE:
                media_name = "%s%s" % (t_item.get_title_string(),
                                       t_item.get_season_episode_string())
            else:
                media_name = t_item.get_title_string()
            if media_name not in can_download_list:
                can_download_list.append(media_name)
                can_download_list_item.append(t_item)
        return can_download_list_item
