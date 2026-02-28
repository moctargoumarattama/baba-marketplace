"""Add phone_digits and indexes to Order, drop guest_token unique

Revision ID: b6f2b2c8a1e3
Revises: dffd828a8d2a
Create Date: 2026-02-08 23:59:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b6f2b2c8a1e3'
down_revision = 'dffd828a8d2a'
branch_labels = None
depends_on = None


def upgrade():
    # Add phone_digits
    with op.batch_alter_table('order') as batch_op:
        batch_op.add_column(sa.Column('phone_digits', sa.String(length=32), nullable=True))

    # Indexes for performance
    op.create_index('ix_order_phone', 'order', ['phone'])
    op.create_index('ix_order_phone_digits', 'order', ['phone_digits'])
    op.create_index('ix_order_created_at', 'order', ['created_at'])
    op.create_index('ix_order_status', 'order', ['status'])
    op.create_index('ix_order_buyer_id', 'order', ['buyer_id'])


def downgrade():
    op.drop_index('ix_order_buyer_id', table_name='order')
    op.drop_index('ix_order_status', table_name='order')
    op.drop_index('ix_order_created_at', table_name='order')
    op.drop_index('ix_order_phone_digits', table_name='order')
    op.drop_index('ix_order_phone', table_name='order')

    with op.batch_alter_table('order') as batch_op:
        batch_op.drop_column('phone_digits')
