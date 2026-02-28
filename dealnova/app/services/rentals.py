import os
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta
from typing import Iterable

from flask import current_app
from PIL import Image, ImageOps
from werkzeug.datastructures import FileStorage

from ..extensions import db
from ..models.rental import RentalArchive, RentalListing, RentalMedia
from .financial_periods import record_rental_commission_entry


RENTAL_UPLOAD_DIR = "uploads/rentals"
MAX_IMAGE_COUNT = 4
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_VIDEO_BYTES = 30 * 1024 * 1024
ARCHIVE_RETENTION_DAYS = 30
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
VIDEO_EXTENSIONS = {"mp4", "mov", "webm", "m4v", "avi", "mkv", "3gp", "mpeg", "mpg", "wmv", "flv"}


def cents_to_dh(cents: int | None) -> str:
    amount = int(cents or 0) / 100
    if abs(amount - int(amount)) < 1e-9:
        return f"{int(amount)} DH"
    return f"{amount:.2f} DH"


def commission_amount_from_owner_fee(owner_fee_cents: int | None, rate_bps: int | None) -> int:
    owner_fee_value = int(owner_fee_cents or 0)
    rate_value = int(rate_bps or 0)
    if owner_fee_value <= 0 or rate_value <= 0:
        return 0
    return max(0, int(round((owner_fee_value * rate_value) / 10000.0)))


def _extension(filename: str) -> str:
    if "." not in (filename or ""):
        return ""
    return filename.rsplit(".", 1)[1].lower().strip()


def _file_size(file_obj: FileStorage) -> int:
    try:
        current = file_obj.stream.tell()
        file_obj.stream.seek(0, os.SEEK_END)
        size = int(file_obj.stream.tell() or 0)
        file_obj.stream.seek(current)
        return size
    except Exception:
        return 0


def _rental_abs_dir() -> str:
    abs_dir = os.path.join(current_app.static_folder, "uploads", "rentals")
    os.makedirs(abs_dir, exist_ok=True)
    return abs_dir


def _relative_rental_path(filename: str) -> str:
    return f"{RENTAL_UPLOAD_DIR}/{filename}"


def save_rental_image(file_obj: FileStorage) -> str:
    size = _file_size(file_obj)
    if size and size > MAX_IMAGE_BYTES:
        raise ValueError("Image trop lourde (max 12MB).")

    abs_dir = _rental_abs_dir()
    filename = f"{uuid.uuid4().hex}.webp"
    abs_path = os.path.join(abs_dir, filename)

    try:
        file_obj.stream.seek(0)
        with Image.open(file_obj.stream) as image:
            image = ImageOps.exif_transpose(image)
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGB")
            if image.mode == "RGBA":
                image = image.convert("RGB")
            image.thumbnail((1920, 1920), Image.LANCZOS)
            image.save(abs_path, "WEBP", quality=84, method=6)
    except Exception as exc:
        raise ValueError("Image invalide ou non lisible.") from exc

    return _relative_rental_path(filename)


def save_rental_video(file_obj: FileStorage) -> str:
    ext = _extension(file_obj.filename or "")
    if ext not in VIDEO_EXTENSIONS:
        raise ValueError("Format video non supporte (mp4, mov, webm, m4v, avi).")

    original_size = _file_size(file_obj)
    if original_size and original_size > MAX_VIDEO_BYTES:
        raise ValueError("Video trop lourde (max 30MB).")

    abs_dir = _rental_abs_dir()
    base_name = f"{uuid.uuid4().hex}"
    source_filename = f"{base_name}.{ext}"
    source_abs = os.path.join(abs_dir, source_filename)

    file_obj.stream.seek(0)
    file_obj.save(source_abs)

    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        return _relative_rental_path(source_filename)

    compressed_filename = f"{base_name}.mp4"
    compressed_abs = os.path.join(abs_dir, compressed_filename)

    try:
        result = subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-i",
                source_abs,
                "-vcodec",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "30",
                "-acodec",
                "aac",
                "-movflags",
                "+faststart",
                compressed_abs,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0 or not os.path.exists(compressed_abs):
            return _relative_rental_path(source_filename)

        if os.path.getsize(compressed_abs) > MAX_VIDEO_BYTES:
            os.remove(compressed_abs)
            return _relative_rental_path(source_filename)

        os.remove(source_abs)
        return _relative_rental_path(compressed_filename)
    except Exception:
        return _relative_rental_path(source_filename)


def static_abs_path(relative_path: str) -> str:
    safe_rel = (relative_path or "").replace("\\", "/").lstrip("/")
    return os.path.abspath(os.path.join(current_app.static_folder, safe_rel))


