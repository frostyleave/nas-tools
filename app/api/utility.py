import asyncio
import hashlib
import ipaddress
import os
import re
import shutil
import socket
from pathlib import Path
from typing import Annotated
from urllib.parse import unquote, urljoin, urlparse, urlunparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

import log
from app.middleware.security import auth_check, get_current_user
from app.models.user import LEVEL_OPERATOR, LEVEL_SYSADMIN, LEVEL_USER
from app.modules.system.backup import Backup
from app.utils import PathUtils, SystemUtils
from app.utils.async_request import AsyncRequestUtils
from app.utils.types import OsType
from config import Config

# 工具/文件路由
utility_router = APIRouter(
    dependencies=[Depends(get_current_user)]
)

# ------------------------
# 常量
# ------------------------
# 图片中转响应大小上限（20MB）
MAX_IMAGE_SIZE = 20 * 1024 * 1024
# 图片中转最多跟随的重定向次数
MAX_IMAGE_REDIRECTS = 3
# 上传文件大小上限（2GB）
MAX_UPLOAD_SIZE = 2 * 1024 * 1024 * 1024

# 豆瓣图片域名，前端只会上送这类地址
DOUBAN_IMG_HOST_RE = re.compile(r"^img\d+\.doubanio\.com$")
DOUBAN_REFERER = "https://movie.douban.com/"


# ------------------------
# 目录浏览
# ------------------------
def _list_root_dirs() -> list[str]:
    """列出根目录：Windows 为盘符，其他系统为 / 下的条目"""
    if SystemUtils.get_system() == OsType.WINDOWS:
        partitions = SystemUtils.get_windows_drives()
        if partitions:
            return partitions
        return [os.path.join("C:/", name) for name in os.listdir("C:/")]
    return [os.path.join("/", name) for name in os.listdir("/")]


def _build_dir_items(dirs: list[str], show_files: bool) -> list[str]:
    """把目录/文件路径转换成 jqueryFileTree 的 li 节点"""
    items = []
    for path in dirs:
        name = os.path.basename(path) or path
        rel_path = path.replace("\\", "/")
        rel_name = name.replace("\\", "/")
        if os.path.isdir(path):
            items.append(f'<li class="directory collapsed"><a rel="{rel_path}/">{rel_name}</a></li>')
        elif show_files:
            ext = os.path.splitext(name)[1][1:]
            items.append(f'<li class="file ext_{ext}"><a rel="{rel_path}">{rel_name}</a></li>')
    return items


@utility_router.post("/dirlist")
@auth_check(LEVEL_OPERATOR)
async def dirlist(request: Request) -> Response:
    """
    目录事件响应（供前端 jqueryFileTree 使用）
    """
    items: list[str] = []
    error: str | None = None
    try:
        form = await request.form()
        in_dir = unquote(form.get("dir") or "")
        if not in_dir or in_dir == "/":
            dirs = _list_root_dirs()
        else:
            target = os.path.normpath(in_dir)
            if not os.path.isdir(target):
                target = os.path.dirname(target)
            dirs = [os.path.join(target, name) for name in os.listdir(target)]
        items = _build_dir_items(dirs, form.get("filter") != "HIDE_FILES_FILTER")
    except Exception as err:
        log.exception("[App]加载路径失败: ")
        error = str(err)

    content = f'<ul class="jqueryFileTree" style="display: none;">{"".join(items)}</ul>'
    if error:
        content += f"加载路径失败: {error}"
    return Response(content=content, media_type="text/html")


# ------------------------
# 文件上传
# ------------------------
def _copy_to_file(source, file_path: Path):
    """把上传的临时文件分块复制到目标路径"""
    with open(file_path, "wb") as dest:
        shutil.copyfileobj(source, dest, length=1024 * 1024)


