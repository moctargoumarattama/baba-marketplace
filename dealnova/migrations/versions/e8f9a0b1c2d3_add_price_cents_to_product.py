"""add price cents to product

Revision ID: e8f9a0b1c2d3
Revises: d4e5f6a7b8c9
Create Date: 2026-03-27 16:40:00.000000
"""

from decimal import Decimal, ROUND_HALF_UP

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e8f9a0b1c2d3"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def _price_to_cents(value) -> int:
    amount = Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int((amount * 100).to_integral_value(rounding=ROUND_HALF_UP))


def upgrade():
    with op.batch_alter_table("product") as batch_op:
        batch_op.add_column(sa.Column("price_cents", sa.Integer(), nullable=True, server_default="0"))
        batch_op.create_index("ix_product_price_cents", ["price_cents"], unique=False)

    connection = op.get_bind()
    product_table = sa.table(
        "product",
        sa.column("id", sa.Integer()),
        sa.column("price", sa.Float()),
        sa.column("price_cents", sa.Integer()),
    )

    rows = connection.execute(sa.select(product_table.c.id, product_table.c.price)).fetchall()
    for row in rows:
        cents = _price_to_cents(row.price)
        normalized_price = float((Decimal(cents) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        connection.execute(
            sa.update(product_table)
            .where(product_table.c.id == row.id)
            .values(price_cents=cents, price=normalized_price)
        )

    with op.batch_alter_table("product") as batch_op:
        batch_op.alter_column("price_cents", existing_type=sa.Integer(), nullable=False, server_default=None)
        batch_op.create_check_constraint("price_cents_non_negative", "price_cents >= 0")


def downgrade():
    with op.batch_alter_table("product") as batch_op:
        batch_op.drop_constraint("price_cents_non_negative", type_="check")
        batch_op.drop_index("ix_product_price_cents")
        batch_op.drop_column("price_cents")
