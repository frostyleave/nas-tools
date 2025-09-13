
from datetime import timedelta

from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm

from web.backend.security import ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS, authenticate_user, create_access_token, decode_access_token, validate_refresh_token


# 鉴权路由
auth_router = APIRouter(prefix="/auth")


@auth_router.post("/token")
async def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):

    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    username = user.username

    access_token = create_access_token(
        data={"sub": username},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    refresh_token = create_access_token(
        data={"sub": username, "type": "refresh"},
        expires_delta=timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    )

    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    secure_flag = scheme == "https"
    
    response = JSONResponse(content={"msg": "登录成功"})
    response.set_cookie("access_token", access_token, httponly=True, samesite="Lax", secure=secure_flag)
    response.set_cookie("refresh_token", refresh_token, httponly=True, samesite="Lax", secure=secure_flag)
    return response


@auth_router.post("/refresh")
async def refresh_token(request: Request):
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="缺少 refresh_token")
    
    username = validate_refresh_token(refresh_token)
    if not username:
        raise HTTPException(status_code=401, detail="无效 refresh_token")
    
    new_access_token = create_access_token(
        data={"sub": username},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    new_refresh_token = create_access_token(
        data={"sub": username, "type": "refresh"},
        expires_delta=timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    )

    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    secure_flag = scheme == "https"

    response = JSONResponse(content={"msg": "刷新成功"})
    response.set_cookie("access_token", new_access_token, httponly=True, samesite="Lax", secure=secure_flag)
    response.set_cookie("refresh_token", new_refresh_token, httponly=True, samesite="Lax", secure=secure_flag)
    return response


@auth_router.post("/logout")
async def logout():
    """
    退出登录：清除 Cookie
    """
    response = JSONResponse(content={"msg": "退出成功"})
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return response
