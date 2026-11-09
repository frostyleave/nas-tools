import hashlib
import os
import re
import stat
from functools import lru_cache

from fastapi.staticfiles import StaticFiles
from starlette.responses import HTMLResponse, Response

# 内容稳定、随版本整体替换的目录：命中后浏览器一年内不再请求
LONG_CACHE_PREFIXES = ("libs/", "img/")
LONG_CACHE_CONTROL = "public, max-age=31536000, immutable"
# 业务资源（页面片段、自研 JS/CSS、组件）每次使用前向服务器协商，改完刷新即生效
REVALIDATE_CACHE_CONTROL = "no-cache, must-revalidate"

# static/libs 的版本号作为路径片段插入 URL：/static/libs/<版本>/...
# 这样 libs 内部 CSS 里的相对 url() 也会自动带上版本，升级后不会命中旧缓存
LIBS_VERSION_SEGMENT_RE = re.compile(r"^libs/[0-9a-f]{10}/(?P<rest>.+)$")
LIBS_URL_RE = re.compile(r"((?:\.\./|/)static/libs/)")


@lru_cache(maxsize=4)
def get_libs_version(libs_dir: str = os.path.join("static", "libs")) -> str:
    """
    计算 static/libs 的内容版本：内容不变则版本不变，无需手工维护。
    只在进程启动后首次使用时计算一次，改动 libs 后需重启服务才会换版本。
    """
    if not os.path.isdir(libs_dir):
        return ""
    digest = hashlib.sha1()
    for root, dirs, files in os.walk(libs_dir):
        dirs.sort()
        for name in sorted(files):
            file_path = os.path.join(root, name)
            rel_path = os.path.relpath(file_path, libs_dir).replace(os.sep, "/")
            digest.update(rel_path.encode("utf-8"))
            try:
                with open(file_path, "rb") as fp:
                    while True:
                        chunk = fp.read(65536)
                        if not chunk:
                            break
                        digest.update(chunk)
            except OSError:
                continue
    return digest.hexdigest()[:10]


def inject_libs_version(html: str, version: str | None = None) -> str:
    """
    给 HTML 中的 /static/libs/、../static/libs/ 链接插入版本路径片段
    """
    if version is None:
        version = get_libs_version()
    if not version:
        return html
    return LIBS_URL_RE.sub(lambda match: f"{match.group(1)}{version}/", html)


def render_html(path: str,
                status_code: int = 200,
                headers: dict | None = None,
                add_libs_version_meta: bool = False) -> HTMLResponse:
    """
    读取 HTML 并注入 libs 版本，供首页与 404/500 等直接返回文件的场景使用
    """
    with open(path, "rb") as fp:
        content = fp.read().decode("utf-8")
    content = inject_libs_version(content)
    if add_libs_version_meta:
        version = get_libs_version()
        if version and 'name="libs-version"' not in content:
            content = content.replace(
                "<head>",
                f'<head>\n  <meta name="libs-version" content="{version}">',
                1
            )
    return HTMLResponse(content=content, status_code=status_code, headers=headers or {})


class StaticFilesWithCache(StaticFiles):
    """
    按路径区分静态资源缓存策略，并为 static/libs 提供版本化 URL：
    - /static/libs/<版本>/...：剥掉版本片段后按原路径返回文件，长缓存 + immutable
    - 其它：no-cache + ETag，文件变化后浏览器立即拿到新版本
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._libs_version = get_libs_version(os.path.join(str(self.directory), "libs"))

    async def get_response(self, path: str, scope) -> Response:
        path = self._normalize_path(path)
        path = self._strip_libs_version(path)
        if path.endswith(".html") and scope.get("method", "GET") in ("GET", "HEAD"):
            html_response = self._html_response(path, scope)
            if html_response is not None:
                return html_response
        response = await super().get_response(path, scope)
        for key, value in self._cache_headers(path).items():
            response.headers[key] = value
        return response

    @staticmethod
    def _normalize_path(path: str) -> str:
        # Windows 下 Starlette 的 get_path() 会产出反斜杠分隔的路径
        # （os.path.normpath），统一成正斜杠，否则版本片段与缓存前缀都匹配不到
        return path.replace("\\", "/").lstrip("/")

    @staticmethod
    def _strip_libs_version(path: str) -> str:
        return LIBS_VERSION_SEGMENT_RE.sub(r"libs/\g<rest>", path)

    @staticmethod
    def _cache_headers(path: str) -> dict:
        if path.lstrip("/").startswith(LONG_CACHE_PREFIXES):
            return {"Cache-Control": LONG_CACHE_CONTROL}
        return {
            "Cache-Control": REVALIDATE_CACHE_CONTROL,
            "Pragma": "no-cache",
            "Expires": "0",
        }

    def _html_response(self, path: str, scope) -> Response | None:
        try:
            full_path, stat_result = self.lookup_path(path)
        except (OSError, ValueError):
            # 交给父类按标准流程报错 (404/401)
            return None
        if not full_path or stat_result is None or not stat.S_ISREG(stat_result.st_mode):
            return None
        with open(full_path, "rb") as fp:
            content = fp.read().decode("utf-8")
        body = inject_libs_version(content, self._libs_version).encode("utf-8")
        # ETag 基于注入版本后的内容，libs 版本变化时 ETag 同步变化，不会错误命中 304
        etag = f'"{hashlib.sha1(body).hexdigest()}"'
        headers = self._cache_headers(path)
        headers["ETag"] = etag
        if scope.get("method", "GET").upper() == "HEAD":
            return Response(status_code=200, headers=headers, media_type="text/html; charset=utf-8")
        if self._etag_matched(scope, etag):
            return Response(status_code=304, headers=headers)
        return Response(content=body, headers=headers, media_type="text/html; charset=utf-8")

    @staticmethod
    def _etag_matched(scope, etag: str) -> bool:
        for key, value in scope.get("headers", []):
            if key.lower() == b"if-none-match":
                candidates = [item.strip() for item in value.decode("latin-1").split(",")]
                return "*" in candidates or etag in candidates
        return False
