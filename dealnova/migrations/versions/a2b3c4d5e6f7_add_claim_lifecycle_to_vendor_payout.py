"""add claim lifecycle to vendor payout

Revision ID: a2b3c4d5e6f7
Revises: f9a1b2c3d4e5
Create Date: 2026-04-20 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a2b3c4d5e6f7"
down_revision = "f9a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vendor_payout", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_claimable",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch_op.add_column(sa.Column("claimed_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("claimed_by_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_payout_claimed_by_id",
            "user",
            ["claimed_by_id"],
            ["id"],
        )


def downgrade():
    with op.batch_alter_table("vendor_payout", schema=None) as batch_op:
        batch_op.drop_constraint("fk_payout_claimed_by_id", type_="foreignkey")
        batch_op.drop_column("claimed_by_id")
        batch_op.drop_column("claimed_at")
        batch_op.drop_column("is_claimable")
