import ipaddress
import secrets
import string

import log
from app.helper.db_helper import DbHelper
from app.utils.commons import singleton
from app.utils.time_utils import TimeUtils
from config import Config

# 系统默认API密钥名称，禁止删除，仅允许重新生成
DEFAULT_API_KEY_NAME = "SYS_DEFAULT"


@singleton
class SecurityCenter:
    """
    安全中心：统一管理 API 密钥，以及外部请求的来源 IP 校验
    """

    def __init__(self):
        self._db = DbHelper()
        self.media_server_webhook_allow_ip = {}
        self.telegram_webhook_allow_ip = {}
        self.synology_webhook_allow_ip = {}
        self.init_config()

    def init_config(self):
        """
        配置变更时刷新 Webhook 白名单
        """
        security = Config().get_config('security') or {}
        self.media_server_webhook_allow_ip = security.get('media_server_webhook_allow_ip') or {}
        self.telegram_webhook_allow_ip = security.get('telegram_webhook_allow_ip') or {}
        self.synology_webhook_allow_ip = security.get('synology_webhook_allow_ip') or {}

    # ------------------------------------------------------------------
    # API 密钥管理
    # ------------------------------------------------------------------

    def get_api_keys(self) -> list[dict]:
        """
        查询全部 API 密钥
        """
        return [{
            "id": item.ID,
            "name": item.NAME,
            "api_key": item.API_KEY,
            "create_time": item.CREATE_TIME,
            "is_default": item.NAME == DEFAULT_API_KEY_NAME
        } for item in self._db.get_api_keys()]

    @staticmethod
    def current_time_str() -> str:
        """
        按配置的时区生成时间字符串，避免容器时区与本地时区不一致
        """
        return TimeUtils.now_str()

    @staticmethod
    def generate_api_key(length: int = 32) -> str:
        """
        生成随机 API 密钥
        """
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))

    def get_default_api_key(self) -> str:
        """
        获取系统默认 API 密钥，供程序内部回调使用
        """
        keys = self.get_api_keys()
        for item in keys:
            if item.get("name") == DEFAULT_API_KEY_NAME:
                return item.get("api_key") or ""
        return keys[0].get("api_key") if keys else ""

    def add_api_key(self, name: str, api_key: str = None) -> tuple[bool, str, str]:
        """
        新增 API 密钥，未指定密钥内容时自动生成
        :return: (是否成功, 提示信息, 密钥内容)
        """
        name = str(name or "").strip()
        if not name:
            return False, "密钥名称不能为空", ""

        keys = self.get_api_keys()
        if any(_key.get("name") == name for _key in keys):
            return False, f"密钥名称 {name} 已存在", ""

        key_value = str(api_key or "").strip() or self.generate_api_key()
        if any(_key.get("api_key") == key_value for _key in keys):
            return False, "密钥内容已存在", ""

        create_time = self.current_time_str()
        if not self._db.insert_api_key(name, key_value, create_time):
            return False, "创建API密钥失败", ""

        log.info(f"【Security】新增API密钥：{name}")
        return True, "创建成功", key_value

    def delete_api_key(self, key_id) -> bool:
        """
        删除 API 密钥（系统默认密钥禁止删除）
        """
        try:
            key_id = int(key_id)
        except (TypeError, ValueError):
            return False
        item = next((_key for _key in self.get_api_keys() if _key.get("id") == key_id), None)
        if not item:
            return False
        if item.get("name") == DEFAULT_API_KEY_NAME:
            log.warn("【Security】系统默认API密钥禁止删除")
            return False
        if not self._db.delete_api_key(key_id):
            return False
        log.info(f"【Security】删除API密钥：id={key_id}")
        return True

    def regenerate_api_key(self, key_id) -> tuple[bool, str, str]:
        """
        重新生成系统默认 API 密钥
        :return: (是否成功, 提示信息, 新的密钥内容)
        """
        try:
            key_id = int(key_id)
        except (TypeError, ValueError):
            return False, "密钥不存在", ""
        item = next((_key for _key in self.get_api_keys() if _key.get("id") == key_id), None)
        if not item:
            return False, "密钥不存在", ""
        if item.get("name") != DEFAULT_API_KEY_NAME:
            return False, "仅系统默认密钥支持重新生成", ""

        key_value = self.generate_api_key()
        if not self._db.update_api_key(key_id,
                                       api_key=key_value,
                                       create_time=self.current_time_str()):
            return False, "重新生成失败", ""
        log.info("【Security】系统默认API密钥已重新生成")
        return True, "重新生成成功", key_value

    def verify_api_key(self, api_key: str) -> bool:
        """
        校验 API 密钥是否有效
        """
        if not api_key:
            return False
        for item in self.get_api_keys():
            try:
                if secrets.compare_digest(str(item.get("api_key") or ""), str(api_key)):
                    return True
            except TypeError:
                continue
        return False

    def ensure_default_api_key(self, cfg: dict) -> bool:
        """
        确保系统默认 API 密钥存在：
        优先使用旧版配置中的密钥值，没有则自动生成。
        :param cfg: 配置文件内容，处理后会移除 security.api_key
        :return: 配置是否发生变化
        """
        security = (cfg or {}).get("security") or {}
        legacy_key = str(security.get("api_key") or "").strip()
        config_changed = False
        if legacy_key:
            security.pop("api_key", None)
            config_changed = True

        keys = self.get_api_keys()
        if any(_key.get("name") == DEFAULT_API_KEY_NAME for _key in keys):
            # 已存在默认密钥时保持其当前值，避免覆盖用户重新生成的结果
            if config_changed:
                log.info("【Security】已移除配置文件中废弃的API密钥配置")
            return config_changed

        # 旧密钥值如已被其它记录占用，则将该记录设为系统默认
        if legacy_key:
            for item in keys:
                if item.get("api_key") == legacy_key:
                    if self._db.update_api_key(item["id"], name=DEFAULT_API_KEY_NAME):
                        log.info("【Security】已将旧版API密钥记录设为系统默认密钥")
                        return True
                    legacy_key = ""
                    break

        ok, _, _ = self.add_api_key(name=DEFAULT_API_KEY_NAME, api_key=legacy_key or None)
        if ok:
            log.info("【Security】已创建系统默认API密钥")
        else:
            log.warn("【Security】创建系统默认API密钥失败")
        return config_changed

    # ------------------------------------------------------------------
    # 外部请求来源 IP 校验
    # ------------------------------------------------------------------

    def check_mediaserver_ip(self, ip):
        return self.allow_access(self.media_server_webhook_allow_ip, ip)

    def check_telegram_ip(self, ip):
        return self.allow_access(self.telegram_webhook_allow_ip, ip)

    def check_synology_ip(self, ip):
        return self.allow_access(self.synology_webhook_allow_ip, ip)

    def check_slack_ip(self, ip):
        return self.allow_access({"ipv4": "127.0.0.1"}, ip)

    @staticmethod
    def allow_access(allow_ips, ip):
        """
        判断IP是否合法
        :param allow_ips: 充许的IP范围 {"ipv4":, "ipv6":}
        :param ip: 需要检查的ip
        """
        if not allow_ips:
            return True
        try:
            ipaddr = ipaddress.ip_address(ip)
            if ipaddr.version == 4:
                if not allow_ips.get('ipv4'):
                    return True
                allow_ipv4s = allow_ips.get('ipv4').split(",")
                for allow_ipv4 in allow_ipv4s:
                    if ipaddr in ipaddress.ip_network(allow_ipv4):
                        return True
            elif ipaddr.ipv4_mapped:
                if not allow_ips.get('ipv4'):
                    return True
                allow_ipv4s = allow_ips.get('ipv4').split(",")
                for allow_ipv4 in allow_ipv4s:
                    if ipaddr.ipv4_mapped in ipaddress.ip_network(allow_ipv4):
                        return True
            else:
                if not allow_ips.get('ipv6'):
                    return True
                allow_ipv6s = allow_ips.get('ipv6').split(",")
                for allow_ipv6 in allow_ipv6s:
                    if ipaddr in ipaddress.ip_network(allow_ipv6):
                        return True
        except Exception:
            log.exception("判断IP是否合法异常: ")
        return False
