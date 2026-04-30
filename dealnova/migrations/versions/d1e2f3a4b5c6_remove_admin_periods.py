"""Remove admin periods.

Revision ID: d1e2f3a4b5c6
Revises: a2b3c4d5e6f7, b7c8d9e0f1a2
Create Date: 2026-04-28 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "d1e2f3a4b5c6"
down_revision = ("a2b3c4d5e6f7", "b7c8d9e0f1a2")
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _columns(inspector, table_name: str) -> set[str]:
    if not _has_table(inspector, table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _indexes(inspector, table_name: str) -> set[str]:
    if not _has_table(inspector, table_name):
        return set()
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _foreign_keys(inspector, table_name: str) -> set[str]:
    if not _has_table(inspector, table_name):
        return set()
    return {fk["name"] for fk in inspector.get_foreign_keys(table_name) if fk.get("name")}


def _drop_column_if_exists(table_name: str, column_name: str, *, fk_name: str | None = None, index_name: str | None = None):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if column_name not in _columns(inspector, table_name):
        return

    with op.batch_alter_table(table_name) as batch_op:
        foreign_keys = _foreign_keys(inspector, table_name)
        indexes = _indexes(inspector, table_name)
        if fk_name and fk_name in foreign_keys:
            batch_op.drop_constraint(fk_name, type_="foreignkey")
        if index_name and index_name in indexes:
            batch_op.drop_index(index_name)
        batch_op.drop_column(column_name)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _drop_column_if_exists("order", "period_id", fk_name="fk_order_period_id_order_period", index_name="ix_order_period_id")
    _drop_column_if_exists(
        "vendor_receipt",
        "period_id",
        fk_name="fk_vendorreceipt_period_id",
        index_name="ix_vendor_receipt_period_id",
    )
    _drop_column_if_exists(
        "financial_entry",
        "period_id",
        fk_name="fk_financial_entry_period_id",
        index_name="ix_financial_entry_period_id",
    )

    inspector = sa.inspect(bind)
    if _has_table(inspector, "order_period"):
        op.drop_table("order_period")
    inspector = sa.inspect(bind)
    if _has_table(inspector, "vendor_period"):
        op.drop_table("vendor_period")
    inspector = sa.inspect(bind)
    if _has_table(inspector, "financial_period"):
        op.drop_table("financial_period")


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "order_period"):
        op.create_table(
            "order_period",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("status", sa.String(length=10), nullable=False, server_default="open"),
            sa.Column("opened_at", sa.DateTime(), nullable=False),
            sa.Column("closed_at", sa.DateTime(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], name="fk_orderperiod_created_by_user"),
        )

    if not _has_table(sa.inspect(bind), "vendor_period"):
        op.create_table(
            "vendor_period",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("vendor_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("start_at", sa.DateTime(), nullable=False),
            sa.Column("end_at", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(length=10), nullable=False, server_default="open"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("closed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["vendor_id"], ["user.id"], name="fk_vendorperiod_vendor_id"),
        )

    if not _has_table(sa.inspect(bind), "financial_period"):
        op.create_table(
            "financial_period",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("end_date", sa.Date(), nullable=False),
            sa.Column("status", sa.String(length=10), nullable=False, server_default="open"),
            sa.Column("closed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("delivery_total_cents", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("subscription_total_cents", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("rental_total_cents", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_cents", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
        )

    inspector = sa.inspect(bind)
    if "period_id" not in _columns(inspector, "order"):
        with op.batch_alter_table("order") as batch_op:
            batch_op.add_column(sa.Column("period_id", sa.Integer(), nullable=True))
            batch_op.create_index("ix_order_period_id", ["period_id"], unique=False)
            batch_op.create_foreign_key("fk_order_period_id_order_period", "order_period", ["period_id"], ["id"])

    inspector = sa.inspect(bind)
    if "period_id" not in _columns(inspector, "vendor_receipt"):
        with op.batch_alter_table("vendor_receipt") as batch_op:
            batch_op.add_column(sa.Column("period_id", sa.Integer(), nullable=True))
            batch_op.create_index("ix_vendor_receipt_period_id", ["period_id"], unique=False)
            batch_op.create_foreign_key("fk_vendorreceipt_period_id", "vendor_period", ["period_id"], ["id"])

    inspector = sa.inspect(bind)
    if "period_id" not in _columns(inspector, "financial_entry"):
        with op.batch_alter_table("financial_entry") as batch_op:
            batch_op.add_column(sa.Column("period_id", sa.Integer(), nullable=True))
            batch_op.create_index("ix_financial_entry_period_id", ["period_id"], unique=False)
            batch_op.create_foreign_key("fk_financial_entry_period_id", "financial_period", ["period_id"], ["id"])
