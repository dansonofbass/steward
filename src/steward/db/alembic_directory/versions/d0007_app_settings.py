"""app_setting: settings chosen in the app (guided setup spec 4). Additive: one new table.

Revision ID: d0007
Revises: d0006
"""
import sqlalchemy as sa
from alembic import op

revision = "d0007"
down_revision = "d0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_setting",
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("sealed", sa.LargeBinary(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["updated_by"], ["user.id"]),
        sa.CheckConstraint("(value IS NULL) <> (sealed IS NULL)", name="ck_app_setting_one"),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("app_setting")
