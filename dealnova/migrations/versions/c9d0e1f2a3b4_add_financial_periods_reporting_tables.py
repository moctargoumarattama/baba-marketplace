"""Add financial periods and financial entries reporting tables.

Revision ID: c9d0e1f2a3b4
Revises: 8a9b0c1d2e3f
Create Date: 2026-02-23 17:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c9d0e1f2a3b4"
down_revision = "8a9b0c1d2e3f"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(col.get("name") == column_name for col in inspector.get_columns(table_name))


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "subscription_payment"):
        op.create_table(
            "subscription_payment",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("months", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("amount_cents", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("paid_at", sa.DateTime(), nullable=False),
            sa.Column("created_by_id", sa.Integer(), nullable=True),
            sa.Column("note", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"], name="fk_subscription_payment_user_id"),
            sa.ForeignKeyConstraint(["created_by_id"], ["user.id"], name="fk_subscription_payment_created_by_id"),
            sa.CheckConstraint("months >= 1", name="ck_subscription_payment_months_positive"),
            sa.CheckConstraint("amount_cents >= 0", name="ck_subscription_payment_amount_non_negative"),
        )
        inspector = sa.inspect(bind)

    if _has_table(inspector, "subscription_payment"):
        if not _has_index(inspector, "subscription_payment", "ix_subscription_payment_user_id"):
            op.create_index("ix_subscription_payment_user_id", "subscription_payment", ["user_id"], unique=False)
        if not _has_index(inspector, "subscription_payment", "ix_subscription_payment_paid_at"):
            op.create_index("ix_subscription_payment_paid_at", "subscription_payment", ["paid_at"], unique=False)
        if not _has_index(inspector, "subscription_payment", "ix_subscription_payment_created_by_id"):
            op.create_index("ix_subscription_payment_created_by_id", "subscription_payment", ["created_by_id"], unique=False)
        if not _has_index(inspector, "subscription_payment", "ix_subscription_payment_created_at"):
            op.create_index("ix_subscription_payment_created_at", "subscription_payment", ["created_at"], unique=False)

    inspector = sa.inspect(bind)
    if not _has_table(inspector, "financial_period"):
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
            sa.CheckConstraint("status IN ('open','closed')", name="ck_financial_period_status"),
            sa.CheckConstraint("end_date >= start_date", name="ck_financial_period_dates"),
            sa.CheckConstraint(
                "delivery_total_cents >= 0",
                name="ck_financial_period_delivery_total_non_negative",
            ),
            sa.CheckConstraint(
                "subscription_total_cents >= 0",
                name="ck_financial_period_subscription_total_non_negative",
            ),
            sa.CheckConstraint(
                "rental_total_cents >= 0",
                name="ck_financial_period_rental_total_non_negative",
            ),
            sa.CheckConstraint("total_cents >= 0", name="ck_financial_period_total_non_negative"),
        )
        inspector = sa.inspect(bind)

    if _has_table(inspector, "financial_period"):
        if not _has_index(inspector, "financial_period", "ix_financial_period_start_date"):
            op.create_index("ix_financial_period_start_date", "financial_period", ["start_date"], unique=False)
        if not _has_index(inspector, "financial_period", "ix_financial_period_end_date"):
            op.create_index("ix_financial_period_end_date", "financial_period", ["end_date"], unique=False)
        if not _has_index(inspector, "financial_period", "ix_financial_period_status"):
            op.create_index("ix_financial_period_status", "financial_period", ["status"], unique=False)
        if not _has_index(inspector, "financial_period", "ix_financial_period_closed_at"):
            op.create_index("ix_financial_period_closed_at", "financial_period", ["closed_at"], unique=False)
        if not _has_index(inspector, "financial_period", "ix_financial_period_created_at"):
            op.create_index("ix_financial_period_created_at", "financial_period", ["created_at"], unique=False)
        if not _has_index(inspector, "financial_period", "ix_financial_period_deleted_at"):
            op.create_index("ix_financial_period_deleted_at", "financial_period", ["deleted_at"], unique=False)

    inspector = sa.inspect(bind)
    if not _has_table(inspector, "financial_entry"):
        op.create_table(
            "financial_entry",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("period_id", sa.Integer(), nullable=True),
            sa.Column(
                "entry_type",
                sa.Enum("delivery_fee", "subscription", "rental_commission", name="financial_entry_type"),
                nullable=False,
            ),
            sa.Column("amount_cents", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("order_id", sa.Integer(), nullable=True),
            sa.Column("rental_archive_id", sa.Integer(), nullable=True),
            sa.Column("subscription_id", sa.Integer(), nullable=True),
            sa.Column("courier_id", sa.Integer(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["period_id"], ["financial_period.id"], name="fk_financial_entry_period_id"),
            sa.ForeignKeyConstraint(["order_id"], ["order.id"], name="fk_financial_entry_order_id"),
            sa.ForeignKeyConstraint(
                ["rental_archive_id"], ["rental_archive.id"], name="fk_financial_entry_rental_archive_id"
            ),
            sa.ForeignKeyConstraint(
                ["subscription_id"], ["subscription_payment.id"], name="fk_financial_entry_subscription_id"
            ),
            sa.ForeignKeyConstraint(["courier_id"], ["user.id"], name="fk_financial_entry_courier_id"),
            sa.UniqueConstraint("entry_type", "order_id", name="uq_financial_entry_type_order_id"),
            sa.UniqueConstraint(
                "entry_type",
                "rental_archive_id",
                name="uq_financial_entry_type_rental_archive_id",
            ),
            sa.UniqueConstraint(
                "entry_type",
                "subscription_id",
                name="uq_financial_entry_type_subscription_id",
            ),
        )
        inspector = sa.inspect(bind)

    if _has_table(inspector, "financial_entry"):
        if not _has_index(inspector, "financial_entry", "ix_financial_entry_period_id"):
            op.create_index("ix_financial_entry_period_id", "financial_entry", ["period_id"], unique=False)
        if not _has_index(inspector, "financial_entry", "ix_financial_entry_entry_type"):
            op.create_index("ix_financial_entry_entry_type", "financial_entry", ["entry_type"], unique=False)
        if not _has_index(inspector, "financial_entry", "ix_financial_entry_created_at"):
            op.create_index("ix_financial_entry_created_at", "financial_entry", ["created_at"], unique=False)
        if not _has_index(inspector, "financial_entry", "ix_financial_entry_order_id"):
            op.create_index("ix_financial_entry_order_id", "financial_entry", ["order_id"], unique=False)
        if not _has_index(inspector, "financial_entry", "ix_financial_entry_rental_archive_id"):
            op.create_index(
                "ix_financial_entry_rental_archive_id",
                "financial_entry",
                ["rental_archive_id"],
                unique=False,
            )
        if not _has_index(inspector, "financial_entry", "ix_financial_entry_subscription_id"):
            op.create_index("ix_financial_entry_subscription_id", "financial_entry", ["subscription_id"], unique=False)
        if not _has_index(inspector, "financial_entry", "ix_financial_entry_courier_id"):
            op.create_index("ix_financial_entry_courier_id", "financial_entry", ["courier_id"], unique=False)
        if not _has_index(inspector, "financial_entry", "ix_financial_entry_deleted_at"):
            op.create_index("ix_financial_entry_deleted_at", "financial_entry", ["deleted_at"], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "financial_entry"):
        op.drop_table("financial_entry")

    inspector = sa.inspect(bind)
    if _has_table(inspector, "financial_period"):
        op.drop_table("financial_period")
