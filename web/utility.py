import os
import hashlib

from urllib.parse import unquote
from pathlib import Path

from fastapi import APIRouter, Request, Depends, Response
from fastapi.responses import FileResponse

import log

from app.utils.system_utils import SystemUtils
from app.utils.types import *

from config import Config

from web.action import WebAction
from web.backend.security import get_current_user
from web.backend.web_utils import WebUtils


# 工具/文件路由
utility_router = APIRouter(
    dependencies=[Depends(get_current_user)]
)


# 目录事件响应
@utility_router.post("/dirlist")
async def dirlist(request: Request):
    """
    目录事件响应
    """
    r = ['<ul class="jqueryFileTree" style="display: none;">']
    try:
        r = ['<ul class="jqueryFileTree" style="display: none;">']
        form = await request.form()
        in_dir = unquote(form.get('dir'))
        ft = form.get("filter")
        if not in_dir or in_dir == "/":
            if SystemUtils.get_system() == OsType.WINDOWS:
                partitions = SystemUtils.get_windows_drives()
                if partitions:
                    dirs = partitions
                else:
                    dirs = [os.path.join("C:/", f) for f in os.listdir("C:/")]
            else:
                dirs = [os.path.join("/", f) for f in os.listdir("/")]
        else:
            d = os.path.normpath(unquote(in_dir))
            if not os.path.isdir(d):
                d = os.path.dirname(d)
            dirs = [os.path.join(d, f) for f in os.listdir(d)]
        for ff in dirs:
            f = os.path.basename(ff)
            if not f:
                f = ff
            if os.path.isdir(ff):
                r.append('<li class="directory collapsed"><a rel="%s/">%s</a></li>' % (
                    ff.replace("\\", "/"), f.replace("\\", "/")))
            else:
                if ft != "HIDE_FILES_FILTER":
                    e = os.path.splitext(f)[1][1:]
                    r.append('<li class="file ext_%s"><a rel="%s">%s</a></li>' % (
                        e, ff.replace("\\", "/"), f.replace("\\", "/")))
        r.append('</ul>')
    except Exception as e:
        log.exception('[App]加载路径失败: ')
        r.append('加载路径失败: %s' % str(e))
    r.append('</ul>')
    return Response(content=''.join(r), media_type="text/html")


# 备份配置文件
@utility_router.post("/backup")
async def backup():
    """
    备份用户设置文件
    :return: 备份文件.zip_file
    """
    zip_file = WebAction().backup()
    if not zip_file:
        return Response(content="创建备份失败", status_code=400)
    return FileResponse(zip_file)


# 上传文件到服务器
@utility_router.post("/upload")
async def upload(request: Request):
    """
    上传文件到服务器
    """
    try:
        form = await request.form()
        files = form.get('file')
        temp_path = Config().get_temp_path()
        if not os.path.exists(temp_path):
            os.makedirs(temp_path)
        file_path = Path(temp_path) / files.filename

        # 保存文件
        with open(file_path, "wb") as f:
            content = await files.read()
            f.write(content)

        return {"code": 0, "filepath": str(file_path)}
    except Exception as e:
        log.exception('[App]文件上传失败: ')
        return {"code": 1, "msg": str(e), "filepath": ""}


# 图片中转服务
@utility_router.get("/img")
async def img(request: Request, url: str):
    """
    图片中转服务
    """
    if not url:
        return Response(content="参数错误", status_code=400)

    # 计算Etag
    etag = hashlib.sha256(url.encode('utf-8')).hexdigest()

    # 检查协商缓存
    if_none_match = request.headers.get('If-None-Match')
    if if_none_match and if_none_match == etag:
        return Response(content='', status_code=304)

    # 获取图片数据
    response = Response(
        content=WebUtils.request_cache(url),
        media_type='image/jpeg'
    )
    response.headers['Cache-Control'] = 'max-age=604800'
    response.headers['Etag'] = etag
    return response

