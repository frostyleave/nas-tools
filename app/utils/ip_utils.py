import ipaddress
import socket

from urllib.parse import urlparse

from app.utils.http_utils import RequestUtils

import log


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
        """
        hostname = urlparse(hostname).hostname
        if IpUtils.is_ip(hostname):
            return IpUtils.is_private_ip(hostname)
        else:
            return IpUtils.is_internal_domain(hostname)

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
        判断域名是否为内部域名
        """
        # 获取域名对应的 IP 地址
        try:
            ip = socket.gethostbyname(domain)
        except socket.error:
            return False

        # 判断 IP 地址是否属于内网 IP 地址范围
        return IpUtils.is_private_ip(ip)

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
              'cb=jQuery110203920624944751099_1529894588086&_=1529894588088&query=%s' % ip
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