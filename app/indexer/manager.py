import json

import log
from app.helper.db_helper import DbHelper
from app.models.model import IndexerInfo, SiteBaseModel, UserSiteConf
from app.utils.commons import singleton
from app.utils.site_utils import SiteUtils


@singleton
class IndexerManager:
    """
    站点索引配置管理器
    """

    # 基础索引配置ID：站点匹配不到具体索引器时兜底使用，禁止修改
    BASE_INDEXER_ID = "_nexus_"

    _indexers : list[SiteBaseModel]

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

    def get_indexer_base_by_id(self, indexer_id) -> SiteBaseModel | None:
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

    def get_base_indexer(self) -> SiteBaseModel | None:
        """
        获取基础索引配置（站点匹配不到具体索引器时兜底）
        """
        return self.get_indexer_base_by_id(self.BASE_INDEXER_ID)

    @classmethod
    def is_base_indexer_id(cls, indexer_id) -> bool:
        """
        是否为基础索引配置ID（包含按站点派生的ID）
        """
        if not indexer_id:
            return False
        return indexer_id == cls.BASE_INDEXER_ID \
            or indexer_id.startswith(f"{cls.BASE_INDEXER_ID}@")

    @classmethod
    def build_site_indexer_id(cls, site_id) -> str:
        """
        派生某站点使用基础索引配置时的独立索引ID
        """
        return f"{cls.BASE_INDEXER_ID}@{site_id}"

    def __match_indexer(self, url, include_public=True) -> SiteBaseModel | None:
        """
        根据url匹配站点索引基础配置
        按主机名精确匹配（忽略协议、端口和 www. 前缀）
        """
        if not url:
            return None
        for indexer in self._indexers:
            if not indexer.domain:
                continue
            if not include_public and indexer.public:
                continue
            if SiteUtils.url_equal(indexer.domain, url):
                return indexer
        return None

    def get_indexer_base(self, url, public=False) -> SiteBaseModel | None:
        """
        根据url获取对应的站点索引基础配置
        :param url: 详情页面地址
        :param public: 是否返回公开站点
        """
        return self.__match_indexer(url, include_public=public)

    def get_public_indexer_base_by_name(self, site_name) -> SiteBaseModel | None:
        """
        根据名称查询对应的公共站点基础索引配置
        :param site_name: 站点名称
        """
        for indexer in self._indexers:
            if indexer.public and indexer.name == site_name:
                return indexer
        return None

    def build_indexer_conf(self, url, site_conf:UserSiteConf=None) -> IndexerInfo | None:
        """
        根据url获取并生成相应的索引器配置
        匹配不到具体索引器时，站点配置使用基础索引配置兜底
        """
        indexer = self.__match_indexer(url)
        if indexer:
            conf_data = self.prepare_datas(site_base=indexer, public=False, site_conf=site_conf)
            return IndexerInfo.from_datas(conf_data)

        if not site_conf:
            return None

        base_indexer = self.get_base_indexer()
        if not base_indexer:
            return None

        conf_data = self.prepare_datas(site_base=base_indexer, public=False, site_conf=site_conf)
        # 基础配置是通用模板：索引ID按站点派生，域名使用站点实际地址
        conf_data["id"] = self.build_site_indexer_id(site_conf.id)
        conf_data["domain"] = site_conf.strict_url or SiteUtils.get_base_url(
            site_conf.signurl or site_conf.rssurl)
        return IndexerInfo.from_datas(conf_data)

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
        indexer_id = data.get('id')
        if not indexer_id:
            return False, '索引站点id不能为空'

        if self.is_base_indexer_id(indexer_id):
            return False, '基础索引配置ID不可使用'

        indexer_info = self.get_indexer_base_by_id(indexer_id)
        if indexer_info:
            return False, '索引站点id重复'

        if not data.get('name') or \
            not data.get('domain') or \
            not data.get('search') or \
            not data.get('torrents') or \
            not data.get('category'):
            return False, '索引站点配置参数不能有空值'
        
        is_public = data.get('public', False)
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
        # 新增索引器后只需补全尚未关联索引器的站点，已有正常关联的站点保持不变
        self.__refresh_site_links(missing_only=True)
        return True, '索引配置已添加'

    def update_indexer(self, data: dict) -> bool:
        """
        更新索引站点，操作DB并重载配置
        """

        indexer_id = data.get('id')
        if not indexer_id:
            return False

        if self.is_base_indexer_id(indexer_id):
            log.warn("【索引器】基础索引配置不允许修改")
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
            self.__refresh_site_links()
        return success

    def delete_indexer(self, siteid):
        """
        删除索引站点，操作DB并重载配置
        """
        if self.is_base_indexer_id(siteid):
            log.warn("【索引器】基础索引配置不允许删除")
            return False
        DbHelper().delete_indexer(siteid)
        self.init_config()
        self.__refresh_site_links()
        return True

    @staticmethod
    def __refresh_site_links(missing_only=False):
        """
        索引器变更后刷新站点的索引器关联（延迟导入，避免模块循环依赖）
        :param missing_only: 只处理尚未关联索引器的站点
        """
        try:
            from app.sites import SitesManager
            SitesManager().refresh_indexer_links(missing_only=missing_only)
        except Exception:
            log.exception("【索引器】刷新站点关联出错：")

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