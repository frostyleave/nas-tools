from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile
from pydantic import BaseModel

from app.utils import TokenCache
from config import Config
from web.action import WebAction
from web.backend.user import User
from web.security import generate_access_token
from web.fastapi_security import jwt_auth, api_key_auth

# API路由
api_router = APIRouter(prefix="/api")


# 登录请求模型
class LoginRequest(BaseModel):
    username: str
    password: str
    remember: Optional[bool] = False
    next: Optional[str] = ""


# 登录响应模型
class LoginResponse(BaseModel):
    code: int
    success: bool
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


# API登录
@api_router.post("/user/login", response_model=LoginResponse)
async def api_login(login_data: LoginRequest):
    username = login_data.username
    password = login_data.password

    if not username or not password:
        return {
            "code": 1,
            "success": False,
            "message": "用户名或密码错误"
        }

    user_info = User().get_user(username)
    if not user_info:
        return {
            "code": 1,
            "success": False,
            "message": "用户名或密码错误"
        }

    # 校验密码
    if not user_info.verify_password(password):
        return {
            "code": 1,
            "success": False,
            "message": "用户名或密码错误"
        }

    # 缓存Token
    token = generate_access_token(username)
    TokenCache.set(token, token)

    return {
        "code": 0,
        "success": True,
        "data": {
            "token": token,
            "apikey": Config().get_config("security").get("api_key"),
            "userinfo": {
                "userid": user_info.id,
                "username": user_info.username,
            }
        }
    }


# 用户信息
@api_router.get("/user/info")
async def api_user_info(username: str = Depends(jwt_auth)):
    user_info = User().get_user(username)
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "code": 0,
        "success": True,
        "data": {
            "userid": user_info.id,
            "username": user_info.username,
        }
    }


# 需要API Key认证的接口示例
@api_router.get("/system/info")
async def api_system_info(_: bool = Depends(api_key_auth)):
    return {
        "code": 0,
        "success": True,
        "data": {
            "version": "1.0.0",
            "name": "NAStool",
        }
    }


# 通用API请求模型
class ApiRequest(BaseModel):
    cmd: str
    data: Optional[Dict[str, Any]] = None


# 通用API响应模型
class ApiResponse(BaseModel):
    code: int
    success: bool
    message: Optional[str] = None
    data: Optional[Any] = None


# 通用API处理
@api_router.post("/", response_model=ApiResponse)
async def api_action(request: ApiRequest, auth: str = Depends(jwt_auth)):
    """
    通用API处理
    """
    cmd = request.cmd
    data = request.data or {}

    # 获取用户信息
    user_info = User().get_user(auth)

    # 将用户信息添加到data中
    if user_info:
        data["user"] = user_info

    # 执行WebAction
    result = WebAction().action(cmd, data)

    # 处理结果
    if isinstance(result, dict):
        code = result.get("code", 0)
        success = code == 0
        message = result.get("message", "")
        data = result.get("data") or result.get("result")

        return {
            "code": code,
            "success": success,
            "message": message,
            "data": data
        }
    else:
        return {
            "code": -1,
            "success": False,
            "message": "未知错误",
            "data": None
        }


# 文件上传
@api_router.post("/upload", response_model=ApiResponse)
async def api_upload(
    file: UploadFile = File(...),
    auth: str = Depends(jwt_auth)
):
    """
    文件上传
    """
    # 读取文件内容
    content = await file.read()

    # 处理文件上传
    result = WebAction().upload_file(
        file_name=file.filename,
        file_content=content
    )

    # 处理结果
    if isinstance(result, dict):
        code = result.get("code", 0)
        success = code == 0
        message = result.get("message", "")
        data = result.get("data") or result.get("result")

        return {
            "code": code,
            "success": success,
            "message": message,
            "data": data
        }
    else:
        return {
            "code": -1,
            "success": False,
            "message": "未知错误",
            "data": None
        }


# 站点信息
@api_router.get("/site/info", response_model=ApiResponse)
async def api_site_info(auth: str = Depends(jwt_auth)):
    """
    获取站点信息
    """
    result = WebAction().get_site_statistics()

    return {
        "code": 0,
        "success": True,
        "data": result.get("data")
    }


# 媒体库信息
@api_router.get("/library/info", response_model=ApiResponse)
async def api_library_info(auth: str = Depends(jwt_auth)):
    """
    获取媒体库信息
    """
    result = WebAction().get_library_mediacount()

    return {
        "code": 0,
        "success": True,
        "data": result
    }


# 下载器信息
@api_router.get("/download/info", response_model=ApiResponse)
async def api_download_info(auth: str = Depends(jwt_auth)):
    """
    获取下载器信息
    """
    result = WebAction().get_downloading()

    return {
        "code": 0,
        "success": True,
        "data": result.get("result")
    }


# 搜索
@api_router.post("/search", response_model=ApiResponse)
async def api_search(request: ApiRequest, auth: str = Depends(jwt_auth)):
    """
    搜索资源
    """
    data = request.data or {}

    # 执行搜索
    result = WebAction().search(data)

    # 处理结果
    if isinstance(result, dict):
        code = result.get("code", 0)
        success = code == 0
        message = result.get("message", "")
        data = result.get("data") or result.get("result")

        return {
            "code": code,
            "success": success,
            "message": message,
            "data": data
        }
    else:
        return {
            "code": -1,
            "success": False,
            "message": "未知错误",
            "data": None
        }


# 识别媒体信息
@api_router.post("/media/identify", response_model=ApiResponse)
async def api_media_identify(request: ApiRequest, auth: str = Depends(jwt_auth)):
    """
    识别媒体信息
    """
    data = request.data or {}

    # 执行识别
    result = WebAction().media_info(data)

    # 处理结果
    if isinstance(result, dict):
        code = result.get("code", 0)
        success = code == 0
        message = result.get("message", "")
        data = result.get("data") or result.get("result")

        return {
            "code": code,
            "success": success,
            "message": message,
            "data": data
        }
    else:
        return {
            "code": -1,
            "success": False,
            "message": "未知错误",
            "data": None
        }


# 刷新配置
@api_router.post("/system/refresh", response_model=ApiResponse)
async def api_system_refresh(auth: str = Depends(api_key_auth)):
    """
    刷新系统配置
    """
    result = WebAction().refresh_process({"type": "restart"})

    return {
        "code": 0,
        "success": True,
        "message": "刷新成功",
        "data": result
    }


# 获取系统进度
@api_router.get("/system/progress", response_model=ApiResponse)
async def api_system_progress(type: str, auth: str = Depends(api_key_auth)):
    """
    获取系统进度
    """
    result = WebAction().refresh_process({"type": type})

    return {
        "code": 0,
        "success": True,
        "data": result
    }
