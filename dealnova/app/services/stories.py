"""Service to generate Discovery Stories & Video Feed for the homepage."""
from __future__ import annotations

import os
from datetime import datetime
from urllib.parse import quote

from flask import current_app, url_for
from sqlalchemy import or_, select

from ..extensions import db
from ..models.product import Product
from ..models.promo import Promo
from ..models.rental import RentalListing, RentalMedia
from ..models.shop import Shop
from .cache import get_catalog_cache
from .public_catalog import _image_url, _product_video_url


def _clean_phone(raw_phone: str | None) -> str:
    phone = "".join(c for c in str(raw_phone or "") if c.isdigit())
    if phone.startswith("0") and len(phone) == 10:
        phone = "212" + phone[1:]
    return phone or "212771182279"


def _whatsapp_link(phone: str, message: str) -> str:
    return f"https://wa.me/{phone}?text={quote(message)}"


def _resolve_product_thumb(prod: Product) -> str:
    """Return a valid product thumbnail that is guaranteed to exist on disk."""
    static_folder = current_app.static_folder or ""
    uploads_dir = os.path.join(static_folder, "uploads")
    photos = [p.strip() for p in (prod.image_file or "").split("|") if p.strip()]
    for p in photos:
        clean = p.replace("\\", "/").lstrip("/")
        if clean.startswith("uploads/"):
            clean = clean[8:]
        if os.path.isfile(os.path.join(uploads_dir, clean)):
            return _image_url(p)
    # Check shop logo
    if prod.shop and prod.shop.logo:
        logo_clean = prod.shop.logo.replace("\\", "/").lstrip("/")
        if logo_clean.startswith("uploads/"):
            logo_clean = logo_clean[8:]
        if os.path.isfile(os.path.join(uploads_dir, logo_clean)):
            return _image_url(prod.shop.logo, shop=True)
    # Known reliable sample images
    for fallback in ("30b87538e2c4494a8fed888c44a822ca.jpg", "06006997b0ac4bfa93566181f50bf3f3.webp", "a9407317efe148b6b011d39b21652a86.jpeg"):
        if os.path.isfile(os.path.join(uploads_dir, fallback)):
            return url_for("static", filename=f"uploads/{fallback}")
    return url_for("static", filename="images/produit.jpeg")


def _resolve_rental_thumb(listing: RentalListing) -> str:
    """Return a valid rental thumbnail that is guaranteed to exist on disk."""
    static_folder = current_app.static_folder or ""
    rentals_dir = os.path.join(static_folder, "uploads", "rentals")
    for m in getattr(listing, "media", []):
        if m.kind == "image" and m.file_path:
            clean = m.file_path.replace("\\", "/").lstrip("/")
            if clean.startswith("uploads/"):
                clean = clean[8:]
            if clean.startswith("rentals/"):
                clean = clean[8:]
            if os.path.isfile(os.path.join(rentals_dir, clean)):
                return _image_url(m.file_path, rental=True)
    if listing.shop and listing.shop.logo:
        logo_clean = listing.shop.logo.replace("\\", "/").lstrip("/")
        if logo_clean.startswith("uploads/"):
            logo_clean = logo_clean[8:]
        if os.path.isfile(os.path.join(static_folder, "uploads", logo_clean)):
            return _image_url(listing.shop.logo, shop=True)
    fallback = os.path.join(rentals_dir, "384fcb07977a4df4992bc858206b7f10.webp")
    if os.path.isfile(fallback):
        return url_for("static", filename="uploads/rentals/384fcb07977a4df4992bc858206b7f10.webp")
    return url_for("static", filename="images/home-refresh/hero.webp")


