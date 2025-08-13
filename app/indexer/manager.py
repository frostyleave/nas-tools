from typing import Dict, List, Optional
from pydantic import BaseModel

import log

from app.helper import DbHelper
from app.helper.json_helper import JsonHelper
from app.utils import SiteUtils
from app.utils.commons import singleton


class IndexerConf(BaseModel):

    id: Optional[str] = None
    name: Optional[str] = None
    domain: Optional[str] = None
    search: dict
    torrents: dict
    batch:  Optional[dict] = None
    render: bool = False
    parser: Optional[str] = None
    browse: Optional[dict] = None
    category: Optional[dict] = None
    source_type: List[str]
    search_type: str
    public: bool = True
    en_expand: bool = False
    proxy: bool = False
    downloader: Optional[int] = None
    builtin: bool = True
    siteid: Optional[int] = None
    cookie: Optional[str] = None
    token: Optional[str] = None
    apikey: Optional[str] = None
    ua: Optional[str] = None
    rule: Optional[str] = None
    pri: Optional[int] = None
    timeout : int = 15


    @classmethod
    def from_datas(cls, datas: Optional[dict] = None, **kwargs):
        merged = {}
        if datas:
            merged.update(datas)
        merged.update(kwargs)
        return cls(**merged)



@singleton
class IndexerManager:
    _indexers = []

    def __init__(self):
        self.init_config()

    def init_config(self):
        """
        初始化: 加载所有索引站点
        """
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
                    'search_type': db_item.SEARCH_TYPE,
                    'downloader': db_item.DOWNLOADER,
                    'public': db_item.PUBLIC,
                    'proxy': db_item.PROXY,
                    'en_expand': db_item.EN_EXPAND
                }
                self._indexers.append(indexer)
        except Exception as err:
            log.error("【索引器】初始化出错：" + str(err))

    def get_all_indexers(self) -> list[Dict]:
        """
        获取所有索引器
        """
        return self._indexers

    def get_indexer_info(self, url, public=False) -> Optional[Dict]:
        """
        根据url获取对应的索引器
        :param url: 详情页面地址
        :param public: 是否为公开索引站点
        """
        for indexer in self._indexers:
            if not public and indexer.get("public"):
                continue
            if SiteUtils.url_equal(indexer.get("domain"), url):
                return indexer
        return None

    def build_indexer_conf(self,
                    url,
                    siteid=None,
                    cookie=None,
                    token=None,
                    apikey=None,
                    name=None,
                    rule=None,
                    public=None,
                    proxy=None,
                    parser=None,
                    ua=None,
                    render=None,
                    pri=None) -> Optional[IndexerConf]:
        """
        根据url获取对应的索引器配置
        """
        if not url:
            return None
        for indexer in self._indexers:
            if not indexer.get("domain"):
                continue
            if SiteUtils.url_equal(indexer.get("domain"), url):
                conf_data = self.prepare_datas(datas=indexer,
                                   siteid=siteid,
                                   cookie=cookie,
                                   token=token,
                                   apikey=apikey,
                                   name=name,
                                   rule=rule,
                                   public=public,
                                   proxy=proxy,
                                   parser=parser,
                                   ua=ua,
                                   render=render,
                                   builtin=True,
                                   pri=pri)
                return IndexerConf.from_datas(conf_data)
        return None

    def prepare_datas(self,
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
                      token=None,
                      apikey=None,
                      rule=None,
                      pri=None):

        result = {}

        if datas:
            # 索引ID
            result["id"] = datas.get('id')
            # 名称
            result["name"] = name if name else datas.get('name')
            # 域名
            result["domain"] = datas.get('domain')
            # 搜索
            result["search"] = datas.get('search', {})
            # 批量搜索，如果为空对象则表示不支持批量搜索
            result["batch"] = result["search"].get("batch", {}) if builtin else {}
            # 是否启用渲染
            result["render"] = render if render is not None else datas.get("render", False)
            # 解析器
            result["parser"] = parser if parser is not None else datas.get('parser')
            if result["parser"] == 'RenderSpider':
                result["render"] = True
                result["parser"] = ''
            # 浏览
            result["browse"] = datas.get('browse', {})
            # 种子过滤
            result["torrents"] = datas.get('torrents', {})
            # 分类
            result["category"] = datas.get('category')
            # 网站资源类型
            result["source_type"] = datas.get('source_type', ['MOVIE', 'TV', 'ANIME'])
            # 支持的搜索类型, 为空默认为标题、英文名
            result["search_type"] = datas.get('search_type', 'title')
            # 是否公开站点
            result["public"] = datas.get('public', public)
            # 是否使用英文名进行扩展搜索
            result["en_expand"] = datas.get('en_expand', False)
            # 是否使用代理
            result["proxy"] = proxy if proxy is not None else datas.get('proxy', False)
            # 指定下载器
            result["downloader"] = datas.get('downloader')
            # 是否内置站点
            result["builtin"] = builtin
            # 站点ID
            result["siteid"] = siteid
            # Cookie
            result["cookie"] = cookie
            result["token"] = token
            result["apikey"] = apikey
            # User-Agent
            result["ua"] = ua
            # 过滤规则
            result["rule"] = rule
            # 索引器优先级
            result["pri"] = pri if pri else 0

        return result