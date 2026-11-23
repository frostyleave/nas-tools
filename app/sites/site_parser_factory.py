"""
接口鉴权的站点用户信息解析器工厂

统一按站点配置的解析器类型构造实例，供数据统计和连通性测试共用。
"""

import log
from app.models.model import UserSiteConf
from app.sites.siteuserinfo._base import _ISiteUserInfo
from app.sites.siteuserinfo.colapt import ColaPTUserInfo
from app.sites.siteuserinfo.mTorrent import MTorrentUserInfo
from app.sites.siteuserinfo.yemapt import YemaUserInfo
from app.utils.types import Spider


def _new_session(session_factory, cookie=None):
    """
    按需创建会话；统计链路传入工厂以复用连接，连通性测试不建会话
    """
    return session_factory(cookie) if session_factory else None


def _build_mtorrent(site_info: UserSiteConf, session_factory, _):
    return MTorrentUserInfo(
        site_info.name, site_info.strict_url, site_info.cookie, '',
        apikey=site_info.apikey,
        session=_new_session(session_factory),
        proxy=site_info.proxy,
    )


def _build_yema(site_info: UserSiteConf, session_factory, require_credentials: bool):
    # API Auth Key 优先取 API Key 字段，其次取 Authorization 字段
    apikey = site_info.apikey or site_info.token
    if not site_info.cookie and not apikey and require_credentials:
        log.warn(f"【Sites】站点 {site_info.name} 未配置Cookie或API Auth Key，无法解析")
        return None
    # Cookie 模式需要会话携带站点 Cookie，接口模式不使用 Cookie
    return YemaUserInfo(
        site_info.name, site_info.strict_url, site_info.cookie, '',
        apikey=apikey,
        session=_new_session(session_factory, site_info.cookie),
        ua=site_info.ua,
        proxy=site_info.proxy,
    )


def _build_colapt(site_info: UserSiteConf, session_factory, require_credentials: bool):
    if not site_info.apikey and require_credentials:
        log.warn(f"【Sites】站点 {site_info.name} 未配置ColaPT API Key，无法解析")
        return None
    return ColaPTUserInfo(
        site_info.name, site_info.strict_url, site_info.cookie, '',
        apikey=site_info.apikey,
        session=_new_session(session_factory),
        ua=site_info.ua,
        proxy=site_info.proxy,
    )


# 解析器类型 → 构造逻辑
_BUILDERS = {
    Spider.MTorrentSpider.value: _build_mtorrent,
    Spider.YemaSpider.value: _build_yema,
    Spider.ColaPTSpider.value: _build_colapt,
}


def is_api_site_parser(parser: str | None) -> bool:
    """
    是否为使用接口鉴权的站点解析器

    :param parser: 站点配置的解析器类型
    :return: 是否需要 API Key/接口鉴权
    """
    return parser in _BUILDERS


def build_api_site_user_info(site_info: UserSiteConf,
                             session_factory=None,
                             require_credentials: bool = True) -> _ISiteUserInfo | None:
    """
    按站点配置构造接口鉴权的用户信息解析器

    :param site_info: 站点配置
    :param session_factory: 可选的会话工厂，统计链路传入 build_async_session 以复用连接
    :param require_credentials: 凭证缺失时是否直接判为无法解析；连通性测试传 False 以便返回具体原因
    :return: 解析器实例；非接口解析器或凭证缺失且 require_credentials 时返回 None
    """
    builder = _BUILDERS.get(site_info.parser)
    if not builder:
        return None
    return builder(site_info, session_factory, require_credentials)
