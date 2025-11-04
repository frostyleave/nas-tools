import json

from typing import List, Optional
from pydantic import BaseModel

import log

from app.helper import DbHelper
from app.utils import SiteUtils
from app.utils.commons import singleton

class IndexerBase(BaseModel):
    """
    站点索引基础配置
    """
    id: str = ''
    name: str = ''
    domain: str = ''
    render: bool = False
    public: bool = True
    proxy: bool = False
    en_expand: bool = False

    search: Optional[dict] = None
    torrents: Optional[dict] = None
    source_type: List[str]
    search_type: str = ''
    parser: Optional[str] = None
    browse: Optional[dict] = None
    category: Optional[dict] = None


class IndexerInfo(BaseModel):

    id: Optional[str] = None
    name: Optional[str] = None
    domain: Optional[str] = None
    search: dict
    torrents: dict
    render: bool = False
    parser: Optional[str] = None
    browse: Optional[dict] = None
    category: Optional[dict] = None
    source_type: List[str]
    search_type: str
    public: bool = True
    en_expand: bool = False
    proxy: bool = False
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
    """
    站点索引配置管理器
    """

    _indexers : List[IndexerBase] = []

    def __init__(self):
        self.init_config()

    def init_config(self):
        """
        初始化: 加载所有站点索引信息
        """
        try:
            self._indexers = []
            db_indexers = DbHelper().get_indexers()

            for db_item in db_indexers:
                try:
                    indexer_data = {
                        'id': db_item.ID,
                        'name': db_item.NAME,
                        'domain': db_item.DOMAIN,
                        'search': json.loads(db_item.SEARCH) if db_item.SEARCH else {},
                        'parser': db_item.PARSER if db_item.PARSER else '',
                        'render': db_item.RENDER,
                        'browse': json.loads(db_item.BROWSE) if db_item.BROWSE else {},
                        'torrents': json.loads(db_item.TORRENTS) if db_item.TORRENTS else {},
                        'category': json.loads(db_item.CATEGORY) if db_item.CATEGORY else {},
                        'source_type': db_item.SOURCE_TYPE.split(',') if db_item.SOURCE_TYPE else [],
                        'search_type': db_item.SEARCH_TYPE,
                        'downloader': db_item.DOWNLOADER,
                        'public': db_item.PUBLIC,
                        'proxy': db_item.PROXY,
                        'en_expand': db_item.EN_EXPAND or False
                    }
                    indexer = IndexerBase(**indexer_data)
                    self._indexers.append(indexer)
                except Exception as e:
                    log.exception(f"【索引器】站点{db_item.NAME} 索引配置异常：", e)
        except Exception as err:
            log.exception("【索引器】初始化出错：", err)

    def get_all_indexer_base(self) -> list[IndexerBase]:
        """
        获取所有索引器基础配置
        """
        return self._indexers

    def get_indexer_base(self, url, public=False) -> Optional[IndexerBase]:
        """
        根据url获取对应的站点索引基础配置
        :param url: 详情页面地址
        :param public: 是否为公开站点
        """
        for indexer in self._indexers:
            if not public and indexer.public:
                continue
            if SiteUtils.url_equal(indexer.domain, url):
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
                    pri=None) -> Optional[IndexerInfo]:
        """
        根据url获取并生成相应的索引器配置
        """
        if not url:
            return None
        for indexer in self._indexers:
            if not indexer.domain:
                continue
            if SiteUtils.url_equal(indexer.domain, url):
                conf_data = self.prepare_datas(conf_data=indexer,
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
                return IndexerInfo.from_datas(conf_data)
        return None

    def prepare_datas(self,
                      conf_data : IndexerBase =None,
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

        if conf_data:
            # 索引ID
            result["id"] = conf_data.id
            # 名称
            result["name"] = name if name else conf_data.name
            # 域名
            result["domain"] = conf_data.domain
            # 搜索
            result["search"] = conf_data.search

            # 是否启用渲染
            result["render"] = render if render is not None else (conf_data.render or False)
            # 解析器
            result["parser"] = parser or conf_data.parser
            if result["parser"] == 'RenderSpider':
                result["render"] = True
                result["parser"] = ''

            # 是否使用代理
            result["proxy"] = proxy if proxy is not None else (conf_data.proxy or False)

            # 浏览
            result["browse"] = conf_data.browse or {}
            # 种子过滤
            result["torrents"] = conf_data.torrents or {}
            # 分类
            result["category"] = conf_data.category or {}
            # 网站资源类型
            result["source_type"] = conf_data.source_type or ['MOVIE', 'TV', 'ANIME']
            # 支持的搜索类型, 为空默认为标题、英文名
            result["search_type"] = conf_data.search_type or 'title'
            # 是否公开站点
            result["public"] = public if public is not None else (conf_data.public or False)
            # 是否使用英文名进行扩展搜索
            result["en_expand"] = conf_data.en_expand or False

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