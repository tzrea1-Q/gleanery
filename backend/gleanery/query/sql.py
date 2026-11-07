"""`run_sql` 的只读执行。"""

import asyncio
import re
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SqlResult:
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    truncated: bool = False
    """行数超过上限被截断。单元格的文本截断另行标记在值里（末尾 `…`）。"""


class SqlRejected(Exception):
    """被拦截（`SQL_NOT_ALLOWED`），语句没有执行。"""


class SqlTimeout(Exception):
    """超时被中断（`SQL_TIMEOUT`）。"""


class SqlFailed(Exception):
    """SQLite 报错（`SQL_ERROR`），消息即 SQLite 的错误信息。"""


_LITERALS = re.compile(r"--[^\n]*|/\*.*?(\*/|$)|'(?:[^']|'')*'", re.DOTALL)
_SHADOWING_CTE = re.compile(
    r"\bv_\w*[\"`\]]?\s*(\([^)]*\))?\s*as\s*(not\s+)?(materialized\s+)?\(", re.IGNORECASE
)


def _defines_view_like_cte(sql: str) -> bool:
    """CTE 的名字会作为读取"来源"报给 authorizer，名为 `v_*` 的 CTE 读底表时和视图分不开，所以不许这样起名。
    `名字 AS (` 只出现在 CTE 定义里（CAST 的类型不以括号开头），先去掉注释和字符串再找。"""
    return bool(_SHADOWING_CTE.search(_LITERALS.sub(" ", sql)))


def _reads_allowed(reads: set[tuple[str, str | None]], views: set[str]) -> bool:
    """直接读视图，或经视图读底表，才放行。

    视图定义里的 DISTINCT 让视图不被展平进外层的 CTE，否则经视图读底表时会丢掉来源。
    """
    return all(table in views or source in views for table, source in reads)


class ReadOnlySql:
    """每次调用新开一个 `mode=ro` + `PRAGMA query_only` 的连接，只放行读 `v_*` 视图。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    async def run(self, sql: str, *, max_rows: int = 200, time_limit: float = 5.0) -> SqlResult:
        return await asyncio.to_thread(self._run, sql, max_rows, time_limit)

    def _run(self, sql: str, max_rows: int, time_limit: float) -> SqlResult:
        statements = []
        pending = ""
        for char in sql:
            pending += char
            if char == ";" and sqlite3.complete_statement(pending):
                statements.append(pending)
                pending = ""
        if pending.strip():
            statements.append(pending)
        if len(statements) != 1:
            raise SqlRejected("只允许一条 SQL 语句")
        if _defines_view_like_cte(statements[0]):
            raise SqlRejected("CTE 的名字不能以 v_ 开头")
        deadline = time.monotonic() + time_limit
        denied = False
        timed_out = False
        reads: set[tuple[str, str | None]] = set()

        def authorize(
            action: int,
            arg1: str | None,
            arg2: str | None,
            database: str | None,
            source: str | None,
        ) -> int:
            nonlocal denied
            if action == sqlite3.SQLITE_READ:
                reads.add((arg1 or "", source))
                return sqlite3.SQLITE_OK
            if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE):
                return sqlite3.SQLITE_OK
            denied = True
            return sqlite3.SQLITE_DENY

        def progress() -> int:
            nonlocal timed_out
            timed_out = time.monotonic() >= deadline
            return int(timed_out)

        try:
            with closing(
                sqlite3.connect(self.db_path.resolve().as_uri() + "?mode=ro", uri=True)
            ) as connection:
                connection.execute("PRAGMA query_only=ON")
                views = {
                    name
                    for (name,) in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'view' AND name GLOB 'v_*'"
                    )
                }
                connection.set_authorizer(authorize)
                # 先只编译不执行，收齐读取记录再判断。
                connection.execute("EXPLAIN " + statements[0]).fetchall()
                if not _reads_allowed(reads, views):
                    raise SqlRejected("只能查询 v_* 视图")
                connection.set_progress_handler(progress, 1000)
                cursor = connection.execute(statements[0])
                rows = cursor.fetchmany(max_rows + 1)

                def cell(value: Any) -> Any:
                    if isinstance(value, bytes):
                        return f"<{len(value)} 字节>"
                    if isinstance(value, str) and len(value) > 500:
                        return value[:500] + "…"
                    return value

                return SqlResult(
                    [col[0] for col in cursor.description or ()],
                    [[cell(v) for v in row] for row in rows[:max_rows]],
                    len(rows) > max_rows,
                )
        except sqlite3.Error as exc:
            if timed_out:
                raise SqlTimeout("SQL 执行超时") from exc
            if denied:
                raise SqlRejected("SQL 操作不允许") from exc
            raise SqlFailed(str(exc)) from exc