def build_homepage_stories() -> list[dict]:
    """Retrieve up to 15 highlighted stories (videos, top promotions, featured boutiques)."""
    stories = []
    seen_ids = set()

    # 1. Products with Videos (Top priority for engagement)
    try:
        video_products = (
            Product.query.filter(
                Product.is_active == True,
                Product.video_file.isnot(None),
                Product.video_file != "",
            )
            .order_by(Product.id.desc())
            .limit(6)
            .all()
        )
        for prod in video_products:
            vid_url = _product_video_url(prod.video_file)
            if not vid_url:
                continue
            thumb = _resolve_product_thumb(prod)
            shop = prod.shop
            shop_name = shop.name if shop else "Baba Market"
            phone = _clean_phone(getattr(shop, "whatsapp_phone", None) or getattr(shop, "phone", None))
            price_dh = f"{prod.price:.0f} DH" if prod.price else ""
            msg = f"Bonjour, j'ai vu votre vidéo sur la story Baba Market pour « {prod.name} » ({price_dh}). Est-il toujours disponible ?"
            
            stories.append({
                "id": f"vid_prod_{prod.id}",
                "title": prod.name,
                "label": "Vidéo 24h",
                "has_video": True,
                "is_promo": False,
                "thumbnail_url": thumb,
                "media_url": vid_url,
                "media_type": "video",
                "price": price_dh,
                "original_price": "",
                "shop_name": shop_name,
                "shop_logo": _image_url(shop.logo, shop=True) if (shop and shop.logo) else "",
                "whatsapp_url": _whatsapp_link(phone, msg),
                "detail_url": url_for("shop.product_detail", pid=prod.id),
            })
            seen_ids.add(f"prod_{prod.id}")
    except Exception as exc:
        current_app.logger.warning("stories video_products query failed: %s", exc)
        try:
            db.session.rollback()
        except Exception:
            pass

    # 2. Locations with Videos
    try:
        now = datetime.utcnow()
        rental_video_rows = (
            db.session.query(RentalListing, RentalMedia)
            .join(RentalMedia, RentalListing.id == RentalMedia.listing_id)
            .filter(
                RentalListing.status == "active",
                RentalMedia.kind == "video",
                RentalMedia.file_path.isnot(None),
                RentalMedia.file_path != "",
            )
            .order_by(RentalListing.id.desc())
            .limit(4)
            .all()
        )
        for listing, media in rental_video_rows:
            vid_url = _image_url(media.file_path, rental=True)
            if not vid_url:
                continue
            thumb = _resolve_rental_thumb(listing)
            phone = _clean_phone(getattr(listing, "contact_phone", None))
            rent_cents = getattr(listing, "rent_cents", None) or 0
            price_dh = f"{rent_cents / 100:.0f} DH" if rent_cents else ""
            msg = f"Bonjour, j'ai vu votre vidéo de location sur Baba Market : « {listing.title} » ({price_dh}). Est-ce toujours disponible ?"

            stories.append({
                "id": f"vid_rent_{listing.id}",
                "title": listing.title,
                "label": "Visite vidéo",
                "has_video": True,
                "is_promo": False,
                "thumbnail_url": thumb,
                "media_url": vid_url,
                "media_type": "video",
                "price": price_dh,
                "original_price": "",
                "shop_name": listing.shop.name if listing.shop else (listing.city or "Location"),
                "shop_logo": _image_url(listing.shop.logo, shop=True) if (listing.shop and listing.shop.logo) else "",
                "whatsapp_url": _whatsapp_link(phone, msg),
                "detail_url": url_for("rentals.location_detail", slug=listing.slug),
            })
    except Exception as exc:
        current_app.logger.warning("stories rental_video_rows query failed: %s", exc)
        try:
            db.session.rollback()
        except Exception:
            pass

    # 3. Active Promotions (Products with active Promo)
    try:
        now = datetime.utcnow()
        promo_rows = (
            db.session.query(Product, Promo)
            .join(Promo, Product.id == Promo.product_id)
            .filter(
                Product.is_active == True,
                Promo.status == "approved",
                Promo.end_date >= now,
            )
            .order_by(Promo.id.desc())
            .limit(8)
            .all()
        )
        for prod, promo in promo_rows:
            if f"prod_{prod.id}" in seen_ids:
                continue
            thumb = _resolve_product_thumb(prod)
            shop = prod.shop
            shop_name = shop.name if shop else "Baba Market"
            phone = _clean_phone(getattr(shop, "whatsapp_phone", None) or getattr(shop, "phone", None))
            
            # Discount calculation
            orig_price = prod.price or 0.0
            val = float(promo.value or 0)
            if promo.type == "percentage" and val > 0:
                final_price = max(0.0, orig_price * (1.0 - (val / 100.0)))
                tag = f"-{int(val)}%"
            elif val > 0:
                final_price = max(0.0, orig_price - val)
                tag = f"-{val:.0f} DH"
            else:
                final_price = orig_price
                tag = "Promo"

            msg = f"Bonjour, j'ai vu la promotion « {prod.name} » à {final_price:.0f} DH au lieu de {orig_price:.0f} DH sur Baba Market. Je souhaite commander !"

            stories.append({
                "id": f"promo_prod_{prod.id}",
                "title": prod.name,
                "label": tag,
                "has_video": False,
                "is_promo": True,
                "thumbnail_url": thumb,
                "media_url": thumb,
                "media_type": "image",
                "price": f"{final_price:.0f} DH",
                "original_price": f"{orig_price:.0f} DH",
                "shop_name": shop_name,
                "shop_logo": _image_url(shop.logo, shop=True) if (shop and shop.logo) else "",
                "whatsapp_url": _whatsapp_link(phone, msg),
                "detail_url": url_for("shop.product_detail", pid=prod.id),
            })
            seen_ids.add(f"prod_{prod.id}")
    except Exception as exc:
        current_app.logger.warning("stories promo_rows query failed: %s", exc)
        try:
            db.session.rollback()
        except Exception:
            pass

    # 4. Verified/Featured Shops with logo if needed to complete the bar
    if len(stories) < 6:
        try:
            shops = (
                Shop.query.filter(
                    Shop.is_active == True,
                    Shop.logo.isnot(None),
                    Shop.logo != "",
                )
                .order_by(Shop.id.desc())
                .limit(6)
                .all()
            )
            for s in shops:
                logo_url = _image_url(s.logo, shop=True)
                banner_url = _image_url(s.banner, shop=True) if s.banner else logo_url
                phone = _clean_phone(getattr(s, "whatsapp_phone", None) or getattr(s, "phone", None))
                msg = f"Bonjour, j'ai découvert votre boutique « {s.name} » sur Baba Market !"
                stories.append({
                    "id": f"shop_{s.id}",
                    "title": s.name,
                    "label": "Boutique",
                    "has_video": False,
                    "is_promo": False,
                    "thumbnail_url": logo_url,
                    "media_url": banner_url,
                    "media_type": "image",
                    "price": "",
                    "original_price": "",
                    "shop_name": s.name,
                    "shop_logo": logo_url,
                    "whatsapp_url": _whatsapp_link(phone, msg),
                    "detail_url": url_for("shops.shop_detail", shop_slug=s.slug),
                })
        except Exception as exc:
            current_app.logger.warning("stories shops query failed: %s", exc)
            try:
                db.session.rollback()
            except Exception:
                pass

    return stories[:15]


def get_homepage_stories() -> list[dict]:
    """Cache stories for 90 seconds."""
    try:
        return get_catalog_cache("homepage:stories:v4", build_homepage_stories, timeout=90)
    except Exception as exc:
        current_app.logger.error("get_homepage_stories cache error: %s", exc)
        try:
            db.session.rollback()
        except Exception:
            pass
        return build_homepage_stories()
