import json

from typing import List, Optional

import log

from app.helper.db_helper import DbHelper
from app.models.model import UserSiteConf, SiteBaseModel, IndexerInfo
from app.utils.site_utils import SiteUtils
from app.utils.commons import singleton


@singleton
class IndexerManager:
    """
    站点索引配置管理器
    """

    _indexers : List[SiteBaseModel] = []

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
                        'parser': db_item.PARSER if db_item.PARSER else '',
                        'search': json.loads(db_item.SEARCH) if db_item.SEARCH else {},
                        'torrents': json.loads(db_item.TORRENTS) if db_item.TORRENTS else {},
                        'category': json.loads(db_item.CATEGORY) if db_item.CATEGORY else {},
                        'public': db_item.PUBLIC,
                        'extra': json.loads(db_item.EXTRA) if db_item.EXTRA else {}
                    }

                    indexer = SiteBaseModel(**indexer_data)
                    self._indexers.append(indexer)
                except Exception as e:
                    log.exception(f"【索引器】站点{db_item.NAME} 索引配置异常：")
        except Exception as err:
            log.exception("【索引器】初始化出错：")

    def get_all_indexer_base(self) -> list[SiteBaseModel]:
        """
        获取所有索引器基础配置
        """
        return self._indexers

    def get_indexer_base_by_id(self, indexer_id) -> Optional[SiteBaseModel]:
        """
        根据url获取对应的站点索引基础配置
        :param indexer_id: indexer_id
        """
        if not indexer_id:
            return None
        for indexer in self._indexers:
            if indexer.id == indexer_id:
                return indexer
        return None
    
    def get_indexer_base(self, url, public=False) -> Optional[SiteBaseModel]:
        """
        根据url获取对应的站点索引基础配置
        :param url: 详情页面地址
        :param public: 是否返回公开站点
        """
        for indexer in self._indexers:
            if not public and indexer.public:
                continue
            if SiteUtils.url_equal(indexer.domain, url):
                return indexer
        return None

    def get_public_indexer_base_by_name(self, site_name) -> Optional[SiteBaseModel]:
        """
        根据名称查询对应的公共站点基础索引配置
        :param site_name: 站点名称
        """
        for indexer in self._indexers:
            if indexer.public and indexer.name == site_name:
                return indexer
        return None

    def build_indexer_conf(self, url, site_conf:UserSiteConf=None) -> Optional[IndexerInfo]:
        """
        根据url获取并生成相应的索引器配置
        """
        if not url:
            return None
        for indexer in self._indexers:
            if not indexer.domain:
                continue
            if SiteUtils.url_equal(indexer.domain, url) == False:
                continue            
            conf_data = self.prepare_datas(site_base=indexer, public=False, site_conf=site_conf)
            return IndexerInfo.from_datas(conf_data)
        return None

    def prepare_datas(self,
                      site_base:SiteBaseModel=None,
                      site_conf:UserSiteConf=None,
                      public=None,
                      builtin=True) -> dict:

        if not site_base:
            return {}
        
        result = {}
        # 索引ID
        result["id"] = site_base.id
        # 名称
        result["name"] = site_base.name
        # 域名
        result["domain"] = site_base.domain
        # 搜索配置
        result["search"] = site_base.search
        # 解析器
        result["parser"] = site_base.parser
        # 种子过滤
        result["torrents"] = site_base.torrents or {}
        # 分类
        result["category"] = site_base.category or {}
        # 查询条件, 默认为 关键词
        result["search_param"] = 'kw'
        # 是否公开站点
        result["public"] = public if public is not None else (site_base.public or False)
        # 是否内置站点
        result["builtin"] = builtin
        # 网站资源类型
        result["source_type"] = ['MOVIE', 'TV', 'ANIME']

        if result["public"] and not site_conf:
            if site_base.extra:
                # 查询条件
                result["search_param"] = site_base.extra.get('search_param', 'kw')
                # 是否使用英文名进行扩展搜索
                result["en_expand"] = site_base.extra.get('en_expand', False)
                # 网站资源类型
                if site_base.extra.get('source_type'):
                    result["source_type"] = site_base.extra.get('source_type').split(',')
                if site_base.extra.get('proxy'):
                    result["proxy"] = site_base.extra.get('proxy', False)
                if site_base.extra.get('render'):
                    result["render"] = site_base.extra.get('render', False)
        elif site_conf:
            # 站点ID
            result["siteid"] = site_conf.id
            # 名称
            result["name"] = site_conf.name
            # 授权参数
            result["cookie"] = site_conf.cookie
            result["token"] = site_conf.token
            result["apikey"] = site_conf.apikey
            # User-Agent
            result["ua"] = site_conf.ua
            # 过滤规则
            result["rule"] = site_conf.rule
            # 索引器优先级
            result["pri"] = site_conf.pri if site_conf.pri else 0
            # 是否使用代理
            result["proxy"] = site_conf.proxy
            # 是否启用渲染
            result["render"] = site_conf.chrome
            # 网站资源类型
            if site_conf.source_type:
                result["source_type"] = site_conf.source_type

        return result

    def add_indexer(self, data: dict):
        """
        新增索引站点，操作DB并重载配置
        """
        is_public = data.get('public')
        extra_json = self.__build_extra_json(data) if is_public else ''
        DbHelper().add_indexer(
            data.get('id'),
            data.get('name'),
            data.get('domain'),
            data.get('search'),
            data.get('torrents'),
            data.get('parser'),
            data.get('category'),
            is_public,
            extra_json
        )
        self.init_config()

    def update_indexer(self, data: dict) -> bool:
        """
        更新索引站点，操作DB并重载配置
        """

        indexer_id = data.get('id')
        if not indexer_id:
            return False

        indexer_info = self.get_indexer_base_by_id(indexer_id)
        if not indexer_info:
            return False

        extra_json = self.__build_extra_json(data) if indexer_info.public else ''
        success = DbHelper().update_indexer(
            indexer_id,
            data.get('domain'),
            data.get('search'),
            data.get('torrents'),
            data.get('parser'),
            data.get('category'),
            extra_json
        )
        if success:
            self.init_config()
        return success

    def delete_indexer(self, siteid):
        """
        删除索引站点，操作DB并重载配置
        """
        DbHelper().delete_indexer(siteid)
        self.init_config()

    @staticmethod
    def __build_extra_json(data: dict):
        """
        构建extra字段的JSON字符串
        """
        extra_config = {
            'render': data.get('render', False),
            'proxy': data.get('proxy', False),
            'en_expand': data.get('en_expand', False),
            'source_type': data.get('source_type', ''),
            'search_param': data.get('search_param'),
        }
        return json.dumps(extra_config)