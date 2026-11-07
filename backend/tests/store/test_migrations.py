import asyncio
import sqlite3
from pathlib import Path

import pytest
from pytest_alembic.tests import (
    test_model_definitions_match_ddl,
    test_single_head_revision,
    test_up_down_consistency,
    test_upgrade,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from gleanery.store import open_database
from tests.support.view_snapshot import assert_view_snapshot

__all__ = [
    "test_model_definitions_match_ddl",
    "test_single_head_revision",
    "test_up_down_consistency",
    "test_upgrade",
]


async def test_new_database_and_constraints(tmp_path: Path) -> None:
    database = await open_database(tmp_path)
    async with database.engine.begin() as connection:
        assert (await connection.execute(text("PRAGMA auto_vacuum"))).scalar_one() == 2
        assert (await connection.execute(text("PRAGMA journal_mode"))).scalar_one() == "wal"
        assert (await connection.execute(text("PRAGMA foreign_keys"))).scalar_one() == 1
        assert (await connection.execute(text("PRAGMA busy_timeout"))).scalar_one() == 5000
        await connection.execute(
            text("INSERT INTO conversation (created_at, updated_at) VALUES (1, 1)")
        )
        await connection.execute(
            text(
                "INSERT INTO message (conversation_id, seq, kind, payload, created_at) "
                "VALUES (1, 0, 'request', '{}', 1)"
            )
        )
        with pytest.raises(IntegrityError):
            await connection.execute(
                text(
                    "INSERT INTO message (conversation_id, seq, kind, payload, created_at) "
                    "VALUES (1, 0, 'request', '{}', 1)"
                )
            )
        await connection.execute(text("DELETE FROM conversation WHERE id = 1"))
        assert (await connection.execute(text("SELECT count(*) FROM message"))).scalar_one() == 0
    await database.close()
    assert not await asyncio.to_thread(lambda: list(tmp_path.glob("gleanery.db.bak-*")))
    with sqlite3.connect(tmp_path / "gleanery.db") as connection:
        assert_view_snapshot(connection)
    database = await open_database(tmp_path)
    await database.close()
    assert not await asyncio.to_thread(lambda: list(tmp_path.glob("gleanery.db.bak-*")))


async def test_existing_database_backup_includes_wal(tmp_path: Path) -> None:
    path = tmp_path / "gleanery.db"
    with sqlite3.connect(path) as existing:
        existing.execute("PRAGMA journal_mode=WAL")
        existing.execute("CREATE TABLE old_data (value TEXT)")
        existing.execute("INSERT INTO old_data VALUES ('保留')")
        existing.commit()
        database = await open_database(tmp_path)
        await database.close()
        backups = await asyncio.to_thread(lambda: list(tmp_path.glob("gleanery.db.bak-*")))
        assert len(backups) == 1
        with sqlite3.connect(backups[0]) as backup:
            assert backup.execute("SELECT value FROM old_data").fetchone() == ("保留",)
            assert not backup.execute(
                "SELECT 1 FROM sqlite_master WHERE name='alembic_version'"
            ).fetchone()


ID_TABLES = ("dataset", "content", "comment", "collection_task")


def _new_dataset(connection: sqlite3.Connection, name: str) -> int:
    cursor = connection.execute(
        "INSERT INTO dataset (name, description, created_at) VALUES (?, '', 1)", (name,)
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


async def test_deleted_ids_are_not_reused(tmp_path: Path) -> None:
    """2026-11-02 M2 冒烟：删掉的数据集 10 的 ID 给了新数据集，旧对话里的卡片指向了别的数据。"""
    database = await open_database(tmp_path)
    await database.close()
    with sqlite3.connect(tmp_path / "gleanery.db") as connection:
        for table in ID_TABLES:
            ddl = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name = ?", (table,)
            ).fetchone()[0]
            assert "AUTOINCREMENT" in ddl, table
        first = _new_dataset(connection, "甲")
        connection.execute("DELETE FROM dataset WHERE id = ?", (first,))
        assert _new_dataset(connection, "乙") > first


async def test_upgrade_keeps_data_and_views(tmp_path: Path) -> None:
    from alembic import command
    from alembic.config import Config

    path = tmp_path / "gleanery.db"
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).parents[2] / "gleanery/store/migrations")
    )
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    await asyncio.to_thread(command.upgrade, config, "0003")
    with sqlite3.connect(path) as connection:
        kept = _new_dataset(connection, "保留")
        dropped = _new_dataset(connection, "删除")
        connection.execute("DELETE FROM dataset WHERE id = ?", (dropped,))
    database = await open_database(tmp_path)
    await database.close()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT dataset_id, name FROM v_datasets").fetchall() == [
            (kept, "保留")
        ]
        assert_view_snapshot(connection)
        # 迁移前已经删掉的最大 ID 无从得知，从迁移后起不再复用
        third = _new_dataset(connection, "新")
        connection.execute("DELETE FROM dataset WHERE id = ?", (third,))
        assert _new_dataset(connection, "再新") > third
