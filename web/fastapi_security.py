from typing import Optional, Union
from fastapi import Request, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.responses import RedirectResponse

from app.utils import TokenCache
from config import Config
from web.backend.user import User
from web.security import identify, generate_access_token


# HTTP Bearer认证
bearer_scheme = HTTPBearer(auto_error=False)


# 会话认证依赖项
async def session_auth(request: Request) -> User:
    """
    检查用户是否通过会话认证
    """
    user_id = request.session.get("user_id")
    if not user_id:
        # 重定向到登录页面
        next_page = request.url.path
        return RedirectResponse(url=f"/?next={next_page}", status_code=status.HTTP_302_FOUND)
    
    user = User().get(user_id)
    if not user:
        # 重定向到登录页面
        next_page = request.url.path
        return RedirectResponse(url=f"/?next={next_page}", status_code=status.HTTP_302_FOUND)
    
    return user


# API Key认证依赖项
async def api_key_auth(request: Request) -> bool:
    """
    检查API Key是否有效
    """
    # 如果配置了不检查API Key，则直接通过
    if not Config().get_config("security").get("check_apikey"):
        return True
    
    # 从请求头获取API Key
    auth = request.headers.get("Authorization")
    if auth:
        auth = str(auth).split()[-1]
        if auth == Config().get_config("security").get("api_key"):
            return True
    
    # 从查询参数获取API Key
    auth = request.query_params.get("apikey")
    if auth and auth == Config().get_config("security").get("api_key"):
        return True
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="安全认证未通过，请检查ApiKey",
        headers={"WWW-Authenticate": "Bearer"},
    )


# JWT认证依赖项
async def jwt_auth(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> str:
    """
    检查JWT Token是否有效
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token未提供",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    latest_token = TokenCache.get(token)
    if not latest_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token无效",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    flag, username = identify(latest_token)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token无效",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not flag and username:
        TokenCache.set(token, generate_access_token(username))
    
    return username


# 获取当前用户依赖项
async def get_current_user(request: Request) -> User:
    """
    获取当前登录用户
    """
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户未登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = User().get(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user


# 组合认证依赖项
async def combined_auth(request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)) -> Union[User, str]:
    """
    组合认证：尝试会话认证和JWT认证
    """
    # 尝试会话认证
    user_id = request.session.get("user_id")
    if user_id:
        user = User().get(user_id)
        if user:
            return user
    
    # 尝试JWT认证
    if credentials:
        token = credentials.credentials
        latest_token = TokenCache.get(token)
        if latest_token:
            flag, username = identify(latest_token)
            if username:
                if not flag:
                    TokenCache.set(token, generate_access_token(username))
                user = User().get_user(username)
                if user:
                    return user
    
    # 尝试API Key认证
    auth = request.headers.get("Authorization")
    if auth:
        auth = str(auth).split()[-1]
        if auth == Config().get_config("security").get("api_key"):
            return "api_key"
    
    auth = request.query_params.get("apikey")
    if auth and auth == Config().get_config("security").get("api_key"):
        return "api_key"
    
    # 所有认证方式都失败
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="认证失败",
        headers={"WWW-Authenticate": "Bearer"},
    )
