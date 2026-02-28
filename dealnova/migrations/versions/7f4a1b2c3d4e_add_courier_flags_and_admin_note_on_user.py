"""Add courier flags and internal note on user.

Revision ID: 7f4a1b2c3d4e
Revises: 6b1d2f4a9c30
Create Date: 2026-02-23 06:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7f4a1b2c3d4e"
down_revision = "6b1d2f4a9c30"
branch_labels = None
depends_on = None


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(col.get("name") == column_name for col in inspector.get_columns(table_name))


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_column(inspector, "user", "courier_is_active"):
        op.add_column(
            "user",
            sa.Column("courier_is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
        inspector = sa.inspect(bind)

    if not _has_column(inspector, "user", "courier_is_available"):
        op.add_column(
            "user",
            sa.Column("courier_is_available", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        inspector = sa.inspect(bind)

    if not _has_column(inspector, "user", "courier_admin_note"):
        op.add_column("user", sa.Column("courier_admin_note", sa.Text(), nullable=True))
        inspector = sa.inspect(bind)

    if not _has_column(inspector, "user", "courier_last_seen_at"):
        op.add_column("user", sa.Column("courier_last_seen_at", sa.DateTime(), nullable=True))
        inspector = sa.inspect(bind)

    ix_active = op.f("ix_user_courier_is_active")
    ix_available = op.f("ix_user_courier_is_available")

    if not _has_index(inspector, "user", ix_active):
        op.create_index(ix_active, "user", ["courier_is_active"], unique=False)
    if not _has_index(inspector, "user", ix_available):
        op.create_index(ix_available, "user", ["courier_is_available"], unique=False)

    op.execute(sa.text("UPDATE user SET courier_is_active = 1 WHERE courier_is_active IS NULL"))
    op.execute(sa.text("UPDATE user SET courier_is_available = 0 WHERE courier_is_available IS NULL"))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    ix_active = op.f("ix_user_courier_is_active")
    ix_available = op.f("ix_user_courier_is_available")

    if _has_index(inspector, "user", ix_available):
        op.drop_index(ix_available, table_name="user")
    if _has_index(inspector, "user", ix_active):
        op.drop_index(ix_active, table_name="user")

    inspector = sa.inspect(bind)
    if _has_column(inspector, "user", "courier_last_seen_at"):
        op.drop_column("user", "courier_last_seen_at")
    if _has_column(inspector, "user", "courier_admin_note"):
        op.drop_column("user", "courier_admin_note")
    if _has_column(inspector, "user", "courier_is_available"):
        op.drop_column("user", "courier_is_available")
    if _has_column(inspector, "user", "courier_is_active"):
        op.drop_column("user", "courier_is_active")
