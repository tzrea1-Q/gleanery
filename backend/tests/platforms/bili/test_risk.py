import pytest

from gleanery.platforms.bili.risk import judge
from gleanery.platforms.bili.selectors import NAV
from gleanery.platforms.types import Capture


@pytest.mark.parametrize(
    ("status", "body", "kind", "signal"),
    [
        (412, "拦截", "x", "http_412"),
        *[(200, {"code": code}, "x", f"code_{code}") for code in (-352, -401, -412, -799, -101)],
        (200, {"deep": [{"v_voucher": "x"}]}, "x", "v_voucher"),
        (200, {"data": {"isLogin": False}}, NAV, "nav_not_login"),
        (200, {"code": 0}, "x", None),
        (200, "not json", "x", None),
    ],
)
def test_judge(status: int, body: object, kind: str, signal: str | None) -> None:
    verdict = judge(
        Capture(platform="bili", kind=kind, url_path="/", status=status, body=body, captured_at=0)
    )
    assert (verdict.signal if verdict else None) == signal
