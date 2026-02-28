"""Add password change window fields on user.

Revision ID: c7a1e2d3f4a5
Revises: b2c3d4e5f6a7
Create Date: 2026-02-25 03:35:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c7a1e2d3f4a5"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(col.get("name") == column_name for col in inspector.get_columns(table_name))


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_column(inspector, "user", "password_change_allowed_until"):
        op.add_column("user", sa.Column("password_change_allowed_until", sa.DateTime(), nullable=True))
        inspector = sa.inspect(bind)

    if not _has_index(inspector, "user", "ix_user_password_change_allowed_until"):
        op.create_index(
            "ix_user_password_change_allowed_until",
            "user",
            ["password_change_allowed_until"],
            unique=False,
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_index(inspector, "user", "ix_user_password_change_allowed_until"):
        op.drop_index("ix_user_password_change_allowed_until", table_name="user")

    inspector = sa.inspect(bind)
    if _has_column(inspector, "user", "password_change_allowed_until"):
        op.drop_column("user", "password_change_allowed_until")
