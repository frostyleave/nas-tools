import ipaddress
import socket
from urllib.parse import urlparse

from cachetools import TTLCache, cached

import log
from app.utils.http_utils import RequestUtils

# 域名解析结果缓存，避免媒体库列表逐条判断时重复做 DNS 查询
_INTERNAL_DOMAIN_CACHE = TTLCache(maxsize=256, ttl=300)


@cached(cache=_INTERNAL_DOMAIN_CACHE)
def _is_internal_domain(domain: str) -> bool:
    try:
        infos = socket.getaddrinfo(domain, None)
    except socket.error:
        return False

    addresses = [str(info[4][0]).split("%", 1)[0] for info in infos]
    return bool(addresses) and all(IpUtils.is_private_ip(ip) for ip in addresses)


class IpUtils:

    @staticmethod
    def is_ipv4(ip):
        """
        判断是不是ipv4
        """
        try:
            socket.inet_pton(socket.AF_INET, ip)
        except AttributeError:  # no inet_pton here,sorry
            try:
                socket.inet_aton(ip)
            except socket.error:
                return False
            return ip.count('.') == 3
        except socket.error:  # not a valid ip
            return False
        return True

    @staticmethod
    def is_ipv6(ip):
        """
        判断是不是ipv6
        """
        try:
            socket.inet_pton(socket.AF_INET6, ip)
        except socket.error:  # not a valid ip
            return False
        return True

    @staticmethod
    def is_internal(hostname):
        """
        判断一个host是内网还是外网

        支持带协议/端口/路径的 URL，也支持直接的 IP 或域名；
        IPv4、IPv6 字面量都按 IP 判断，其余按域名解析。
        """
        host = urlparse(hostname).hostname
        if not host:
            return False
        try:
            return ipaddress.ip_address(host).is_private
        except ValueError:
            return IpUtils.is_internal_domain(host)

    @staticmethod
    def is_ip(addr):
        """
        判断是不是ip
        """
        try:
            socket.inet_aton(addr)
            return True
        except socket.error:
            return False

    @staticmethod
    def is_internal_domain(domain):
        """
        判断域名是否为内部域名（解析结果必须全部是内网地址，结果缓存 5 分钟）
        """
        if not domain:
            return False
        return _is_internal_domain(domain)

    @staticmethod
    def is_private_ip(ip_str):
        """
        判断是不是内网ip
        """
        try:
            return ipaddress.ip_address(ip_str.strip()).is_private
        except Exception as e:
            print(e)
            return False
        
    @staticmethod
    def get_location(ip):
        """
        根据IP址查询真实地址
        """
        if not IpUtils.is_ipv4(ip):
            return ""
        url = 'https://sp0.baidu.com/8aQDcjqpAAV3otqbppnN2DJv/api.php?co=&resource_id=6006&t=1529895387942&ie=utf8' \
              '&oe=gbk&cb=op_aladdin_callback&format=json&tn=baidu&' \
              f'cb=jQuery110203920624944751099_1529894588086&_=1529894588088&query={ip}'
        try:
            r = RequestUtils().get_res(url)
            if r:
                r.encoding = 'gbk'
                html = r.text
                c1 = html.split('location":"')[1]
                c2 = c1.split('","')[0]
                return c2
            else:
                return ""
        except Exception as err:
            log.exception('[Web]根据IP址查询真实地址失败: ')
            return ""