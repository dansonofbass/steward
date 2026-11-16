"""manual institution unique index

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("uq_institution_manual", "institution", ["source"], unique=True,
                    sqlite_where=sa.text("source = 'manual'"))


def downgrade() -> None:
    op.drop_index("uq_institution_manual", table_name="institution")
