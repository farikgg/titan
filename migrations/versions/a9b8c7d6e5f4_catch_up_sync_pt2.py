"""catch_up_sync_pt2

Revision ID: a9b8c7d6e5f4
Revises: f3b2e1a9c8d7
Create Date: 2026-04-08 15:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9b8c7d6e5f4'
down_revision: Union[str, Sequence[str], None] = 'f3b2e1a9c8d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Поля в таблицу offer_items
    op.add_column('offer_items', sa.Column('raw_name', sa.String(length=500), nullable=True))
    op.add_column('offer_items', sa.Column('unit', sa.String(length=50), nullable=True))
    
    # 2. Изменение типа quantity в offer_items (Integer -> Numeric)
    op.alter_column('offer_items', 'quantity',
               existing_type=sa.INTEGER(),
               type_=sa.Numeric(precision=12, scale=3),
               existing_nullable=False)


def downgrade() -> None:
    op.alter_column('offer_items', 'quantity',
               existing_type=sa.Numeric(precision=12, scale=3),
               type_=sa.INTEGER(),
               existing_nullable=False)
    op.drop_column('offer_items', 'unit')
    op.drop_column('offer_items', 'raw_name')
