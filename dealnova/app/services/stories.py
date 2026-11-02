"""Service to generate Discovery Stories & Video Feed for the homepage."""
from __future__ import annotations

import os
import random
from datetime import datetime, timedelta
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


def _format_product_story(prod: Product, is_24h: bool) -> dict | None:
    vid_url = _product_video_url(prod.video_file) if prod.video_file else ""
    thumb = _resolve_product_thumb(prod)
    shop = prod.shop
    shop_name = shop.name if shop else "Baba Market"
    phone = _clean_phone(getattr(shop, "whatsapp_phone", None) or getattr(shop, "phone", None))
    price_dh = f"{prod.price:.0f} DH" if prod.price else ""
    has_video = bool(vid_url)
    media_url = vid_url if has_video else thumb
    media_type = "video" if has_video else "image"
    label = "Vidéo 24h" if has_video else ("Nouveau 24h" if is_24h else "Nouveau")
    msg = f"Bonjour, j'ai vu votre story Baba Market pour « {prod.name} » ({price_dh}). Est-il toujours disponible ?"
    return {
        "id": f"{'vid_' if has_video else ''}prod_{prod.id}",
        "title": prod.name,
        "label": label,
        "has_video": has_video,
        "is_promo": False,
        "thumbnail_url": thumb,
        "media_url": media_url,
        "media_type": media_type,
        "price": price_dh,
        "original_price": "",
        "shop_name": shop_name,
        "shop_logo": _image_url(shop.logo, shop=True) if (shop and shop.logo) else "",
        "whatsapp_url": _whatsapp_link(phone, msg),
        "detail_url": url_for("shop.product_detail", pid=prod.id),
    }


def _format_rental_story(listing: RentalListing, media: RentalMedia | None, is_24h: bool) -> dict | None:
    vid_url = _image_url(media.file_path, rental=True) if (media and media.kind == "video") else ""
    thumb = _resolve_rental_thumb(listing)
    phone = _clean_phone(getattr(listing, "contact_phone", None))
    rent_cents = getattr(listing, "rent_cents", None) or 0
    price_dh = f"{rent_cents / 100:.0f} DH" if rent_cents else ""
    has_video = bool(vid_url)
    media_url = vid_url if has_video else thumb
    media_type = "video" if has_video else "image"
    label = "Visite vidéo" if has_video else ("Location 24h" if is_24h else "Location")
    msg = f"Bonjour, j'ai vu votre story de location sur Baba Market : « {listing.title} » ({price_dh}). Est-ce toujours disponible ?"
    return {
        "id": f"{'vid_' if has_video else ''}rent_{listing.id}",
        "title": listing.title,
        "label": label,
        "has_video": has_video,
        "is_promo": False,
        "thumbnail_url": thumb,
        "media_url": media_url,
        "media_type": media_type,
        "price": price_dh,
        "original_price": "",
        "shop_name": listing.shop.name if listing.shop else (listing.city or "Location"),
        "shop_logo": _image_url(listing.shop.logo, shop=True) if (listing.shop and listing.shop.logo) else "",
        "whatsapp_url": _whatsapp_link(phone, msg),
        "detail_url": url_for("rentals.location_detail", slug=listing.slug),
    }


def _format_promo_story(prod: Product, promo: Promo, is_24h: bool) -> dict | None:
    thumb = _resolve_product_thumb(prod)
    shop = prod.shop
    shop_name = shop.name if shop else "Baba Market"
    phone = _clean_phone(getattr(shop, "whatsapp_phone", None) or getattr(shop, "phone", None))
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
        tag = "Promo 24h" if is_24h else "Promo"

    msg = f"Bonjour, j'ai vu la promotion « {prod.name} » à {final_price:.0f} DH au lieu de {orig_price:.0f} DH sur Baba Market. Je souhaite commander !"
    return {
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
    }


