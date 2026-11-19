import os
import platform
import shutil
import threading
import time
from importlib.util import find_spec
from urllib.parse import urlsplit

import log
from app.utils.commons import singleton
from app.utils.http_utils import RequestUtils
from config import Config

# 手动指定浏览器内核路径
CHROME_PATH_ENV = "NASTOOL_CHROME_PATH"

# 常见系统浏览器路径
LINUX_CHROME_PATHS = (
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/opt/google/chrome/chrome",
)
MACOS_CHROME_PATHS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)

# 容器内通常以非 root 运行，关闭沙箱并禁用共享内存依赖
BASE_LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--lang=zh-CN",
]


def _windows_chrome_paths():
    roots = (
        os.environ.get("PROGRAMFILES"),
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("LOCALAPPDATA"),
    )
    return [
        os.path.join(root, "Google", "Chrome", "Application", "chrome.exe")
        for root in roots if root
    ]


def find_chrome_executable():
    """
    查找可用的 Chrome/Chromium 可执行文件
    """
    env_path = os.environ.get(CHROME_PATH_ENV)
    if env_path:
        return env_path if os.path.isfile(env_path) else None

    if os.name == "nt":
        candidates = _windows_chrome_paths()
    elif platform.system() == "Darwin":
        candidates = list(MACOS_CHROME_PATHS)
    else:
        candidates = list(LINUX_CHROME_PATHS)

    for path in candidates:
        if os.path.isfile(path):
            return path

    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _default_browser_path():
    """
    patchright/playwright 安装浏览器的默认目录
    """
    explicit = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if explicit and explicit != "0":
        return explicit
    if os.name == "nt":
        return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ms-playwright")
    if platform.system() == "Darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Caches", "ms-playwright")
    return os.path.join(os.path.expanduser("~"), ".cache", "ms-playwright")


def has_bundled_browser():
    """
    是否已安装 patchright/playwright 自带的 Chromium
    """
    root = _default_browser_path()
    try:
        return any(entry.startswith("chromium") for entry in os.listdir(root))
    except OSError:
        return False


