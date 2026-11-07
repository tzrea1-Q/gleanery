import re
from decimal import Decimal, InvalidOperation


def parse_count(text: str | int | None) -> tuple[int | None, bool]:
    if isinstance(text, int):
        return text, False
    if text is None:
        return None, False
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([万wW亿]?)\s*(\+?)\s*", text)
    if not match:
        return None, False
    number, unit, plus = match.groups()
    try:
        return int(
            Decimal(number) * {"": 1, "万": 10000, "w": 10000, "W": 10000, "亿": 100000000}[unit]
        ), bool(unit or plus)
    except (InvalidOperation, ValueError, OverflowError):
        return None, False
