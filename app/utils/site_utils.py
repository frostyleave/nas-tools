from urllib import parse

mteam_sites = [
    'kp.m-team.cc',
    'xp.m-team.cc',
    'ap.m-team.cc'
]

_special_domains = [
    'u2.dmhy.org',
    'pt.ecust.pp.ua',
]

class SiteUtils:

    @staticmethod
    def url_equal(url1: str, url2: str):
        """
        比较两个地址是否为同一个网站
        """
        if not url1 or not url2:
            return False
        if url1.startswith("http"):
            url1 = parse.urlparse(url1).netloc
        if url2.startswith("http"):
            url2 = parse.urlparse(url2).netloc
        if url1.replace("www.", "") == url2.replace("www.", ""):
            return True
        return False

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
        获取URL的域名部分，只保留最后两级
        """
        if not url:
            return ""
        for domain in _special_domains:
            if domain in url:
                return domain
        _, netloc = SiteUtils.get_url_netloc(url)
        if netloc:
            locs = netloc.split(".")
            if len(locs) > 3:
                return netloc
            return ".".join(locs[-2:])
        return ""

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