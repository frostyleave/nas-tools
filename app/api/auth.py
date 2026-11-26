import ipaddress
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm

from app.middleware.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    COOKIE_MAX_AGE,
    REFRESH_TOKEN_EXPIRE_DAYS,
    authenticate_user,
    create_access_token,
    validate_refresh_token,
)

# 鉴权路由
auth_router = APIRouter(prefix="/auth")


@auth_router.post("/token")
def login(request: Request, form_data: Annotated[OAuth2PasswordRequestForm, Depends()]):
    """
    登陆: 验证授权信息, 生成access_token和refresh_token
    """
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
    
    response = JSONResponse(content={
        "msg": "登录成功",
        "token_type": "bearer",
        "access_token": access_token
    })
    response.set_cookie("access_token", access_token, httponly=True, samesite="Lax", secure=secure_flag)
    response.set_cookie("refresh_token", refresh_token, httponly=True, samesite="Lax", secure=secure_flag, max_age=COOKIE_MAX_AGE)
    return response


@auth_router.post("/refresh")
def refresh_token(request: Request):
    """
    刷新access_token
    """
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

    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    secure_flag = scheme == "https"

    response = JSONResponse(content={
        "msg": "刷新成功",
        "token_type": "bearer",
        "access_token": new_access_token
    })
    response.set_cookie("access_token", new_access_token, httponly=True, samesite="Lax", secure=secure_flag)
    response.set_cookie("refresh_token", refresh_token, httponly=True, samesite="Lax", secure=secure_flag, max_age=COOKIE_MAX_AGE)
    return response


@auth_router.post("/logout")
def logout():
    """
    退出登录：清除 Cookie
    """
    response = JSONResponse(content={"msg": "退出成功"})
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return response


def _is_local_address(ip: str) -> bool:
    """
    判断地址是否为本机或内网地址（Docker 反向代理、内网服务的直连对端）
    """
    try:
        ipaddr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if isinstance(ipaddr, ipaddress.IPv6Address) and ipaddr.ipv4_mapped:
        ipaddr = ipaddr.ipv4_mapped
    return ipaddr.is_loopback or ipaddr.is_private or ipaddr.is_link_local


def get_real_ip(request: Request) -> str:
    """
    获取请求的真实ip：直连对端是本机或内网反向代理时才采信转发头
    """
    if not request.client:
        return "unknown"
    peer = request.client.host
    if not _is_local_address(peer):
        return peer
    # 从右往左跳过本机/内网代理，取第一个外部地址
    x_forwarded_for = request.headers.get("x-forwarded-for") or ""
    chain = [item.strip() for item in x_forwarded_for.split(",") if item.strip()]
    for ip in reversed(chain):
        if not _is_local_address(ip):
            return ip
    if chain:
        # 整条链路都是内网地址时无法区分代理与直连客户端，以直连对端为准
        return peer
    x_real_ip = (request.headers.get("x-real-ip") or "").strip()
    if x_real_ip:
        return x_real_ip
    return peer
