from __future__ import annotations

from pydantic import BaseModel


class ErrorBody(BaseModel):
    """REST 错误统一格式，与 Agent 工具的错误约定一致。"""

    code: str
    message: str
    hint: str | None = None


class ApiError(Exception):
    """路由里抛出它，`create_app` 注册的处理器把它转成 `ErrorBody` 响应。"""

    def __init__(self, status: int, code: str, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = ErrorBody(code=code, message=message, hint=hint)


def not_implemented() -> ApiError:
    return ApiError(501, "NOT_IMPLEMENTED", "尚未实现")
