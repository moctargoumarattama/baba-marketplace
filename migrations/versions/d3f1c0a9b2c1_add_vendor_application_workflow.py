"""add vendor application workflow

Revision ID: d3f1c0a9b2c1
Revises: c7e79ae193c0
Create Date: 2026-05-07 13:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d3f1c0a9b2c1"
down_revision = "c7e79ae193c0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "vendor_application",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("phone", sa.String(length=40), nullable=False),
        sa.Column("phone_digits", sa.String(length=32), nullable=False),
        sa.Column("email", sa.String(length=120), nullable=True),
        sa.Column("email_normalized", sa.String(length=120), nullable=True),
        sa.Column("shop_name", sa.String(length=160), nullable=False),
        sa.Column("city", sa.String(length=80), nullable=False),
        sa.Column("shop_type", sa.String(length=80), nullable=False),
        sa.Column("short_description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by_id", sa.Integer(), nullable=True),
        sa.Column("created_user_id", sa.Integer(), nullable=True),
        sa.Column("created_shop_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("request_ip", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id"],
            ["user.id"],
            name="fk_vendorapplication_reviewed_by_id",
        ),
        sa.ForeignKeyConstraint(
            ["created_user_id"],
            ["user.id"],
            name="fk_vendorapplication_created_user_id",
        ),
        sa.ForeignKeyConstraint(
            ["created_shop_id"],
            ["shop.id"],
            name="fk_vendorapplication_created_shop_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("created_user_id"),
        sa.UniqueConstraint("created_shop_id"),
    )

    with op.batch_alter_table("vendor_application", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_vendor_application_phone_digits"), ["phone_digits"], unique=False)
        batch_op.create_index(batch_op.f("ix_vendor_application_email_normalized"), ["email_normalized"], unique=False)
        batch_op.create_index(batch_op.f("ix_vendor_application_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_vendor_application_reviewed_at"), ["reviewed_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_vendor_application_reviewed_by_id"), ["reviewed_by_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_vendor_application_created_user_id"), ["created_user_id"], unique=True)
        batch_op.create_index(batch_op.f("ix_vendor_application_created_shop_id"), ["created_shop_id"], unique=True)
        batch_op.create_index(batch_op.f("ix_vendor_application_created_at"), ["created_at"], unique=False)


def downgrade():
    with op.batch_alter_table("vendor_application", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_vendor_application_created_at"))
        batch_op.drop_index(batch_op.f("ix_vendor_application_created_shop_id"))
        batch_op.drop_index(batch_op.f("ix_vendor_application_created_user_id"))
        batch_op.drop_index(batch_op.f("ix_vendor_application_reviewed_by_id"))
        batch_op.drop_index(batch_op.f("ix_vendor_application_reviewed_at"))
        batch_op.drop_index(batch_op.f("ix_vendor_application_status"))
        batch_op.drop_index(batch_op.f("ix_vendor_application_email_normalized"))
        batch_op.drop_index(batch_op.f("ix_vendor_application_phone_digits"))

    op.drop_table("vendor_application")
