"""enforce unique pending vendor requests

Revision ID: a91d6f0b3e2c
Revises: f2b9c1d4a7e0
Create Date: 2026-05-07 19:35:00.000000
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "a91d6f0b3e2c"
down_revision = "f2b9c1d4a7e0"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    dialect_name = (bind.dialect.name or "").lower()

    if dialect_name in {"sqlite", "postgresql"}:
        op.execute(
            """
            UPDATE vendor_application
            SET
                status = 'rejected',
                review_note = CASE
                    WHEN COALESCE(review_note, '') = ''
                        THEN 'Auto-rejet technique: doublon pending (phone).'
                    ELSE review_note || ' | Auto-rejet technique: doublon pending (phone).'
                END,
                reviewed_at = COALESCE(reviewed_at, CURRENT_TIMESTAMP)
            WHERE id IN (
                SELECT older.id
                FROM vendor_application AS older
                JOIN vendor_application AS newer
                    ON older.phone_digits = newer.phone_digits
                   AND older.status = 'pending'
                   AND newer.status = 'pending'
                   AND older.id < newer.id
            )
            """
        )
        op.execute(
            """
            UPDATE vendor_application
            SET
                status = 'rejected',
                review_note = CASE
                    WHEN COALESCE(review_note, '') = ''
                        THEN 'Auto-rejet technique: doublon pending (email).'
                    ELSE review_note || ' | Auto-rejet technique: doublon pending (email).'
                END,
                reviewed_at = COALESCE(reviewed_at, CURRENT_TIMESTAMP)
            WHERE id IN (
                SELECT older.id
                FROM vendor_application AS older
                JOIN vendor_application AS newer
                    ON older.email_normalized = newer.email_normalized
                   AND older.email_normalized IS NOT NULL
                   AND newer.email_normalized IS NOT NULL
                   AND older.status = 'pending'
                   AND newer.status = 'pending'
                   AND older.id < newer.id
            )
            """
        )

        op.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_vendor_application_pending_phone
            ON vendor_application (phone_digits)
            WHERE status = 'pending'
            """
        )
        op.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_vendor_application_pending_email
            ON vendor_application (email_normalized)
            WHERE status = 'pending' AND email_normalized IS NOT NULL
            """
        )


def downgrade():
    bind = op.get_bind()
    dialect_name = (bind.dialect.name or "").lower()
    if dialect_name in {"sqlite", "postgresql"}:
        op.execute("DROP INDEX IF EXISTS uq_vendor_application_pending_phone")
        op.execute("DROP INDEX IF EXISTS uq_vendor_application_pending_email")
