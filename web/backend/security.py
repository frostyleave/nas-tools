from datetime import datetime, timedelta
from functools import partial, wraps
from typing import Optional

from fastapi import HTTPException, Request, status
from fastapi.requests import HTTPConnection
from jose import JWTError, jwt
from passlib.context import CryptContext

import log

from config import Config
from web.backend.user import User, UserManager

def get_secret() -> str:
    """
    从 Config 单例获取 JWT Secret
    """
    return Config().get_config("security").get("jwt_secret")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 10      # 访问 token 过期时间
REFRESH_TOKEN_EXPIRE_DAYS = 7         # 刷新 token 过期时间
COOKIE_MAX_AGE = REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60  # cookie最大生存时间

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ------------------------
# 密码与用户工具函数
# ------------------------
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def authenticate_user(username: str, password: str) -> User:
    user = UserManager().get_user_by_name(username)
    if not user or not user.verify_password(password):
        return None
    return user

# ------------------------
# JWT 工具函数
# ------------------------
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, get_secret(), algorithm=ALGORITHM)

def decode_access_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, get_secret(), algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
        return username
    except JWTError:
        return None
    
def validate_refresh_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, get_secret(), algorithms=[ALGORITHM])
        if not payload or payload.get("type") != "refresh":
            return None
        username: str = payload.get("sub")
        if username is None:
            return None
        return username
    except JWTError:
        return None
    

# 解析http请求中的用户
async def get_current_user(request: HTTPConnection):
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="缺少 access_token")
    username = decode_access_token(token)
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效 token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = UserManager().get_user_by_name(username)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


def auth_required(func=None):
    """
    API安全认证
    """
    if func is None:
        return partial(auth_required)

    @wraps(func)
    async def wrapper(*args, **kwargs):

        check_apikey = Config().get_config("security").get("check_apikey")
        if not check_apikey:
            return func(*args, **kwargs)
        
        log.debug(f"【Security】{func.__name__} 认证检查")
        
        setting_api_key = Config().get_config("security").get("api_key")
        request: Request = kwargs.get("request") or args[0]

        # 允许在请求头Authorization中添加apikey
        auth = request.headers.get("Authorization")
        if auth:
            auth = str(auth).split()[-1]
            if auth == setting_api_key:
                return await func(*args, **kwargs)
            
        # 允许使用在api后面拼接 ?apikey=xxx 的方式进行验证
        auth = request.query_params.get("apikey")
        if auth:
            if auth == setting_api_key:
                return await func(*args, **kwargs)
            
        log.warn(f"【Security】{func.__name__} 认证未通过, 请检查API Key")
        return {
            "code": 401,
            "success": False,
            "message": "安全认证未通过, 请检查ApiKey"
        }

    return wrapper