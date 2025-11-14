import chardet
import datetime
import re

from typing import Optional, Tuple
from urllib.parse import quote, urlencode

from jinja2 import Template
from pyquery import PyQuery

from app.sites.siteconf import SiteConf
import log

from app.indexer.client.browser import PlaywrightHelper, WaitElement
from app.indexer.manager import IndexerInfo
from app.utils import StringUtils, RequestUtils
from app.utils.system_utils import SystemUtils
from app.utils.types import MediaType


from config import Config

class TorrentSpider(object):

    # 索引器ID
    indexerid = None
    # 索引器名称
    indexername = None
    # 站点域名
    domain = None
    # 站点Cookie
    cookie = None
    # 站点UA
    ua = None
    # 代理
    proxies = None
    # 是否渲染
    render = False
    # Referer
    referer = None
    # 搜索路径、方式配置
    search_conf = {}
    # 浏览配置
    browse = {}
    # 站点分类配置
    category = {}
    # 站点种子列表配置
    list_conf = {}
    # 站点种子字段配置
    fields_conf = {}
    # 页码
    page = 0
    # 搜索条数
    result_num = 100
    # 种子列表
    torrents_info_array = []
    # 加载等待元素
    wait_element = None
    # 超时时间
    timeout = 20

    def __init__(self, indexer: IndexerInfo, referer=None):

        self.torrents_info_array = []
        self.result_num = 100
        # 索引器
        if indexer:
            self._indexer = indexer
            self.indexerid = indexer.id
            self.indexername = indexer.name
            self.search_conf = indexer.search
            self.browse = indexer.browse
            self.category = indexer.category
            self.list_conf = indexer.torrents.get("list", {})
            self.fields_conf = indexer.torrents.get("fields")
            self.render = indexer.render
            self.domain = indexer.domain
            if self.domain and not str(self.domain).endswith("/"):
                self.domain = self.domain + "/"

            self.ua = indexer.ua if indexer.ua else Config().get_ua()

            if indexer.proxy:
                self.proxies = Config().get_proxies()
            if indexer.cookie:
                self.cookie = RequestUtils.cookie_parse(indexer.cookie)

            wait_navigation = self.search_conf.get('navigation')
            if wait_navigation:
                wait_pair = StringUtils.split_and_filter(wait_navigation, ":")
                if len(wait_pair) == 2:
                    self.wait_element = WaitElement(wait_pair[0], wait_pair[1])
            
            if 'hr' not in self.fields_conf:
                grap_conf = SiteConf().get_grap_conf(self.domain)
                if grap_conf:
                    self.fields_conf['hr'] = grap_conf.get('HR')

        if referer:
            self.referer = referer

    def search(self, keyword: str, page=None, mtype=None) -> Tuple[bool, list]:
        """
        页面查询
        :param keyword: 搜索关键字，如果数组则为批量搜索
        :param page: 页码
        :param referer: Referer
        :param mtype: 媒体类型
        """
        if not self.search_conf or not self.domain:
            return True, []
        
        searchurl = self._build_search_url(keyword, page, mtype)

        log.info(f"【Spider】[{self.indexername}]开始请求: {searchurl}")

        # 浏览器仿真
        if self.render:
            noGraphical = SystemUtils.is_windows() is False and SystemUtils.is_macos() is False
            cookie_str = self._indexer.cookie
            page_source = PlaywrightHelper().get_page_source(
                url=searchurl,
                cookies=cookie_str,
                ua=self.ua,
                proxy=True if self._indexer.proxy else False,
                timeout=self.timeout,
                wait_item=self.wait_element,
                headless=noGraphical
            )
            return self.parse(page_source)
        
        html_content = self._sample_request(searchurl)
        return self.parse(html_content)
    

    def _build_search_url(self, keyword: str = None, page=None, mtype=None) -> str:
        """
        构建请求地址
        """
        # 种子搜索相对路径
        paths = self.search_conf.get("paths", [])
        torrentspath = ""
        if len(paths) == 1:
            torrentspath = paths[0].get("path", "")
        else:
            for path in paths:
                if path.get("type") == "all" and not mtype:
                    torrentspath = path.get("path")
                    break
                elif path.get("type") == "movie" and mtype == MediaType.MOVIE:
                    torrentspath = path.get("path")
                    break
                elif path.get("type") == "tv" and mtype == MediaType.TV:
                    torrentspath = path.get("path")
                    break
                elif path.get("type") == "anime" and mtype == MediaType.ANIME:
                    torrentspath = path.get("path")
                    break
        
        searchurl = ''

        # 关键字搜索
        if keyword:
            # 单个查询
            search_word = keyword
            # 查询模式与
            search_mode = "0"

            # 搜索URL
            if self.search_conf.get("params"):
                # 变量字典
                inputs_dict = {"keyword": search_word}
                # 查询参数
                params = {
                    "search_mode": search_mode,
                    "page": page or 0,
                    "notnewword": 1,
                }
                # 额外参数
                for key, value in self.search_conf.get("params").items():
                    params.update({"%s" % key: str(value).format(**inputs_dict)})
                # 分类条件
                if self.category:
                    if mtype == MediaType.MOVIE:
                        cats = self.category.get("movie") or []
                    elif mtype:
                        cats = self.category.get("tv") or []
                    else:
                        cats = (self.category.get("movie") or []) + (
                            self.category.get("tv") or []
                        )
                    for cat in cats:
                        if self.category.get("field"):
                            value = params.get(self.category.get("field"), "")
                            params.update(
                                {
                                    "%s" % self.category.get("field"): value
                                    + self.category.get("delimiter", " ")
                                    + cat.get("id")
                                }
                            )
                        else:
                            params.update({"%s" % cat.get("id"): 1})
                searchurl = self.domain + torrentspath + "?" + urlencode(params)
            else:
                # 变量字典
                inputs_dict = {"keyword": quote(search_word), "page": page or 0}
                # 无额外参数
                searchurl = self.domain + str(torrentspath).format(**inputs_dict)

        # 列表浏览
        else:
            # 变量字典
            inputs_dict = {"page": page or 0, "keyword": ""}
            # 有单独浏览路径
            if self.browse:
                torrentspath = self.browse.get("path")
                if self.browse.get("start"):
                    start_page = int(self.browse.get("start")) + int(page or 0)
                    inputs_dict.update({"page": start_page})
            elif page:
                torrentspath = torrentspath + f"?page={page}"
            # 搜索Url
            searchurl = self.domain + str(torrentspath).format(**inputs_dict)
        
        return searchurl

    
    def _sample_request(self, searchurl):
        # requests请求
        ret = RequestUtils(
            cookies=self.cookie,
            timeout=self.timeout,
            referer=self.referer,
            proxies=self.proxies
        ).get_res(searchurl, allow_redirects=True)

        if ret is None:
            log.warn(f"【Spider】[{self.indexername}] 请求失败: {searchurl}")
            return ''
        
        # 使用chardet检测字符编码
        raw_data = ret.content
        if raw_data:
            try:
                result = chardet.detect(raw_data)
                encoding = result['encoding']
                # 解码为字符串
                return raw_data.decode(encoding)
            except Exception as e:
                log.debug(f"chardet解码失败: {str(e)}")
                # 探测utf-8解码
                if re.search(r"charset=\"?utf-8\"?", ret.text, re.IGNORECASE):
                    ret.encoding = "utf-8"
                else:
                    ret.encoding = ret.apparent_encoding
                return ret.text
        else:
            return ret.text

    def _gettitle_default(self, torrent) -> str:
        # title default
        if "title" not in self.fields_conf:
            return ''
        
        torrents_title = ''
        selector = self.fields_conf.get("title", {})
        if "selector" in selector:
            title = torrent(selector.get("selector", "")).clone()
            self.__remove(title, selector)
            items = self.__attribute_or_text(title, selector)
            torrents_title = self.__index(items, selector)
        elif "text" in selector:
            render_dict = {}
            if "title_default" in self.fields_conf:
                title_default_selector = self.fields_conf.get("title_default", {})
                title_default_item = torrent(
                    title_default_selector.get("selector", "")
                ).clone()
                self.__remove(title_default_item, title_default_selector)
                items = self.__attribute_or_text(title_default_item, selector)
                title_default = self.__index(items, title_default_selector)
                render_dict.update({"title_default": title_default})
            if "title_optional" in self.fields_conf:
                title_optional_selector = self.fields_conf.get("title_optional", {})
                title_optional_item = torrent(
                    title_optional_selector.get("selector", "")
                ).clone()
                self.__remove(title_optional_item, title_optional_selector)
                items = self.__attribute_or_text(
                    title_optional_item, title_optional_selector
                )
                title_optional = self.__index(items, title_optional_selector)
                render_dict.update({"title_optional": title_optional})
            torrents_title = Template(selector.get("text")).render(
                fields=render_dict
            )
        return self.__filter_text(torrents_title, selector.get("filters"))

    def _gettitle_optional(self, torrent) -> str:
        # title optional
        if "description" not in self.fields_conf:
            return ''
        
        torrent_description = ''
        selector = self.fields_conf.get("description", {})
        if "selector" in selector or "selectors" in selector:
            description = torrent(
                selector.get("selector", selector.get("selectors", ""))
            ).clone()
            if description:
                self.__remove(description, selector)
                items = self.__attribute_or_text(description, selector)
                torrent_description = self.__index(items, selector)
        elif "text" in selector:
            render_dict = {}
            if "tags" in self.fields_conf:
                tags_selector = self.fields_conf.get("tags", {})
                tags_item = torrent(tags_selector.get("selector", "")).clone()
                self.__remove(tags_item, tags_selector)
                items = self.__attribute_or_text(tags_item, tags_selector)
                tag = self.__index(items, tags_selector)
                render_dict.update({"tags": tag})
            if "subject" in self.fields_conf:
                subject_selector = self.fields_conf.get("subject", {})
                subject_item = torrent(subject_selector.get("selector", "")).clone()
                self.__remove(subject_item, subject_selector)
                items = self.__attribute_or_text(subject_item, subject_selector)
                subject = self.__index(items, subject_selector)
                render_dict.update({"subject": subject})
            if "description_free_forever" in self.fields_conf:
                description_free_forever_selector = self.fields_conf.get(
                    "description_free_forever", {}
                )
                description_free_forever_item = torrent(
                    description_free_forever_selector.get("selector", "")
                ).clone()
                self.__remove(
                    description_free_forever_item, description_free_forever_selector
                )
                items = self.__attribute_or_text(
                    description_free_forever_item, description_free_forever_selector
                )
                description_free_forever = self.__index(
                    items, description_free_forever_selector
                )
                render_dict.update(
                    {"description_free_forever": description_free_forever}
                )
            if "description_normal" in self.fields_conf:
                description_normal_selector = self.fields_conf.get("description_normal", {})
                description_normal_item = torrent(
                    description_normal_selector.get("selector", "")
                ).clone()
                self.__remove(description_normal_item, description_normal_selector)
                items = self.__attribute_or_text(
                    description_normal_item, description_normal_selector
                )
                description_normal = self.__index(items, description_normal_selector)
                render_dict.update({"description_normal": description_normal})
            torrent_description = Template(selector.get("text")).render(
                fields=render_dict
            )

        return self.__filter_text(torrent_description, selector.get("filters"))

    def _getdetails(self, torrent) -> str:
        # details
        if "details" not in self.fields_conf:
            return ''
        
        torrents_page_url = ''

        selector = self.fields_conf.get("details", {})
        details = torrent(selector.get("selector", "")).clone()
        self.__remove(details, selector)
        items = self.__attribute_or_text(details, selector)
        item = self.__index(items, selector)
        detail_link = self.__filter_text(item, selector.get("filters"))
        if detail_link:
            if not detail_link.startswith("http"):
                if detail_link.startswith("//"):
                    torrents_page_url = (self.domain.split(":")[0] + ":" + detail_link)
                elif detail_link.startswith("/"):
                    torrents_page_url = self.domain + detail_link[1:]
                else:
                    torrents_page_url = self.domain + detail_link
            else:
                torrents_page_url = detail_link
        return torrents_page_url

    def _getdownload(self, torrent) -> str:
        # download link
        if "download" not in self.fields_conf:
            return ''
        
        torrents_enclosure = ''

        selector = self.fields_conf.get("download", {})

        if "detail" in selector:
            detail = selector.get("detail", {})
            if "xpath" in detail:
                torrents_enclosure = (
                    f'[{detail.get("xpath", "")}'
                    f'|{self.cookie or ""}'
                    f'|{self.ua or ""}'
                    f'|{self.referer or ""}]'
                )
            elif "hash" in detail:
                torrents_enclosure = (
                    f'#{detail.get("hash", "")}'
                    f'|{self.cookie or ""}'
                    f'|{self.ua or ""}'
                    f'|{self.referer or ""}#'
                )
        else:
            download = torrent(selector.get("selector", "")).clone()
            self.__remove(download, selector)
            items = self.__attribute_or_text(download, selector)
            item = self.__index(items, selector)
            download_link = self.__filter_text(item, selector.get("filters"))
            if download_link:
                if not download_link.startswith(
                    "http"
                ) and not download_link.startswith("magnet"):
                    torrents_enclosure = (
                        self.domain + download_link[1:]
                        if download_link.startswith("/")
                        else self.domain + download_link
                    )
                else:
                    torrents_enclosure = download_link
        return torrents_enclosure

    def _getimdbid(self, torrent) -> str:
        # imdbid
        if "imdbid" not in self.fields_conf:
            return
        selector = self.fields_conf.get("imdbid", {})
        imdbid = torrent(selector.get("selector", "")).clone()
        self.__remove(imdbid, selector)
        items = self.__attribute_or_text(imdbid, selector)
        item = self.__index(items, selector)
        return self.__filter_text(item, selector.get("filters"))

    def _getsize(self, torrent) -> int:
        # torrent size
        if "size" not in self.fields_conf:
            return 0
        selector = self.fields_conf.get("size", {})
        size = torrent(selector.get("selector", selector.get("selectors", ""))).clone()
        self.__remove(size, selector)
        items = self.__attribute_or_text(size, selector)
        item = self.__index(items, selector)
        item = self.__filter_text(item, selector.get("filters")).replace("\n", "").strip()
        if item:
            return StringUtils.num_filesize(item)
        return 0

    def _getleechers(self, torrent) -> str:
        # torrent leechers
        if "leechers" not in self.fields_conf:
            return ''
        
        selector = self.fields_conf.get("leechers", {})
        leechers = torrent(selector.get("selector", "")).clone()
        self.__remove(leechers, selector)
        items = self.__attribute_or_text(leechers, selector)
        item = self.__index(items, selector)
        if item:
            torrents_peers = item.split("/")[0]
            return self.__filter_text(torrents_peers, selector.get("filters"))
        else:
            return '0'
        
    def _getseeders(self, torrent) -> str:
        # torrent leechers
        if "seeders" not in self.fields_conf:
            return
        
        selector = self.fields_conf.get("seeders", {})
        seeders = torrent(selector.get("selector", "")).clone()
        self.__remove(seeders, selector)
        items = self.__attribute_or_text(seeders, selector)
        item = self.__index(items, selector)
        if item:
            torrents_seeders = item.split("/")[0]
            return self.__filter_text(torrents_seeders, selector.get("filters"))
        else:
            return '0'

    def _getgrabs(self, torrent) -> str:
        # torrent grabs
        if "grabs" not in self.fields_conf:
            return
        
        selector = self.fields_conf.get("grabs", {})
        grabs = torrent(selector.get("selector", "")).clone()
        self.__remove(grabs, selector)
        items = self.__attribute_or_text(grabs, selector)
        item = self.__index(items, selector)
        if item:
            torrents_grabs = item.split("/")[0]
            return self.__filter_text(torrents_grabs, selector.get("filters"))
        else:
            return '0'
        
    def _getpubdate(self, torrent) -> str:
        # torrent pubdate
        if "date_added" not in self.fields_conf:
            return ''
        
        selector = self.fields_conf.get("date_added", {})
        pubdate = torrent(selector.get("selector", "")).clone()
        self.__remove(pubdate, selector)
        items = self.__attribute_or_text(pubdate, selector)
        
        torrents_pubdate = self.__index(items, selector)
        return self.__filter_text(torrents_pubdate, selector.get("filters"))

    def _getelapsed_date(self, torrent) -> str:
        # torrent pubdate
        if "date_elapsed" not in self.fields_conf:
            return ''
        
        selector = self.fields_conf.get("date_elapsed", {})
        date_elapsed = torrent(selector.get("selector", "")).clone()
        self.__remove(date_elapsed, selector)
        items = self.__attribute_or_text(date_elapsed, selector)
        
        torrents_date_elapsed = self.__index(items, selector)
        return self.__filter_text(torrents_date_elapsed, selector.get("filters"))

    def _getdownloadvolumefactor(self, torrent) -> Optional[float]:
        # downloadvolumefactor
        selector = self.fields_conf.get("downloadvolumefactor")
        if not selector:
            return None
        
        torrents_downloadvolumefactor = 1.0
        if "case" in selector:
            for downloadvolumefactorselector in list(selector.get("case", {}).keys()):
                downloadvolumefactor = torrent(downloadvolumefactorselector)
                if len(downloadvolumefactor) > 0:
                    downloadvolumefactor = selector.get("case", {}).get(downloadvolumefactorselector)
                    if downloadvolumefactor is not None:
                        torrents_downloadvolumefactor = float(downloadvolumefactor)
                        break
        elif "selector" in selector:
            downloadvolume = torrent(selector.get("selector", "")).clone()
            self.__remove(downloadvolume, selector)
            items = self.__attribute_or_text(downloadvolume, selector)
            item = self.__index(items, selector)
            if item:
                downloadvolumefactor = re.search(r"(\d+\.?\d*)", item)
                if downloadvolumefactor is not None:
                    torrents_downloadvolumefactor = float(downloadvolumefactor.group(1))
        return torrents_downloadvolumefactor

    def _getuploadvolumefactor(self, torrent) -> Optional[float]:
        # uploadvolumefactor
        selector = self.fields_conf.get("uploadvolumefactor")
        if not selector:
            return None
        
        torrents_uploadvolumefactor = 1.0
        if "case" in selector:
            for uploadvolumefactorselector in list(selector.get("case", {}).keys()):
                uploadvolumefactor = torrent(uploadvolumefactorselector)
                if len(uploadvolumefactor) > 0:
                    uploadvolumefactor = selector.get("case", {}).get(uploadvolumefactorselector)
                    if uploadvolumefactor is not None:
                        torrents_uploadvolumefactor = float(uploadvolumefactor)
                    break
        elif "selector" in selector:
            uploadvolume = torrent(selector.get("selector", "")).clone()
            self.__remove(uploadvolume, selector)
            items = self.__attribute_or_text(uploadvolume, selector)
            item = self.__index(items, selector)
            if item:
                uploadvolumefactor = re.search(r"(\d+\.?\d*)", item)
                if uploadvolumefactor is not None:
                    torrents_uploadvolumefactor = float(uploadvolumefactor.group(1))
        return torrents_uploadvolumefactor

    def _getlabels(self, torrent) -> str:
        # labels
        if "labels" not in self.fields_conf:
            return ''
        selector = self.fields_conf.get("labels", {})
        labels = torrent(selector.get("selector", "")).clone()
        self.__remove(labels, selector)
        items = self.__attribute_or_text(labels, selector)
        if items:
            return "|".join(items)
        return ''

    def _checkhr(self, torrent) -> bool:
        # h & r
        if "hr" not in self.fields_conf:
            return False
        selector = self.fields_conf.get("hr")
        if selector:
            if isinstance(selector, dict):
                hr_tag = torrent(selector.get("selector", ""))
            else:
                hr_tag = torrent(selector)
            return False if hr_tag is None else True        
        return False

    def _getinfo(self, torrent_html):
        """
        解析单条种子数据
        """
        torrents_info = {"indexer": self.indexerid}
        try:
            torrents_info["title"] = self._gettitle_default(torrent_html)
            torrents_info["description"] = self._gettitle_optional(torrent_html)
            torrents_info["page_url"] = self._getdetails(torrent_html)
            torrents_info["enclosure"] = self._getdownload(torrent_html)
            torrents_info["grabs"] = self._getgrabs(torrent_html)
            torrents_info["peers"] = self._getleechers(torrent_html)
            torrents_info["seeders"] = self._getseeders(torrent_html)
            torrents_info["size"] = self._getsize(torrent_html)
            torrents_info["imdbid"] = self._getimdbid(torrent_html)
            torrents_info["downloadvolumefactor"] = self._getdownloadvolumefactor(torrent_html)
            torrents_info["uploadvolumefactor"] = self._getuploadvolumefactor(torrent_html)
            torrents_info["pubdate"] = self._getpubdate(torrent_html)
            torrents_info["date_elapsed"] = self._getelapsed_date(torrent_html)
            torrents_info["labels"] = self._getlabels(torrent_html)
            torrents_info["hr"] = self._checkhr(torrent_html)
        except Exception as err:
            log.exception(f"【Spider】{self.indexername} 搜索出现错误：")
        return torrents_info

    def __filter_text(self, text, filters):
        """
        对文件进行处理
        """
        if not text or not filters or not isinstance(filters, list):
            return text
        if not isinstance(text, str):
            text = str(text)
        for filter_item in filters:
            if not text:
                break
            try:
                method_name = filter_item.get("name")
                args = filter_item.get("args")
                if method_name == "re_search" and isinstance(args, list):
                    re_search = re.search(r"%s" % args[0], text)
                    if re_search:
                        text = re_search.group(args[-1])
                if method_name == "re_sub" and isinstance(args, list):
                    text = re.sub(r"%s" % args[0], args[1], text)
                if method_name == "re_format" and isinstance(args, list):
                    text = self.__format_string(args[0], args[1], text)
                elif method_name == "split" and isinstance(args, list):
                    text = text.split(r"%s" % args[0])[args[-1]]
                elif method_name == "replace" and isinstance(args, list):
                    text = text.replace(r"%s" % args[0], r"%s" % args[-1])
                elif method_name == "dateparse" and isinstance(args, str):
                    text = datetime.datetime.strptime(text, r"%s" % args)
                elif method_name == "strip":
                    text = text.strip()
                elif method_name == "appendleft":
                    text = f"{args}{text}"
            except Exception as err:
                log.exception(f"【Spider】{self.indexername} 文本过滤出错: ")
        return text.strip()

    def __format_string(self, pattern: str, template: str, param_str: str) -> str:
        # 使用正则表达式提取所有参数
        matches = re.findall(pattern, param_str)
        if not matches:
            return template  # 如果没有匹配到，返回原模板

        # 如果匹配项是嵌套的（多个组），展平到一个列表中
        if isinstance(matches[0], tuple):
            values = [item for match in matches for item in match]
        else:
            values = matches

        # 将模板字符串中的占位符替换为提取的参数
        formatted_str = template.format(*values)
        return formatted_str

    @staticmethod
    def __remove(item, selector):
        """
        移除元素
        """
        if selector and "remove" in selector:
            removelist = selector.get("remove", "").split(", ")
            for v in removelist:
                item.remove(v)

    @staticmethod
    def __attribute_or_text(item, selector):
        if not selector:
            return item
        if not item:
            return []
        if "attribute" in selector:
            items = [i.attr(selector.get("attribute")) for i in item.items() if i]
        else:
            items = [i.text() for i in item.items() if i]
        return items

    @staticmethod
    def __index(items, selector):
        if not selector:
            return items
        if not items:
            return items
        if "contents" in selector and len(items) > int(selector.get("contents")):
            items = items[0].split("\n")[selector.get("contents")]
        elif "index" in selector and len(items) > int(selector.get("index")):
            items = items[int(selector.get("index"))]
        elif isinstance(items, list):
            items = items[0]
        return items

    def parse(self, html_text):
        """
        解析整个页面
        """
        try:
            if not html_text:
                log.warn(f"【Spider】[{self.indexername}]返回页面信息为空")
                return True, []
            
            # 获取站点文本
            html_text = html_text.replace("\u200b", "")
            if not html_text:
                return True, []
            
            # 解析站点文本对象
            html_doc = PyQuery(html_text)
            # 种子筛选器
            torrents_selector = self.list_conf.get("selector", "")
            # 遍历种子html列表
            result_list = html_doc(torrents_selector)
            if not result_list:
                log.warn(f"【Spider】[{self.indexername}]没有搜索到结果")
                return False, []

            for torn in result_list:
                torn_copy = self._getinfo(PyQuery(torn))
                if not torn_copy['title']:
                    continue
                self.torrents_info_array.append(torn_copy)
                if len(self.torrents_info_array) >= int(self.result_num):
                    break

            return False, self.torrents_info_array
        except Exception as err:
            self.is_error = True
            log.exception(f"【Spider】{self.indexername} 错误: ")
            return True, []
