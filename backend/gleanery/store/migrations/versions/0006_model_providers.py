"""模型配置：ChatGPT 套餐的 client_id，接口给的模型显示名。"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("model_config") as batch:
        batch.add_column(sa.Column("model_labels", sa.JSON()))
        batch.add_column(sa.Column("client_id", sa.Text()))


def downgrade() -> None:
    with op.batch_alter_table("model_config") as batch:
        batch.drop_column("client_id")
        batch.drop_column("model_labels")
