from __future__ import annotations

import json

from gleanery.platforms.bili.selectors import NAV
from gleanery.platforms.types import Capture, RiskVerdict


def judge(capture: Capture) -> RiskVerdict | None:
    if capture.status == 412:
        return RiskVerdict(kind="risk", signal="http_412", signal_type="status")
    if "v_voucher" in json.dumps(capture.body, ensure_ascii=False):
        return RiskVerdict(kind="risk", signal="v_voucher", signal_type="page")
    body = capture.body
    if isinstance(body, dict):
        code = body.get("code")
        if code in (-352, -401, -412, -799):
            return RiskVerdict(kind="risk", signal=f"code_{code}", signal_type="code")
        if code == -101:
            return RiskVerdict(kind="login_required", signal="code_-101", signal_type="login_lost")
        if capture.kind == NAV and (
            not isinstance(body.get("data"), dict) or body["data"].get("isLogin") is not True
        ):
            return RiskVerdict(
                kind="login_required", signal="nav_not_login", signal_type="login_lost"
            )
    elif capture.kind == NAV:
        return RiskVerdict(kind="login_required", signal="nav_not_login", signal_type="login_lost")
    return None
