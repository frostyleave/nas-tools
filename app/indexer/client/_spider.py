import chardet
import copy
import datetime
import re
from urllib.parse import quote, urlencode

from jinja2 import Template
from pyquery import PyQuery

from app.utils.system_utils import SystemUtils
import log

from app.indexer.client.browser import PlaywrightHelper, WaitElement
from app.utils import StringUtils, RequestUtils
from app.utils.exception_utils import ExceptionUtils
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
    search = {}
    # 批量搜索配置
    batch = {}
    # 浏览配置
    browse = {}
    # 站点分类配置
    category = {}
    # 站点种子列表配置
    list = {}
    # 站点种子字段配置
    fields = {}
    # 页码
    page = 0
    # 搜索条数
    result_num = 100
    # 单个种子信息
    torrents_info = {}
    # 种子列表
    torrents_info_array = []
    # 加载等待元素
    wait_element = None
    timeout = 20

    def __init__(self, indexer, referer=None):

        self.torrents_info_array = []
        self.result_num = Config().get_config('pt').get('site_search_result_num') or 100
        # 索引器
        if indexer:
            self._indexer = indexer
            self.indexerid = indexer.id
            self.indexername = indexer.name
            self.search = indexer.search
            self.batch = indexer.batch
            self.browse = indexer.browse
            self.category = indexer.category
            self.list = indexer.torrents.get("list", {})
            self.fields = indexer.torrents.get("fields")
            self.render = indexer.render
            self.domain = indexer.domain
            if self.domain and not str(self.domain).endswith("/"):
                self.domain = self.domain + "/"
            if indexer.ua:
                self.ua = indexer.ua
            else:
                self.ua = Config().get_ua()
            if indexer.proxy:
                self.proxies = Config().get_proxies()
            if indexer.cookie:
                self.cookie = RequestUtils.cookie_parse(indexer.cookie)

            wait_navigation = self.search.get('navigation')
            if wait_navigation:
                wait_pair = StringUtils.split_and_filter(wait_navigation, ":")
                if len(wait_pair) == 2:
                    self.wait_element = WaitElement(wait_pair[0], wait_pair[1])

        if referer:
            self.referer = referer

    def search_torrents(self, keyword: [str, list] = None, page=None, mtype=None):
        """
        页面查询
        :param keyword: 搜索关键字，如果数组则为批量搜索
        :param page: 页码
        :param referer: Referer
        :param mtype: 媒体类型
        """
        if not self.search or not self.domain:
            return False, []
        
        searchurl = self.build_search_url(keyword, page, mtype)

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
        
        html_content = self.sample_request(searchurl)
        return self.parse(html_content)
    

    def build_search_url(self, keyword: [str, list] = None, page=None, mtype=None):
        """
        构建请求地址
        """
        # 种子搜索相对路径
        paths = self.search.get("paths", [])
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
            if isinstance(keyword, list):
                # 批量查询
                if self.batch:
                    delimiter = self.batch.get("delimiter") or " "
                    space_replace = self.batch.get("space_replace") or " "
                    search_word = delimiter.join(
                        [str(k).replace(" ", space_replace) for k in keyword]
                    )
                else:
                    search_word = " ".join(keyword)
                # 查询模式：或
                search_mode = "1"
            else:
                # 单个查询
                search_word = keyword
                # 查询模式与
                search_mode = "0"

            # 搜索URL
            if self.search.get("params"):
                # 变量字典
                inputs_dict = {"keyword": search_word}
                # 查询参数
                params = {
                    "search_mode": search_mode,
                    "page": page or 0,
                    "notnewword": 1,
                }
                # 额外参数
                for key, value in self.search.get("params").items():
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

    
    def sample_request(self, searchurl):
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
                log.warn(f"chardet解码失败: {str(e)}")
                # 探测utf-8解码
                if re.search(r"charset=\"?utf-8\"?", ret.text, re.IGNORECASE):
                    ret.encoding = "utf-8"
                else:
                    ret.encoding = ret.apparent_encoding
                return ret.text
        else:
            return ret.text

    def Gettitle_default(self, torrent):
        # title default
        if "title" not in self.fields:
            return
        selector = self.fields.get("title", {})
        if "selector" in selector:
            title = torrent(selector.get("selector", "")).clone()
            self.__remove(title, selector)
            items = self.__attribute_or_text(title, selector)
            self.torrents_info["title"] = self.__index(items, selector)
        elif "text" in selector:
            render_dict = {}
            if "title_default" in self.fields:
                title_default_selector = self.fields.get("title_default", {})
                title_default_item = torrent(
                    title_default_selector.get("selector", "")
                ).clone()
                self.__remove(title_default_item, title_default_selector)
                items = self.__attribute_or_text(title_default_item, selector)
                title_default = self.__index(items, title_default_selector)
                render_dict.update({"title_default": title_default})
            if "title_optional" in self.fields:
                title_optional_selector = self.fields.get("title_optional", {})
                title_optional_item = torrent(
                    title_optional_selector.get("selector", "")
                ).clone()
                self.__remove(title_optional_item, title_optional_selector)
                items = self.__attribute_or_text(
                    title_optional_item, title_optional_selector
                )
                title_optional = self.__index(items, title_optional_selector)
                render_dict.update({"title_optional": title_optional})
            self.torrents_info["title"] = Template(selector.get("text")).render(
                fields=render_dict
            )
        self.torrents_info["title"] = self.__filter_text(
            self.torrents_info.get("title"), selector.get("filters")
        )

    def Gettitle_optional(self, torrent):
        # title optional
        if "description" not in self.fields:
            return
        selector = self.fields.get("description", {})
        if "selector" in selector or "selectors" in selector:
            description = torrent(
                selector.get("selector", selector.get("selectors", ""))
            ).clone()
            if description:
                self.__remove(description, selector)
                items = self.__attribute_or_text(description, selector)
                self.torrents_info["description"] = self.__index(items, selector)
        elif "text" in selector:
            render_dict = {}
            if "tags" in self.fields:
                tags_selector = self.fields.get("tags", {})
                tags_item = torrent(tags_selector.get("selector", "")).clone()
                self.__remove(tags_item, tags_selector)
                items = self.__attribute_or_text(tags_item, tags_selector)
                tag = self.__index(items, tags_selector)
                render_dict.update({"tags": tag})
            if "subject" in self.fields:
                subject_selector = self.fields.get("subject", {})
                subject_item = torrent(subject_selector.get("selector", "")).clone()
                self.__remove(subject_item, subject_selector)
                items = self.__attribute_or_text(subject_item, subject_selector)
                subject = self.__index(items, subject_selector)
                render_dict.update({"subject": subject})
            if "description_free_forever" in self.fields:
                description_free_forever_selector = self.fields.get(
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
            if "description_normal" in self.fields:
                description_normal_selector = self.fields.get("description_normal", {})
                description_normal_item = torrent(
                    description_normal_selector.get("selector", "")
                ).clone()
                self.__remove(description_normal_item, description_normal_selector)
                items = self.__attribute_or_text(
                    description_normal_item, description_normal_selector
                )
                description_normal = self.__index(items, description_normal_selector)
                render_dict.update({"description_normal": description_normal})
            self.torrents_info["description"] = Template(selector.get("text")).render(
                fields=render_dict
            )
        self.torrents_info["description"] = self.__filter_text(
            self.torrents_info.get("description"), selector.get("filters")
        )

    def Getdetails(self, torrent):
        # details
        if "details" not in self.fields:
            return
        selector = self.fields.get("details", {})
        details = torrent(selector.get("selector", "")).clone()
        self.__remove(details, selector)
        items = self.__attribute_or_text(details, selector)
        item = self.__index(items, selector)
        detail_link = self.__filter_text(item, selector.get("filters"))
        if detail_link:
            if not detail_link.startswith("http"):
                if detail_link.startswith("//"):
                    self.torrents_info["page_url"] = (
                        self.domain.split(":")[0] + ":" + detail_link
                    )
                elif detail_link.startswith("/"):
                    self.torrents_info["page_url"] = self.domain + detail_link[1:]
                else:
                    self.torrents_info["page_url"] = self.domain + detail_link
            else:
                self.torrents_info["page_url"] = detail_link

    def Getdownload(self, torrent):
        # download link
        if "download" not in self.fields:
            return
        selector = self.fields.get("download", {})

        if "detail" in selector:
            detail = selector.get("detail", {})
            if "xpath" in detail:
                self.torrents_info["enclosure"] = (
                    f'[{detail.get("xpath", "")}'
                    f'|{self.cookie or ""}'
                    f'|{self.ua or ""}'
                    f'|{self.referer or ""}]'
                )
            elif "hash" in detail:
                self.torrents_info["enclosure"] = (
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
                    self.torrents_info["enclosure"] = (
                        self.domain + download_link[1:]
                        if download_link.startswith("/")
                        else self.domain + download_link
                    )
                else:
                    self.torrents_info["enclosure"] = download_link

    def Getimdbid(self, torrent):
        # imdbid
        if "imdbid" not in self.fields:
            return
        selector = self.fields.get("imdbid", {})
        imdbid = torrent(selector.get("selector", "")).clone()
        self.__remove(imdbid, selector)
        items = self.__attribute_or_text(imdbid, selector)
        item = self.__index(items, selector)
        self.torrents_info["imdbid"] = item
        self.torrents_info["imdbid"] = self.__filter_text(
            self.torrents_info.get("imdbid"), selector.get("filters")
        )

    def Getsize(self, torrent):
        # torrent size
        if "size" not in self.fields:
            return
        selector = self.fields.get("size", {})
        size = torrent(selector.get("selector", selector.get("selectors", ""))).clone()
        self.__remove(size, selector)
        items = self.__attribute_or_text(size, selector)
        item = self.__index(items, selector)
        item = self.__filter_text(item, selector.get("filters"))
        if item:
            self.torrents_info["size"] = StringUtils.num_filesize(
                item.replace("\n", "").strip()
            )
            self.torrents_info["size"] = self.__filter_text(
                self.torrents_info.get("size"), selector.get("filters")
            )
            self.torrents_info["size"] = StringUtils.num_filesize(
                self.torrents_info.get("size")
            )

    def Getleechers(self, torrent):
        # torrent leechers
        if "leechers" not in self.fields:
            return
        selector = self.fields.get("leechers", {})
        leechers = torrent(selector.get("selector", "")).clone()
        self.__remove(leechers, selector)
        items = self.__attribute_or_text(leechers, selector)
        item = self.__index(items, selector)
        if item:
            self.torrents_info["peers"] = item.split("/")[0]
            self.torrents_info["peers"] = self.__filter_text(
                self.torrents_info.get("peers"), selector.get("filters")
            )
        else:
            self.torrents_info["peers"] = 0

    def Getseeders(self, torrent):
        # torrent leechers
        if "seeders" not in self.fields:
            return
        selector = self.fields.get("seeders", {})
        seeders = torrent(selector.get("selector", "")).clone()
        self.__remove(seeders, selector)
        items = self.__attribute_or_text(seeders, selector)
        item = self.__index(items, selector)
        if item:
            self.torrents_info["seeders"] = item.split("/")[0]
            self.torrents_info["seeders"] = self.__filter_text(
                self.torrents_info.get("seeders"), selector.get("filters")
            )
        else:
            self.torrents_info["seeders"] = 0

    def Getgrabs(self, torrent):
        # torrent grabs
        if "grabs" not in self.fields:
            return
        selector = self.fields.get("grabs", {})
        grabs = torrent(selector.get("selector", "")).clone()
        self.__remove(grabs, selector)
        items = self.__attribute_or_text(grabs, selector)
        item = self.__index(items, selector)
        if item:
            self.torrents_info["grabs"] = item.split("/")[0]
            self.torrents_info["grabs"] = self.__filter_text(
                self.torrents_info.get("grabs"), selector.get("filters")
            )
        else:
            self.torrents_info["grabs"] = 0

    def Getpubdate(self, torrent):
        # torrent pubdate
        if "date_added" not in self.fields:
            return
        selector = self.fields.get("date_added", {})
        pubdate = torrent(selector.get("selector", "")).clone()
        self.__remove(pubdate, selector)
        items = self.__attribute_or_text(pubdate, selector)
        self.torrents_info["pubdate"] = self.__index(items, selector)
        self.torrents_info["pubdate"] = self.__filter_text(
            self.torrents_info.get("pubdate"), selector.get("filters")
        )

    def Getelapsed_date(self, torrent):
        # torrent pubdate
        if "date_elapsed" not in self.fields:
            return
        selector = self.fields.get("date_elapsed", {})
        date_elapsed = torrent(selector.get("selector", "")).clone()
        self.__remove(date_elapsed, selector)
        items = self.__attribute_or_text(date_elapsed, selector)
        self.torrents_info["date_elapsed"] = self.__index(items, selector)
        self.torrents_info["date_elapsed"] = self.__filter_text(
            self.torrents_info.get("date_elapsed"), selector.get("filters")
        )

    def Getdownloadvolumefactor(self, torrent):
        # downloadvolumefactor
        selector = self.fields.get("downloadvolumefactor", {})
        if not selector:
            return
        self.torrents_info["downloadvolumefactor"] = 1
        if "case" in selector:
            for downloadvolumefactorselector in list(selector.get("case", {}).keys()):
                downloadvolumefactor = torrent(downloadvolumefactorselector)
                if len(downloadvolumefactor) > 0:
                    self.torrents_info["downloadvolumefactor"] = selector.get(
                        "case", {}
                    ).get(downloadvolumefactorselector)
                    break
        elif "selector" in selector:
            downloadvolume = torrent(selector.get("selector", "")).clone()
            self.__remove(downloadvolume, selector)
            items = self.__attribute_or_text(downloadvolume, selector)
            item = self.__index(items, selector)
            if item:
                downloadvolumefactor = re.search(r"(\d+\.?\d*)", item)
                if downloadvolumefactor:
                    self.torrents_info["downloadvolumefactor"] = int(
                        downloadvolumefactor.group(1)
                    )

    def Getuploadvolumefactor(self, torrent):
        # uploadvolumefactor
        selector = self.fields.get("uploadvolumefactor", {})
        if not selector:
            return
        self.torrents_info["uploadvolumefactor"] = 1
        if "case" in selector:
            for uploadvolumefactorselector in list(selector.get("case", {}).keys()):
                uploadvolumefactor = torrent(uploadvolumefactorselector)
                if len(uploadvolumefactor) > 0:
                    self.torrents_info["uploadvolumefactor"] = selector.get(
                        "case", {}
                    ).get(uploadvolumefactorselector)
                    break
        elif "selector" in selector:
            uploadvolume = torrent(selector.get("selector", "")).clone()
            self.__remove(uploadvolume, selector)
            items = self.__attribute_or_text(uploadvolume, selector)
            item = self.__index(items, selector)
            if item:
                uploadvolumefactor = re.search(r"(\d+\.?\d*)", item)
                if uploadvolumefactor:
                    self.torrents_info["uploadvolumefactor"] = int(
                        uploadvolumefactor.group(1)
                    )

    def Getlabels(self, torrent):
        # labels
        if "labels" not in self.fields:
            return
        selector = self.fields.get("labels", {})
        labels = torrent(selector.get("selector", "")).clone()
        self.__remove(labels, selector)
        items = self.__attribute_or_text(labels, selector)
        if items:
            self.torrents_info["labels"] = "|".join(items)

    def Getinfo(self, torrent):
        """
        解析单条种子数据
        """
        self.torrents_info = {"indexer": self.indexerid}
        try:
            self.Gettitle_default(torrent)
            self.Gettitle_optional(torrent)
            self.Getdetails(torrent)
            self.Getdownload(torrent)
            self.Getgrabs(torrent)
            self.Getleechers(torrent)
            self.Getseeders(torrent)
            self.Getsize(torrent)
            self.Getimdbid(torrent)
            self.Getdownloadvolumefactor(torrent)
            self.Getuploadvolumefactor(torrent)
            self.Getpubdate(torrent)
            self.Getelapsed_date(torrent)
            self.Getlabels(torrent)
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            log.error("【Spider】%s 搜索出现错误：%s" % (self.indexername, str(err)))
        return self.torrents_info

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
                    text = self.format_string(args[0], args[1], text)
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
                ExceptionUtils.exception_traceback(err)
        return text.strip()

    def format_string(self, pattern: str, template: str, param_str: str) -> str:
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
                return False, []
            # 获取站点文本
            html_text = html_text.replace("\u200b", "")
            if not html_text:
                return False, []
            # 解析站点文本对象
            html_doc = PyQuery(html_text)
            # 种子筛选器
            torrents_selector = self.list.get("selector", "")
            # 遍历种子html列表
            result_list = html_doc(torrents_selector)
            if not result_list:
                log.warn(f"【Spider】[{self.indexername}]没有搜索到结果")
                return False, []

            for torn in result_list:
                torn_copy = copy.deepcopy(self.Getinfo(PyQuery(torn)))
                if not torn_copy['title']:
                    continue
                self.torrents_info_array.append(torn_copy)
                if len(self.torrents_info_array) >= int(self.result_num):
                    break

            return True, self.torrents_info_array
        except Exception as err:
            self.is_error = True
            ExceptionUtils.exception_traceback(err)
            log.warn(f"【Spider】{self.indexername} 错误: {str(err)}")
            return False, []
