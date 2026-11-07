import pytest

from gleanery.platforms.xhs.links import parse_link

NOTE = "abcdef0123456789abcdef01"


@pytest.mark.parametrize(
    ("text", "ext"),
    [
        (NOTE, {}),
        (NOTE.upper(), {}),
        (f" https://www.xiaohongshu.com/explore/{NOTE} ", {}),
        (f"http://xiaohongshu.com/explore/{NOTE}?other=1#part", {}),
        (
            f"www.xiaohongshu.com/discovery/item/{NOTE}?xsec_token=a%2Bb&xsec_source=app+share",
            {"xsec_token": "a+b", "xsec_source": "app share"},
        ),
        (
            f"看看这篇 https://www.xiaohongshu.com/explore/{NOTE}?xsec_token=secret 复制本条信息",
            {"xsec_token": "secret"},
        ),
        (f"xiaohongshu.com/explore/{NOTE}?xsec_source=app", {"xsec_source": "app"}),
    ],
)
def test_parse_link(text: str, ext: dict[str, str]) -> None:
    ref = parse_link(text)
    assert ref is not None
    note_id = NOTE.upper() if text == NOTE.upper() else NOTE
    assert ref.platform == "xhs"
    assert ref.platform_id == note_id
    assert ref.url == f"https://www.xiaohongshu.com/explore/{note_id}"
    assert ref.ext == ext


@pytest.mark.parametrize(
    "text",
    [
        "",
        "https://xhslink.com/abc",
        f"https://xiaohongshu.com/user/profile/{NOTE}",
        f"https://xiaohongshu.com/topic/{NOTE}",
        f"https://evil.com/explore/{NOTE}",
        f"https://evil.com/xiaohongshu.com/explore/{NOTE}",
        f"https://xiaohongshu.com.evil.com/explore/{NOTE}",
        f"https://xiaohongshu.com/explore/{NOTE}a",
        NOTE[:-1],
        "g" * 24,
    ],
)
def test_rejected_link(text: str) -> None:
    assert parse_link(text) is None
