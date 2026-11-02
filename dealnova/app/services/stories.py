"""Service to generate Discovery Stories & Video Feed for the homepage."""
from __future__ import annotations

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
            photos = [p.strip() for p in (prod.image_file or "").split("|") if p.strip()]
            thumb = _image_url(photos[0]) if photos else url_for("static", filename="img/placeholders/product.svg")
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
            cover = next((m.file_path for m in listing.media if m.kind == "image" and m.file_path), "")
            thumb = _image_url(cover, rental=True) if cover else url_for("static", filename="img/placeholders/location.svg")
            phone = _clean_phone(getattr(listing, "contact_phone", None))
            price_dh = f"{listing.price:.0f} DH" if listing.price else ""
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
                Promo.is_active == True,
                Promo.start_date <= now,
                Promo.end_date >= now,
            )
            .order_by(Promo.id.desc())
            .limit(8)
            .all()
        )
        for prod, promo in promo_rows:
            if f"prod_{prod.id}" in seen_ids:
                continue
            photos = [p.strip() for p in (prod.image_file or "").split("|") if p.strip()]
            if not photos:
                continue
            img_url = _image_url(photos[0])
            shop = prod.shop
            shop_name = shop.name if shop else "Baba Market"
            phone = _clean_phone(getattr(shop, "whatsapp_phone", None) or getattr(shop, "phone", None))
            
            # Discount calculation
            orig_price = prod.price or 0.0
            if promo.discount_percent and promo.discount_percent > 0:
                final_price = orig_price * (1.0 - (promo.discount_percent / 100.0))
                tag = f"-{int(promo.discount_percent)}%"
            elif promo.discount_amount and promo.discount_amount > 0:
                final_price = max(0.0, orig_price - promo.discount_amount)
                tag = f"-{promo.discount_amount:.0f} DH"
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
                "thumbnail_url": img_url,
                "media_url": img_url,
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
        return get_catalog_cache("homepage:stories:v2", build_homepage_stories, timeout=90)
    except Exception as exc:
        current_app.logger.error("get_homepage_stories cache error: %s", exc)
        try:
            db.session.rollback()
        except Exception:
            pass
        return build_homepage_stories()
