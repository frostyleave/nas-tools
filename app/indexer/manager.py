import log
from app.helper import DbHelper
from app.helper.json_helper import JsonHelper
from app.utils import StringUtils
from app.utils.commons import singleton

@singleton
class IndexerManager:
    _indexers = []

    def __init__(self):
        self.init_config()

    def init_config(self):
        try:
            self._indexers = []
            db_indexers = DbHelper().get_indexers()
            for db_item in db_indexers:
                indexer = {
                    'id': db_item.ID,
                    'name': db_item.NAME,
                    'domain': db_item.DOMAIN,
                    'search': JsonHelper.de_json(db_item.SEARCH) if db_item.SEARCH else None,
                    'parser': db_item.PARSER,
                    'render': db_item.RENDER,
                    'browse': JsonHelper.de_json(db_item.BROWSE) if db_item.BROWSE else None,
                    'torrents': JsonHelper.de_json(db_item.TORRENTS) if db_item.TORRENTS else None,
                    'category': JsonHelper.de_json(db_item.CATEGORY) if db_item.CATEGORY else None,
                    'source_type': db_item.SOURCE_TYPE.split(',') if db_item.SOURCE_TYPE else [],
                    'search_type': db_item.SEARCH_TYPE.split(',') if db_item.SEARCH_TYPE else [],
                    'downloader': db_item.DOWNLOADER,
                    'public': db_item.PUBLIC,
                    'proxy': db_item.PROXY
                }
                self._indexers.append(indexer)
        except Exception as err:
            log.error("【索引器】初始化出错：" + str(err))

    def get_all_indexers(self):
        return self._indexers

    def get_indexer_info(self, url, public=False):
        for indexer in self._indexers:
            if not public and indexer.get("public"):
                continue
            if StringUtils.url_equal(indexer.get("domain"), url):
                return indexer
        return None

    def get_indexer(self,
                    url,
                    siteid=None,
                    cookie=None,
                    name=None,
                    rule=None,
                    public=None,
                    proxy=None,
                    parser=None,
                    ua=None,
                    render=None,
                    pri=None):
        if not url:
            return None
        for indexer in self._indexers:
            if not indexer.get("domain"):
                continue
            if StringUtils.url_equal(indexer.get("domain"), url):
                return IndexerConf(datas=indexer,
                                   siteid=siteid,
                                   cookie=cookie,
                                   name=name,
                                   rule=rule,
                                   public=public,
                                   proxy=proxy,
                                   parser=parser,
                                   ua=ua,
                                   render=render,
                                   builtin=True,
                                   pri=pri)
        return None


class IndexerConf(object):

    def __init__(self,
                 datas=None,
                 name=None,
                 public=True,
                 proxy=None,
                 parser=None,
                 render=None,
                 builtin=True,
                 ua=None,
                 siteid=None,
                 cookie=None,
                 rule=None,
                 pri=None):
        if not datas:
            return
        # 索引ID
        self.id = datas.get('id')
        # 名称
        self.name = name if name else datas.get('name')
        # 域名
        self.domain = datas.get('domain')
        # 搜索
        self.search = datas.get('search', {})
        # 批量搜索，如果为空对象则表示不支持批量搜索
        self.batch = self.search.get("batch", {}) if builtin else {}
        # 是否启用渲染
        self.render = render if render is not None else datas.get("render", False)
        # 解析器
        self.parser = parser if parser is not None else datas.get('parser')
        if self.parser == 'RenderSpider':
            self.render = True
        # 浏览
        self.browse = datas.get('browse', {})
        # 种子过滤
        self.torrents = datas.get('torrents', {})
        # 分类
        self.category = datas.get('category')
        # 网站资源类型
        self.source_type = datas.get('source_type', ['MOVIE', 'TV', 'ANIME'])
        # 支持的搜索类型, 为空默认为标题、英文名
        self.search_type = datas.get('search_type', ['title'])
        # 是否公开站点
        self.public = datas.get('public', public)
        # 是否使用代理
        self.proxy = proxy if proxy is not None else datas.get('proxy', False)
        # 指定下载器
        self.downloader = datas.get('downloader')
        # 是否内置站点
        self.builtin = builtin
        # 站点ID
        self.siteid = siteid
        # Cookie
        self.cookie = cookie
        # User-Agent
        self.ua = ua
        # 过滤规则
        self.rule = rule
        # 索引器优先级
        self.pri = pri if pri else 0
