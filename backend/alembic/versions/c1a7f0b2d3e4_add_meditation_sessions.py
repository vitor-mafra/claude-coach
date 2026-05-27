"""add meditation_sessions

Revision ID: c1a7f0b2d3e4
Revises: 554436b298f2
Create Date: 2026-05-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1a7f0b2d3e4'
down_revision: Union[str, Sequence[str], None] = '554436b298f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'meditation_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('duration_min', sa.Integer(), nullable=True),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('note', sa.String(length=512), nullable=True),
        sa.Column('external_id', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('external_id'),
    )
    with op.batch_alter_table('meditation_sessions', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_meditation_sessions_date'), ['date'], unique=False
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('meditation_sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_meditation_sessions_date'))

    op.drop_table('meditation_sessions')
