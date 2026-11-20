from charset_normalizer import from_bytes

import aiohttp

# 全局异步会话：应用启动时创建，供图片代理等异步请求复用连接池
_session: aiohttp.ClientSession | None = None


def decode_bytes(content: bytes, encoding: str | None = None) -> str:
    """
    解码 HTTP 响应内容

    优先使用响应头 charset，其次识别页面内声明的 utf-8，最后按 utf-8 解码，
    失败时用 charset_normalizer 探测（替代 apparent_encoding）。
    """
    if encoding:
        try:
            return content.decode(encoding, errors="replace")
        except LookupError:
            pass

    head = content[:4096].lower()
    if b"charset=utf-8" in head or b'charset="utf-8"' in head:
        return content.decode("utf-8", errors="replace")

    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        best = from_bytes(content).best()
        if best:
            return str(best)
        return content.decode("utf-8", errors="replace")


def init_async_client() -> aiohttp.ClientSession:
    """
    初始化全局异步会话，必须在事件循环内调用

    注意：会话只能在其创建时的事件循环内使用和关闭，因此不要跨线程/跨循环复用。
    """
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=100, ssl=False, ttl_dns_cache=300),
            # total=None 让大文件可以边下边传，连接与读取阶段分别限时
            timeout=aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=20),
        )
    return _session


def get_async_session() -> aiohttp.ClientSession:
    """
    获取全局异步会话；lifespan 未初始化时兜底创建
    """
    if _session is None or _session.closed:
        return init_async_client()
    return _session


async def close_async_client():
    """
    关闭全局异步会话
    """
    global _session
    if _session:
        await _session.close()
        _session = None
