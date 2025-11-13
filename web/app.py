import os

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import log

from web.action import action_router
from web.auth import auth_router
from web.data import data_router
from web.open import open_router
from web.streaming import streaming_router
from web.utility import utility_router

from web.backend.wallpaper import get_login_wallpaper
from web.lifespan import lifespan

from version import APP_VERSION

# FastAPI App
app = FastAPI(
    title="NAStool",
    lifespan=lifespan,
    version=APP_VERSION,
)

# 启用CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 启用压缩
app.add_middleware(GZipMiddleware, minimum_size=1000)

# 注册路由
app.include_router(open_router)
app.include_router(data_router)
app.include_router(auth_router)
app.include_router(action_router)
app.include_router(streaming_router)
app.include_router(utility_router)

# 静态文件
app.mount("/static", StaticFiles(directory="web/static"), name="static")


# 页面不存在
@app.exception_handler(404)
async def page_not_found(request: Request, exc):
    return FileResponse("web/static/404.html", status_code=404)

# 服务错误
@app.exception_handler(500)
async def page_server_error(request: Request, exc):
    return FileResponse("web/static/500.html", status_code=500)

# favicon.ico
@app.get("/favicon.ico")
async def favicon():
    """
    网站图标
    """
    favicon_path = os.path.join("web", "static", "favicon.ico")
    if os.path.exists(favicon_path):
        return FileResponse(favicon_path)
    else:
        raise HTTPException(status_code=404, detail="Favicon not found")


# 禁止搜索引擎
@app.get("/robots.txt")
async def robots():
    """
    禁止搜索引擎
    """
    return FileResponse("robots.txt")


# 主页面
@app.get("/", response_class=HTMLResponse)
async def home_page():
    return FileResponse("web/static/index.html")


# bing
@app.post("/data/bing")
async def bing():

    image_code, img_title, img_link = get_login_wallpaper()

    data = {
        "imageCode" : image_code,
        "imgTitle" : img_title,
        "imgLink" : img_link
    }

    return JSONResponse(
        content=jsonable_encoder({
            "code": 0,
            "msg": "success",
            "data": data
        }),
        status_code=200
    )
