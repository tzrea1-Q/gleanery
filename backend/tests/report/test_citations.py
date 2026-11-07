import json
from dataclasses import asdict
from pathlib import Path

import pytest

from gleanery.report.citations import CitationRef, malformed, parse, refs, to_footnotes

CASES = json.loads(Path(__file__).with_name("citation_cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_cases(case):
    assert [asdict(marker) for marker in parse(case["text"])] == [
        {**marker, "refs": tuple(marker["refs"])} for marker in case["markers"]
    ]
    assert [asdict(ref) for ref in refs(case["text"])] == case["refs"]
    assert malformed(case["text"]) == case["malformed"]


def test_footnotes():
    text = "已有[^3]。[[c:1,m:2]] 和 [[c:1]]。\n\n[^3]: 原注"
    assert to_footnotes(text, {CitationRef("content", 1): "来源"}) == (
        "已有[^3]。[^4][^5] 和 [^4]。\n\n[^3]: 原注\n\n[^4]: 来源\n[^5]: 失效引用（m:2）"
    )
    assert to_footnotes("没有引用\n", {}) == "没有引用\n"
