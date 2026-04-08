"""add runtime state table

Revision ID: d4e5f6a7b8c9
Revises: c7a1e2d3f4a5
Create Date: 2026-03-27 15:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d4e5f6a7b8c9"
down_revision = "c7a1e2d3f4a5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "runtime_state",
        sa.Column("state_key", sa.String(length=120), nullable=False),
        sa.Column("value_int", sa.BigInteger(), nullable=True),
        sa.Column("value_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("state_key"),
    )
    op.create_index(op.f("ix_runtime_state_updated_at"), "runtime_state", ["updated_at"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_runtime_state_updated_at"), table_name="runtime_state")
    op.drop_table("runtime_state")
