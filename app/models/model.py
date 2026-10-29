import ssl
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from requests.adapters import HTTPAdapter


class SiteBaseModel(BaseModel):
    """
    站点基础配置
    """
    id: str = ''
    name: str = ''
    domain: str = ''
    public: bool = False

    search: dict | None = None
    torrents: dict | None = None
    parser: str | None = None
    category: dict | None = None
    extra: dict | None = None

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
    parser : str | None = None

    cookie: str | None = None
    token: str | None = None
    apikey: str | None = None
    passkey: str | None = None
    uid: str | None = None

    chrome: bool
    """ 是否开启开启浏览器仿真 """
    proxy: bool
    """ 是否使用代理服务 """

    uses: list[str]
    rss_enable: bool
    """ 是否启用-RSS订阅 """
    brush_enable: bool
    """ 是否启用-刷流 """
    statistic_enable: bool
    """ 是否启用-数据统计 """

    ua: str | None = None
    rule: str | None= None
    """ 过滤规则 """
    download_setting: str | None = None
    """ 下载配置 """
    source_type: list[str] = None
    """ 站点资源类型 """
    parse_detail: bool
    """ 是否解析RSS种子详情 """
    unread_msg_notify: bool
    """ 是否发送站点未读消息通知 """
    subtitle: bool
    """ 是否从详情页下载字幕 """

    limit_interval: int | None = None
    limit_count: int | None = None
    limit_seconds: int | None = None

    @classmethod
    def from_datas(cls, datas: dict | None = None, **kwargs):
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
    id: str | None= None
    name: str | None= None
    domain: str | None= None
    public: bool = True
    search: dict
    torrents: dict
    parser: str | None= None
    category: dict | None = None

    search_param: str
    source_type: list[str]
    en_expand: bool = False

    builtin: bool = True

    siteid: int | None = None
    cookie: str | None= None
    token: str | None= None
    apikey: str | None= None
    ua: str | None= None
    rule: str | None= None
    pri: int | None = None
    proxy: bool = False
    render: bool = False
    timeout : int = 15

    @classmethod
    def from_datas(cls, datas: dict | None = None, **kwargs):
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
