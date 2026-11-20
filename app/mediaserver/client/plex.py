import os
from datetime import datetime
from urllib.parse import quote

from cachetools import TTLCache, cached
from lxml import etree

import log
from app.mediaserver.client._base import _IMediaClient
from app.utils import RequestUtils
from app.utils.types import MediaServerType, MediaType
from config import Config

# Plex 媒体类型对应的数字编码，详见 Plex API 的 type 参数
PLEX_SEARCH_TYPE = {
    "movie": 1,
    "show": 2,
    "episode": 4,
    "artist": 8
}
# Plex MediaContainer 下的媒体条目标签
PLEX_MEDIA_TAGS = ("Video", "Directory", "Track", "Photo", "Clip")


class Plex(_IMediaClient):
    # 媒体服务器ID
    client_id = "plex"
    # 媒体服务器类型
    client_type = MediaServerType.PLEX
    # 媒体服务器名称
    client_name = MediaServerType.PLEX.value

    # 私有属性
    _host = None
    _token = None
    _play_host = None
    _machine_identifier = None
    _connected = False

    def __init__(self, config=None):
        if config:
            self._client_config = config
        else:
            self._client_config = Config().get_config('plex')
        self._libraries = []
        self._connected = False
        self._machine_identifier = None
        self.init_config()

    def init_config(self):
        self._connected = False
        self._machine_identifier = None
        self._libraries = []
        if not self._client_config:
            return
        self._host = self.__format_host(self._client_config.get('host'))
        self._token = self._client_config.get('token')
        if self._host and self._token:
            self._connected = self.__connect(self._host, self._token)
        self.__init_play_host()

    @staticmethod
    def __format_host(host):
        """
        补全主机地址的协议和结尾斜杠
        """
        if not host:
            return None
        if not host.startswith('http'):
            host = "http://" + host
        if not host.endswith('/'):
            host = host + "/"
        return host

    def __init_play_host(self):
        """
        初始化播放地址，留空时与服务器地址一致
        """
        play_host = self._client_config.get('play_host')
        if not play_host:
            self._play_host = self._host
            return
        play_host = self.__format_host(play_host)
        if "app.plex.tv" in play_host:
            self._play_host = play_host + "desktop/"
        else:
            self._play_host = play_host + "web/index.html"

    @staticmethod
    def __headers(token=None):
        """
        构造 Plex 请求头
        """
        headers = {
            "X-Plex-Product": "NAStool",
            "X-Plex-Version": "1.0",
            "X-Plex-Platform": "Python",
            "X-Plex-Device": "NAStool",
            "X-Plex-Device-Name": "NAStool"
        }
        if token:
            headers["X-Plex-Token"] = token
        return headers

    @staticmethod
    def __to_int(value, default=0):
        """
        将 Plex 返回的属性值转为整数
        """
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def __children(container, *tags):
        """
        取出 MediaContainer 下的子节点
        """
        if container is None:
            return []
        return [child for child in container if not tags or child.tag in tags]

    def __query(self, path, params=None, container_start=None, container_size=None):
        """
        请求 Plex 接口，返回 MediaContainer 节点
        """
        if not self._host or not self._token:
            return None
        url = path if str(path).startswith("http") else f"{self._host.rstrip('/')}{path}"
        headers = self.__headers(self._token)
        if container_start is not None:
            headers["X-Plex-Container-Start"] = str(container_start)
        if container_size is not None:
            headers["X-Plex-Container-Size"] = str(container_size)
        try:
            res = RequestUtils(headers=headers, timeout=30).get_res(url, params=params)
            if res is None:
                log.error(f"【{self.client_name}】请求 {path} 无返回数据")
                return None
            if res.status_code not in (200, 201, 204):
                log.error(f"【{self.client_name}】请求 {path} 失败，状态码：{res.status_code}")
                return None
            if not res.content:
                return etree.Element("MediaContainer")
            return etree.fromstring(res.content)
        except Exception as e:
            log.exception(f"【{self.client_name}】请求 {path} 出错: ")
            return None

    def __fetch_items(self, path, params=None, container_size=100, max_items=None):
        """
        分页获取 Plex 媒体条目
        """
        items = []
        container_start = 0
        while True:
            container = self.__query(path,
                                     params=params,
                                     container_start=container_start,
                                     container_size=container_size)
            if container is None:
                break
            page_items = self.__children(container, *PLEX_MEDIA_TAGS)
            items.extend(page_items)
            if max_items and len(items) >= max_items:
                return items[:max_items]
            total_size = self.__to_int(container.get("totalSize") or container.get("size")) \
                or len(page_items)
            container_start += container_size
            if not page_items or container_start >= total_size:
                break
        return items

    def __get_sections(self, section_id=None):
        """
        获取媒体库节点列表
        """
        container = self.__query("/library/sections")
        sections = self.__children(container, "Directory")
        if section_id is None:
            return sections
        # /library/sections/{id} 返回的是筛选器列表，分区信息需从分区列表中过滤
        return [section for section in sections if str(section.get("key")) == str(section_id)]

    def __get_section_total(self, section_key, libtype=None, include_collections=False):
        """
        获取媒体库条目总数
        """
        params = {"includeCollections": int(bool(include_collections))}
        if libtype:
            params["type"] = PLEX_SEARCH_TYPE.get(libtype, libtype)
        container = self.__query(f"/library/sections/{section_key}/all",
                                 params=params,
                                 container_start=0,
                                 container_size=0)
        if container is None:
            return 0
        return self.__to_int(container.get("totalSize") or container.get("size"))

    @staticmethod
    def __get_location(item):
        """
        获取条目的本地路径：电影取媒体文件，剧集取媒体库目录
        """
        if item.tag == "Video":
            for media in item.findall("Media"):
                for part in media.findall("Part"):
                    if part.get("file"):
                        return part.get("file")
        for location in item.findall("Location"):
            if location.get("path"):
                return location.get("path")
        return None

    def __get_item_location(self, item):
        """
        获取条目的本地路径，列表中不带路径时再查询详情
        """
        path = self.__get_location(item)
        if path is None and item.tag == "Directory" and item.get("ratingKey"):
            detail = self.__query(f'/library/metadata/{item.get("ratingKey")}')
            details = self.__children(detail, *PLEX_MEDIA_TAGS)
            if details:
                path = self.__get_location(details[0])
        return path

    def __connect(self, host, token):
        """
        使用服务器地址和 Token 连接 Plex
        """
        host = self.__format_host(host)
        try:
            res = RequestUtils(headers=self.__headers(token), timeout=30).get_res(host)
            if res is None or res.status_code != 200:
                log.info(f"【{self.client_name}】连接服务器失败：{host}，"
                         f"状态码：{res.status_code if res else '无响应'}")
                return False
            container = etree.fromstring(res.content)
            self._host = host
            self._token = token
            self._machine_identifier = container.get("machineIdentifier")
            return True
        except Exception as e:
            log.exception(f"【{self.client_name}】Plex服务器连接失败: ")
            return False

    @classmethod
    def match(cls, ctype):
        return ctype in [cls.client_id, cls.client_type, cls.client_name]

    def get_type(self):
        return self.client_type

    def get_status(self):
        """
        测试连通性
        """
        return bool(self._connected)

    @staticmethod
    def get_user_count(**kwargs):
        """
        获得用户数量，Plex只能配置一个用户，固定返回1
        """
        return 1

    def get_activity_log(self, num):
        """
        获取Plex活动记录
        """
        if not self._connected:
            return []
        ret_array = []
        try:
            # type的含义: 1 电影 4 剧集单集，详见 Plex API 的 type 参数
            # 根据最后播放时间倒序获取数据
            historys = self.__fetch_items("/library/all",
                                          params={"sort": "lastViewedAt:desc",
                                                  "limit": num,
                                                  "type": "1,4"},
                                          max_items=num)
            for item in historys:
                last_viewed = item.get("lastViewedAt")
                # 过滤掉最后播放时间为空的
                if not last_viewed:
                    continue
                if item.get("type") == "episode":
                    event_title = "{} {}{} {}".format(
                        item.get("grandparentTitle"),
                        "S" + str(item.get("parentIndex")),
                        "E" + str(item.get("index")),
                        item.get("title")
                    )
                    event_str = f"开始播放剧集 {event_title}"
                else:
                    event_title = "{} {}".format(item.get("title"), "(" + str(item.get("year")) + ")")
                    event_str = f"开始播放电影 {event_title}"

                event_type = "PL"
                event_date = datetime.fromtimestamp(self.__to_int(last_viewed)).strftime('%Y-%m-%d %H:%M:%S')
                activity = {"type": event_type, "event": event_str, "date": event_date}
                ret_array.append(activity)
        except Exception as e:
            log.exception(f"【{self.client_name}】获取播放记录出错: ")
            return []
        if ret_array:
            ret_array = sorted(ret_array, key=lambda x: x['date'], reverse=True)
        return ret_array

    def get_medias_count(self):
        """
        获得电影、电视剧、动漫媒体数量
        :return: MovieCount SeriesCount SongCount
        """
        if not self._connected:
            return {}
        sections = self.__get_sections()
        MovieCount = SeriesCount = SongCount = EpisodeCount = 0
        for sec in sections:
            if sec.get("type") == "movie":
                MovieCount += self.__get_section_total(sec.get("key"), "movie")
            if sec.get("type") == "show":
                SeriesCount += self.__get_section_total(sec.get("key"), "show")
                EpisodeCount += self.__get_section_total(sec.get("key"), "episode", include_collections=True)
            if sec.get("type") == "artist":
                SongCount += self.__get_section_total(sec.get("key"), "artist")
        return {
            "MovieCount": MovieCount,
            "SeriesCount": SeriesCount,
            "SongCount": SongCount,
            "EpisodeCount": EpisodeCount
        }

    def get_movies(self, title, year=None):
        """
        根据标题和年份，检查电影是否在Plex中存在，存在则返回列表
        :param title: 标题
        :param year: 年份，为空则不过滤
        :return: 含title、year属性的字典列表
        """
        if not self._connected:
            return None
        params = {"type": PLEX_SEARCH_TYPE["movie"]}
        if title:
            params["title"] = title
        if year:
            params["year"] = year
        movies = self.__fetch_items("/library/all", params=params)
        ret_movies = []
        for movie in movies:
            ret_movies.append({'title': movie.get("title"),
                               'year': self.__to_int(movie.get("year"), None)})
        return ret_movies

    def get_tv_episodes(self,
                        item_id=None,
                        title=None,
                        year=None,
                        tmdbid=None,
                        season=None):
        """
        根据标题、年份、季查询电视剧所有集信息
        :param item_id: Plex中的ID
        :param title: 标题
        :param year: 年份，可以为空，为空时不按年份过滤
        :param tmdbid: TMDBID
        :param season: 季号，数字
        :return: 所有集的列表
        """
        if not self._connected:
            return []
        if not item_id:
            params = {"type": PLEX_SEARCH_TYPE["show"]}
            if title:
                params["title"] = title
            if year:
                params["year"] = year
            videos = self.__fetch_items("/library/all", params=params, max_items=1)
            if not videos:
                return []
            item_id = videos[0].get("ratingKey") or videos[0].get("key")
            if not item_id:
                return []
        episodes = self.__fetch_items(f"/library/metadata/{item_id}/allLeaves")
        ret_tvs = []
        for episode in episodes:
            # 季号 0 为特别篇，只有空值才不过滤季
            if season not in (None, "") and self.__to_int(episode.get("parentIndex")) != int(season):
                continue
            ret_tvs.append({
                "season_num": self.__to_int(episode.get("parentIndex")),
                "episode_num": self.__to_int(episode.get("index"))
            })
        return ret_tvs

    def get_no_exists_episodes(self, meta_info, season, total_num):
        """
        根据标题、年份、季、总集数，查询Plex中缺少哪几集
        :param meta_info: 已识别的需要查询的媒体信息
        :param season: 季号，数字
        :param total_num: 该季的总集数
        :return: 该季不存在的集号列表
        """
        if not self._connected:
            return None
        # 没有季默认为第1季，季号 0 为特别篇
        if season is None or season == "":
            season = 1
        episodes = self.get_tv_episodes(title=meta_info.title,
                                        year=meta_info.year,
                                        season=season)
        exists_episodes = [episode['episode_num'] for episode in episodes]
        total_episodes = [episode for episode in range(1, total_num + 1)]
        return list(set(total_episodes).difference(set(exists_episodes)))

    def get_episode_image_by_id(self, item_id, season_id, episode_id):
        """
        根据itemid、season_id、episode_id从Plex查询图片地址
        :param item_id: 在Plex中具体的一集的ID
        :param season_id: 季,目前没有使用
        :param episode_id: 集,目前没有使用
        :return: 图片对应在TMDB中的URL
        """
        if not self._connected:
            return None
        try:
            container = self.__query(f'/library/metadata/{item_id}/posters')
            for image in self.__children(container):
                if image.get("key") and image.get("key").startswith('http'):
                    return image.get("key")
            return None
        except Exception as e:
            log.exception(f"【{self.client_name}】获取剧集封面出错：")
            return None

    def get_remote_image_by_id(self, item_id, image_type):
        """
        根据ItemId从Plex查询图片地址
        :param item_id: 在Emby中的ID
        :param image_type: 图片的类型，Poster或者Backdrop等
        :return: 图片对应在TMDB中的URL
        """
        if not self._connected:
            return None
        try:
            if image_type == "Poster":
                container = self.__query(f'/library/metadata/{item_id}/posters')
            else:
                container = self.__query(f'/library/metadata/{item_id}/arts')
            for image in self.__children(container):
                if image.get("key") and image.get("key").startswith('http'):
                    return image.get("key")
        except Exception as e:
            log.exception(f"【{self.client_name}】获取封面出错：")
        return None

    def get_local_image_by_id(self, item_id, remote=True):
        """
        根据ItemId从媒体服务器查询有声书图片地址
        :param item_id: 在Emby中的ID
        :param remote: 是否远程使用
        """
        return None

    def refresh_root_library(self):
        """
        通知Plex刷新整个媒体库
        """
        if not self._connected:
            return False
        return self.__query('/library/sections/all/refresh') is not None

    def refresh_library_by_items(self, items):
        """
        按路径刷新媒体库
        """
        if not self._connected:
            return False
        # _libraries可能未初始化,初始化一下
        if not self._libraries:
            try:
                self._libraries = self.__get_sections()
            except Exception as err:
                log.exception(f"【{self.client_name}】尝试初始化媒体库链接失败: ")
        result_dict = {}
        for item in items:
            file_path = item.get("file_path")
            lib_key, path = self.__find_librarie(file_path, self._libraries)
            # 如果存在同一剧集的多集,key(path)相同会合并
            result_dict[path] = lib_key
        if "" in result_dict:
            # 如果有匹配失败的,刷新整个库
            self.refresh_root_library()
        else:
            # 否则一个一个刷新
            for path, lib_key in result_dict.items():
                log.info(f"【{self.client_name}】刷新媒体库：{lib_key} : {path}")
                self.__query(f'/library/sections/{lib_key}/refresh', params={"path": path})

    @staticmethod
    def __find_librarie(path, libraries):
        """
        判断这个path属于哪个媒体库
        多个媒体库配置的目录不应有重复和嵌套,
        使用os.path.commonprefix([path, location]) == location应该没问题
        """
        if path is None:
            return "", ""
        # 只要路径,不要文件名
        dir_path = os.path.dirname(path)
        try:
            for lib in libraries:
                for location in lib.findall("Location"):
                    location_path = location.get("path")
                    if location_path and os.path.commonprefix([dir_path, location_path]) == location_path:
                        return lib.get("key"), dir_path
        except Exception as err:
            log.exception("【Plex】判断path归属媒体库异常: ")
        return "", ""

    def get_libraries(self):
        """
        获取媒体服务器所有媒体库列表
        """
        if not self._connected:
            return []
        try:
            self._libraries = self.__get_sections()
        except Exception as err:
            log.exception(f"【{self.client_name}】尝试初始化媒体库连接失败: ")
            return []
        libraries = []
        for library in self._libraries:
            match library.get("type"):
                case "movie":
                    library_type = MediaType.MOVIE.value
                    image_list_str = self.get_libraries_image(library.get("key"), 1)
                case "show":
                    library_type = MediaType.TV.value
                    image_list_str = self.get_libraries_image(library.get("key"), 2)
                case _:
                    continue
            libraries.append({
                "id": library.get("key"),
                "name": library.get("title"),
                "paths": [location.get("path") for location in library.findall("Location")
                          if location.get("path")],
                "type": library_type,
                "image_list": image_list_str,
                "link": f"{self._play_host or self._host}#!/media/{self._machine_identifier}"
                        f"/com.plexapp.plugins.library?source={library.get('key')}"
            })
        return libraries

    @cached(cache=TTLCache(maxsize=512, ttl=3600))
    def get_libraries_image(self, library_key, type):
        """
        获取媒体服务器最近添加的媒体的图片列表
        param: library_key
        param: type type的含义: 1 电影 2 剧集，详见 Plex API 的 type 参数
        """
        if not self._connected:
            return ""
        # 返回结果
        poster_urls = {}
        # 页码计数
        container_start = 0
        # 需要的总条数/每页的条数
        total_size = 4

        # 如果总数不足,接续获取下一页
        while len(poster_urls) < total_size:
            container = self.__query("/hubs/home/recentlyAdded",
                                     params={"type": type, "sectionID": library_key},
                                     container_start=container_start,
                                     container_size=total_size)
            items = self.__children(container, *PLEX_MEDIA_TAGS)
            for item in items:
                if item.get("type") == 'episode':
                    # 如果是剧集的单集,则去找上级的图片
                    thumb = item.get("parentThumb")
                else:
                    # 否则就用自己的图片
                    thumb = item.get("thumb")
                if thumb is not None:
                    poster_urls[thumb] = None
                if len(poster_urls) == total_size:
                    break
            if len(items) < total_size:
                break
            container_start += total_size
        image_list_str = ", ".join(
            [self._get_image_url(url) for url in list(poster_urls.keys())[:total_size]])
        return image_list_str

    def _get_image_url(self, path):
        """
        拼接 Plex 图片完整地址；只有内网地址才走 NT 中转
        """
        if not path:
            return ""
        url = path if str(path).startswith("http") else f"{self._host.rstrip('/')}{path}"
        if "X-Plex-Token" not in url:
            url = f"{url}{'&' if '?' in url else '?'}X-Plex-Token={self._token}"
        return self.get_nt_image_url(url)

    def get_iteminfo(self, itemid):
        """
        获取单个项目详情
        """
        if not self._connected:
            return {}
        try:
            container = self.__query(f'/library/metadata/{itemid}', params={"includeGuids": 1})
            items = self.__children(container, *PLEX_MEDIA_TAGS)
            if not items:
                return {}
            ids = self.__get_ids(items[0].findall("Guid"))
            return {'ProviderIds': {'Tmdb': ids['tmdb_id'], 'Imdb': ids['imdb_id']}}
        except Exception as err:
            log.exception(f"【{self.client_name}】获取单个项目详情异常: ")
            return {}

    def get_play_url(self, item_id):
        """
        拼装媒体播放链接
        :param item_id: 媒体的的ID
        """
        return f'{self._play_host or self._host}#!/server/{self._machine_identifier}/details?key={item_id}'

    def get_items(self, parent):
        """
        获取媒体服务器所有媒体库列表
        """
        if not parent:
            yield {}
        if not self._connected:
            yield {}
        try:
            sections = self.__get_sections(parent)
            if sections:
                section = sections[0]
                section_type = section.get("type")
                items = self.__fetch_items(f"/library/sections/{parent}/all",
                                           params={"type": PLEX_SEARCH_TYPE.get(section_type, 1),
                                                   "includeGuids": 1})
                for item in items:
                    ids = self.__get_ids(item.findall("Guid"))
                    yield {"id": item.get("ratingKey"),
                           "library": self.__to_int(item.get("librarySectionID") or parent, None),
                           "type": item.get("type"),
                           "title": item.get("title"),
                           "originalTitle": item.get("originalTitle"),
                           "year": self.__to_int(item.get("year"), None),
                           "tmdbid": ids['tmdb_id'],
                           "imdbid": ids['imdb_id'],
                           "tvdbid": ids['tvdb_id'],
                           "path": self.__get_item_location(item)}
        except Exception as err:
            log.exception(f"【{self.client_name}】获取媒体服务器所有媒体库列表失败: ")
        yield {}

    @staticmethod
    def __get_ids(guids):
        guid_mapping = {
            "imdb://": "imdb_id",
            "tmdb://": "tmdb_id",
            "tvdb://": "tvdb_id"
        }
        ids = {}
        for prefix, varname in guid_mapping.items():
            ids[varname] = None
        for guid in guids or []:
            guid_id = guid.get("id") if hasattr(guid, "get") else None
            if not guid_id:
                continue
            for prefix, varname in guid_mapping.items():
                # 找到匹配的ID
                if guid_id.startswith(prefix):
                    ids[varname] = guid_id[len(prefix):]
                    break
        return ids

    def get_playing_sessions(self):
        """
        获取正在播放的会话
        """
        if not self._connected:
            return []
        container = self.__query("/status/sessions")
        ret_sessions = []
        for session in self.__children(container, "Video", "Track", "Photo"):
            bitrate = sum([self.__to_int(media.get("bitrate")) for media in session.findall("Media")])
            player = session.find("Player")
            ret_sessions.append({
                "type": session.tag,
                "bitrate": bitrate,
                "address": player.get("address") if player is not None else None
            })
        return ret_sessions

    def get_webhook_message(self, message):
        """
        解析Plex报文
        eventItem  字段的含义
        event      事件类型
        item_type  媒体类型 TV,MOV
        item_name  TV:琅琊榜 S1E6 剖心明志 虎口脱险
                   MOV:猪猪侠大冒险(2001)
        overview   剧情描述
        """
        eventItem = {'event': message.get('event', '')}
        if message.get('Metadata'):
            if message.get('Metadata', {}).get('type') == 'episode':
                eventItem['item_type'] = "TV"
                eventItem['item_name'] = "{} {}{} {}".format(
                    message.get('Metadata', {}).get('grandparentTitle'),
                    "S" + str(message.get('Metadata', {}).get('parentIndex')),
                    "E" + str(message.get('Metadata', {}).get('index')),
                    message.get('Metadata', {}).get('title'))
                eventItem['item_id'] = message.get('Metadata', {}).get('ratingKey')
                eventItem['season_id'] = message.get('Metadata', {}).get('parentIndex')
                eventItem['episode_id'] = message.get('Metadata', {}).get('index')

                if message.get('Metadata', {}).get('summary') and len(message.get('Metadata', {}).get('summary')) > 100:
                    eventItem['overview'] = str(message.get('Metadata', {}).get('summary'))[:100] + "..."
                else:
                    eventItem['overview'] = message.get('Metadata', {}).get('summary')
            else:
                eventItem['item_type'] = "MOV" if message.get('Metadata', {}).get('type') == 'movie' else "SHOW"
                eventItem['item_name'] = "{} {}".format(
                    message.get('Metadata', {}).get('title'), "(" + str(message.get('Metadata', {}).get('year')) + ")")
                eventItem['item_id'] = message.get('Metadata', {}).get('ratingKey')
                if len(message.get('Metadata', {}).get('summary')) > 100:
                    eventItem['overview'] = str(message.get('Metadata', {}).get('summary'))[:100] + "..."
                else:
                    eventItem['overview'] = message.get('Metadata', {}).get('summary')
        if eventItem.get('event') == "library.new":
            eventItem['play_url'] = f"/open?url=" \
                                    f"{quote(self.get_play_url(message.get('Metadata', {}).get('key')))}&type=plex"
        if message.get('Player'):
            eventItem['ip'] = message.get('Player').get('publicAddress')
            eventItem['client'] = message.get('Player').get('title')
            # 这里给个空,防止拼消息的时候出现None
            eventItem['device_name'] = ' '
        if message.get('Account'):
            eventItem['user_name'] = message.get("Account").get('title')

        return eventItem

    def get_resume(self, user_name, num=12):
        """
        获取继续观看的媒体
        """
        if not self._connected or not user_name:
            return []
        items = self.__fetch_items('/hubs/continueWatching/items', container_size=num, max_items=num)
        ret_resume = []
        for item in items:
            item_type = MediaType.MOVIE.value if item.get("type") == "movie" else MediaType.TV.value
            if item_type == MediaType.MOVIE.value:
                name = item.get("title")
            else:
                if self.__to_int(item.get("parentIndex")) == 1:
                    name = f"{item.get('grandparentTitle')} 第{item.get('index')}集"
                else:
                    name = f"{item.get('grandparentTitle')} 第{item.get('parentIndex')}季第{item.get('index')}集"
            link = self.get_play_url(item.get("key"))
            image = self._get_image_url(item.get("art") or item.get("grandparentArt"))
            view_offset = self.__to_int(item.get("viewOffset"))
            duration = self.__to_int(item.get("duration"))
            ret_resume.append({
                "id": item.get("key"),
                "name": name,
                "type": item_type,
                "image": image,
                "link": link,
                "percent": view_offset / duration * 100 if view_offset and duration else 0
            })
        return ret_resume

    def get_latest(self, num=20):
        """
        获取最近添加媒体
        """
        if not self._connected:
            return []
        items = self.__fetch_items('/library/recentlyAdded', container_size=num, max_items=num)
        ret_resume = []
        for item in items:
            item_type = MediaType.MOVIE.value if item.get("type") == "movie" else MediaType.TV.value
            link = self.get_play_url(item.get("key"))
            title = item.get("title") if item_type == MediaType.MOVIE.value else \
                f"{item.get('parentTitle')} 第{item.get('index')}季"
            image = self._get_image_url(item.get("thumb")
                                        or item.get("parentThumb")
                                        or item.get("grandparentThumb"))
            ret_resume.append({
                "id": item.get("key"),
                "name": title,
                "type": item_type,
                "image": image,
                "link": link
            })
        return ret_resume
