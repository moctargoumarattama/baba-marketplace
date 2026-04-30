"""allow draft and expired order status

Revision ID: f9a1b2c3d4e5
Revises: e8f9a0b1c2d3
Create Date: 2026-04-20 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision = "f9a1b2c3d4e5"
down_revision = "e8f9a0b1c2d3"
branch_labels = None
depends_on = None


OLD_ORDER_STATUSES = ("pending", "shipped", "delivered", "cancelled", "archived")
NEW_ORDER_STATUSES = ("pending", "shipped", "delivered", "cancelled", "archived", "draft", "expired")


def _status_column():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for column in inspector.get_columns("order"):
        if column.get("name") == "status":
            return column
    return None


def _enum_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _mysql_default_sql(column, allowed_statuses: tuple[str, ...]) -> str:
    raw_default = column.get("default") if column else None
    if raw_default is None:
        return ""
    default = str(raw_default).strip("'\"")
    if default not in allowed_statuses:
        return ""
    return f" DEFAULT '{default}'"


def _is_mysql_enum(column) -> bool:
    return bool(column and isinstance(column.get("type"), mysql.ENUM))


def upgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name
    column = _status_column()

    if dialect == "sqlite":
        with op.batch_alter_table("order", schema=None):
            pass
        return

    if dialect in {"mysql", "mariadb"} and _is_mysql_enum(column):
        op.execute(
            sa.text(
                "ALTER TABLE `order` "
                f"MODIFY COLUMN `status` ENUM({_enum_values(NEW_ORDER_STATUSES)}) "
                f"NOT NULL{_mysql_default_sql(column, NEW_ORDER_STATUSES)}"
            )
        )


def downgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name
    column = _status_column()

    if dialect == "sqlite":
        with op.batch_alter_table("order", schema=None):
            pass
        return

    if dialect in {"mysql", "mariadb"} and _is_mysql_enum(column):
        op.execute(sa.text("UPDATE `order` SET `status` = 'pending' WHERE `status` IN ('draft', 'expired')"))
        op.execute(
            sa.text(
                "ALTER TABLE `order` "
                f"MODIFY COLUMN `status` ENUM({_enum_values(OLD_ORDER_STATUSES)}) "
                f"NOT NULL{_mysql_default_sql(column, OLD_ORDER_STATUSES)}"
            )
        )
