import json
import base64

from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any

from app.utils import TokenCache
from config import Config
from web.action import WebAction
from web.backend.user import User
from web.security import generate_access_token, generate_refresh_token, refresh_access_token, revoke_refresh_token
from web.fastapi_security import jwt_auth


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


# 刷新Token请求模型
class RefreshTokenRequest(BaseModel):
    refresh_token: str


# 刷新Token响应模型
class RefreshTokenResponse(BaseModel):
    code: int
    success: bool
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


# API登录
@api_router.post("/user/login")
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

    # 生成双Token
    access_token = generate_access_token(username)
    refresh_token = generate_refresh_token(user_info.id, device_info=login_data.remember)

    # 缓存access_token
    TokenCache.set(access_token, access_token)

    # 创建响应数据
    response_data = {
        "code": 0,
        "success": True,
        "data": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token": access_token,  # 保持向后兼容
            "apikey": Config().get_config("security").get("api_key"),
            "userinfo": {
                "userid": user_info.id,
                "username": user_info.username,
            }
        }
    }

    # 创建响应对象

    response = JSONResponse(content=response_data)

    # 设置会话数据（为了兼容现有的/web路由）
    session_data = {
        "user_id": user_info.id,
        "username": user_info.username
    }

    # 设置会话cookie
    SESSION_COOKIE_NAME = "nastool_session"
    SESSION_MAX_AGE = 14 * 24 * 60 * 60  # 14天
    session_cookie = base64.b64encode(json.dumps(session_data).encode()).decode()

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_cookie,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/"
    )

    return response


# 刷新授权
@api_router.post("/auth/refresh", response_model=RefreshTokenResponse)
async def api_refresh_token(request: RefreshTokenRequest):
    """
    使用refresh_token刷新access_token
    """
    try:
        success, new_access_token, username = refresh_access_token(request.refresh_token)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Refresh token无效或已过期",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 缓存新的access_token
        TokenCache.set(new_access_token, new_access_token)

        # 获取用户信息
        user_info = User().get_user(username)

        return {
            "code": 0,
            "success": True,
            "data": {
                "access_token": new_access_token,
                "userinfo": {
                    "userid": user_info.id,
                    "username": user_info.username,
                }
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"刷新token失败: {str(e)}"
        )


# 登出（吊销refresh_token）
@api_router.post("/auth/logout")
async def api_logout(request: RefreshTokenRequest):
    """
    登出并吊销refresh_token
    """
    try:
        success = revoke_refresh_token(request.refresh_token)

        return {
            "code": 0,
            "success": True,
            "message": "登出成功" if success else "登出失败"
        }

    except Exception as e:
        return {
            "code": 1,
            "success": False,
            "message": f"登出失败: {str(e)}"
        }



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
async def api_upload(file: UploadFile = File(...), auth: str = Depends(jwt_auth)):
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
