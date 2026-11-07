import json
import os
import sqlite3
from pathlib import Path

SNAPSHOT = Path(__file__).parents[1] / "snapshots" / "views.json"


def assert_view_snapshot(connection: sqlite3.Connection, snapshot: Path = SNAPSHOT) -> None:
    views = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='view' AND name GLOB 'v_*' ORDER BY name"
    ).fetchall()
    actual = {
        name: [
            [row[1], row[2]]
            for row in connection.execute("SELECT * FROM pragma_table_info(?)", (name,))
        ]
        for (name,) in views
    }
    if os.environ.get("GLEANERY_UPDATE_SNAPSHOTS") == "1":
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(
            json.dumps(actual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    elif snapshot.exists():
        assert actual == json.loads(snapshot.read_text(encoding="utf-8"))
    else:
        assert not actual, "视图快照不存在"
