"""user.celebrations and user.sound, membership.growth_seen: Celebrations and Sound move from each device to the person,
and each person's mark for the growth stage they last saw in a book (phase 17 spec 3.4, 3.6). Null is "never chosen"
and "never seen".

Revision ID: d0005
Revises: d0004
"""
import sqlalchemy as sa
from alembic import op

revision = "d0005"
down_revision = "d0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Plain ADD COLUMNs: a batch rebuild would drop and recreate "user" while other tables point at it (as d0003).
    op.add_column("user", sa.Column("celebrations", sa.Boolean(), nullable=True))
    op.add_column("user", sa.Column("sound", sa.Boolean(), nullable=True))
    op.add_column("membership", sa.Column("growth_seen", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("membership", "growth_seen")
    op.drop_column("user", "sound")
    op.drop_column("user", "celebrations")
