import pytest

from gleanery.platforms.types import Capture
from gleanery.platforms.xhs import selectors
from gleanery.platforms.xhs.risk import judge


def capture(kind: str, body: object, status: int = 200, headers: dict[str, str] | None = None):
    return Capture(
        platform="xhs",
        kind=kind,
        url_path="/",
        status=status,
        headers=headers or {},
        body=body,
        captured_at=0,
    )


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        (capture(selectors.SSR_USER, {"logged_in": True, "guest": False}), None),
        (capture(selectors.SSR_USER, {"logged_in": False, "guest": True}), "ssr_not_login"),
        (capture(selectors.SSR_USER, {"logged_in": None, "guest": None}), "ssr_not_login"),
        (capture(selectors.NAVIGATE, {"path": "/explore/abc"}), None),
        (capture(selectors.NAVIGATE, {"path": "/website-login/captcha"}), "verify_page"),
        (capture(selectors.USER_ME, {"code": 0, "data": {"guest": False}}), None),
        (capture(selectors.USER_ME, {"code": -101, "success": False}), "user_me_guest"),
        (capture(selectors.COMMENTS, {"code": -1, "success": False}), None),
        (capture(selectors.COMMENTS, {}, 200, {"Verifytype": "102"}), "verify_header"),
        (capture(selectors.FEED, "", 429), "http_429"),
    ],
)
def test_judge(item: Capture, expected: str | None) -> None:
    verdict = judge(item)
    assert (verdict.signal if verdict else None) == expected