@singleton
class BrowserHelper:
    """
    浏览器仿真：按需启动 Chrome/Chromium 并执行页面操作

    同步 API 只能在普通线程中调用，不能运行在已存在的事件循环里。
    """

    _lock = threading.Lock()
    _available = None
    _unavailable_reason = ""
    _sync_playwright = None
    _library = ""

    def __init__(self):
        self.init_config()

    def init_config(self):
        self._available = None
        self._unavailable_reason = ""
        if self.available:
            log.info(f"【Browser】浏览器仿真可用：{self._library}")
        elif self._library:
            log.warn(f"【Browser】浏览器仿真不可用：{self._unavailable_reason}")
        else:
            log.info(f"【Browser】浏览器仿真未启用：{self._unavailable_reason}")

    @property
    def available(self):
        if self._available is None:
            self._detect()
        return self._available

    @property
    def unavailable_reason(self):
        if self._available is None:
            self._detect()
        return self._unavailable_reason

    def _detect(self):
        self._sync_playwright = None
        self._library = ""
        for module in ("patchright", "playwright"):
            if find_spec(module) is not None:
                self._library = module
                break

        if not self._library:
            self._available = False
            self._unavailable_reason = "当前镜像未内置浏览器仿真依赖（非 ext 镜像）"
            return

        if find_chrome_executable() or has_bundled_browser():
            self._available = True
            self._unavailable_reason = ""
            return

        self._available = False
        self._unavailable_reason = (
            "未检测到 Chrome/Chromium（当前镜像未内置浏览器内核，请使用 ext 镜像，"
            f"或通过环境变量 {CHROME_PATH_ENV} 指定浏览器路径）"
        )

    def _sync_playwright_api(self):
        if self._sync_playwright:
            return self._sync_playwright
        if self._library == "playwright":
            from playwright.sync_api import sync_playwright
        else:
            from patchright.sync_api import sync_playwright
        self._sync_playwright = sync_playwright
        return sync_playwright

    @staticmethod
    def _use_headless():
        """
        Linux 下没有可用的 X 显示时退回无头模式，其余环境使用有头模式
        """
        system = platform.system()
        if system in ("Windows", "Darwin"):
            return False
        if os.environ.get("DISPLAY"):
            return False
        try:
            from app.helper.display_helper import DisplayHelper
            DisplayHelper()
        except Exception:
            log.exception("【Browser】启动虚拟显示失败：")
        return not os.environ.get("DISPLAY")

    @staticmethod
    def _launch_kwargs(headless):
        kwargs = {
            "headless": headless,
            "args": list(BASE_LAUNCH_ARGS),
        }
        executable = find_chrome_executable()
        if executable:
            kwargs["executable_path"] = executable
        return kwargs

    @staticmethod
    def _build_cookies(url, cookie):
        if not cookie:
            return []
        split = urlsplit(url)
        if not split.hostname:
            return []
        origin = f"{split.scheme}://{split.netloc}/"
        return [
            {"name": name, "value": value, "url": origin}
            for name, value in RequestUtils.cookie_parse(cookie).items()
        ]

    @staticmethod
    def _clear_profile_lock(profile_dir):
        for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
            path = os.path.join(profile_dir, name)
            try:
                if os.path.lexists(path):
                    os.remove(path)
            except OSError:
                pass

    @staticmethod
    def _proxy_server(proxy):
        if not proxy:
            return None
        proxies = Config().get_proxies() or {}
        return proxies.get("https") or proxies.get("http")

    def run(self, url, callback, cookie=None, ua=None, proxy=False,
            profile_dir=None, timeout=60):
        """
        打开页面并执行 callback(page)，返回 (是否成功, 结果信息)
        """
        if not self.available:
            return False, self.unavailable_reason
        if not callback:
            return False, "浏览器仿真未提供操作回调"

        headless = self._use_headless()
        with self._lock:
            try:
                return self._run(url, callback, cookie, ua, proxy,
                                 profile_dir, timeout, headless)
            except Exception as err:
                log.exception("【Browser】浏览器仿真执行失败：")
                return False, f"浏览器仿真执行失败：{err!s}"

    def _run(self, url, callback, cookie, ua, proxy, profile_dir, timeout, headless):
        sync_playwright = self._sync_playwright_api()
        launch_kwargs = self._launch_kwargs(headless)
        proxy_server = self._proxy_server(proxy)
        if proxy_server:
            launch_kwargs["proxy"] = {"server": proxy_server}

        with sync_playwright() as playwright:
            browser = None
            if profile_dir:
                os.makedirs(profile_dir, exist_ok=True)
                self._clear_profile_lock(profile_dir)
                context = playwright.chromium.launch_persistent_context(
                    profile_dir, no_viewport=True, user_agent=ua or None, **launch_kwargs)
            else:
                browser = playwright.chromium.launch(**launch_kwargs)
                context = browser.new_context(
                    no_viewport=True,
                    user_agent=ua or None,
                )

            try:
                context.set_default_timeout(timeout * 1000)
                cookies = self._build_cookies(url, cookie)
                if cookies:
                    context.add_cookies(cookies)
                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_navigation_timeout(timeout * 1000)
                try:
                    return callback(page)
                except Exception as err:
                    log.exception("【Browser】页面操作失败：")
                    self._save_screenshot(page)
                    return False, f"页面操作失败：{err!s}"
            finally:
                context.close()
                if browser:
                    browser.close()

    def stop_service(self):
        """
        关闭按需启动的虚拟显示，浏览器实例在每次 run 结束时已关闭
        """
        if not self.available:
            return
        try:
            from app.helper.display_helper import DisplayHelper
            from app.utils.commons import INSTANCES
            display = INSTANCES.get(DisplayHelper)
            if display:
                display.stop_service()
        except Exception:
            log.exception("【Browser】关闭虚拟显示失败：")

    @staticmethod
    def _save_screenshot(page):
        try:
            path = os.path.join(
                Config().get_temp_path(),
                f"browser_fail_{time.strftime('%Y%m%d%H%M%S')}.png")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            page.screenshot(path=path)
            log.warn(f"【Browser】已保存失败截图：{path}")
        except Exception:
            pass
