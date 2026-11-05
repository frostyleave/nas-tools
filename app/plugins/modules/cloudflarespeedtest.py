import csv
import os
import shlex
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path
from threading import Event

from app.helper import ThreadHelper
from app.plugins import EventManager
from app.plugins.modules._base import _IPluginModule
from app.utils import IpUtils, RequestUtils, SystemUtils
from app.utils.types import EventType
from config import Config


class CloudflareSpeedTest(_IPluginModule):
    # 插件名称
    module_name = "Cloudflare IP优选"
    # 插件描述
    module_desc = "🌩 测试 Cloudflare CDN 延迟和速度，自动优选IP。"
    # 插件图标
    module_icon = "cloudflare.jpg"
    # 主题色
    module_color = "#F6821F"
    # 插件版本
    module_version = "1.0"
    # 插件作者
    module_author = "thsrite"
    # 作者主页
    author_url = "https://github.com/thsrite"
    # 插件配置项ID前缀
    module_config_prefix = "cloudflarespeedtest_"
    # 加载顺序
    module_order = 12
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    eventmanager = None
    _customhosts = False
    _cf_ip = None
    _cron = None
    _onlyonce = False
    _ipv4 = False
    _ipv6 = False
    _version = None
    _additional_args = None
    _re_install = False
    _notify = False
    _check = False
    _cf_path = None
    _release_prefix = 'https://github.com/XIU2/CloudflareSpeedTest/releases/download'
    _binary_name = 'CloudflareST'

    # 退出事件
    _event = Event()


    @staticmethod
    def get_fields():
        return [
            # 同一板块
            {
                'type': 'div',
                'content': [
                    # 同一行
                    [
                        {
                            'title': '优选IP',
                            'required': "required",
                            'tooltip': '第一次使用，请先将 自定义Hosts插件 中所有 Cloudflare CDN IP 统一改为一个 IP。后续会自动变更。需搭配[自定义Hosts]插件使用',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'cf_ip',
                                    'placeholder': '121.121.121.121',
                                }
                            ]
                        },
                        {
                            'title': '优选周期',
                            'required': "required",
                            'tooltip': 'Cloudflare CDN优选周期，支持5位cron表达式',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'cron',
                                    'placeholder': '0 0 0 ? *',
                                }
                            ]
                        },
                        {
                            'title': 'CloudflareSpeedTest版本',
                            'required': "",
                            'tooltip': '如当前版本与CloudflareSpeedTest最新版本不一致，可开启重装后运行获取新版本',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'version',
                                    'placeholder': '暂未安装',
                                }
                            ]
                        }
                    ],
                    [
                        {
                            'title': 'IPv4',
                            'required': "",
                            'tooltip': '优选测速ipv4；v4和v6必须其一，都不选择则默认ipv4',
                            'type': 'switch',
                            'id': 'ipv4',
                        },
                        {
                            'title': 'IPv6',
                            'required': "",
                            'tooltip': '优选测速ipv6；v4和v6必须其一，都不选择则默认ipv4。选择ipv6会大大加长测速时间。',
                            'type': 'switch',
                            'id': 'ipv6',
                        },
                        {
                            'title': '自动校准',
                            'required': "",
                            'tooltip': '开启后，会自动查询自定义hosts插件中出现次数最多的ip替换到优选IP。（如果出现次数最多的ip不止一个，则不做兼容处理）',
                            'type': 'switch',
                            'id': 'check',
                        },
                    ],
                    [
                        {
                            'title': '立即运行一次',
                            'required': "",
                            'tooltip': '打开后立即运行一次（点击此对话框的确定按钮后即会运行，周期未设置也会运行），关闭后将仅按照优选周期运行（同时上次触发运行的任务如果在运行中也会停止）',
                            'type': 'switch',
                            'id': 'onlyonce',
                        },
                        {
                            'title': '重装后运行',
                            'required': "",
                            'tooltip': '开启后，每次会重新下载CloudflareSpeedTest，网络不好慎选',
                            'type': 'switch',
                            'id': 're_install',
                        },
                        {
                            'title': '运行时通知',
                            'required': "",
                            'tooltip': '运行任务后会发送通知（需要打开插件消息通知）',
                            'type': 'switch',
                            'id': 'notify',
                        },
                    ]
                ]
            },
            {
                'type': 'details',
                'summary': '高级参数',
                'tooltip': 'CloudflareSpeedTest的高级参数，请勿随意修改（请勿新增-f -o参数）',
                'content': [
                    [
                        {
                            'required': "",
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'additional_args',
                                    'placeholder': '-dd'
                                }
                            ]
                        }
                    ]
                ]
            }
        ]

    @staticmethod
    def get_script():
        """
        返回插件额外的JS代码
        """
        return """
        $(document).ready(function () {
          $('#cloudflarespeedtest_version').prop('disabled', true);
        });
         """

    def init_config(self, config=None):
        self.eventmanager = EventManager()

        # 读取配置
        if config:
            self._onlyonce = config.get("onlyonce")
            self._cron = self.quartz_cron_compatible(config.get("cron"))
            self._cf_ip = config.get("cf_ip")
            self._version = config.get("version")
            self._ipv4 = config.get("ipv4")
            self._ipv6 = config.get("ipv6")
            self._re_install = config.get("re_install")
            self._additional_args = config.get("additional_args") or ""
            self._notify = config.get("notify")
            self._check = config.get("check")

        # 停止现有任务
        self.stop_service()
        # 重新开始，清除退出事件
        self.reset_stop_event()

        # 启动定时任务 & 立即运行一次
        if self.get_state() or self._onlyonce:

            if self._onlyonce:
                self.info("Cloudflare CDN优选服务启动，立即运行一次")
                ThreadHelper().start_thread(self.__cloudflareSpeedTest, ())
                # 关闭一次性开关
                self._onlyonce = False
                self.__update_config()

            if self._cron:
                self._cron_job = self.add_cron_job(self.__cloudflareSpeedTest, self._cron, 'Cloudflare CDN优选')

    def __cloudflareSpeedTest(self):
        """
        CloudflareSpeedTest优选
        """
        # 捕获本次运行的事件对象，插件重载后旧线程仍能被旧的置位事件终止
        event = self._event
        self._cf_path = self.get_data_path()
        ipv4_file = os.path.join(self._cf_path, "ip.txt")
        ipv6_file = os.path.join(self._cf_path, "ipv6.txt")
        result_file = os.path.join(self._cf_path, "result_hosts.txt")

        # 获取自定义Hosts插件，若无设置则停止
        custom_hosts = self.get_config("CustomHosts")
        if not custom_hosts or not custom_hosts.get("hosts"):
            self.error("Cloudflare CDN优选依赖于自定义Hosts，请先维护hosts")
            return
        self._customhosts = custom_hosts.get("enable")

        if not self._cf_ip:
            self.error("CloudflareSpeedTest加载成功，首次运行，需要配置优选ip")
            return

        # ipv4和ipv6必须其一
        if not self._ipv4 and not self._ipv6:
            self._ipv4 = True
            self.__update_config()
            self.warn("Cloudflare CDN优选未指定ip类型，默认ipv4")

        err_flag, release_version = self.__check_envirment()
        if err_flag and release_version:
            # 更新版本
            self._version = release_version
            self.__update_config()

        hosts = custom_hosts.get("hosts")
        if isinstance(hosts, str):
            hosts = hosts.split('\n')

        # 校正优选ip
        if self._check:
            self.__check_cf_if(hosts=hosts)

        # 开始优选
        if err_flag:
            if event.is_set():
                self.info("Cloudflare CDN优选服务已停止")
                return
            self.info("正在进行Cloudflare CDN优选，请耐心等待")
            # 执行优选命令，-dd不测速
            self.__run_speed_test(ipv4_file if self._ipv4 else None,
                                  ipv6_file if self._ipv6 else None,
                                  result_file)

            # 获取优选后最优ip
            best_ip = self.__read_best_ip(result_file)
            if not (IpUtils.is_ipv4(best_ip) or IpUtils.is_ipv6(best_ip)):
                self.error("获取到最优ip格式错误，请重试")
                return
            self.info(f"获取到最优ip==>[{best_ip}]")

            if best_ip == self._cf_ip:
                self.info("CloudflareSpeedTest CDN优选ip未变，不做处理")
                return

            # 替换优选ip
            err_hosts = custom_hosts.get("err_hosts")
            enable = custom_hosts.get("enable")

            # 处理ip
            new_hosts = []
            for host in hosts:
                if host and host != '\n':
                    host_arr = str(host).split()
                    if host_arr and host_arr[0] == self._cf_ip:
                        new_hosts.append(host.replace(self._cf_ip, best_ip))
                    else:
                        new_hosts.append(host)

            # 更新自定义Hosts
            self.update_config({
                "hosts": new_hosts,
                "err_hosts": err_hosts,
                "enable": enable
            }, "CustomHosts")

            # 更新优选ip
            old_ip = self._cf_ip
            self._cf_ip = best_ip
            self.__update_config()
            self.info(f"Cloudflare CDN优选ip [{best_ip}] 已替换自定义Hosts插件")

            # 解发自定义hosts插件重载
            self.info("通知CustomHosts插件重载 ...")
            self.eventmanager.send_event(EventType.PluginReload,
                                         {
                                             "plugin_id": "CustomHosts"
                                         })
            if self._notify:
                self.send_message(
                    title="【Cloudflare优选任务完成】",
                    text=f"原ip：{old_ip}\n"
                         f"新ip：{best_ip}"
                )
        else:
            self.error("CloudflareSpeedTest环境检查未通过，停止运行")
            self._onlyonce = False
            self.__update_config()
            self.stop_service()

    def __run_speed_test(self, ipv4_file: str | None, ipv6_file: str | None, result_file: str):
        """
        以参数列表方式执行 CloudflareST，避免拼接 shell 命令
        """
        args = [os.path.join(self._cf_path, self._binary_name)]
        if self._additional_args:
            args.extend(shlex.split(self._additional_args))
        args.extend(["-o", result_file])
        if ipv4_file:
            args.extend(["-f", ipv4_file])
        if ipv6_file:
            args.extend(["-f", ipv6_file])
        self.info(f"正在执行优选命令 {' '.join(args)}")
        try:
            subprocess.run(args, cwd=self._cf_path, check=False)
        except Exception as err:
            self.error(f"执行CloudflareSpeedTest失败：{err!s}")

    def __read_best_ip(self, result_file: str) -> str:
        """
        读取结果CSV中速度最快的IP（跳过表头）
        """
        try:
            with open(result_file, encoding="utf-8") as f:
                reader = csv.reader(f)
                # 跳过表头
                next(reader, None)
                for row in reader:
                    if row and row[0].strip():
                        return row[0].strip()
        except Exception as err:
            self.error(f"读取优选结果失败：{err!s}")
        return ""

    def __check_cf_if(self, hosts):
        """
        校正cf优选ip
        防止特殊情况下cf优选ip和自定义hosts插件中ip不一致
        """
        # 统计每个IP地址出现的次数
        ip_count = {}
        for host in hosts:
            ip = host.split()[0]
            if ip in ip_count:
                ip_count[ip] += 1
            else:
                ip_count[ip] = 1

        # 找出出现次数最多的IP地址
        max_ips = []  # 保存最多出现的IP地址
        max_count = 0
        for ip, count in ip_count.items():
            if count > max_count:
                max_ips = [ip]  # 更新最多的IP地址
                max_count = count
            elif count == max_count:
                max_ips.append(ip)

        # 如果出现次数最多的ip不止一个，则不做兼容处理
        if len(max_ips) != 1:
            return

        if max_ips[0] != self._cf_ip:
            self._cf_ip = max_ips[0]
            self.info(f"获取到自定义hosts插件中ip {max_ips[0]} 出现次数最多，已自动校正优选ip")

    def __check_envirment(self):
        """
        环境检查
        """
        # 是否安装标识
        install_flag = False

        # 是否重新安装
        if self._re_install:
            install_flag = True
            shutil.rmtree(self._cf_path, ignore_errors=True)
            self.info(f'删除CloudflareSpeedTest目录 {self._cf_path}，开始重新安装')

        # 判断目录是否存在
        os.makedirs(self._cf_path, exist_ok=True)

        # 获取CloudflareSpeedTest最新版本
        release_version = self.__get_release_version()
        if not release_version:
            # 如果升级失败但是有可执行文件CloudflareST，则可继续运行，反之停止
            if Path(f'{self._cf_path}/{self._binary_name}').exists():
                self.warn("获取CloudflareSpeedTest版本失败，存在可执行版本，继续运行")
                return True, None
            elif self._version:
                self.error(f"获取CloudflareSpeedTest版本失败，获取上次运行版本{self._version}，开始安装")
                install_flag = True
            else:
                release_version = "v2.2.2"
                self._version = release_version
                self.error(f"获取CloudflareSpeedTest版本失败，获取默认版本{release_version}，开始安装")
                install_flag = True

        # 有更新
        if not install_flag and release_version != self._version:
            self.info(f"检测到CloudflareSpeedTest有版本[{release_version}]更新，开始安装")
            install_flag = True

        # 重装后数据库有版本数据，但是本地没有则重装
        if not install_flag and release_version == self._version and not Path(
                f'{self._cf_path}/{self._binary_name}').exists():
            self.warn("未检测到CloudflareSpeedTest本地版本，重新安装")
            install_flag = True

        if not install_flag:
            self.info("CloudflareSpeedTest无新版本，存在可执行版本，继续运行")
            return True, None

        # 检查环境、安装
        if SystemUtils.is_windows():
            # todo
            self.error("CloudflareSpeedTest暂不支持windows平台")
            return False, None
        elif SystemUtils.is_macos():
            # mac
            uname = SystemUtils.execute('uname -m')
            arch = 'amd64' if uname == 'x86_64' else 'arm64'
            cf_file_name = f'CloudflareST_darwin_{arch}.zip'
            download_url = f'{self._release_prefix}/{release_version}/{cf_file_name}'
            return self.__os_install(download_url, cf_file_name, release_version)
        else:
            # docker
            uname = SystemUtils.execute('uname -m')
            arch = 'amd64' if uname == 'x86_64' else 'arm64'
            cf_file_name = f'CloudflareST_linux_{arch}.tar.gz'
            download_url = f'{self._release_prefix}/{release_version}/{cf_file_name}'
            return self.__os_install(download_url, cf_file_name, release_version)

    def __os_install(self, download_url, cf_file_name, release_version):
        """
        macos docker安装cloudflare
        """
        archive = Path(self._cf_path) / cf_file_name
        binary = Path(self._cf_path) / self._binary_name

        # 手动下载安装包后，无需在此下载
        if not archive.exists():
            self.__download(download_url, archive)

        # 判断是否下载好安装包
        if not archive.exists():
            # 如果升级失败但是有可执行文件CloudflareST，则可继续运行，反之停止
            if binary.exists():
                self.warn("CloudflareSpeedTest安装失败，存在可执行版本，继续运行")
                return True, None
            self.error("CloudflareSpeedTest安装失败，无可用版本，停止运行")
            shutil.rmtree(self._cf_path, ignore_errors=True)
            return False, None

        try:
            # 解压
            self.__extract(archive)
            # 赋权
            if binary.exists():
                binary.chmod(0o755)
            # 删除压缩包
            archive.unlink(missing_ok=True)
            if binary.exists():
                self.info(f"CloudflareSpeedTest安装成功，当前版本：{release_version}")
                return True, release_version
            self.error("CloudflareSpeedTest安装失败，请检查")
            shutil.rmtree(self._cf_path, ignore_errors=True)
            return False, None
        except Exception as err:
            # 如果升级失败但是有可执行文件CloudflareST，则可继续运行，反之停止
            if binary.exists():
                self.error(f"CloudflareSpeedTest安装失败：{err!s}，继续使用现版本运行")
                return True, None
            self.error(f"CloudflareSpeedTest安装失败：{err!s}，无可用版本，停止运行")
            shutil.rmtree(self._cf_path, ignore_errors=True)
            return False, None

    def __download(self, download_url: str, target: Path):
        """
        下载安装包，直连失败且未配置代理时尝试加速镜像
        """
        proxies = Config().get_proxies()
        urls = [download_url]
        if not proxies or not proxies.get("https"):
            urls.append(f"https://ghproxy.com/{download_url}")

        for url in urls:
            res = RequestUtils(proxies=proxies, timeout=(10, 60)).get_res(url, stream=True)
            if not res or res.status_code != 200:
                continue
            try:
                with open(target, "wb") as f:
                    for chunk in res.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                if target.exists() and target.stat().st_size > 0:
                    return
                target.unlink(missing_ok=True)
            except Exception as err:
                self.warn(f"下载CloudflareSpeedTest失败：{err!s}")
                target.unlink(missing_ok=True)
            finally:
                res.close()

    @staticmethod
    def __extract(archive: Path):
        """
        解压安装包
        """
        if archive.name.endswith(".zip"):
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(archive.parent)
            return
        with tarfile.open(archive, "r:gz") as tf:
            try:
                # data 过滤器会拒绝越界路径，仅保留安全成员
                tf.extractall(archive.parent, filter="data")
            except TypeError:
                tf.extractall(archive.parent)

    def __update_config(self):
        """
        更新优选插件配置
        """
        self.update_config({
            "onlyonce": False,
            "cron": self._cron,
            "cf_ip": self._cf_ip,
            "version": self._version,
            "ipv4": self._ipv4,
            "ipv6": self._ipv6,
            "re_install": self._re_install,
            "additional_args": self._additional_args,
            "notify": self._notify,
            "check": self._check
        })

    @staticmethod
    def __get_release_version():
        """
        获取CloudflareSpeedTest最新版本
        """
        version_res = RequestUtils().get_res(
            "https://api.github.com/repos/XIU2/CloudflareSpeedTest/releases/latest")
        if not version_res:
            version_res = RequestUtils(proxies=Config().get_proxies()).get_res(
                "https://api.github.com/repos/XIU2/CloudflareSpeedTest/releases/latest")
        if version_res:
            ver_json = version_res.json()
            version = f"{ver_json['tag_name']}"
            return version
        else:
            return None

    def get_state(self):
        return self._cf_ip and True if self._cron else False

    def stop_service(self):
        """
          退出插件
          """
        # 通知优选线程退出，避免重载后旧线程继续执行
        self.set_stop_event()
        try:
            self.remove_job(self._cron_job)
        except Exception as e:
            print(str(e))

