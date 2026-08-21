"""remove delivery module schema

Revision ID: 20260511rm_delivery
Revises: 20260508push
Create Date: 2026-05-11 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260511rm_delivery"
down_revision = "20260508push"
branch_labels = None
depends_on = None


ORDER_DELIVERY_COLUMNS = [
    "delivery_price_cents",
    "delivery_platform_fee_cents",
    "delivery_source",
    "delivery_city",
    "delivery_address",
    "delivery_lat",
    "delivery_lng",
    "delivery_maps_url",
    "customer_name",
    "customer_phone",
    "special_item",
    "special_pickup_address",
    "special_pickup_lat",
    "special_pickup_lng",
    "special_pickup_maps_url",
    "special_dropoff_address",
    "special_dropoff_lat",
    "special_dropoff_lng",
    "special_dropoff_maps_url",
    "special_note",
    "special_datetime",
    "special_is_urgent",
    "delivery_status",
]


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def _safe_drop_enum_type(bind, enum_name: str) -> None:
    dialect = bind.dialect.name
    if dialect != "postgresql":
        return
    op.execute(sa.text(f'DROP TYPE IF EXISTS "{enum_name}"'))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "order" in table_names:
        for index_name in (
            "ix_order_delivery_platform_fee_cents",
            "ix_order_delivery_source",
            "ix_order_delivery_status",
        ):
            if _has_index(inspector, "order", index_name):
                op.drop_index(index_name, table_name="order")

        for column_name in ORDER_DELIVERY_COLUMNS:
            if _has_column(inspector, "order", column_name):
                op.drop_column("order", column_name)

    if "platform_settings" in table_names:
        for column_name in (
            "shipping_kenitra",
            "shipping_temara",
            "shipping_rabat",
            "shipping_sale",
            "delivery_platform_fee_fixed_cents",
        ):
            if _has_column(inspector, "platform_settings", column_name):
                op.drop_column("platform_settings", column_name)

    if "delivery_inquiry" in table_names:
        op.drop_table("delivery_inquiry")

    _safe_drop_enum_type(bind, "delivery_status")


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "platform_settings" in table_names:
        if not _has_column(inspector, "platform_settings", "shipping_kenitra"):
            op.add_column("platform_settings", sa.Column("shipping_kenitra", sa.Integer(), nullable=False, server_default="2000"))
        if not _has_column(inspector, "platform_settings", "shipping_temara"):
            op.add_column("platform_settings", sa.Column("shipping_temara", sa.Integer(), nullable=False, server_default="2500"))
        if not _has_column(inspector, "platform_settings", "shipping_rabat"):
            op.add_column("platform_settings", sa.Column("shipping_rabat", sa.Integer(), nullable=False, server_default="3000"))
        if not _has_column(inspector, "platform_settings", "shipping_sale"):
            op.add_column("platform_settings", sa.Column("shipping_sale", sa.Integer(), nullable=False, server_default="2500"))
        if not _has_column(inspector, "platform_settings", "delivery_platform_fee_fixed_cents"):
            op.add_column(
                "platform_settings",
                sa.Column("delivery_platform_fee_fixed_cents", sa.Integer(), nullable=False, server_default="0"),
            )

    if "order" in table_names:
        missing = {name for name in ORDER_DELIVERY_COLUMNS if not _has_column(inspector, "order", name)}
        if "delivery_price_cents" in missing:
            op.add_column("order", sa.Column("delivery_price_cents", sa.Integer(), nullable=True, server_default="0"))
        if "delivery_platform_fee_cents" in missing:
            op.add_column("order", sa.Column("delivery_platform_fee_cents", sa.Integer(), nullable=True, server_default="0"))
        if "delivery_source" in missing:
            op.add_column("order", sa.Column("delivery_source", sa.String(length=20), nullable=False, server_default="marketplace"))
        if "delivery_city" in missing:
            op.add_column("order", sa.Column("delivery_city", sa.String(length=120), nullable=True))
        if "delivery_address" in missing:
            op.add_column("order", sa.Column("delivery_address", sa.Text(), nullable=True))
        if "delivery_lat" in missing:
            op.add_column("order", sa.Column("delivery_lat", sa.Float(), nullable=True))
        if "delivery_lng" in missing:
            op.add_column("order", sa.Column("delivery_lng", sa.Float(), nullable=True))
        if "delivery_maps_url" in missing:
            op.add_column("order", sa.Column("delivery_maps_url", sa.Text(), nullable=True))
        if "customer_name" in missing:
            op.add_column("order", sa.Column("customer_name", sa.String(length=150), nullable=True))
        if "customer_phone" in missing:
            op.add_column("order", sa.Column("customer_phone", sa.String(length=30), nullable=True))
        if "special_item" in missing:
            op.add_column("order", sa.Column("special_item", sa.Text(), nullable=True))
        if "special_pickup_address" in missing:
            op.add_column("order", sa.Column("special_pickup_address", sa.Text(), nullable=True))
        if "special_pickup_lat" in missing:
            op.add_column("order", sa.Column("special_pickup_lat", sa.Float(), nullable=True))
        if "special_pickup_lng" in missing:
            op.add_column("order", sa.Column("special_pickup_lng", sa.Float(), nullable=True))
        if "special_pickup_maps_url" in missing:
            op.add_column("order", sa.Column("special_pickup_maps_url", sa.Text(), nullable=True))
        if "special_dropoff_address" in missing:
            op.add_column("order", sa.Column("special_dropoff_address", sa.Text(), nullable=True))
        if "special_dropoff_lat" in missing:
            op.add_column("order", sa.Column("special_dropoff_lat", sa.Float(), nullable=True))
        if "special_dropoff_lng" in missing:
            op.add_column("order", sa.Column("special_dropoff_lng", sa.Float(), nullable=True))
        if "special_dropoff_maps_url" in missing:
            op.add_column("order", sa.Column("special_dropoff_maps_url", sa.Text(), nullable=True))
        if "special_note" in missing:
            op.add_column("order", sa.Column("special_note", sa.Text(), nullable=True))
        if "special_datetime" in missing:
            op.add_column("order", sa.Column("special_datetime", sa.String(length=80), nullable=True))
        if "special_is_urgent" in missing:
            op.add_column("order", sa.Column("special_is_urgent", sa.Boolean(), nullable=False, server_default=sa.text("0")))
        if "delivery_status" in missing:
            status_enum = sa.Enum("new", "delivered", "canceled", name="delivery_status")
            if bind.dialect.name == "postgresql":
                status_enum.create(bind, checkfirst=True)
            op.add_column("order", sa.Column("delivery_status", status_enum, nullable=False, server_default="new"))

    inspector = sa.inspect(bind)
    if "order" in inspector.get_table_names():
        if _has_column(inspector, "order", "delivery_platform_fee_cents") and not _has_index(
            inspector, "order", "ix_order_delivery_platform_fee_cents"
        ):
            op.create_index("ix_order_delivery_platform_fee_cents", "order", ["delivery_platform_fee_cents"], unique=False)
        if _has_column(inspector, "order", "delivery_source") and not _has_index(inspector, "order", "ix_order_delivery_source"):
            op.create_index("ix_order_delivery_source", "order", ["delivery_source"], unique=False)
        if _has_column(inspector, "order", "delivery_status") and not _has_index(inspector, "order", "ix_order_delivery_status"):
            op.create_index("ix_order_delivery_status", "order", ["delivery_status"], unique=False)

    if "delivery_inquiry" not in inspector.get_table_names():
        op.create_table(
            "delivery_inquiry",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("name", sa.String(length=150), nullable=False),
            sa.Column("phone", sa.String(length=40), nullable=False),
            sa.Column("city", sa.String(length=50), nullable=False),
            sa.Column("price_cents", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("item_text", sa.String(length=255), nullable=True),
            sa.Column("pickup_text", sa.String(length=255), nullable=True),
            sa.Column("dropoff_text", sa.String(length=255), nullable=True),
            sa.Column("note_text", sa.String(length=255), nullable=True),
            sa.Column("urgent", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("desired_datetime", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_delivery_inquiry_created_at", "delivery_inquiry", ["created_at"], unique=False)
        op.create_index("ix_delivery_inquiry_phone", "delivery_inquiry", ["phone"], unique=False)
        op.create_index("ix_delivery_inquiry_city", "delivery_inquiry", ["city"], unique=False)