def build_homepage_stories_pool() -> dict:
    """Retrieve pool of 24h prioritized publications and recent fallback publications."""
    now = datetime.utcnow()
    cutoff_24h = now - timedelta(hours=24)
    stories_24h = []
    stories_recent = []
    seen_24h = set()
    seen_recent = set()

    # ==========================================
    # 1. PUBLICATIONS DES DERNIÈRES 24 HEURES (PRIORITÉ)
    # ==========================================

    # 1a. Produits avec vidéo publiés dans les 24h
    try:
        vp_24h = (
            Product.query.filter(
                Product.is_active == True,
                Product.video_file.isnot(None),
                Product.video_file != "",
                Product.created_at >= cutoff_24h,
            )
            .order_by(Product.id.desc())
            .limit(25)
            .all()
        )
        for p in vp_24h:
            item = _format_product_story(p, is_24h=True)
            if item and item["id"] not in seen_24h:
                stories_24h.append(item)
                seen_24h.add(item["id"])
    except Exception as exc:
        current_app.logger.warning("stories vp_24h failed: %s", exc)
        try:
            db.session.rollback()
        except Exception:
            pass

    # 1b. Locations avec vidéo publiées dans les 24h
    try:
        rv_24h = (
            db.session.query(RentalListing, RentalMedia)
            .join(RentalMedia, RentalListing.id == RentalMedia.listing_id)
            .filter(
                RentalListing.status == "active",
                RentalMedia.kind == "video",
                RentalMedia.file_path.isnot(None),
                RentalMedia.file_path != "",
                RentalListing.created_at >= cutoff_24h,
            )
            .order_by(RentalListing.id.desc())
            .limit(15)
            .all()
        )
        for listing, media in rv_24h:
            item = _format_rental_story(listing, media, is_24h=True)
            if item and item["id"] not in seen_24h:
                stories_24h.append(item)
                seen_24h.add(item["id"])
    except Exception as exc:
        current_app.logger.warning("stories rv_24h failed: %s", exc)
        try:
            db.session.rollback()
        except Exception:
            pass

    # 1c. Promotions actives créées dans les 24h
    try:
        pr_24h = (
            db.session.query(Product, Promo)
            .join(Promo, Product.id == Promo.product_id)
            .filter(
                Product.is_active == True,
                Promo.status == "approved",
                Promo.end_date >= now,
                Promo.created_at >= cutoff_24h,
            )
            .order_by(Promo.id.desc())
            .limit(25)
            .all()
        )
        for p, promo in pr_24h:
            item = _format_promo_story(p, promo, is_24h=True)
            if item and item["id"] not in seen_24h:
                stories_24h.append(item)
                seen_24h.add(item["id"])
    except Exception as exc:
        current_app.logger.warning("stories pr_24h failed: %s", exc)
        try:
            db.session.rollback()
        except Exception:
            pass

    # 1d. Tous les autres produits actifs publiés dans les dernières 24h (jusqu'à 50 articles)
    try:
        all_p_24h = (
            Product.query.filter(
                Product.is_active == True,
                Product.created_at >= cutoff_24h,
            )
            .order_by(Product.id.desc())
            .limit(50)
            .all()
        )
        for p in all_p_24h:
            item = _format_product_story(p, is_24h=True)
            if item and item["id"] not in seen_24h:
                stories_24h.append(item)
                seen_24h.add(item["id"])
    except Exception as exc:
        current_app.logger.warning("stories all_p_24h failed: %s", exc)
        try:
            db.session.rollback()
        except Exception:
            pass

    # 1e. Annonces de location publiées dans les 24h
    try:
        all_r_24h = (
            RentalListing.query.filter(
                RentalListing.status == "active",
                RentalListing.created_at >= cutoff_24h,
            )
            .order_by(RentalListing.id.desc())
            .limit(20)
            .all()
        )
        for listing in all_r_24h:
            item = _format_rental_story(listing, None, is_24h=True)
            if item and item["id"] not in seen_24h:
                stories_24h.append(item)
                seen_24h.add(item["id"])
    except Exception as exc:
        current_app.logger.warning("stories all_r_24h failed: %s", exc)
        try:
            db.session.rollback()
        except Exception:
            pass

    # ==========================================
    # 2. PUBLICATIONS RÉCENTES (FALLBACK SI PAS DE 24H OU POUR COMPLÉTER)
    # ==========================================

    # 2a. Produits avec vidéo récents
    try:
        vp_recent = (
            Product.query.filter(
                Product.is_active == True,
                Product.video_file.isnot(None),
                Product.video_file != "",
            )
            .order_by(Product.id.desc())
            .limit(15)
            .all()
        )
        for p in vp_recent:
            item = _format_product_story(p, is_24h=False)
            if item and item["id"] not in seen_recent and item["id"] not in seen_24h:
                stories_recent.append(item)
                seen_recent.add(item["id"])
    except Exception as exc:
        current_app.logger.warning("stories vp_recent failed: %s", exc)
        try:
            db.session.rollback()
        except Exception:
            pass

    # 2b. Locations avec vidéo récentes
    try:
        rv_recent = (
            db.session.query(RentalListing, RentalMedia)
            .join(RentalMedia, RentalListing.id == RentalMedia.listing_id)
            .filter(
                RentalListing.status == "active",
                RentalMedia.kind == "video",
                RentalMedia.file_path.isnot(None),
                RentalMedia.file_path != "",
            )
            .order_by(RentalListing.id.desc())
            .limit(10)
            .all()
        )
        for listing, media in rv_recent:
            item = _format_rental_story(listing, media, is_24h=False)
            if item and item["id"] not in seen_recent and item["id"] not in seen_24h:
                stories_recent.append(item)
                seen_recent.add(item["id"])
    except Exception as exc:
        current_app.logger.warning("stories rv_recent failed: %s", exc)
        try:
            db.session.rollback()
        except Exception:
            pass

    # 2c. Promotions actives récentes
    try:
        pr_recent = (
            db.session.query(Product, Promo)
            .join(Promo, Product.id == Promo.product_id)
            .filter(
                Product.is_active == True,
                Promo.status == "approved",
                Promo.end_date >= now,
            )
            .order_by(Promo.id.desc())
            .limit(20)
            .all()
        )
        for p, promo in pr_recent:
            item = _format_promo_story(p, promo, is_24h=False)
            if item and item["id"] not in seen_recent and item["id"] not in seen_24h:
                stories_recent.append(item)
                seen_recent.add(item["id"])
    except Exception as exc:
        current_app.logger.warning("stories pr_recent failed: %s", exc)
        try:
            db.session.rollback()
        except Exception:
            pass

    # 2d. Produits actifs récents avec photo
    try:
        all_p_recent = (
            Product.query.filter(
                Product.is_active == True,
            )
            .order_by(Product.id.desc())
            .limit(40)
            .all()
        )
        for p in all_p_recent:
            item = _format_product_story(p, is_24h=False)
            if item and item["id"] not in seen_recent and item["id"] not in seen_24h:
                stories_recent.append(item)
                seen_recent.add(item["id"])
    except Exception as exc:
        current_app.logger.warning("stories all_p_recent failed: %s", exc)
        try:
            db.session.rollback()
        except Exception:
            pass

    # 2e. Boutiques partenaires avec logo
    try:
        shops = (
            Shop.query.filter(
                Shop.is_active == True,
                Shop.logo.isnot(None),
                Shop.logo != "",
            )
            .order_by(Shop.id.desc())
            .limit(8)
            .all()
        )
        for s in shops:
            logo_url = _image_url(s.logo, shop=True)
            banner_url = _image_url(s.banner, shop=True) if s.banner else logo_url
            phone = _clean_phone(getattr(s, "whatsapp_phone", None) or getattr(s, "phone", None))
            msg = f"Bonjour, j'ai découvert votre boutique « {s.name} » sur Baba Market !"
            item = {
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
            }
            if item["id"] not in seen_recent and item["id"] not in seen_24h:
                stories_recent.append(item)
                seen_recent.add(item["id"])
    except Exception as exc:
        current_app.logger.warning("stories shops failed: %s", exc)
        try:
            db.session.rollback()
        except Exception:
            pass

    return {
        "stories_24h": stories_24h,
        "stories_recent": stories_recent,
    }


