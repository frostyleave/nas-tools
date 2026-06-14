from fastapi.staticfiles import StaticFiles
from starlette.responses import Response

class NoCacheStaticFiles(StaticFiles):
    def __init__(self, *args, **kwargs):
        # 默认缓存时间设为 0
        super().__init__(*args, **kwargs)

    async def get_response(self, path: str, scope) -> Response:
        response = await super().get_response(path, scope)
        # 强制浏览器每次使用资源前都向服务器验证 (ETag 校验)
        # 如果文件没变，服务器会返回 304，速度极快且不费流量
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response