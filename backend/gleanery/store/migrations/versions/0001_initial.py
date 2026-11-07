"""基础表。"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
    )
    op.create_table(
        "message",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("conversation.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("conversation_id", "seq"),
    )
    op.create_table(
        "setting",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
    )
    op.create_table(
        "model_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("preset", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("api_style", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("available_models", sa.JSON(), nullable=True),
        sa.Column("models_fetched_at", sa.BigInteger(), nullable=True),
        sa.Column("favorites", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
    )


def downgrade() -> None:
    # 不支持降级。
    pass
