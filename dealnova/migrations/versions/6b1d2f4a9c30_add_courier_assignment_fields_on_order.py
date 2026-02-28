"""Add courier assignment and delivery lifecycle fields on order.

Revision ID: 6b1d2f4a9c30
Revises: 9e2a1b4c6d7f
Create Date: 2026-02-23 11:10:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6b1d2f4a9c30"
down_revision = "9e2a1b4c6d7f"
branch_labels = None
depends_on = None


DELIVERY_STATUSES = ("new", "assigned", "picked_up", "delivering", "delivered", "canceled")


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(col.get("name") == column_name for col in inspector.get_columns(table_name))


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def _has_foreign_key(inspector, table_name: str, fk_name: str) -> bool:
    return any(fk.get("name") == fk_name for fk in inspector.get_foreign_keys(table_name))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    delivery_enum = sa.Enum(*DELIVERY_STATUSES, name="delivery_status")
    if dialect != "sqlite":
        delivery_enum.create(bind, checkfirst=True)

    if not _has_column(inspector, "order", "courier_id"):
        op.add_column("order", sa.Column("courier_id", sa.Integer(), nullable=True))
        inspector = sa.inspect(bind)
    if not _has_column(inspector, "order", "delivery_status"):
        op.add_column(
            "order",
            sa.Column(
                "delivery_status",
                sa.Enum(*DELIVERY_STATUSES, name="delivery_status"),
                nullable=False,
                server_default="new",
            ),
        )
        inspector = sa.inspect(bind)
    if not _has_column(inspector, "order", "assigned_at"):
        op.add_column("order", sa.Column("assigned_at", sa.DateTime(), nullable=True))
        inspector = sa.inspect(bind)
    if not _has_column(inspector, "order", "picked_up_at"):
        op.add_column("order", sa.Column("picked_up_at", sa.DateTime(), nullable=True))
        inspector = sa.inspect(bind)

    if dialect != "sqlite" and not _has_foreign_key(inspector, "order", "fk_order_courier_id_user"):
        op.create_foreign_key(
            "fk_order_courier_id_user",
            "order",
            "user",
            ["courier_id"],
            ["id"],
        )
        inspector = sa.inspect(bind)

    if not _has_index(inspector, "order", "ix_order_courier_id"):
        op.create_index("ix_order_courier_id", "order", ["courier_id"], unique=False)
    if not _has_index(inspector, "order", "ix_order_delivery_status"):
        op.create_index("ix_order_delivery_status", "order", ["delivery_status"], unique=False)
    if not _has_index(inspector, "order", "ix_order_assigned_at"):
        op.create_index("ix_order_assigned_at", "order", ["assigned_at"], unique=False)
    if not _has_index(inspector, "order", "ix_order_picked_up_at"):
        op.create_index("ix_order_picked_up_at", "order", ["picked_up_at"], unique=False)

    op.execute(sa.text("UPDATE \"order\" SET delivery_status = 'delivered' WHERE status = 'delivered'"))
    op.execute(sa.text("UPDATE \"order\" SET delivery_status = 'canceled' WHERE status = 'cancelled'"))
    op.execute(
        sa.text(
            "UPDATE \"order\" "
            "SET delivery_status = 'assigned', assigned_at = COALESCE(assigned_at, created_at) "
            "WHERE courier_id IS NOT NULL AND delivery_status = 'new'"
        )
    )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if _has_index(inspector, "order", "ix_order_picked_up_at"):
        op.drop_index("ix_order_picked_up_at", table_name="order")
    if _has_index(inspector, "order", "ix_order_assigned_at"):
        op.drop_index("ix_order_assigned_at", table_name="order")
    if _has_index(inspector, "order", "ix_order_delivery_status"):
        op.drop_index("ix_order_delivery_status", table_name="order")
    if _has_index(inspector, "order", "ix_order_courier_id"):
        op.drop_index("ix_order_courier_id", table_name="order")

    inspector = sa.inspect(bind)
    if dialect != "sqlite" and _has_foreign_key(inspector, "order", "fk_order_courier_id_user"):
        op.drop_constraint("fk_order_courier_id_user", "order", type_="foreignkey")

    inspector = sa.inspect(bind)
    if _has_column(inspector, "order", "picked_up_at"):
        op.drop_column("order", "picked_up_at")
    if _has_column(inspector, "order", "assigned_at"):
        op.drop_column("order", "assigned_at")
    if _has_column(inspector, "order", "delivery_status"):
        op.drop_column("order", "delivery_status")
    if _has_column(inspector, "order", "courier_id"):
        op.drop_column("order", "courier_id")

    if dialect != "sqlite":
        sa.Enum(*DELIVERY_STATUSES, name="delivery_status").drop(bind, checkfirst=True)
