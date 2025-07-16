from fastapi import Request, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.utils import TokenCache
from web.backend.user import User
from web.security import identify, generate_access_token


# HTTP Bearer认证
bearer_scheme = HTTPBearer(auto_error=False)


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



