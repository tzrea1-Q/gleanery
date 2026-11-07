from datetime import datetime, tzinfo


def local_datetime(ms: int, tz: tzinfo | None) -> datetime:
    """UTC 毫秒 → 本地时区的 aware datetime；tz 为 None 时用本机时区。"""
    return datetime.fromtimestamp(ms / 1000, tz).astimezone(tz)


def local_iso(ms: int | None, tz: tzinfo | None) -> str | None:
    """给 Agent 的时间：本地时区、精确到分钟、带偏移，如 `2026-10-30T14:05+08:00`。"""
    if ms is None:
        return None
    return local_datetime(ms, tz).isoformat(timespec="minutes")


def local_text(ms: int | None, tz: tzinfo | None) -> str:
    """给人看的时间：`2026-10-30 14:05:00`，空值为空串。"""
    if ms is None:
        return ""
    return local_datetime(ms, tz).strftime("%Y-%m-%d %H:%M:%S")
