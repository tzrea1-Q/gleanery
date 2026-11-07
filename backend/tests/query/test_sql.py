from pathlib import Path

import pytest

from gleanery.query.sql import ReadOnlySql, SqlRejected, SqlTimeout
from gleanery.store import open_database
from tests.support.library import seed_library


async def test_sql_boundaries(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    async with db.sessionmaker() as session:
        await seed_library(session)
    sql = ReadOnlySql(tmp_path / "gleanery.db")
    for statement in (
        "INSERT INTO content DEFAULT VALUES",
        "UPDATE content SET title = 'x'",
        "DELETE FROM content",
        "DROP TABLE content",
        "PRAGMA table_info(content)",
        "ATTACH DATABASE ':memory:' AS x",
        "SELECT 1; SELECT 2",
        "SELECT * FROM content",
        "WITH v_contents AS (SELECT * FROM setting) SELECT * FROM v_contents",
        "WITH v_x AS (SELECT ext FROM content) SELECT * FROM v_x",
        'WITH "v_x"(a) AS MATERIALIZED (SELECT ext FROM content) SELECT * FROM "v_x"',
        "WITH t AS (SELECT 1), v_x /* 注释 */ AS (SELECT ext FROM content) SELECT * FROM v_x",
        "WITH t AS (SELECT * FROM v_contents) SELECT * FROM t, content",
        "SELECT * FROM v_contents WHERE content_id IN (SELECT id FROM content)",
    ):
        with pytest.raises(SqlRejected):
            await sql.run(statement)
    for view in ("v_contents", "v_comments", "v_subtitles", "v_datasets", "v_dataset_items"):
        assert len((await sql.run(f"SELECT count(*) FROM {view}")).rows) == 1
    result = await sql.run("SELECT count(*) FROM v_contents")
    assert result.rows == [[4]]
    # 经视图的 CTE、子查询、连接都放行。
    result = await sql.run(
        "WITH t AS (SELECT content_id, likes FROM v_contents) "
        "SELECT count(*) FROM t JOIN v_dataset_items USING (content_id) "
        "WHERE content_id IN (SELECT content_id FROM v_comments)"
    )
    assert result.rows == [[4]]  # v1、v3（两个数据集各一行）、v4
    # 字符串和注释里的 "v_x AS (" 不算 CTE 定义。
    result = await sql.run("SELECT 'v_x AS (' AS s -- v_y AS (\n FROM v_datasets LIMIT 1")
    assert result.rows == [["v_x AS ("]]
    with pytest.raises(SqlTimeout):
        await sql.run(
            "WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n) SELECT sum(x) FROM n",
            time_limit=0.001,
        )
    result = await sql.run(
        "WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<201) SELECT x FROM n"
    )
    assert result.truncated and len(result.rows) == 200
    result = await sql.run("SELECT printf('%600s', 'x'), CAST('abc' AS BLOB)")
    assert len(result.rows[0][0]) == 501 and result.rows[0][0].endswith("…")
    assert result.rows[0][1] == "<3 字节>"
    await db.close()
