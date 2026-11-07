import pytest

from gleanery.platforms.bili.links import parse_link


@pytest.mark.parametrize(
    "text", ["BV1tYWA6DEmS", "av123", "https://m.bilibili.com/video/BV1tYWA6DEmS?p=1"]
)
def test_link(text: str) -> None:
    assert parse_link(text) is not None


@pytest.mark.parametrize("text", ["https://b23.tv/abc", "https://evil.test/video/av123", "av123x"])
def test_bad_link(text: str) -> None:
    assert parse_link(text) is None
