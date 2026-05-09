"""add vendor change request workflow

Revision ID: f2b9c1d4a7e0
Revises: e18ac9a4f54d
Create Date: 2026-05-07 18:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f2b9c1d4a7e0"
down_revision = "e18ac9a4f54d"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "vendor_change_request",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vendor_id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("request_type", sa.String(length=30), nullable=False),
        sa.Column("current_value", sa.String(length=255), nullable=False),
        sa.Column("requested_value", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["vendor_id"],
            ["user.id"],
            name="fk_vendorchangerequest_vendor_id",
        ),
        sa.ForeignKeyConstraint(
            ["shop_id"],
            ["shop.id"],
            name="fk_vendorchangerequest_shop_id",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id"],
            ["user.id"],
            name="fk_vendorchangerequest_reviewed_by_id",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    with op.batch_alter_table("vendor_change_request", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_vendor_change_request_vendor_id"), ["vendor_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_vendor_change_request_shop_id"), ["shop_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_vendor_change_request_request_type"), ["request_type"], unique=False)
        batch_op.create_index(batch_op.f("ix_vendor_change_request_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_vendor_change_request_reviewed_at"), ["reviewed_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_vendor_change_request_reviewed_by_id"), ["reviewed_by_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_vendor_change_request_created_at"), ["created_at"], unique=False)


def downgrade():
    with op.batch_alter_table("vendor_change_request", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_vendor_change_request_created_at"))
        batch_op.drop_index(batch_op.f("ix_vendor_change_request_reviewed_by_id"))
        batch_op.drop_index(batch_op.f("ix_vendor_change_request_reviewed_at"))
        batch_op.drop_index(batch_op.f("ix_vendor_change_request_status"))
        batch_op.drop_index(batch_op.f("ix_vendor_change_request_request_type"))
        batch_op.drop_index(batch_op.f("ix_vendor_change_request_shop_id"))
        batch_op.drop_index(batch_op.f("ix_vendor_change_request_vendor_id"))

    op.drop_table("vendor_change_request")
