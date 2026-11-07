import sqlite3
from pathlib import Path

import pytest

from tests.support.view_snapshot import assert_view_snapshot


def test_view_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = tmp_path / "snapshots" / "views.json"
    with sqlite3.connect(tmp_path / "views.db") as connection:
        connection.execute("CREATE TABLE example (name TEXT, count BIGINT)")
        connection.execute("CREATE VIEW v_example AS SELECT name, count FROM example")
        with pytest.raises(AssertionError):
            assert_view_snapshot(connection, snapshot)
        monkeypatch.setenv("GLEANERY_UPDATE_SNAPSHOTS", "1")
        assert_view_snapshot(connection, snapshot)
        assert '"BIGINT"' in snapshot.read_text(encoding="utf-8")
        monkeypatch.delenv("GLEANERY_UPDATE_SNAPSHOTS")
        assert_view_snapshot(connection, snapshot)
        connection.execute("DROP VIEW v_example")
        with pytest.raises(AssertionError):
            assert_view_snapshot(connection, snapshot)
