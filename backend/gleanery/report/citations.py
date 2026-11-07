"""报告正文里的引用标记（ADR-0006）。

纯函数，不碰数据库。语法与前端 `src/lib/citations.ts` 保持一致，两边跑同一份用例表。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

MAX_IDS = 10
MARKER = re.compile(r"\[\[\s*([cm]\s*:\s*[0-9]+(?:\s*,\s*[cm]\s*:\s*[0-9]+)*)\s*\]\]")
_REF = re.compile(r"([cm])\s*:\s*([0-9]+)")


@dataclass(frozen=True)
class CitationRef:
    kind: Literal["content", "comment"]
    id: int

    def label(self) -> str:
        return f"{'c' if self.kind == 'content' else 'm'}:{self.id}"


@dataclass(frozen=True)
class CitationMarker:
    start: int
    end: int
    """不含。"""
    refs: tuple[CitationRef, ...]
    """按书写顺序，标记内重复的 ID 已去重。"""
    too_many: bool


def parse(markdown: str) -> list[CitationMarker]:
    markers = []
    for match in MARKER.finditer(markdown):
        found = _REF.findall(match.group(1))
        unique = tuple(
            dict.fromkeys(
                CitationRef("content" if kind == "c" else "comment", int(number))
                for kind, number in found
            )
        )
        markers.append(CitationMarker(match.start(), match.end(), unique, len(found) > MAX_IDS))
    return markers


def malformed(markdown: str) -> list[str]:
    """近似标记的原文，按出现顺序。Agent 保存时据此报 `INVALID_CITATION`。"""
    result = []
    for match in re.finditer(r"\[\[([^\[\]]*)\]\]", markdown):
        body = match.group(1).strip()
        if not MARKER.fullmatch(match.group()) and (
            re.match(r"[cmCM]\s*(?::|[0-9])", body) or re.fullmatch(r"[0-9]+", body)
        ):
            result.append(match.group())
    return result


def refs(markdown: str) -> list[CitationRef]:
    """全文去重，按首次出现顺序。"""
    return list(dict.fromkeys(ref for marker in parse(markdown) for ref in marker.refs))


def to_footnotes(markdown: str, notes: Mapping[CitationRef, str]) -> str:
    """把标记换成 `[^n]` 脚注，文末列出定义（导出用）。"""
    markers = parse(markdown)
    if not markers:
        return markdown
    existing = (int(number) for number in re.findall(r"\[\^([0-9]+)\]", markdown))
    next_number = max(existing, default=0) + 1
    numbers: dict[CitationRef, int] = {}
    parts = []
    position = 0
    for marker in markers:
        parts.append(markdown[position : marker.start])
        for ref in marker.refs:
            if ref not in numbers:
                numbers[ref] = next_number
                next_number += 1
            parts.append(f"[^{numbers[ref]}]")
        position = marker.end
    parts.append(markdown[position:])
    definitions = "\n".join(
        f"[^{number}]: {notes.get(ref, f'失效引用（{ref.label()}）')}"
        for ref, number in numbers.items()
    )
    body = "".join(parts)
    separator = "" if body.endswith("\n\n") else "\n" if body.endswith("\n") else "\n\n"
    return body + separator + definitions