async def _save_upload(upload_file: UploadFile, file_path: Path):
    """校验大小后在线程池写盘，避免阻塞事件循环"""
    if upload_file.size is not None and upload_file.size > MAX_UPLOAD_SIZE:
        raise ValueError("文件超过大小限制")
    await run_in_threadpool(_copy_to_file, upload_file.file, file_path)
    if os.path.getsize(file_path) > MAX_UPLOAD_SIZE:
        raise ValueError("文件超过大小限制")


@utility_router.post("/upload")
@auth_check(LEVEL_USER)
async def upload(request: Request):
    """
    上传文件到服务器临时目录
    """
    file_path = None
    try:
        form = await request.form()
        files = form.get("file")
        if not isinstance(files, UploadFile) or not files.filename:
            return {"code": 1, "msg": "未获取到上传文件", "filepath": ""}

        # 只保留文件名，防止 ../、绝对路径、Windows 盘符等路径穿越
        file_name = PathUtils.safe_filename(files.filename)
        if not file_name:
            log.warn(f"【Security】非法的上传文件名: {files.filename}")
            return {"code": 1, "msg": "文件名无效", "filepath": ""}

        temp_path = Path(Config().get_temp_path()).resolve()
        temp_path.mkdir(parents=True, exist_ok=True)
        file_path = (temp_path / file_name).resolve()
        # 二次校验：解析后必须仍位于临时目录内
        if not PathUtils.is_within_dir(file_path, temp_path) or file_path.parent != temp_path:
            log.warn(f"【Security】非法的上传文件名: {files.filename}")
            return {"code": 1, "msg": "文件名无效", "filepath": ""}

        await _save_upload(files, file_path)
        return {"code": 0, "filepath": str(file_path)}
    except Exception as err:
        # 清理写了一半的文件
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass
        log.exception("[App]文件上传失败: ")
        return {"code": 1, "msg": str(err), "filepath": ""}


# ------------------------
# 配置备份
# ------------------------
@utility_router.post("/backup")
@auth_check(LEVEL_SYSADMIN)
def backup() -> Response:
    """
    备份用户设置文件

    同步接口：备份包含拷贝与压缩，交给线程池执行，避免阻塞事件循环。
    """
    zip_file = Backup().backup()
    if not zip_file:
        return Response(content="创建备份失败", status_code=400)
    return FileResponse(zip_file)


