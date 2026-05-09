from datetime import datetime, timedelta

from ..extensions import db


DEFAULT_RENTAL_MONTHLY_DURATION_DAYS = 14
DEFAULT_RENTAL_DAILY_DURATION_DAYS = 14
RENTAL_LISTING_DURATION_DAYS = DEFAULT_RENTAL_MONTHLY_DURATION_DAYS


def _safe_duration_days(raw_value, fallback: int) -> int:
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        parsed = int(fallback)
    return max(1, min(3650, parsed))


def rental_duration_days_for_type(listing_type: str | None, settings=None) -> int:
    kind = (listing_type or "").strip().lower()

    if settings is None:
        try:
            from .platform_settings import PlatformSettings

            settings = PlatformSettings.get()
        except Exception:
            settings = None

    if kind == "daily":
        raw_days = getattr(settings, "rental_daily_duration_days", DEFAULT_RENTAL_DAILY_DURATION_DAYS)
        return _safe_duration_days(raw_days, DEFAULT_RENTAL_DAILY_DURATION_DAYS)

    raw_days = getattr(settings, "rental_monthly_duration_days", DEFAULT_RENTAL_MONTHLY_DURATION_DAYS)
    return _safe_duration_days(raw_days, DEFAULT_RENTAL_MONTHLY_DURATION_DAYS)


def _default_expires_at():
    return datetime.utcnow() + timedelta(days=rental_duration_days_for_type("monthly"))


class RentalListing(db.Model):
    __tablename__ = "rental_listing"

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", name="fk_rentallisting_owner_id"),
        nullable=False,
        index=True,
    )
    shop_id = db.Column(
        db.Integer,
        db.ForeignKey("shop.id", name="fk_rentallisting_shop_id"),
        nullable=False,
        index=True,
    )

    title = db.Column(db.String(180), nullable=False)
    slug = db.Column(db.String(220), nullable=False, unique=True, index=True)
    description = db.Column(db.Text, nullable=False)

    listing_type = db.Column(db.String(20), nullable=False, default="monthly", index=True)  # monthly|daily
    property_type = db.Column(db.String(30), nullable=False, default="apartment")  # room|apartment|studio|store

    city = db.Column(db.String(120), nullable=False, index=True)
    area = db.Column(db.String(120), nullable=True)

    rent_cents = db.Column(db.Integer, nullable=False, default=0)
    currency = db.Column(db.String(3), nullable=False, default="MAD")

    deposit_cents = db.Column(db.Integer, nullable=True)
    deposit_required = db.Column(db.Boolean, nullable=False, default=False)

    owner_fee_cents = db.Column(db.Integer, nullable=True)
    owner_fee_text = db.Column(db.String(255), nullable=True)
    owner_fee_negotiable = db.Column(db.Boolean, nullable=False, default=False)

    platform_commission_mode = db.Column(db.String(30), nullable=False, default="success_commission")  # success_commission only
    platform_commission_rate_bps = db.Column(db.Integer, nullable=False, default=0)  # ex: 1000 => 10%
    platform_commission_fixed_cents = db.Column(db.Integer, nullable=True)

    status = db.Column(db.String(20), nullable=False, default="active", index=True)  # active|reserved|taken|expired|archived
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False, default=_default_expires_at, index=True)

    view_count = db.Column(db.Integer, nullable=False, default=0)
    last_viewed_at = db.Column(db.DateTime, nullable=True)

    owner = db.relationship("User", backref="rental_listings")
    shop = db.relationship("Shop", backref="rental_listings")
    media = db.relationship("RentalMedia", back_populates="listing", cascade="all, delete-orphan", lazy=True)

    __table_args__ = (
        db.CheckConstraint("rent_cents >= 0", name="ck_rentallisting_rent_non_negative"),
        db.CheckConstraint(
            "deposit_cents IS NULL OR deposit_cents >= 0",
            name="ck_rentallisting_deposit_non_negative",
        ),
        db.CheckConstraint(
            "owner_fee_cents IS NULL OR owner_fee_cents >= 0",
            name="ck_rentallisting_owner_fee_non_negative",
        ),
        db.CheckConstraint(
            "platform_commission_rate_bps >= 0",
            name="ck_rentallisting_platform_rate_non_negative",
        ),
        db.CheckConstraint(
            "platform_commission_fixed_cents IS NULL OR platform_commission_fixed_cents >= 0",
            name="ck_rentallisting_platform_fixed_non_negative",
        ),
        db.CheckConstraint("view_count >= 0", name="ck_rentallisting_views_non_negative"),
        db.Index("ix_rental_listing_shop_status", "shop_id", "status"),
        db.Index("ix_rental_listing_created_id", "created_at", "id"),
        db.Index("ix_rental_listing_status_created", "status", "created_at"),
        db.Index("ix_rental_listing_owner_created", "owner_id", "created_at"),
    )

    def mark_view(self):
        self.view_count = int(self.view_count or 0) + 1
        self.last_viewed_at = datetime.utcnow()


