"""add ignored_puuids table

Revision ID: 6d4b0e9a2f17
Revises: 8f2c1a9d4b73
Create Date: 2026-08-28 21:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6d4b0e9a2f17'
down_revision: Union[str, Sequence[str], None] = '8f2c1a9d4b73'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('ignored_puuids',
    sa.Column('puuid', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('tag', sa.String(), nullable=False),
    sa.Column('region', sa.String(), nullable=False),
    sa.Column('ignored_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('puuid')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('ignored_puuids')
