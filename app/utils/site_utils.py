import ipaddress
from urllib import parse

mteam_sites = [
    'kp.m-team.cc',
    'xp.m-team.cc',
    'ap.m-team.cc',
    'next.m-team.cc'
]

# 主域名不是最后两级的特殊站点
_special_domains = [
    'u2.dmhy.org',
    'pt.ecust.pp.ua',
]

# 常见多级公共后缀，截取主域名时需要多保留一级
_MULTI_LEVEL_SUFFIXES = {
    "com.cn", "net.cn", "org.cn", "gov.cn", "edu.cn", "ac.cn",
    "com.hk", "net.hk", "org.hk", "com.tw", "net.tw", "org.tw",
    "com.au", "net.au", "org.au", "co.uk", "org.uk", "ac.uk", "gov.uk",
    "co.jp", "or.jp", "ne.jp", "co.kr", "or.kr", "com.br", "com.ru",
}


def _is_ip(host: str) -> bool:
    """
    是否为IP地址
    """
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


class SiteUtils:

    @staticmethod
    def url_equal(url1: str, url2: str):
        """
        比较两个地址是否为同一个站点地址
        只比较归一化后的主机名（忽略协议、路径、端口、账号信息和 www. 前缀）
        """
        host1 = SiteUtils.get_url_host(url1)
        host2 = SiteUtils.get_url_host(url2)
        return bool(host1) and host1 == host2

    @staticmethod
    def get_url_host(url: str):
        """
        获取URL归一化后的主机名
        去掉协议、路径、端口、账号信息、首尾的点以及 www. 前缀，统一小写
        """
        if not url:
            return ""
        url = url.strip()
        if not url.startswith("http"):
            url = f"http://{url}"
        netloc = parse.urlparse(url).netloc
        # 去掉账号信息
        if "@" in netloc:
            netloc = netloc.rsplit("@", 1)[-1]
        # 去掉端口（兼容IPv6的方括号写法）
        if netloc.startswith("["):
            netloc = netloc.split("]")[0].lstrip("[")
        elif ":" in netloc:
            netloc = netloc.split(":")[0]
        netloc = netloc.strip(".").lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc

    @staticmethod
    def get_url_netloc(url: str):
        """
        获取URL的协议和域名部分
        """
        if not url:
            return "", ""
        if not url.startswith("http"):
            return "http", url
        addr = parse.urlparse(url)
        return addr.scheme, addr.netloc

    @staticmethod
    def get_url_domain(url: str):
        """
        获取URL对应的站点主域名（可注册域），子域名归一到同一个主域名
        """
        host = SiteUtils.get_url_host(url)
        if not host:
            return ""
        for domain in _special_domains:
            if host == domain or host.endswith(f".{domain}"):
                return domain
        if _is_ip(host):
            return host
        locs = host.split(".")
        if len(locs) <= 2:
            return host
        if ".".join(locs[-2:]) in _MULTI_LEVEL_SUFFIXES:
            return ".".join(locs[-3:])
        return ".".join(locs[-2:])

    @staticmethod
    def get_url_sld(url: str):
        """
        获取URL的二级域名部分，不含端口，若为IP则返回IP
        """
        if not url:
            return ""
        _, netloc = SiteUtils.get_url_netloc(url)
        if not netloc:
            return ""
        netloc = netloc.split(":")[0].split(".")
        if len(netloc) >= 2:
            return netloc[-2]
        return netloc[0]

    @staticmethod
    def get_base_url(url: str):
        """
        获取URL根地址
        """
        if not url:
            return ""
        scheme, netloc = SiteUtils.get_url_netloc(url)
        return f"{scheme}://{netloc}"
    

    @staticmethod
    def is_mteam_sites(url: str):
        """
        是否为mteam站点
        """
        if not url:
            return False
        domain = SiteUtils.get_url_domain(url)
        return domain in mteam_sites