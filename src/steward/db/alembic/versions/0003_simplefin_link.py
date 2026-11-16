"""simplefin link table

Revision ID: 0003
Revises: 0002
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table('simplefin_link',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('access_url', sa.Text(), nullable=False),
    sa.Column('claimed_at', sa.DateTime(), nullable=False),
    sa.Column('last_sync_at', sa.DateTime(), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('simplefin_link')
