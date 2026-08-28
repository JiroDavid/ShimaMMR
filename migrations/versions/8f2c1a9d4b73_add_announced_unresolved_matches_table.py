"""add announced_unresolved_matches table

Revision ID: 8f2c1a9d4b73
Revises: 51856e81f4ee
Create Date: 2026-08-28 21:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f2c1a9d4b73'
down_revision: Union[str, Sequence[str], None] = '51856e81f4ee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('announced_unresolved_matches',
    sa.Column('external_match_id', sa.String(), nullable=False),
    sa.Column('announced_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('external_match_id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('announced_unresolved_matches')