# ------------------------
# 通用图片中转 /img
# ------------------------
def _is_allowed_image_url(url: str) -> bool:
    """
    校验 /img 的中转目标

    /img 的主要用途是中转 Jellyfin / Emby / Plex 的海报，目标通常是内网或回环地址，
    因此不能按 IP 段拦截；这里只限制 http/https，避免 file:// 等本地协议被读取。
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.hostname)


async def _fetch_image(url: str) -> tuple[bytes | None, int]:
    """
    异步抓取图片，手动跟随重定向并限制跳转次数、协议与响应大小

    :return: (图片内容, 建议返回的状态码)；内容为 None 时按状态码返回错误
    """
    client = AsyncRequestUtils.get_http_client()
    current_url = url
    for _ in range(MAX_IMAGE_REDIRECTS + 1):
        if not _is_allowed_image_url(current_url):
            log.warn(f"【Security】图片代理拒绝了不支持的地址: {current_url}")
            raise HTTPException(status_code=400, detail="非法的图片地址")
        try:
            async with client.stream("GET", current_url,
                                     follow_redirects=False,
                                     timeout=20.0) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("Location")
                    if not location:
                        return None, 502
                    current_url = urljoin(current_url, location)
                    continue
                if resp.status_code != 200:
                    return None, 502
                content = bytearray()
                async for chunk in resp.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_IMAGE_SIZE:
                        log.warn(f"【Security】图片代理响应超过大小上限，已终止: {current_url}")
                        return None, 413
                return bytes(content), 200
        except httpx.RequestError as err:
            log.warn(f"【Http】图片代理请求失败 {current_url}: {err!s}")
            return None, 502
    return None, 502


@utility_router.get("/img")
async def img(request: Request, url: str):
    """
    图片中转服务

    异步接口：复用全局 AsyncClient 的连接池，不占用线程池工作线程。
    """
    if not url:
        return Response(content="参数错误", status_code=400)

    # 计算 Etag
    etag = hashlib.sha256(url.encode("utf-8")).hexdigest()

    # 检查协商缓存
    if_none_match = request.headers.get("If-None-Match")
    if if_none_match and if_none_match == etag:
        return Response(content="", status_code=304)

    content, status_code = await _fetch_image(url)
    if content is None:
        detail = "图片过大" if status_code == 413 else "获取图片失败"
        return Response(content=detail, status_code=status_code)

    response = Response(content=content, media_type="image/jpeg")
    response.headers["Cache-Control"] = "max-age=604800"
    response.headers["Etag"] = etag
    return response


# ------------------------
# 豆瓣图片中转 /doubanimg
# ------------------------
def _parse_host_port(url: str) -> tuple[str, int] | None:
    """解析 http(s) 地址，返回 (host, port) 或 None"""
    try:
        parsed = urlparse(url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    return parsed.hostname, port


def _addresses_are_public(infos) -> bool:
    """解析结果中的所有 IP 都必须是公网地址"""
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(str(info[4][0]).split("%", 1)[0])
        except ValueError:
            return False
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False
    return True


async def _is_public_remote_url(url: str) -> bool:
    """
    校验图片代理目标地址，防止 SSRF（异步解析，不阻塞事件循环）
    """
    target = _parse_host_port(url)
    if not target:
        return False
    host, port = target
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError, ValueError):
        return False
    return _addresses_are_public(infos)


def _force_webp(url: str) -> str:
    """把豆瓣图片地址的后缀替换为 .webp"""
    parsed = urlparse(url)
    root, ext = os.path.splitext(parsed.path)
    # 已经是 webp 或没有后缀，直接返回
    if ext.lower() == ".webp" or not ext:
        return url
    return urlunparse(parsed._replace(path=root + ".webp"))


async def _limited_image_stream(resp):
    """
    边转发边限制响应大小，防止上游返回超大文件耗尽带宽/内存
    """
    total = 0
    async for chunk in resp.aiter_bytes():
        total += len(chunk)
        if total > MAX_IMAGE_SIZE:
            log.warn(f"【Security】图片代理响应超过大小上限，已截断: {resp.url}")
            await resp.aclose()
            return
        yield chunk


@utility_router.get("/doubanimg")
async def proxy_douban_image(
    url: Annotated[str, Query(..., description="Douban image url")]
):
    """
    豆瓣图片中转服务

    只允许豆瓣图片域名，并在转发前做 DNS 解析防止 SSRF。
    """
    parsed = urlparse(url)
    # 安全校验：只允许豆瓣图片域名
    if parsed.scheme != "https" \
            or not parsed.hostname \
            or not DOUBAN_IMG_HOST_RE.match(parsed.hostname):
        raise HTTPException(status_code=400, detail="Invalid url")

    webp_url = _force_webp(url)
    if not await _is_public_remote_url(webp_url):
        raise HTTPException(status_code=400, detail="Invalid url")

    client = AsyncRequestUtils.get_http_client()
    headers = {
        "Referer": DOUBAN_REFERER,
        "User-Agent": Config().get_ua(),
    }

    try:
        # 不自动跟随重定向，避免被跳转到内网地址
        resp = await client.get(webp_url, headers=headers, follow_redirects=False)
    except httpx.RequestError as err:
        raise HTTPException(status_code=502, detail="Upstream connection error") from err

    if resp.status_code != 200:
        await resp.aclose()
        raise HTTPException(status_code=502, detail="Upstream request failed")

    try:
        content_length = int(resp.headers.get("content-length") or 0)
    except ValueError:
        content_length = 0
    if content_length > MAX_IMAGE_SIZE:
        await resp.aclose()
        raise HTTPException(status_code=413, detail="Upstream image too large")

    return StreamingResponse(
        _limited_image_stream(resp),
        media_type=resp.headers.get("content-type", "image/webp"),
        headers={"Cache-Control": "public, max-age=86400"},
    )