def get_homepage_stories(limit: int = 15) -> list[dict]:
    """Retrieve homepage stories: 24h publications prioritized & randomized, fallback to recent."""
    try:
        pool = get_catalog_cache("homepage:stories:v5-pool", build_homepage_stories_pool, timeout=60)
    except Exception as exc:
        current_app.logger.error("get_homepage_stories cache error: %s", exc)
        try:
            db.session.rollback()
        except Exception:
            pass
        pool = build_homepage_stories_pool()

    stories_24h = list(pool.get("stories_24h") or [])
    stories_recent = list(pool.get("stories_recent") or [])

    # Mélange aléatoire des publications des dernières 24h pour une égalité de chance
    random.shuffle(stories_24h)

    # Mélange aléatoire des publications récentes pour offrir de la nouveauté
    random.shuffle(stories_recent)

    # Priorité absolue aux publications des 24 heures
    selected = stories_24h[:limit]

    # Si moins de 15 stories (ou 0 dans les 24h), on complète avec les récentes
    if len(selected) < limit:
        seen = {s["id"] for s in selected}
        for item in stories_recent:
            if item["id"] not in seen:
                selected.append(item)
                seen.add(item["id"])
                if len(selected) >= limit:
                    break

    return selected


def build_homepage_stories() -> list[dict]:
    """Backward compatibility alias for tests and direct callers."""
    return get_homepage_stories()