class RentalMedia(db.Model):
    __tablename__ = "rental_media"

    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(
        db.Integer,
        db.ForeignKey("rental_listing.id", name="fk_rentalmedia_listing_id"),
        nullable=False,
        index=True,
    )
    kind = db.Column(db.String(10), nullable=False)  # image|video
    file_path = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    listing = db.relationship("RentalListing", back_populates="media")

    __table_args__ = (
        db.CheckConstraint("kind IN ('image','video')", name="ck_rentalmedia_kind"),
    )


class RentalArchive(db.Model):
    __tablename__ = "rental_archive"

    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, nullable=True, index=True)
    owner_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", name="fk_rentalarchive_owner_id"),
        nullable=False,
        index=True,
    )
    shop_id = db.Column(
        db.Integer,
        db.ForeignKey("shop.id", name="fk_rentalarchive_shop_id"),
        nullable=False,
        index=True,
    )

    title = db.Column(db.String(180), nullable=False)
    slug = db.Column(db.String(220), nullable=True, index=True)
    city = db.Column(db.String(120), nullable=False, index=True)
    area = db.Column(db.String(120), nullable=True)
    listing_type = db.Column(db.String(20), nullable=False, index=True)
    property_type = db.Column(db.String(30), nullable=False)

    rent_cents = db.Column(db.Integer, nullable=False, default=0)
    currency = db.Column(db.String(3), nullable=False, default="MAD")
    deposit_cents = db.Column(db.Integer, nullable=True)
    owner_fee_cents = db.Column(db.Integer, nullable=True)
    owner_fee_text = db.Column(db.String(255), nullable=True)
    owner_fee_negotiable = db.Column(db.Boolean, nullable=False, default=False)
    platform_commission_rate_bps = db.Column(db.Integer, nullable=False, default=0)
    platform_commission_fixed_cents = db.Column(db.Integer, nullable=False, default=0)
    platform_commission_amount_cents = db.Column(db.Integer, nullable=False, default=0)

    archived_view_count = db.Column(db.Integer, nullable=False, default=0)

    closed_reason = db.Column(db.String(30), nullable=False, index=True)  # taken|expired|deleted_by_owner|deleted_by_admin
    closed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    created_at_original = db.Column(db.DateTime, nullable=True)
    expires_at_original = db.Column(db.DateTime, nullable=True)
    archive_delete_after = db.Column(db.DateTime, nullable=True, index=True)

    owner = db.relationship("User", backref="rental_archives")
    shop = db.relationship("Shop", backref="rental_archives")

    __table_args__ = (
        db.CheckConstraint("rent_cents >= 0", name="ck_rentalarchive_rent_non_negative"),
        db.CheckConstraint(
            "deposit_cents IS NULL OR deposit_cents >= 0",
            name="ck_rentalarchive_deposit_non_negative",
        ),
        db.CheckConstraint(
            "owner_fee_cents IS NULL OR owner_fee_cents >= 0",
            name="ck_rentalarchive_owner_fee_non_negative",
        ),
        db.CheckConstraint(
            "platform_commission_rate_bps >= 0",
            name="ck_rentalarchive_platform_rate_non_negative",
        ),
        db.CheckConstraint(
            "platform_commission_fixed_cents >= 0",
            name="ck_rentalarchive_platform_fixed_non_negative",
        ),
        db.CheckConstraint(
            "platform_commission_amount_cents >= 0",
            name="ck_rentalarchive_platform_amount_non_negative",
        ),
        db.CheckConstraint(
            "archived_view_count >= 0",
            name="ck_rentalarchive_views_non_negative",
        ),
        db.Index("ix_rental_archive_closed_id", "closed_at", "id"),
        db.Index("ix_rental_archive_reason_closed", "closed_reason", "closed_at"),
        db.Index("ix_rental_archive_owner_closed", "owner_id", "closed_at"),
        db.Index("ix_rental_archive_owner_reason_closed", "owner_id", "closed_reason", "closed_at"),
    )

