import os
from pathlib import Path

from gleanery.fixtures.leak import load_blocklist, scan


def test_fixtures_have_no_leaks() -> None:
    blocklist = load_blocklist(os.environ.get("GLEANERY_LEAK_BLOCKLIST"))
    root = Path(__file__).parent / "fixtures"
    leaks = {
        str(path): found
        for path in root.rglob("*.json")
        if (found := scan(path.read_text(encoding="utf-8"), blocklist))
    }
    assert not leaks
