"""Add maintenance run and error log tables.

Revision ID: f1c2d3e4f5a6
Revises: e3b8a4c9f2d1
Create Date: 2026-02-22 19:40:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f1c2d3e4f5a6"
down_revision = "e3b8a4c9f2d1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "maintenance_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("result_counts", sa.JSON(), nullable=True),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_maintenance_runs_mode"), "maintenance_runs", ["mode"], unique=False)
    op.create_index(op.f("ix_maintenance_runs_started_at"), "maintenance_runs", ["started_at"], unique=False)
    op.create_index(op.f("ix_maintenance_runs_finished_at"), "maintenance_runs", ["finished_at"], unique=False)

    op.create_table(
        "error_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=True),
        sa.Column("method", sa.String(length=16), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("short_message", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_error_logs_status_code"), "error_logs", ["status_code"], unique=False)
    op.create_index(op.f("ix_error_logs_created_at"), "error_logs", ["created_at"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_error_logs_created_at"), table_name="error_logs")
    op.drop_index(op.f("ix_error_logs_status_code"), table_name="error_logs")
    op.drop_table("error_logs")

    op.drop_index(op.f("ix_maintenance_runs_finished_at"), table_name="maintenance_runs")
    op.drop_index(op.f("ix_maintenance_runs_started_at"), table_name="maintenance_runs")
    op.drop_index(op.f("ix_maintenance_runs_mode"), table_name="maintenance_runs")
    op.drop_table("maintenance_runs")