def delete_static_file(relative_path: str) -> bool:
    if not relative_path:
        return False
    abs_path = static_abs_path(relative_path)
    static_root = os.path.abspath(current_app.static_folder)
    if not abs_path.startswith(static_root):
        return False
    if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
        return False
    try:
        os.remove(abs_path)
        return True
    except Exception:
        return False


def archive_listing(listing: RentalListing, closed_reason: str, closed_at: datetime | None = None) -> RentalArchive:
    closed_time = closed_at or datetime.utcnow()
    rate_bps = int(listing.platform_commission_rate_bps or 0)
    commission_amount_cents = commission_amount_from_owner_fee(listing.owner_fee_cents, rate_bps)
    archive = RentalArchive(
        listing_id=listing.id,
        owner_id=listing.owner_id,
        shop_id=listing.shop_id,
        title=listing.title,
        slug=listing.slug,
        city=listing.city,
        area=listing.area,
        listing_type=listing.listing_type,
        property_type=listing.property_type,
        rent_cents=listing.rent_cents,
        currency=listing.currency or "MAD",
        deposit_cents=listing.deposit_cents,
        owner_fee_cents=listing.owner_fee_cents,
        owner_fee_text=listing.owner_fee_text,
        owner_fee_negotiable=bool(listing.owner_fee_negotiable),
        platform_commission_rate_bps=rate_bps,
        platform_commission_fixed_cents=0,
        platform_commission_amount_cents=commission_amount_cents,
        archived_view_count=int(listing.view_count or 0),
        closed_reason=closed_reason,
        closed_at=closed_time,
        created_at_original=listing.created_at,
        expires_at_original=listing.expires_at,
        archive_delete_after=closed_time + timedelta(days=ARCHIVE_RETENTION_DAYS),
    )
    db.session.add(archive)
    record_rental_commission_entry(archive, note="rental listing closed as taken")
    return archive




def _delete_media_rows(media_rows: Iterable[RentalMedia]) -> int:
    removed_files = 0
    for media in media_rows:
        if delete_static_file(media.file_path):
            removed_files += 1
        db.session.delete(media)
    return removed_files


def archive_and_remove_listing(listing: RentalListing, closed_reason: str) -> dict:
    archive_listing(listing, closed_reason=closed_reason)
    media_rows = list(listing.media or [])
    removed_files = _delete_media_rows(media_rows)
    db.session.delete(listing)
    return {"removed_files": removed_files, "media_count": len(media_rows)}


def cleanup_orphan_rental_media_files() -> int:
    abs_dir = _rental_abs_dir()
    used_rel_paths = {
        (row.file_path or "").replace("\\", "/").lstrip("/")
        for row in RentalMedia.query.with_entities(RentalMedia.file_path).all()
    }
    removed = 0
    for name in os.listdir(abs_dir):
        abs_path = os.path.join(abs_dir, name)
        if not os.path.isfile(abs_path):
            continue
        rel_path = _relative_rental_path(name).replace("\\", "/").lstrip("/")
        if rel_path in used_rel_paths:
            continue
        try:
            os.remove(abs_path)
            removed += 1
        except Exception:
            continue
    return removed


def cleanup_expired_rentals(now: datetime | None = None, include_archive_purge: bool = True) -> dict:
    current_time = now or datetime.utcnow()
    to_archive = (
        RentalListing.query
        .filter(RentalListing.is_active == True)
        .filter(
            (RentalListing.expires_at <= current_time)
            | (RentalListing.status.in_(["taken", "expired"]))
        )
        .all()
    )

    archived_count = 0
    removed_media_files = 0

    for listing in to_archive:
        reason = "expired" if listing.expires_at and listing.expires_at <= current_time else (listing.status or "expired")
        if reason not in {"taken", "expired", "deleted_by_owner", "deleted_by_admin"}:
            reason = "expired"
        result = archive_and_remove_listing(listing, closed_reason=reason)
        archived_count += 1
        removed_media_files += int(result.get("removed_files") or 0)

    deleted_archives = 0
    if include_archive_purge:
        archive_cutoff = current_time - timedelta(days=ARCHIVE_RETENTION_DAYS)
        old_archives = (
            RentalArchive.query
            .filter(RentalArchive.closed_at <= archive_cutoff)
            .all()
        )
        deleted_archives = len(old_archives)
        for archive in old_archives:
            db.session.delete(archive)

    db.session.commit()

    orphan_removed = cleanup_orphan_rental_media_files()
    return {
        "archived_count": archived_count,
        "removed_media_files": removed_media_files,
        "purged_archives": deleted_archives,
        "orphan_media_removed": orphan_removed,
    }

