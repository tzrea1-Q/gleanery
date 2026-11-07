"""模型错误的统一分类。"""

from dataclasses import dataclass

from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, ModelQuotaExceededError, UserError
from pydantic_ai.providers.openai_chatgpt import CredentialsRefreshError

from gleanery.api.errors import ErrorBody

# 令牌端点的错误体不是扁平的 `{"error": "..."}` 时，Pydantic AI 不会标"the grant was rejected"，
# 但错误码还在消息里，所以按错误码再找一遍。
_REJECTED_GRANT_MARKS = (
    "the grant was rejected",
    "invalid_grant",
    "invalid_refresh_token",
    "token_expired",
    "refresh_token_expired",
    "refresh_token_invalidated",
    "refresh_token_reused",
)


@dataclass(frozen=True)
class ModelFailure:
    body: ErrorBody
    config_status: str | None = None
    """配置要转成的状态；None 表示不变。"""
    config_reason: str | None = None


def grant_rejected(error: CredentialsRefreshError) -> bool:
    return any(mark in str(error) for mark in _REJECTED_GRANT_MARKS)


def _chain(error: BaseException | None) -> list[BaseException]:
    """沿 `__cause__` 展开。刷新失败发生在 httpx auth 里，到这里已被 SDK 包过两层。"""
    chain: list[BaseException] = []
    while error is not None and error not in chain:
        chain.append(error)
        error = error.__cause__
    return chain


def _brief(error: BaseException | None) -> str:
    """给用户看的错误摘要。只用上游状态码和 SDK 的错误消息，它们不含请求头，不会带出 Key。"""
    if isinstance(error, ModelHTTPError):
        return f"上游 {error.status_code}"
    if isinstance(error, ModelAPIError):
        return f"{type(error).__name__}: {error.message[:200]}"
    return type(error).__name__ if error else "未知错误"


def classify_model_error(error: BaseException | None, kind: str) -> ModelFailure:
    code = error.provider_error_code if isinstance(error, ModelAPIError) else None
    body = repr(error.body) if isinstance(error, ModelAPIError) and not code else ""
    status = error.status_code if isinstance(error, ModelHTTPError) else None
    chain = _chain(error)

    def matches(value: str) -> bool:
        return code == value or value in body

    if matches("subscription_sharing_usage_limit_exceeded"):
        return ModelFailure(
            ErrorBody(
                code="MODEL_QUOTA_EXCEEDED",
                message="ChatGPT 套餐额度已用完",
                hint="可以在 Manage usage 里查看用量",
            )
        )
    if matches("subscription_sharing_user_not_eligible"):
        return ModelFailure(
            ErrorBody(code="MODEL_NOT_ELIGIBLE", message="需要 Plus 或 Pro", hint="请换个模型"),
            "unavailable",
            "需要 Plus 或 Pro",
        )
    if kind == "chatgpt_plan":
        reason = None
        if matches("chatpass_v2_scope_not_authorized") or any(
            isinstance(item, UserError) and "do not grant ChatGPT plan usage" in str(item)
            for item in chain
        ):
            reason = "未授权使用 ChatGPT 套餐"
        elif status == 401 or any(
            isinstance(item, CredentialsRefreshError) and grant_rejected(item) for item in chain
        ):
            reason = "授权已失效"
        if reason:
            return ModelFailure(
                ErrorBody(
                    code="MODEL_RECONNECT_REQUIRED",
                    message="ChatGPT 套餐需要重新连接",
                    hint=reason,
                ),
                "needs_reconnect",
                reason,
            )
    if matches("unsupported_capability"):
        return ModelFailure(
            ErrorBody(
                code="MODEL_UNSUPPORTED",
                message="这个模型不支持本次请求用到的功能",
                hint="请检查模型设置或换个模型",
            )
        )
    if status in (401, 403):
        return ModelFailure(
            ErrorBody(code="MODEL_AUTH_FAILED", message="模型凭证无效", hint="请检查模型设置"),
            "unavailable",
            "凭证无效",
        )
    if status == 429 or isinstance(error, ModelQuotaExceededError):
        return ModelFailure(
            ErrorBody(code="MODEL_RATE_LIMITED", message="模型请求次数受限", hint="请稍后重试")
        )
    return ModelFailure(
        ErrorBody(
            code="MODEL_ERROR",
            message=f"模型请求失败：{_brief(error)}",
            hint="请重试或更换模型",
        )
    )
