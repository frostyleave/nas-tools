import base64
import hashlib
import hmac
import json
import re
import struct
import time
from datetime import datetime, timedelta, timezone

import log
from app.helper import ThreadHelper
from app.plugins.modules._base import _IPluginModule
from app.utils import SchedulerUtils, TimeUtils
from config import Config

# M-Team 站点时间固定为 UTC+8，profile 返回的时间是该时区的本地时间
_SITE_TZ = timezone(timedelta(hours=8))
# 签名 API 地址，按顺序容灾
_API_HOSTS = ("https://api.m-team.cc/api", "https://api.m-team.io/api", "https://api2.m-team.cc/api")
_WEB_ORIGIN = "https://kp.m-team.cc"
_APP_VERSION = "2.0.0"
_WEB_VERSION = "2000"
_TIMEOUT = 30
# 默认每天 09:00 执行
_DEFAULT_CRON = "0 9 * * *"
# 距上次登录超过该天数才重新登录
_LOGIN_INTERVAL_DAYS = 30
_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M")
# 前端入口脚本
_APP_JS_PATTERN = re.compile(r"https://static\.m-team\.cc/static/js/main\.[0-9a-f]+\.js")


class _MTeamClient:
    """
    M-Team 签名 API 客户端

    请求需带 _timestamp 与 _sgin 两个表单字段：
    _sgin = Base64(HMAC-SHA1("{METHOD}&{/api 路径}&{毫秒时间戳}", 密钥))
    """

    def __init__(self, proxy: dict | None = None):
        try:
            from curl_cffi import CurlMime
            from curl_cffi import requests as curl_requests
        except ImportError as err:
            raise RuntimeError("未安装 curl_cffi 依赖，请先执行 pip install curl_cffi") from err
        self._curl_requests = curl_requests
        self._mime_cls = CurlMime
        self._session = curl_requests.Session(impersonate="chrome", proxies=proxy or None)
        self._api = _API_HOSTS[0]
        # 签名密钥每次登录前从官网前端资源中重新获取
        self._secret = ""

    def _sign(self, method: str, path: str, ts_ms: int) -> str:
        if not self._secret:
            raise RuntimeError("签名密钥未初始化")
        msg = f"{method}&{path}&{ts_ms}".encode()
        digest = hmac.new(self._secret.encode(), msg, hashlib.sha1).digest()
        return base64.b64encode(digest).decode()

    @staticmethod
    def _headers() -> dict:
        return {
            "ts": str(int(time.time())),
            "version": _APP_VERSION,
            "webVersion": _WEB_VERSION,
            "visitorId": "",
            "Origin": _WEB_ORIGIN,
            "Referer": _WEB_ORIGIN + "/",
            "Accept": "application/json, text/plain, */*",
        }

    @staticmethod
    def _json(resp) -> dict:
        try:
            body = resp.json()
            return body if isinstance(body, dict) else {}
        except Exception:
            return {"code": -1, "message": (resp.text or "")[:200]}

    @staticmethod
    def code_of(body: dict) -> int:
        try:
            return int(body.get("code"))
        except (TypeError, ValueError, AttributeError):
            return -1

    @classmethod
    def is_success(cls, body: dict) -> bool:
        return cls.code_of(body) == 0

    def _send(self, path: str, method: str = "POST", fields: dict | None = None,
              params: dict | None = None, rotate: bool = True):
        """
        发送签名请求，连接失败时按顺序切换接口域名
        """
        ts_ms = int(time.time() * 1000)
        hosts = [self._api] + [host for host in _API_HOSTS if host != self._api] if rotate else [self._api]
        last_error = None
        for base in hosts:
            try:
                if method == "GET":
                    query = dict(params or {})
                    query["_timestamp"] = str(ts_ms)
                    query["_sgin"] = self._sign("GET", "/api" + path, ts_ms)
                    resp = self._session.get(base + path, params=query,
                                             headers=self._headers(), timeout=_TIMEOUT)
                else:
                    data = dict(fields or {})
                    data["_timestamp"] = str(ts_ms)
                    data["_sgin"] = self._sign("POST", "/api" + path, ts_ms)
                    mime = self._mime_cls()
                    for key, value in data.items():
                        mime.addpart(key, data=str(value).encode())
                    resp = self._session.post(base + path, multipart=mime,
                                              headers=self._headers(), timeout=_TIMEOUT)
            except Exception as err:
                last_error = err
                continue
            self._api = base
            return resp
        raise last_error or RuntimeError("M-Team 接口请求失败")

    def get_profile(self, apikey: str) -> dict:
        """
        使用站点 API Key 查询账号信息（该接口不需要签名）
        """
        headers = {
            "x-api-key": apikey,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
        }
        last_error = None
        for base in [self._api] + [host for host in _API_HOSTS if host != self._api]:
            try:
                resp = self._session.post(base + "/member/profile", headers=headers,
                                          json={}, timeout=_TIMEOUT)
            except Exception as err:
                last_error = err
                continue
            self._api = base
            return self._json(resp)
        raise last_error or RuntimeError("M-Team 账号信息查询失败")

    def cookie_header(self) -> str:
        """
        当前会话的 cookie，格式可直接粘贴到站点配置或请求头
        """
        return "; ".join(f"{morsel.name}={morsel.value}"
                         for morsel in self._session.cookies.jar)

    def cookie_export_json(self) -> str:
        """
        导出 Cookie-Editor 扩展可导入的 JSON
        """
        items = []
        for morsel in self._session.cookies.jar:
            domain = getattr(morsel, "domain", "") or getattr(morsel, "hostname", "") or ""
            expires = getattr(morsel, "expires", None)
            items.append({
                "domain": domain,
                "expirationDate": int(expires) if expires else None,
                "hostOnly": not domain.startswith("."),
                "httpOnly": self._is_http_only_cookie(morsel),
                "name": morsel.name,
                "path": getattr(morsel, "path", "") or "/",
                "sameSite": "unspecified",
                "secure": bool(getattr(morsel, "secure", False)),
                "session": not bool(expires),
                "storeId": "0",
                "value": morsel.value,
            })
        return json.dumps(items, ensure_ascii=False, indent=2)

    @staticmethod
    def _is_http_only_cookie(morsel) -> bool:
        """
        兼容 curl_cffi 与标准库两种 cookie 对象
        """
        if getattr(morsel, "http_only", False):
            return True
        checker = getattr(morsel, "has_nonstandard_attr", None)
        try:
            return bool(checker and checker("HttpOnly"))
        except Exception:
            return False

    def refresh_secret(self):
        """
        从官网前端入口脚本中重新提取签名密钥，并用一次签名请求验证
        """
        html = self._session.get(_WEB_ORIGIN + "/login", timeout=_TIMEOUT).text
        matched = _APP_JS_PATTERN.search(html)
        if not matched:
            raise RuntimeError("未能在登录页找到前端入口脚本")
        script = self._session.get(matched.group(0), timeout=60).text

        candidates = self._secret_candidates(script)
        if not candidates:
            raise RuntimeError("未能从网页资源中解析出签名密钥")
        for secret in candidates:
            if self._secret_works(secret):
                self._secret = secret
                return secret
        raise RuntimeError("网页资源中解析出的签名密钥均不可用")

    @staticmethod
    def _secret_candidates(script: str) -> list:
        """
        前端通过 ["H","L",...].join("") 拼出密钥，收集所有可能的候选值
        """
        candidates = []
        # 优先按 env 中 secret:xxx 的变量名定位其赋值
        for var_name in re.findall(r"secret:([A-Za-z_$][\w$]*)", script):
            matched = re.search(re.escape(var_name) + r'\s*=\s*[A-Za-z_$][\w$.]*\.join\(\[([^\]]+)\],\s*""\)', script)
            if matched:
                candidates.append("".join(re.findall(r'"([^"]*)"', matched.group(1))))
        # 兜底：扫描所有字符串数组的 join("") 调用
        for arr in re.findall(r'\.join\(\[([^\]]{2,600})\],\s*""\)', script):
            parts = re.findall(r'"([^"]*)"', arr)
            if 4 <= len(parts) and all(len(part) <= 8 for part in parts):
                candidates.append("".join(parts))
        result = []
        for secret in candidates:
            if 8 <= len(secret) <= 64 and secret not in result:
                result.append(secret)
        return result

    def _secret_works(self, secret: str) -> bool:
        """用不需要鉴权的接口验证候选密钥是否可用"""
        current = self._secret
        self._secret = secret
        try:
            body = self._json(self._send("/system/unix", method="GET", rotate=False))
            return self.is_success(body)
        except Exception:
            return False
        finally:
            self._secret = current

    def login(self, username: str, password: str, totp_secret: str = ""):
        """
        账号密码登录，需要两步验证时自动填入 TOTP 动态码
        :return: (token, 错误信息)
        """
        fields = {"username": username, "password": password, "turnstile": ""}
        resp = self._send("/login", fields=fields)
        body = self._json(resp)

        if self.code_of(body) == 1001:
            if not self._totp(totp_secret):
                return None, "账号需要两步验证，但 TOTP 密钥无效"
            self._wait_totp_window()
            fields["otpCode"] = self._totp(totp_secret)
            resp = self._send("/login", fields=fields, rotate=False)
            body = self._json(resp)

        token = resp.headers.get("authorization")
        if self.code_of(body) == 0 and token:
            return token, ""
        return None, body.get("message") or f"登录失败（code={body.get('code')}）"

    @staticmethod
    def _totp(secret: str, digits: int = 6, period: int = 30) -> str:
        """
        生成 TOTP 动态码，支持直接粘贴 otpauth:// 整串
        """
        value = str(secret or "").strip()
        matched = re.search(r"(?:^|[?&])secret=([A-Za-z2-7=]+)", value)
        if matched:
            value = matched.group(1)
        key = re.sub(r"\s+", "", value).upper().rstrip("=")
        if not key:
            return ""
        try:
            raw = base64.b32decode(key + "=" * (-len(key) % 8))
        except Exception:
            return ""
        counter = int(time.time()) // period
        digest = hmac.new(raw, struct.pack(">Q", counter), hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
        return f"{code % (10 ** digits):0{digits}d}"

    @staticmethod
    def _wait_totp_window(min_seconds: int = 15, period: int = 30):
        """窗口快结束时先等待，避免动态码在提交时失效"""
        remaining = period - int(time.time()) % period
        if remaining < min_seconds:
            time.sleep(remaining + 1)


class MTeamMonthLogin(_IPluginModule):
    # 插件名称
    module_name = "M-Team每月登录"
    # 插件描述
    module_desc = "定期检查 M-Team 上次登录时间，超过 30 天自动登录保号。"
    # 插件图标
    module_icon = "mteam.png"
    # 主题色
    module_color = "#3B82F6"
    # 插件版本
    module_version = "1.0"
    # 插件作者
    module_author = "frostyleave"
    # 插件配置项ID前缀
    module_config_prefix = "mteam_month_login_"
    # 加载顺序
    module_order = 0
    # 可使用的用户级别
    auth_level = 2

    # 运行参数
    _enabled = False
    _cron = None
    _username = ""
    _password = ""
    _totp_secret = ""
    _onlyonce = False
    _notify = False
    _use_proxy = False

    @staticmethod
    def get_fields():
        return [
            {
                'type': 'div',
                'content': [
                    [
                        {
                            'title': '启用插件',
                            'type': 'switch',
                            'id': 'enabled',
                            'tooltip': '开启后按运行周期检查登录状态'
                        },
                        {
                            'title': '立即运行一次',
                            'type': 'switch',
                            'id': 'onlyonce',
                            'tooltip': '保存配置后立即检查一次'
                        },
                        {
                            'title': '运行通知',
                            'type': 'switch',
                            'id': 'notify',
                            'tooltip': '执行登录后发送通知（需要在插件消息中配置）'
                        },
                        {
                            'title': '使用代理',
                            'type': 'switch',
                            'id': 'proxy',
                            'tooltip': '通过系统代理访问 M-Team'
                        }
                    ]
                ]
            },
            {
                'type': 'div',
                'content': [
                    [
                        {
                            'title': '运行周期',
                            'type': 'text',
                            'tooltip': 'cron 表达式，默认每天 09:00 执行',
                            'content': [
                                {
                                    'id': 'cron',
                                    'placeholder': '0 9 * * *'
                                }
                            ]
                        }
                    ]
                ]
            },
            {
                'type': 'div',
                'content': [
                    [
                        {
                            'title': '用户名',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'username',
                                    'placeholder': 'M-Team 用户名'
                                }
                            ]
                        },
                        {
                            'title': '密码',
                            'type': 'password',
                            'content': [
                                {
                                    'id': 'password',
                                    'placeholder': 'M-Team 密码'
                                }
                            ]
                        }
                    ]
                ]
            },
            {
                'type': 'div',
                'content': [
                    [
                        {
                            'title': 'TOTP 密钥',
                            'type': 'password',
                            'tooltip': '账号开启两步验证时必填，可粘贴 otpauth:// 整串',
                            'content': [
                                {
                                    'id': 'totp_secret',
                                    'placeholder': 'Base32 密钥'
                                }
                            ]
                        }
                    ]
                ]
            }
        ]

    def init_config(self, config: dict | None = None):
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._cron = (config.get("cron") or "").strip() or _DEFAULT_CRON
        self._username = (config.get("username") or "").strip()
        self._password = config.get("password") or ""
        self._totp_secret = (config.get("totp_secret") or "").strip()
        self._onlyonce = bool(config.get("onlyonce"))
        self._notify = bool(config.get("notify"))
        self._use_proxy = bool(config.get("proxy"))

        # 停止旧任务
        self.stop_service()

        if not (self._enabled or self._onlyonce):
            return
        if not self._username or not self._password:
            self.warn("未配置用户名或密码，插件不会执行")
            return

        # 立即运行一次
        if self._onlyonce:
            config["onlyonce"] = False
            self.update_config(config)
            ThreadHelper().start_thread(self.check_login, ())
            self.info("M-Team 登录检查启动，立即运行一次")

        # 周期运行
        if self._enabled and self._cron:
            self._cron_job = SchedulerUtils.add_job(scheduler=self.get_scheduler(),
                                                    func=self.check_login,
                                                    func_desc="M-Team每月登录",
                                                    cron=str(self._cron))

    def check_login(self):
        """
        检查上次登录时间，达到 30 天后执行登录
        """
        self.info("开始检查 M-Team 登录状态")
        try:
            client = _MTeamClient(proxy=self._get_proxies())
        except Exception as err:
            self.error(f"M-Team 客户端初始化失败：{err}")
            self._record("client_error", f"客户端初始化失败：{err}")
            return

        try:
            apikey = self._find_apikey()
            profile, reason = self._read_profile(client, apikey)

            last_login_text = ""
            if profile is not None:
                last_login_text = (profile.get("memberStatus") or {}).get("lastLogin") or ""
                last_login_ms = self._parse_site_time(last_login_text)
                elapsed_days = (time.time() * 1000 - last_login_ms) / 86400000 if last_login_ms else 0
                if elapsed_days:
                    if elapsed_days < _LOGIN_INTERVAL_DAYS:
                        self.info(f"上次登录距今 {elapsed_days:.1f} 天，未达到 {_LOGIN_INTERVAL_DAYS} 天，跳过登录")
                        self._record("skipped",
                                     f"API接口获取上次登录时间 {last_login_text}，"
                                     f"未达到 {_LOGIN_INTERVAL_DAYS} 天，跳过登录")
                        return
                    reason = (f"API接口获取上次登录时间 {last_login_text}，"
                              f"已达到 {_LOGIN_INTERVAL_DAYS} 天")
                    self.info(f"上次登录距今 {elapsed_days:.1f} 天，开始登录")
                else:
                    reason = "无法获取上次登录时间"
                    self.warn("无法获取上次登录时间，直接执行登录")

            # 每次登录前重新获取签名密钥
            client.refresh_secret()
            new_token, error = client.login(self._username, self._password, self._totp_secret)
            if not new_token:
                msg = f"M-Team 登录失败：{error}"
                self.error(msg)
                self._record("failed", msg)
                self._notify_result("M-Team每月登录失败", msg)
                return

            self.info("模拟登录成功，登录凭证仅记录到历史，不持久化复用")
            self._record("success", self._success_message(reason, new_token, client))
            self._notify_result("M-Team每月登录成功", f"模拟登录成功（{reason}）")
        except Exception as err:
            log.exception("【M-Team每月登录】执行异常: ")
            self._record("error", f"执行异常：{err}")
        finally:
            self.info("M-Team 登录检查结束")

    def _find_apikey(self) -> str:
        """
        从站点配置中查找 M-Team 站点的 API Key
        """
        from app.helper import DbHelper
        for site in DbHelper().get_config_site() or []:
            if site.API_KEY and "m-team" in str(site.SIGNURL or "").lower():
                return site.API_KEY
        return ""

    def _read_profile(self, client: _MTeamClient, apikey: str):
        """
        通过站点 API Key 读取账号信息，不需要登录凭证
        :return: (profile, 未读取成功的原因)
        """
        if not apikey:
            self.warn("站点配置中未找到 M-Team 的 API Key，无法读取上次登录时间")
            return None, "站点配置中未找到 M-Team 的 API Key"
        body = client.get_profile(apikey)
        if client.is_success(body) and isinstance(body.get("data"), dict):
            return body["data"], ""
        reason = f"API Key 读取账号信息失败（{body.get('message') or body.get('code')}）"
        self.warn(reason)
        return None, reason

    def _success_message(self, reason: str, token: str, client: _MTeamClient) -> str:
        """
        生成登录成功的历史记录：token、cookie，以及可复制到浏览器的凭证
        """
        lines = [f"{reason}，模拟登录成功",
                 f"token={token}",
                 "",
                 "网页端登录凭证保存在 localStorage 的 auth 中，打开 kp.m-team.cc 后在控制台执行：",
                 f"localStorage.setItem('auth', '{token}'); location.href = '/';"]
        cookie = client.cookie_header()
        if cookie:
            lines.extend(["", f"cookie={cookie}", "", "Cookie-Editor 扩展可导入的 JSON：",
                          client.cookie_export_json()])
        return "\n".join(lines)

    def _get_proxies(self):
        if not self._use_proxy:
            return None
        return Config().get_proxies() or None

    @staticmethod
    def _parse_site_time(value) -> int:
        """
        解析站点时间（UTC+8 的本地时间字符串），返回毫秒时间戳
        """
        text = str(value or "").strip()
        text = re.sub(r"\s*[（(][^()（）]*[）)]\s*$", "", text)
        if not text:
            return 0
        for fmt in _TIME_FORMATS:
            try:
                moment = datetime.strptime(text, fmt).replace(tzinfo=_SITE_TZ)
                return int(moment.timestamp() * 1000)
            except ValueError:
                continue
        return 0

    def _record(self, status: str, message: str):
        """
        写入当天的运行历史，状态取值：success/skipped/failed/error/client_error
        """
        key = TimeUtils.now_str("%Y-%m-%d")
        value = {"status": status, "message": message, "time": TimeUtils.now_str()}
        if self.get_history(key=key):
            self.update_history(key=key, value=value)
        else:
            self.history(key=key, value=value)

    def format_history(self, key, value):
        if isinstance(value, dict) and value.get("status"):
            status_text = {
                "success": "登录成功",
                "skipped": "无需登录",
                "failed": "登录失败",
                "error": "执行异常",
                "client_error": "依赖异常",
            }.get(value.get("status"), value.get("status"))
            return f"{status_text}：{value.get('message') or ''}"
        return super().format_history(key, value)

    def _notify_result(self, title: str, text: str):
        if not self._notify:
            return
        try:
            self.send_message(title=title, text=text)
        except Exception:
            log.exception("【M-Team每月登录】发送通知失败: ")

    def stop_service(self):
        try:
            self.remove_job(self._cron_job)
        except Exception as err:
            log.exception(f"【M-Team每月登录】移除定时任务失败: {err}")
        self._cron_job = None

    def get_state(self):
        return bool(self._enabled and self._cron)
