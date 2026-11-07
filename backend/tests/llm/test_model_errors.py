import pytest
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, ModelQuotaExceededError, UserError
from pydantic_ai.providers.openai_chatgpt import CredentialsRefreshError

from gleanery.llm.errors import classify_model_error


@pytest.mark.parametrize(
    ("error", "kind", "code", "status"),
    [
        (
            ModelAPIError(
                "m", "失败", provider_error_code="subscription_sharing_usage_limit_exceeded"
            ),
            "chatgpt_plan",
            "MODEL_QUOTA_EXCEEDED",
            None,
        ),
        (
            ModelAPIError("m", "失败", body={"code": "subscription_sharing_user_not_eligible"}),
            "chatgpt_plan",
            "MODEL_NOT_ELIGIBLE",
            "unavailable",
        ),
        (
            ModelAPIError("m", "失败", provider_error_code="unsupported_capability"),
            "chatgpt_plan",
            "MODEL_UNSUPPORTED",
            None,
        ),
        (
            ModelHTTPError(status_code=401, model_name="m"),
            "chatgpt_plan",
            "MODEL_RECONNECT_REQUIRED",
            "needs_reconnect",
        ),
        (
            ModelHTTPError(status_code=403, model_name="m"),
            "anthropic",
            "MODEL_AUTH_FAILED",
            "unavailable",
        ),
        (ModelHTTPError(status_code=429, model_name="m"), "anthropic", "MODEL_RATE_LIMITED", None),
        (ModelQuotaExceededError("m", "失败"), "anthropic", "MODEL_RATE_LIMITED", None),
        (
            UserError("These credentials do not grant ChatGPT plan usage"),
            "chatgpt_plan",
            "MODEL_RECONNECT_REQUIRED",
            "needs_reconnect",
        ),
        (RuntimeError("secret token"), "chatgpt_plan", "MODEL_ERROR", None),
    ],
)
def test_错误分类(error: BaseException, kind: str, code: str, status: str | None) -> None:
    result = classify_model_error(error, kind)
    assert (result.body.code, result.config_status) == (code, status)
    assert "secret token" not in result.body.model_dump_json()


def test_沿异常链识别被拒的刷新() -> None:
    error = RuntimeError("连接失败")
    error.__cause__ = CredentialsRefreshError("the grant was rejected", "chatgpt")
    assert classify_model_error(error, "chatgpt_plan").body.code == "MODEL_RECONNECT_REQUIRED"
    error.__cause__ = CredentialsRefreshError("网络失败", "chatgpt")
    assert classify_model_error(error, "chatgpt_plan").body.code == "MODEL_ERROR"
