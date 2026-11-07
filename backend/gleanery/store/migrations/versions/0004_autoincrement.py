"""数据集、内容、评论、采集任务的 ID 不再复用。

SQLite 默认把删掉的最大 rowid 再发给新行。对话记录、导出卡片和 Agent 都按 ID 指代这些行，
复用后旧引用会指向别的数据，所以改成 AUTOINCREMENT。
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TABLES = ("dataset", "content", "comment", "collection_task")


def upgrade() -> None:
    bind = op.get_bind()
    # 重建表时要先删掉引用它们的视图，否则 SQLite 改名时校验视图会失败；之后按原定义重建。
    views = bind.execute(
        sa.text("SELECT name, sql FROM sqlite_master WHERE type = 'view' ORDER BY name")
    ).all()
    for name, _ in views:
        op.execute(f"DROP VIEW {name}")
    for table in TABLES:
        ddl = bind.execute(
            sa.text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = :name"),
            {"name": table},
        ).scalar_one()
        if "AUTOINCREMENT" in ddl:
            continue
        with op.batch_alter_table(
            table, recreate="always", table_kwargs={"sqlite_autoincrement": True}
        ):
            pass
    for _, sql in views:
        op.execute(sql)


def downgrade() -> None:
    # 不支持降级。
    pass
