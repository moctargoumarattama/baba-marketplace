"""Add order periods and link orders to periods.

Revision ID: c4d5e6f7a8b9
Revises: a9b8c7d6e5f4
Create Date: 2026-02-23 12:10:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c4d5e6f7a8b9"
down_revision = "a9b8c7d6e5f4"
branch_labels = None
depends_on = None


def upgrade():
    # Recover from interrupted SQLite batch migrations.
    op.execute(sa.text("DROP TABLE IF EXISTS _alembic_tmp_order"))

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    table_names = set(inspector.get_table_names())
    if "order_period" not in table_names:
        op.create_table(
            "order_period",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("status", sa.String(length=10), nullable=False, server_default="open"),
            sa.Column("opened_at", sa.DateTime(), nullable=False),
            sa.Column("closed_at", sa.DateTime(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], name="fk_orderperiod_created_by_user"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_order_period_status"), "order_period", ["status"], unique=False)
        op.create_index(op.f("ix_order_period_opened_at"), "order_period", ["opened_at"], unique=False)
        op.create_index(op.f("ix_order_period_closed_at"), "order_period", ["closed_at"], unique=False)
        op.create_index(op.f("ix_order_period_created_by"), "order_period", ["created_by"], unique=False)

    # Refresh inspector after potential table creation.
    inspector = sa.inspect(bind)
    order_columns = {col["name"] for col in inspector.get_columns("order")}
    order_indexes = {idx["name"] for idx in inspector.get_indexes("order")}
    order_fk_names = {fk.get("name") for fk in inspector.get_foreign_keys("order")}

    if "period_id" not in order_columns:
        op.add_column("order", sa.Column("period_id", sa.Integer(), nullable=True))

    order_period_idx = op.f("ix_order_period_id")
    if order_period_idx not in order_indexes:
        op.create_index(order_period_idx, "order", ["period_id"], unique=False)

    # SQLite can't add FK on existing table without full table rebuild.
    # Skip FK creation there to keep migration fast and avoid long locks.
    if dialect != "sqlite" and "fk_order_period_id_order_period" not in order_fk_names:
        op.create_foreign_key(
            "fk_order_period_id_order_period",
            "order",
            "order_period",
            ["period_id"],
            ["id"],
        )


def downgrade():
    with op.batch_alter_table("order", schema=None) as batch_op:
        batch_op.drop_constraint("fk_order_period_id_order_period", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_order_period_id"))
        batch_op.drop_column("period_id")

    op.drop_index(op.f("ix_order_period_created_by"), table_name="order_period")
    op.drop_index(op.f("ix_order_period_closed_at"), table_name="order_period")
    op.drop_index(op.f("ix_order_period_opened_at"), table_name="order_period")
    op.drop_index(op.f("ix_order_period_status"), table_name="order_period")
    op.drop_table("order_period")
