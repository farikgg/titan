"""add_status_to_price_model

Revision ID: ed324688a18f
Revises: 3b2f8d2c9f1a
Create Date: 2026-03-25 18:26:31.503541

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ed324688a18f'
down_revision: Union[str, Sequence[str], None] = '3b2f8d2c9f1a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Добавляем колонку статуса для цен
    op.add_column('prices', sa.Column('status', sa.String(length=20), nullable=True))
    op.create_index(op.f('ix_prices_status'), 'prices', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_prices_status'), table_name='prices')
    op.drop_column('prices', 'status')
