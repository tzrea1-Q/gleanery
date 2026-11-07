"""报告、修订与引用快照。"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.Integer(), sa.ForeignKey("dataset.id", ondelete="SET NULL")),
        sa.Column(
            "created_in_conversation_id",
            sa.Integer(),
            sa.ForeignKey("conversation.id", ondelete="SET NULL"),
        ),
        sa.Column("basis", sa.JSON()),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sqlite_autoincrement=True,
    )
    op.create_table(
        "report_revision",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "report_id",
            sa.Integer(),
            sa.ForeignKey("report.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "conversation_id", sa.Integer(), sa.ForeignKey("conversation.id", ondelete="SET NULL")
        ),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sqlite_autoincrement=True,
    )
    op.create_index(
        "ix_report_revision_report_id_version",
        "report_revision",
        ["report_id", "version"],
        unique=True,
    )
    op.create_table(
        "report_citation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "report_id",
            sa.Integer(),
            sa.ForeignKey("report.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("author", sa.Text()),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("saved_at", sa.BigInteger(), nullable=False),
        sqlite_autoincrement=True,
    )
    op.create_index(
        "ix_report_citation_report_id_kind_target_id",
        "report_citation",
        ["report_id", "kind", "target_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("report_citation")
    op.drop_table("report_revision")
    op.drop_table("report")
