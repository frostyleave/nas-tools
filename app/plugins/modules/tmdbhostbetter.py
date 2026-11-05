import json
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import ClassVar

import requests
from python_hosts import Hosts, HostsEntry

from app.helper import ThreadHelper
from app.plugins.modules._base import _IPluginModule
from app.utils import IpUtils, RequestUtils, SystemUtils
from config import Config


class TmdbHostBetter(_IPluginModule):
    # 插件名称
    module_name = "TMDB API IP优选"
    module_desc = "通过DNS查询TMDB API域名的候选IP并测速，自动优选最佳IP写入系统hosts。"
    # 插件图标
    module_icon = "tmdb.png"
    # 主题色
    module_color = "#01B3E3"
    # 插件版本
    module_version = "1.0"
    # 插件作者
    module_author = "frostyleave"
    # 作者主页
    author_url = "https://github.com/frostyleave"
    # 插件配置项ID前缀
    module_config_prefix = "tmdb_host_better_"
    # 加载顺序
    module_order = 14
    # 可使用的用户级别
    auth_level = 1

    # 默认优选域名
    _default_domains: ClassVar[list[str]] = [
        "api.tmdb.org",
    ]

    # dnschecker.org 站点地址
    _dnschecker_url = "https://dnschecker.org"
    # 单次最多查询的DNS服务器数量
    _max_dns_servers = 10

    # dnschecker.org 查询失败时的备用 DoH 接口（均为国内可直连的解析器，可拿到不同的CDN节点IP）
    _backup_dns_servers: ClassVar[list[str]] = [
        "https://dns.alidns.com/resolve",
        "https://doh.pub/dns-query",
        "https://doh.360.cn/query"
    ]

    # 记录类型与DNS Answer中的type对应关系
    _record_types: ClassVar[dict[str, int]] = {"A": 1, "AAAA": 28}

    # 写入系统hosts文件的区块标识
    _hosts_block_start = "# TmdbHostBetter Start"
    _hosts_block_end = "# TmdbHostBetter End"

    # 私有属性
    _cron = None
    _onlyonce = False
    _notify = False
    _ipv4 = True
    _ipv6 = False
    _sync_hosts = True
    _domains = None
    _port = 443
    _timeout = 3
    _country = "jp"

    @classmethod
    def get_fields(cls):
        return [
            # 同一板块
            {
                'type': 'div',
                'content': [
                    # 同一行
                    [
                        {
                            'title': '立即运行一次',
                            'required': "",
                            'tooltip': '打开后立即运行一次（点击此对话框的确定按钮后即会运行，周期未设置也会运行），关闭后将仅按照优选周期运行',
                            'type': 'switch',
                            'id': 'onlyonce',
                            'col': 'col-12 col-md-6 col-lg-4',
                        },
                        {
                            'title': '运行时通知',
                            'required': "",
                            'tooltip': '运行任务后发送通知（需要打开插件消息通知）',
                            'type': 'switch',
                            'id': 'notify',
                            'col': 'col-12 col-md-6 col-lg-4',
                        },
                        {
                            'title': '写入系统Hosts',
                            'required': "",
                            'tooltip': '将优选结果写入系统hosts文件并立即生效，如因权限问题无法写入将记录错误日志',
                            'type': 'switch',
                            'id': 'sync_hosts',
                            'col': 'col-12 col-md-6 col-lg-4',
                        },
                    ],
                    [
                        {
                            'title': 'IPv4',
                            'required': "",
                            'tooltip': '优选IPv4地址；v4和v6必须其一，都不选择则默认IPv4',
                            'type': 'switch',
                            'id': 'ipv4',
                            'col': 'col-12 col-md-6 col-lg-4',
                        },
                        {
                            'title': 'IPv6',
                            'required': "",
                            'tooltip': '优选IPv6地址；v4和v6必须其一，都不选择则默认IPv4',
                            'type': 'switch',
                            'id': 'ipv6',
                            'col': 'col-12 col-md-6 col-lg-4',
                        },
                    ],
                    [
                        {
                            'title': '检测端口',
                            'required': "",
                            'tooltip': '通过TCP连接检测IP延迟的端口，默认443',
                            'type': 'text',
                            'col': 'col-12 col-md-6 col-lg-4',
                            'content': [
                                {
                                    'id': 'port',
                                    'placeholder': '443',
                                }
                            ]
                        },
                        {
                            'title': '查询节点',
                            'required': "",
                            'tooltip': 'dnschecker.org 的DNS查询节点国家代码，默认jp，可填us、sg、hk、de等',
                            'type': 'text',
                            'col': 'col-12 col-md-6 col-lg-4',
                            'content': [
                                {
                                    'id': 'country',
                                    'placeholder': 'jp',
                                }
                            ]
                        },
                        {
                            'title': '优选周期',
                            'required': "",
                            'tooltip': 'TMDB IP优选周期，支持5位cron表达式',
                            'type': 'text',
                            'col': 'col-12 col-md-6 col-lg-4',
                            'content': [
                                {
                                    'id': 'cron',
                                    'placeholder': '0 3 * * *',
                                }
                            ]
                        },
                    ],
                    [
                        {
                            'title': '优选域名',
                            'required': "",
                            'tip': f"默认域名：{'、'.join(cls._default_domains)}",
                            'type': 'textarea',
                            'col': 'col-12',
                            'content':
                                {
                                    'id': 'domains',
                                    'placeholder': '每行一个域名，留空使用默认域名',
                                    'rows': 6,
                                }
                        }
                    ]
                ]
            }
        ]

    def init_config(self, config=None):
        # 读取配置
        if config:
            self._onlyonce = config.get("onlyonce")
            self._cron = self.quartz_cron_compatible(config.get("cron"))
            self._notify = config.get("notify")
            self._ipv4 = config.get("ipv4")
            self._ipv6 = config.get("ipv6")
            self._sync_hosts = config.get("sync_hosts", True)
            self._domains = config.get("domains")
            self._port = self.__parse_port(config.get("port"))
            self._country = self.__parse_country(config.get("country"))

        # ipv4和ipv6必须其一
        if not self._ipv4 and not self._ipv6:
            self._ipv4 = True
            self.update_config({
                "onlyonce": False,
                "cron": self._cron,
                "notify": self._notify,
                "ipv4": self._ipv4,
                "ipv6": self._ipv6,
                "sync_hosts": self._sync_hosts,
                "domains": self._domains,
                "port": self._port,
                "country": self._country
            })
            self.warn("TMDB IP优选未指定IP类型，默认IPv4")

        # 停止现有任务
        self.stop_service()

        # 启动定时任务 & 立即运行一次
        if self.get_state() or self._onlyonce:
            if self._onlyonce:
                self.info("TMDB IP优选服务启动，立即运行一次")
                ThreadHelper().start_thread(self.__host_better, ())
                # 关闭一次性开关
                self._onlyonce = False
                self.__update_config()

            if self._cron:
                self._cron_job = self.add_cron_job(self.__host_better, self._cron, 'TMDB IP优选')

    def __host_better(self):
        """
        TMDB IP优选
        """
        domains = self.__get_domains()
        if not domains:
            self.error("未配置有效的优选域名，停止运行")
            return

        self.info(f"开始TMDB IP优选，域名：{', '.join(domains)}")
        if Config().get_proxies():
            self.info("已配置代理，但IP延迟测试为直连测试（hosts优选生效同样依赖直连，不经过代理）")

        # 获取dnschecker.org指定节点的DNS服务器，失败则改用备用DNS接口
        session = requests.Session()
        server_ids, dnschecker_error = self.__get_dnschecker_server_ids(session)
        if server_ids:
            self.info(f"使用dnschecker.org查询候选IP，节点：{self._country}，"
                      f"服务器数：{len(server_ids)}")
        else:
            reason = f"（{dnschecker_error}）" if dnschecker_error else ""
            self.warn(f"dnschecker.org访问失败{reason}，将使用备用DNS接口查询")

        results = []
        for domain in domains:
            for record_type, enabled in (("A", self._ipv4), ("AAAA", self._ipv6)):
                if not enabled:
                    continue

                # 查询候选IP
                ips = self.__query_dns(domain, record_type, server_ids, session)
                if not ips:
                    self.warn(f"{domain} 未查询到 {record_type} 记录")
                    continue

                # 测速优选
                best_ip, latency, failures = self.__find_best_ip(ips)
                if not best_ip:
                    detail = "；".join(f"{ip}（{reason}）" for ip, reason in sorted(failures.items()))
                    self.warn(f"{domain} 的 {record_type} 候选IP均不可用（TCP {self._port}）：{detail}")
                    continue

                self.info(f"{domain} 优选 {record_type} IP：{best_ip}（{latency:.0f}ms），"
                          f"候选：{', '.join(sorted(ips))}")
                results.append((domain, best_ip, latency))

        if not results:
            self.error("TMDB IP优选完成，未获取到任何可用IP")
            return

        # 写入系统hosts
        changed = False
        if self._sync_hosts:
            changed = self.__update_system_hosts(results)

        # 发送通知
        if self._notify and (changed or not self._sync_hosts):
            self.send_message(
                title="【TMDB IP优选任务完成】",
                text="\n".join(f"{domain} -> {ip}（{latency:.0f}ms）" for domain, ip, latency in results)
            )

    def __query_dns(self, domain, record_type, server_ids=None, session=None):
        """
        优先通过dnschecker.org查询候选IP，失败时使用备用DNS接口
        """
        if server_ids:
            ips = self.__query_dnschecker(domain, record_type, server_ids, session)
            if ips:
                return ips
            self.debug(f"dnschecker.org未查询到{domain}的{record_type}记录，改用备用DNS接口")
        return self.__query_backup_dns(domain, record_type)

    def __get_dnschecker_server_ids(self, session=None):
        """
        获取dnschecker.org指定节点的DNS服务器ID列表，返回(服务器ID列表, 失败原因)
        """
        headers = self.__dnschecker_headers()
        headers["accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        servers = []
        error = ""
        for page_url in (f"{self._dnschecker_url}/country/{self._country}", self._dnschecker_url):
            res, reason = self.__dnschecker_request(page_url, headers, session=session)
            if not res:
                error = error or reason or "请求失败"
                continue
            servers = self.__parse_dns_servers(res.text)
            if servers:
                break
            error = "页面中未找到DNS服务器列表"
            self.debug(f"dnschecker页面（{page_url}）未解析到DNS服务器列表，"
                       f"HTTP {res.status_code}，{res.headers.get('content-type', '')}")

        server_ids = [str(server.get("id")) for server in servers
                      if str(server.get("country", "")).lower() == self._country]
        # 页面未按节点返回服务器时，退化为使用页面中的全部服务器
        if not server_ids:
            server_ids = [str(server.get("id")) for server in servers if server.get("id")]
        if not server_ids:
            error = error or "未获取到可用的DNS服务器"
        else:
            error = ""
        return server_ids[:self._max_dns_servers], error

    def __parse_dns_servers(self, html):
        """
        解析页面中预置的DNS服务器列表dns_json_array
        """
        try:
            match = re.search(r"var dns_json_array = JSON\.parse\('(.*?)'\);", html or "", re.DOTALL)
            if not match:
                return []
            literal = match.group(1).replace("\\'", "'")
            servers = json.loads(json.loads('"' + literal + '"'))
            return servers if isinstance(servers, list) else []
        except Exception as err:
            self.debug(f"解析dnschecker服务器列表失败：{err}")
            return []

    def __query_dnschecker(self, domain, record_type, server_ids, session=None):
        """
        通过dnschecker.org各节点的DNS服务器查询域名某一记录类型的候选IP
        """
        headers = self.__dnschecker_headers()

        def query(server_id):
            url = f"{self._dnschecker_url}/ajax/dns-lookup/{server_id}/{record_type}/{domain}"
            res, _ = self.__dnschecker_request(url, headers, {"cd_flag": 1}, session)
            if not res:
                return set()
            try:
                ips_str = ((res.json() or {}).get("result") or {}).get("ips")
            except Exception as err:
                self.debug(f"dnschecker返回解析失败（服务器{server_id}）：{err}")
                return set()

            # 接口返回的多个IP使用<br />分隔
            if isinstance(ips_str, list):
                candidates = ips_str
            else:
                candidates = re.split(r"<br\s*/?>|[\s,;]+", str(ips_str or ""))

            ips = set()
            for ip in candidates:
                ip = str(ip).strip()
                if (record_type == "A" and IpUtils.is_ipv4(ip)) \
                        or (record_type == "AAAA" and IpUtils.is_ipv6(ip)):
                    ips.add(ip)
            return ips

        ips = set()
        with ThreadPoolExecutor(max_workers=min(8, len(server_ids))) as executor:
            futures = [executor.submit(query, server_id) for server_id in server_ids]
            for future in as_completed(futures):
                try:
                    ips.update(future.result())
                except Exception as err:
                    self.debug(f"查询dnschecker服务器失败：{err}")
        return ips

    def __dnschecker_request(self, url, headers, params=None, session=None):
        """
        请求dnschecker.org，直连失败时尝试使用代理，返回(响应, 失败原因)
        """
        error = ""
        try:
            res = RequestUtils(headers=headers, session=session, timeout=10).get_res(url, params=params)
            if res and res.ok:
                return res, ""
            if res is not None:
                error = self.__describe_dnschecker_error(res)
                self.debug(f"dnschecker请求失败：{error}，{res.text[:120]}")
        except Exception as err:
            error = f"请求异常：{err}"
            self.warn(f"dnschecker请求异常：{err}")

        proxies = Config().get_proxies()
        if proxies:
            try:
                res = RequestUtils(headers=headers, proxies=proxies, session=session, timeout=15).get_res(
                    url, params=params)
                if res and res.ok:
                    return res, ""
                if res is not None:
                    error = self.__describe_dnschecker_error(res)
            except Exception as err:
                error = f"代理请求异常：{err}"
                self.warn(f"dnschecker代理请求异常：{err}")
        return None, error

    @staticmethod
    def __describe_dnschecker_error(res):
        """
        描述dnschecker.org请求失败的原因
        """
        text = res.text or ""
        if res.status_code == 403 and ("Just a moment" in text or "cf-chl" in text):
            return "Cloudflare 人机验证，HTTP 403"
        content_type = res.headers.get("content-type", "")
        return f"HTTP {res.status_code}" + (f"，{content_type}" if content_type else "")

    def __dnschecker_headers(self):
        """
        dnschecker.org请求头
        """
        return {
            "referer": f"{self._dnschecker_url}/country/{self._country}",
            "origin": self._dnschecker_url,
            "User-Agent": Config().get_ua(),
            "accept": "application/json, text/javascript, */*; q=0.01",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "x-requested-with": "XMLHttpRequest"
        }

    def __query_backup_dns(self, domain, record_type):
        """
        通过备用DNS over HTTPS接口查询候选IP
        """
        ips = set()
        with ThreadPoolExecutor(max_workers=len(self._backup_dns_servers)) as executor:
            futures = [executor.submit(self.__query_backup_dns_server, url, domain, record_type)
                       for url in self._backup_dns_servers]
            for future in as_completed(futures):
                try:
                    ips.update(future.result())
                except Exception as err:
                    self.debug(f"{domain} {record_type} 查询异常：{err}")
        return ips

    def __query_backup_dns_server(self, url, domain, record_type):
        """
        请求单个备用DNS over HTTPS接口，直连失败时尝试使用代理
        """
        headers = {"Accept": "application/dns-json"}
        params = {"name": domain, "type": record_type}
        res = None
        try:
            res = RequestUtils(headers=headers, timeout=4).get_res(url, params=params)
        except Exception as err:
            self.debug(f"DNS接口 {url} 直连异常：{err}")

        if not res or not res.ok:
            proxies = Config().get_proxies()
            if proxies:
                try:
                    res = RequestUtils(headers=headers, proxies=proxies, timeout=6).get_res(url, params=params)
                except Exception as err:
                    self.debug(f"DNS接口 {url} 代理访问异常：{err}")

        if not res or not res.ok:
            return set()

        try:
            answers = (res.json() or {}).get("Answer") or []
        except Exception as err:
            self.debug(f"DNS接口 {url} 返回解析失败：{err}")
            return set()

        ips = set()
        answer_type = self._record_types.get(record_type)
        for answer in answers:
            if not isinstance(answer, dict) or answer.get("type") != answer_type:
                continue
            ip = str(answer.get("data", "")).strip()
            if (record_type == "A" and IpUtils.is_ipv4(ip)) \
                    or (record_type == "AAAA" and IpUtils.is_ipv6(ip)):
                ips.add(ip)
        return ips

    def __find_best_ip(self, ips):
        """
        并发测试候选IP延迟，返回(最优IP, 延迟, 失败原因)
        """
        results = {}
        with ThreadPoolExecutor(max_workers=min(8, len(ips))) as executor:
            futures = {executor.submit(self.__test_latency, ip): ip for ip in ips}
            for future in as_completed(futures):
                ip = futures[future]
                try:
                    results[ip] = future.result()
                except Exception as err:
                    results[ip] = (float("inf"), f"{type(err).__name__}: {err}")

        best_ip = None
        best_latency = float("inf")
        failures = {}
        for ip, (latency, reason) in results.items():
            if latency < best_latency:
                best_ip = ip
                best_latency = latency
            elif latency == float("inf"):
                failures[ip] = reason or "不可达"

        return best_ip, best_latency, failures

    def __test_latency(self, ip):
        """
        TCP连接延迟测试，最多测3次取最小值，返回(延迟, 失败原因)
        """
        latencies = []
        last_error = ""
        for _ in range(3):
            try:
                start_time = time.time()
                with socket.create_connection((ip, self._port), timeout=self._timeout):
                    latencies.append((time.time() - start_time) * 1000)
            except Exception as err:
                last_error = f"{type(err).__name__}: {err}" if str(err) else type(err).__name__
                # 端口明确拒绝时重试无意义
                if isinstance(err, ConnectionRefusedError):
                    break
        return (min(latencies) if latencies else float("inf")), last_error

    def __update_system_hosts(self, results):
        """
        将优选结果写入系统hosts文件，返回是否有变化
        """
        hosts_path = self.__get_hosts_path()
        try:
            system_hosts = Hosts(path=hosts_path)
        except Exception as err:
            self.error(f"读取系统hosts文件失败：{err}")
            return False

        # 移除上次写入的优选区块，同时记录旧区块内容用于比对
        update_domains = {domain for domain, _, _ in results}
        old_block = []
        entries = []
        in_block = False
        for entry in system_hosts.entries:
            if entry.entry_type == "comment":
                comment = (entry.comment or "").strip()
                if comment == self._hosts_block_start:
                    in_block = True
                    continue
                if comment == self._hosts_block_end:
                    in_block = False
                    continue
            if in_block:
                if entry.entry_type in ("ipv4", "ipv6"):
                    old_block.append((entry.address, tuple(entry.names)))
                continue
            # 清除其他来源中本插件管理的域名，避免与优选IP冲突
            if entry.entry_type in ("ipv4", "ipv6"):
                names = [name for name in entry.names if name not in update_domains]
                if not names:
                    continue
                if len(names) != len(entry.names):
                    entries.append(HostsEntry(entry_type=entry.entry_type,
                                              address=entry.address,
                                              names=names,
                                              comment=entry.comment))
                    continue
            entries.append(entry)

        # 生成新的优选记录
        new_block = []
        for domain, ip, _ in results:
            try:
                new_block.append(HostsEntry(entry_type="ipv4" if IpUtils.is_ipv4(ip) else "ipv6",
                                            address=ip,
                                            names=[domain]))
            except Exception as err:
                self.error(f"{domain} {ip} hosts记录生成失败：{err}")

        if not new_block:
            self.error("未生成有效的hosts记录")
            return False

        # 优选结果无变化时不重复写入
        new_signature = [(entry.address, tuple(entry.names)) for entry in new_block]
        if old_block == new_signature:
            self.info("TMDB IP优选结果与系统hosts一致，不做处理")
            return False

        # 插入到自定义Hosts插件区块之前，避免其重载时覆盖本插件记录
        insert_at = len(entries)
        for index, entry in enumerate(entries):
            if entry.entry_type == "comment" and (entry.comment or "").strip() == "# CustomHostsPlugin":
                insert_at = index
                break
        block = [HostsEntry(entry_type="comment", comment=self._hosts_block_start)]
        block.extend(new_block)
        block.append(HostsEntry(entry_type="comment", comment=self._hosts_block_end))
        entries[insert_at:insert_at] = block

        # 写入系统hosts
        try:
            system_hosts.entries = entries
            system_hosts.write()
        except Exception as err:
            self.error(f"更新系统hosts文件失败：{str(err) or '请检查权限'}")
            return False

        self.info(f"TMDB IP优选结果已写入系统hosts文件：{hosts_path}")
        return True

    @staticmethod
    def __get_hosts_path():
        """
        获取系统hosts文件路径
        """
        if SystemUtils.is_windows():
            return r"c:\windows\system32\drivers\etc\hosts"
        return "/etc/hosts"

    def __get_domains(self):
        """
        解析优选域名，未配置时使用默认域名
        """
        raw_domains = self._domains
        if isinstance(raw_domains, str):
            raw_domains = re.split(r"[\s,;]+", raw_domains)
        if not raw_domains:
            return list(self._default_domains)

        domains = []
        domain_re = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
        for domain in raw_domains:
            domain = str(domain).strip().lower()
            if not domain:
                continue
            if domain_re.match(domain):
                if domain not in domains:
                    domains.append(domain)
            else:
                self.warn(f"忽略无效域名：{domain}")
        return domains or list(self._default_domains)

    @staticmethod
    def __parse_port(port):
        """
        解析检测端口，非法时默认443
        """
        try:
            port = int(port)
            if 0 < port < 65536:
                return port
        except (TypeError, ValueError):
            pass
        return 443

    @staticmethod
    def __parse_country(country):
        """
        解析dnschecker查询节点国家代码，非法时默认jp
        """
        country = str(country or "").strip().lower()
        if re.fullmatch(r"[a-z]{2}", country):
            return country
        return "jp"

    def __update_config(self):
        """
        更新插件配置
        """
        self.update_config({
            "onlyonce": False,
            "cron": self._cron,
            "notify": self._notify,
            "ipv4": self._ipv4,
            "ipv6": self._ipv6,
            "sync_hosts": self._sync_hosts,
            "domains": self._domains,
            "port": self._port,
            "country": self._country
        })

    def get_state(self):
        return True if self._cron else False

    def stop_service(self):
        """
        退出插件
        """
        try:
            self.remove_job(self._cron_job)
        except Exception as e:
            print(str(e))
