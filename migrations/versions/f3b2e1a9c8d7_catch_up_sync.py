"""catch_up_sync

Revision ID: f3b2e1a9c8d7
Revises: ed324688a18f
Create Date: 2026-04-08 15:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f3b2e1a9c8d7'
down_revision: Union[str, Sequence[str], None] = 'ed324688a18f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Новые таблицы: analog_requests, product_analogs
    op.create_table('analog_requests',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('deal_id', sa.String(length=50), nullable=True),
        sa.Column('client_id', sa.String(length=50), nullable=True),
        sa.Column('email_thread_id', sa.String(length=255), nullable=True, comment='conversationId из почты'),
        sa.Column('product_name', sa.String(length=500), nullable=True),
        sa.Column('product_code', sa.String(length=100), nullable=True),
        sa.Column('brand', sa.String(length=200), nullable=True),
        sa.Column('supplier', sa.String(length=200), nullable=True),
        sa.Column('request_status', sa.String(length=20), server_default='pending', nullable=False, comment='pending / sent / answered / resolved'),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('response_received_at', sa.DateTime(), nullable=True),
        sa.Column('parsed_result', sa.JSON(), nullable=True),
        sa.Column('manager_id', sa.Integer(), nullable=True, comment='user.id менеджера'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_analog_requests_deal_id'), 'analog_requests', ['deal_id'], unique=False)
    op.create_index(op.f('ix_analog_requests_email_thread_id'), 'analog_requests', ['email_thread_id'], unique=False)
    op.create_index(op.f('ix_analog_requests_product_code'), 'analog_requests', ['product_code'], unique=False)
    op.create_index(op.f('ix_analog_requests_request_status'), 'analog_requests', ['request_status'], unique=False)

    op.create_table('product_analogs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('source_product_name', sa.String(length=500), nullable=True),
        sa.Column('source_product_code', sa.String(length=100), nullable=False),
        sa.Column('source_brand', sa.String(length=200), nullable=True),
        sa.Column('supplier_name', sa.String(length=200), nullable=True),
        sa.Column('analog_product_name', sa.String(length=500), nullable=True),
        sa.Column('analog_product_code', sa.String(length=100), nullable=False),
        sa.Column('analog_brand', sa.String(length=200), nullable=True),
        sa.Column('match_type', sa.String(length=10), nullable=True, comment='1:1 or 1:N'),
        sa.Column('confidence_level', sa.Float(), nullable=True, comment='0.0 to 1.0'),
        sa.Column('status', sa.String(length=20), server_default='new', nullable=False, comment='new / confirmed / archived'),
        sa.Column('added_from', sa.String(length=20), nullable=True, comment='email / manual / import'),
        sa.Column('email_thread_id', sa.String(length=255), nullable=True),
        sa.Column('confirmed_by', sa.Integer(), nullable=True, comment='user.id менеджера'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_product_code', 'analog_product_code', name='uq_analog_pair')
    )
    op.create_index(op.f('ix_product_analogs_analog_product_code'), 'product_analogs', ['analog_product_code'], unique=False)
    op.create_index(op.f('ix_product_analogs_source_product_code'), 'product_analogs', ['source_product_code'], unique=False)
    op.create_index(op.f('ix_product_analogs_status'), 'product_analogs', ['status'], unique=False)

    # 2. Поля в таблицу offers
    op.add_column('offers', sa.Column('payment_terms', sa.Text(), nullable=True))
    op.add_column('offers', sa.Column('delivery_terms', sa.Text(), nullable=True))
    op.add_column('offers', sa.Column('warranty_terms', sa.Text(), nullable=True))
    op.add_column('offers', sa.Column('manager_email', sa.String(length=255), nullable=True))
    # client_email уже мог быть добавлен в 16f5ad85c442? Нет, там был только currency.
    # Проверим 16f5ad85c442...
    op.add_column('offers', sa.Column('client_email', sa.String(length=255), nullable=True))
    op.add_column('offers', sa.Column('incoterms', sa.String(length=100), nullable=True))
    op.add_column('offers', sa.Column('deadline', sa.String(length=100), nullable=True))
    op.add_column('offers', sa.Column('delivery_place', sa.String(length=255), nullable=True))
    op.add_column('offers', sa.Column('vat_enabled', sa.Boolean(), nullable=True))
    op.add_column('offers', sa.Column('lead_time', sa.String(length=255), nullable=True))
    op.add_column('offers', sa.Column('client_company_name', sa.String(length=255), nullable=True))
    op.add_column('offers', sa.Column('client_address', sa.String(length=255), nullable=True))
    op.add_column('offers', sa.Column('subject', sa.String(length=500), nullable=True))

    # 3. Поля в таблицу prices
    op.add_column('prices', sa.Column('raw_name', sa.String(length=500), nullable=True))
    op.add_column('prices', sa.Column('quantity', sa.Numeric(precision=12, scale=3), nullable=True))
    op.add_column('prices', sa.Column('unit', sa.String(length=50), nullable=True))
    op.add_column('prices', sa.Column('container_size', sa.Numeric(precision=10, scale=3), nullable=True))
    op.add_column('prices', sa.Column('container_unit', sa.String(length=10), nullable=True))
    op.add_column('prices', sa.Column('unit_price', sa.Numeric(precision=12, scale=4), nullable=True))
    op.add_column('prices', sa.Column('unit_measure', sa.String(length=20), nullable=True))
    op.add_column('prices', sa.Column('unit_price_missing', sa.Boolean(), server_default='false', nullable=False))

    # 4. Типы данных в users (Integer -> BigInteger)
    op.alter_column('users', 'tg_id',
               existing_type=sa.INTEGER(),
               type_=sa.BigInteger(),
               existing_nullable=False)
    op.alter_column('users', 'bitrix_user_id',
               existing_type=sa.INTEGER(),
               type_=sa.BigInteger(),
               existing_nullable=False)


def downgrade() -> None:
    op.drop_column('prices', 'unit_price_missing')
    op.drop_column('prices', 'unit_measure')
    op.drop_column('prices', 'unit_price')
    op.drop_column('prices', 'container_unit')
    op.drop_column('prices', 'container_size')
    op.drop_column('prices', 'unit')
    op.drop_column('prices', 'quantity')
    op.drop_column('prices', 'raw_name')

    op.drop_column('offers', 'subject')
    op.drop_column('offers', 'client_address')
    op.drop_column('offers', 'client_company_name')
    op.drop_column('offers', 'lead_time')
    op.drop_column('offers', 'vat_enabled')
    op.drop_column('offers', 'delivery_place')
    op.drop_column('offers', 'deadline')
    op.drop_column('offers', 'incoterms')
    op.drop_column('offers', 'client_email')
    op.drop_column('offers', 'manager_email')
    op.drop_column('offers', 'warranty_terms')
    op.drop_column('offers', 'delivery_terms')
    op.drop_column('offers', 'payment_terms')

    op.drop_index(op.f('ix_product_analogs_status'), table_name='product_analogs')
    op.drop_index(op.f('ix_product_analogs_source_product_code'), table_name='product_analogs')
    op.drop_index(op.f('ix_product_analogs_analog_product_code'), table_name='product_analogs')
    op.drop_table('product_analogs')

    op.drop_index(op.f('ix_analog_requests_request_status'), table_name='analog_requests')
    op.drop_index(op.f('ix_analog_requests_product_code'), table_name='analog_requests')
    op.drop_index(op.f('ix_analog_requests_email_thread_id'), table_name='analog_requests')
    op.drop_index(op.f('ix_analog_requests_deal_id'), table_name='analog_requests')
    op.drop_table('analog_requests')
