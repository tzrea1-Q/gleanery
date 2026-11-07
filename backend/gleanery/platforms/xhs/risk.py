"""小红书风控判定：纯函数。"""

from __future__ import annotations

from typing import Any

from gleanery.platforms.types import Capture, RiskVerdict
from gleanery.platforms.xhs import selectors


def judge(capture: Capture) -> RiskVerdict | None:
    if capture.status in selectors.RISK_STATUSES:
        return RiskVerdict(kind="risk", signal=f"http_{capture.status}", signal_type="status")
    if {"verifytype", "verifyuuid"} & {key.lower() for key in capture.headers}:
        return RiskVerdict(kind="risk", signal="verify_header", signal_type="status")
    body: Any = capture.body
    if capture.kind == selectors.NAVIGATE:
        path = body.get("path", "") if isinstance(body, dict) else ""
        if any(item in path for item in selectors.VERIFY_PATHS):
            return RiskVerdict(kind="risk", signal="verify_page", signal_type="page")
        return None
    if capture.kind == selectors.SSR_USER:
        if not isinstance(body, dict) or body.get("logged_in") is not True or body.get("guest"):
            return RiskVerdict(
                kind="risk_and_login", signal="ssr_not_login", signal_type="login_lost"
            )
        return None
    if isinstance(body, dict):
        code = body.get("code")
        if code in (300011, 300012):
            return RiskVerdict(kind="risk", signal=f"code_{code}", signal_type="code")
        # -104"您当前登录的账号没有权限访问"：2026-11-03 实测游客访问要登录的接口时返回。
        if code in (-100, -104):
            return RiskVerdict(
                kind="risk_and_login", signal=f"code_{code}", signal_type="login_lost"
            )
    if capture.kind == selectors.USER_ME:
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict) or data.get("guest") is True:
            return RiskVerdict(
                kind="risk_and_login", signal="user_me_guest", signal_type="login_lost"
            )
    return None
