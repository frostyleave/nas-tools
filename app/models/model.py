import ssl

from dataclasses import dataclass
from requests.adapters import HTTPAdapter
from typing import Any, List, Optional
from pydantic import BaseModel


class SiteBaseModel(BaseModel):
    """
    站点基础配置
    """
    id: str = ''
    name: str = ''
    domain: str = ''
    public: bool = False

    search: Optional[dict] = None
    torrents: Optional[dict] = None
    parser: Optional[str] = None
    category: Optional[dict] = None
    extra: Optional[dict] = None

    def get(self, key: str, default: Any = None) -> Any:
        """像字典一样获取字段值，若字段不存在则返回默认值"""
        return getattr(self, key, default)


class UserSiteConf(BaseModel):
    """
    用户PT站点配置信息
    """
    id: int
    name: str
    pri: int
    signurl: str
    strict_url: str
    rssurl: str = ''
    indexer_id: str = ''
    parser : Optional[str] = None

    cookie: Optional[str] = None
    token: Optional[str] = None
    apikey: Optional[str] = None
    passkey: Optional[str] = None
    uid: Optional[str] = None

    chrome: bool
    """ 是否开启开启浏览器仿真 """
    proxy: bool
    """ 是否使用代理服务 """

    uses: List[str]
    rss_enable: bool
    """ 是否启用-RSS订阅 """
    brush_enable: bool
    """ 是否启用-刷流 """
    statistic_enable: bool
    """ 是否启用-数据统计 """

    ua: Optional[str] = None
    rule: Optional[str] = None
    """ 过滤规则 """
    download_setting: Optional[str] = None
    """ 下载配置 """
    source_type: List[str] = None
    """ 站点资源类型 """
    parse_detail: bool
    """ 是否解析RSS种子详情 """
    unread_msg_notify: bool
    """ 是否发送站点未读消息通知 """
    subtitle: bool
    """ 是否从详情页下载字幕 """

    limit_interval: Optional[int] = None
    limit_count: Optional[int] = None
    limit_seconds: Optional[int] = None

    @classmethod
    def from_datas(cls, datas: Optional[dict] = None, **kwargs):
        merged = {}
        if datas:
            merged.update(datas)
        merged.update(kwargs)
        return cls(**merged)

    def get(self, key: str, default: Any = None) -> Any:
        """像字典一样获取字段值，若字段不存在则返回默认值"""
        return getattr(self, key, default)


@dataclass
class BrushedTorrentUpdate:
    """刷流种子删除/状态更新信息"""
    task_id: int
    torrent_id: str
    uploaded: int
    downloaded: int


class IndexerInfo(BaseModel):
    """
    站点索引配置(综合站点基础信息+用户配置)
    """
    id: Optional[str] = None
    name: Optional[str] = None
    domain: Optional[str] = None
    public: bool = True
    search: dict
    torrents: dict
    parser: Optional[str] = None
    category: Optional[dict] = None

    search_param: str
    source_type: List[str]
    en_expand: bool = False

    builtin: bool = True

    siteid: Optional[int] = None
    cookie: Optional[str] = None
    token: Optional[str] = None
    apikey: Optional[str] = None
    ua: Optional[str] = None
    rule: Optional[str] = None
    pri: Optional[int] = None
    proxy: bool = False
    render: bool = False
    timeout : int = 15

    @classmethod
    def from_datas(cls, datas: Optional[dict] = None, **kwargs):
        merged = {}
        if datas:
            merged.update(datas)
        merged.update(kwargs)
        return cls(**merged)
    
    def get(self, key: str, default: Any = None) -> Any:
        """像字典一样获取字段值，若字段不存在则返回默认值"""
        return getattr(self, key, default)


# 创建一个自定义的 SSL 上下文，忽略 EOF 错误
class SSLAdapter(HTTPAdapter):

    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context()
        # 核心设置：允许非预期的 EOF
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        kwargs['ssl_context'] = context
        return super().init_poolmanager(*args, **kwargs)
