import pytest

from gleanery.platforms.normalize import parse_count


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1.2万", (12000, True)),
        ("3w", (30000, True)),
        ("1亿", (100000000, True)),
        ("999+", (999, True)),
        ("10万+", (100000, True)),
        ("42", (42, False)),
        (42, (42, False)),
        (None, (None, False)),
        ("-", (None, False)),
        ("", (None, False)),
    ],
)
def test_parse_count(value: str | int | None, expected: tuple[int | None, bool]) -> None:
    assert parse_count(value) == expected
