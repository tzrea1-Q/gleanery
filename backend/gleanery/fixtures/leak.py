from __future__ import annotations

import ipaddress
import re
from pathlib import Path

_PATTERNS = {
    "cookie": re.compile(
        r"SESSDATA|bili_jct|DedeUserID|web_session|\ba1\s*=|\bwebId\s*=|websectiga|sec_poison_id",
        re.I,
    ),
    "avatar": re.compile(r"hdslb\.com/bfs/face|sns-avatar|sns-img", re.I),
    "ip": re.compile(
        r"(?<![\w.:])(?:\d{1,3}\.){3}\d{1,3}(?![\w.:])|(?<![\w:])(?:[0-9a-f]{0,4}:){2,}[0-9a-f:]{0,4}(?![\w:])",
        re.I,
    ),
}


def scan(text: str, blocklist: tuple[str, ...] = ()) -> list[str]:
    findings = []
    for name, pattern in _PATTERNS.items():
        for match in pattern.finditer(text):
            if name == "ip":
                try:
                    ipaddress.ip_address(match.group())
                except ValueError:
                    continue
            findings.append(name)
            break
    if any(entry and entry in text for entry in blocklist):
        findings.append("blocklist")
    return findings


def load_blocklist(path: str | None) -> tuple[str, ...]:
    return (
        tuple(line.strip() for line in Path(path).read_text().splitlines() if line.strip())
        if path
        else ()
    )
