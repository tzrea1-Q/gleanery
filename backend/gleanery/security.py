import secrets
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from gleanery.api.errors import ErrorBody
from gleanery.deps import AppDeps


class LocalSecurity:
    def __init__(self, app: ASGIApp, deps: AppDeps) -> None:
        self.app = app
        self.token = deps.launch_token
        self.origins = {
            f"http://127.0.0.1:{deps.port}",
            f"http://localhost:{deps.port}",
            *deps.extra_origins,
        }
        self.hosts = {urlsplit(origin).netloc for origin in self.origins}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        error: tuple[int, str, str] | None = None
        if headers.get("host") not in self.hosts:
            error = (400, "BAD_HOST", "无效的 Host")
        elif (
            scope["method"] in {"POST", "PUT", "PATCH", "DELETE"}
            and headers.get("origin") not in self.origins
        ):
            error = (403, "BAD_ORIGIN", "无效的 Origin")
        elif scope["path"].startswith("/api/") and not secrets.compare_digest(
            HTTPConnection(scope).cookies.get("gleanery_session", "").encode(), self.token.encode()
        ):
            error = (401, "NO_SESSION", "请重新运行 gleanery 打开应用")
        if error:
            status, code, message = error
            response = JSONResponse(ErrorBody(code=code, message=message).model_dump(), status)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
