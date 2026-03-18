"""add_price_validity_fields

Revision ID: 3b2f8d2c9f1a
Revises: 09da51fa6609
Create Date: 2026-03-18

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3b2f8d2c9f1a"
down_revision: Union[str, Sequence[str], None] = "09da51fa6609"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Добавляем поля срока действия цены (FUCHS и в целом).
    op.add_column("prices", sa.Column("first_seen_at", sa.DateTime(), nullable=True))
    op.add_column("prices", sa.Column("valid_from", sa.DateTime(), nullable=True))
    op.add_column(
        "prices",
        sa.Column("valid_days", sa.Integer(), server_default="90", nullable=False),
    )

    op.create_index(op.f("ix_prices_first_seen_at"), "prices", ["first_seen_at"], unique=False)
    op.create_index(op.f("ix_prices_valid_from"), "prices", ["valid_from"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_prices_valid_from"), table_name="prices")
    op.drop_index(op.f("ix_prices_first_seen_at"), table_name="prices")

    op.drop_column("prices", "valid_days")
    op.drop_column("prices", "valid_from")
    op.drop_column("prices", "first_seen_at")

