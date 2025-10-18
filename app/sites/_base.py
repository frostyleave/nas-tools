from typing import List, Optional

from pydantic import BaseModel


class PtSiteConf(BaseModel):
    """
    PT站点配置
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
    ua: Optional[str] = None
    token: Optional[str] = None
    apikey: Optional[str] = None
    passkey: Optional[str] = None
    uid: Optional[str] = None

    rule: Optional[str] = None
    download_setting: Optional[str] = None
    uses: List[str]
    rss_enable: bool
    brush_enable: bool
    statistic_enable: bool
    parse: bool
    unread_msg_notify: bool
    chrome: bool
    proxy: bool
    subtitle: bool
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

