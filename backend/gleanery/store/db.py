from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DB_FILENAME = "gleanery.db"


@dataclass
class Database:
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]

    async def close(self) -> None:
        await self.engine.dispose()


def _set_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


async def open_database(data_dir: Path) -> Database:
    """升级并打开 `<data_dir>/gleanery.db`。"""
    path = data_dir / DB_FILENAME
    await asyncio.to_thread(_upgrade, path)
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    event.listen(engine.sync_engine, "connect", _set_pragmas)
    return Database(engine=engine, sessionmaker=async_sessionmaker(engine, expire_on_commit=False))


def _upgrade(path: Path) -> None:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}".replace("%", "%%"))
    head = ScriptDirectory.from_config(config).get_current_head()
    existed = path.exists()
    with closing(sqlite3.connect(path)) as connection:
        version_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        ).fetchone()
        revisions = (
            connection.execute("SELECT version_num FROM alembic_version").fetchall()
            if version_table
            else []
        )
        if revisions == [(head,)]:
            return
        if existed:
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            backup = path.with_name(f"{path.name}.bak-{timestamp}")
            with backup.open("xb"), closing(sqlite3.connect(backup)) as destination:
                connection.backup(destination)
    command.upgrade(config, "head")
