"""Public catalogue queries with SQL filtering, ordering and pagination."""
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
import time
import unicodedata

from flask import url_for
from sqlalchemy import and_, case, cast, Integer, literal, or_, select, union_all
from sqlalchemy.orm import joinedload, selectinload

from ..extensions import db
from ..models.category import Category
from ..models.product import Product
from ..models.promo import Promo
from ..models.rental import RentalListing, RentalMedia
from ..models.shop import Shop
from .cache import get_catalog_cache
from .image import image_variant
from .marketplace_feed import _base_product_query, _public_location_query
from .pricing import cents_to_money
from .public_text import clean_shop_description


UNIVERSES = {"products", "services", "locations", "promotions", "shops", "search"}
DISCOVERY_UNIVERSES = frozenset(("products", "services", "locations", "promotions"))
DISCOVERY_INTERVAL = 30 * 60
LOCAL_CITIES = ("Rabat", "Salé", "Kénitra", "Témara")
_SEARCH_STOPWORDS = frozenset((
    "a", "au", "aux", "avec", "avez", "bonjour", "ce", "cherche", "chercher", "dans", "de", "des",
    "du", "en", "est", "et", "il", "je", "la", "le", "les", "ma", "me", "mes", "moi", "mon",
    "plait", "pour", "que", "quel", "quelle", "quelles", "quels", "qui", "recherche", "s", "sur",
    "svp", "un", "une", "veux", "voudrais", "vous",
))
_SEARCH_SINGULAR_EXCEPTIONS = frozenset((
    "bois", "couscous", "frais", "francais", "gris", "jus", "matelas", "noix", "prix", "repas", "souris", "tapis",
))
_SQL_ACCENT_REPLACEMENTS = tuple(
    (variant, plain)
    for plain, variants in (("a", "àâäáãå"), ("c", "ç"), ("e", "éèêë"), ("i", "îïíì"),
                            ("o", "ôöóòõ"), ("u", "ùûüú"), ("y", "ÿý"), ("oe", "œ"), ("ae", "æ"))
    for variant in variants
)


@dataclass(frozen=True)
class CatalogFilters:
    universe: str = "products"
    q: str = ""
    cat: int | None = None
    shop: int | None = None
    city: str = ""
    listing_type: str = ""
    property_type: str = ""
    min_price: float | None = None
    max_price: float | None = None
    stock: bool = False
    promo: bool = False
    sort: str = "new"
    page: int = 1
    per_page: int = 12
    smart: bool = False
    rotation_slot: int | None = None


def parse_catalog_filters(args):
    def value(key, alias=None):
        return str(args.get(key) or (args.get(alias) if alias else "") or "").strip()

    def text(key, maximum):
        result = " ".join(value(key).split())
        if len(result) > maximum or "\x00" in result:
            raise ValueError("Raccourcissez votre recherche." if key == "q" else "Le nom de ville ou de quartier saisi n'est pas valide.")
        return result

    def integer(key, default=None):
        raw = value(key)
        if not raw:
            return default
        if not raw.isascii() or not raw.isdigit() or len(raw) > 10:
            raise ValueError("Ce filtre n'est pas valide. Réinitialisez votre recherche.")
        parsed = int(raw)
        if not 1 <= parsed <= 2_147_483_647:
            raise ValueError("Ce filtre n'est pas valide. Réinitialisez votre recherche.")
        return parsed

    def money(key, alias):
        raw = value(key, alias).replace(",", ".")
        if not raw:
            return None
        try:
            parsed = Decimal(raw)
            if not parsed.is_finite() or not Decimal(0) <= parsed <= Decimal("1000000000"):
                raise ValueError
            return float(parsed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        except (InvalidOperation, ValueError):
            label = "minimum" if key == "min_price" else "maximum"
            raise ValueError(f"Le prix {label} n'est pas valide. Saisissez un montant positif.") from None

    def boolean(key):
        raw = value(key).lower()
        if raw not in ("", "0", "1", "false", "true"):
            raise ValueError("Ce filtre n'est pas valide. Réinitialisez votre recherche.")
        return raw in ("1", "true")

    universe = value("universe") or "products"
    if universe not in UNIVERSES:
        raise ValueError("Cette catégorie n'existe pas.")
    sort = value("sort") or "new"
    sort = {"price_asc": "low", "price_desc": "high", "newest": "new"}.get(sort, sort)
    if sort not in ("new", "low", "high", "discover") or (sort == "discover" and universe not in DISCOVERY_UNIVERSES):
        raise ValueError("Ce tri n'est pas disponible.")
    listing_type = value("listing_type", "type")
    property_type = value("property_type")
    if listing_type not in ("", "monthly", "daily"):
        raise ValueError("Ce type de location n'est pas disponible.")
    if property_type not in ("", "room", "apartment", "studio", "store"):
        raise ValueError("Ce type de logement n'est pas disponible.")
    minimum, maximum = money("min_price", "min"), money("max_price", "max")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError("Le prix minimum doit être inférieur au prix maximum.")
    return CatalogFilters(
        universe=universe, q=text("q", 160), cat=integer("cat"), shop=integer("shop"),
        city=text("city", 120), listing_type=listing_type, property_type=property_type,
        min_price=minimum, max_price=maximum, stock=boolean("stock"), promo=boolean("promo"),
        sort=sort, page=integer("page", 1), per_page=min(24, integer("per_page", 12)), smart=boolean("smart"),
        rotation_slot=integer("rotation_slot"),
    )


def _contains(column, value):
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return column.ilike(f"%{escaped}%", escape="\\")


def _fold_search_text(value):
    text = str(value or "").casefold().replace("œ", "oe").replace("æ", "ae")
    return "".join(char for char in unicodedata.normalize("NFKD", text)
                   if not unicodedata.combining(char))


def _smart_search_tokens(value):
    tokens = []
    for token in re.findall(r"[^\W_]+", _fold_search_text(value)[:160]):
        if token in _SEARCH_STOPWORDS:
            continue
        if len(token) > 4 and token.endswith(("s", "x")) and token not in _SEARCH_SINGULAR_EXCEPTIONS:
            token = token[:-1]
        if token not in tokens:
            tokens.append(token)
        if len(tokens) == 6:
            break
    return tokens


def _prepare_smart_search():
    if db.engine.dialect.name == "sqlite":
        # SQLite's lower() only handles ASCII and a long replace() expression
        # exhausts its parser stack. A connection-local deterministic scalar
        # function keeps filtering/counting/pagination inside the SQL query.
        connection = db.session.connection().connection
        if not connection.info.get("bm_assistant_fold_registered"):
            connection.driver_connection.create_function("bm_assistant_fold", 1, _fold_search_text, deterministic=True)
            connection.info["bm_assistant_fold_registered"] = True


def _fold_search_column(column, text):
    if db.engine.dialect.name == "sqlite":
        return db.func.bm_assistant_fold(column)
    expression = db.func.lower(db.func.coalesce(column, ""))
    # A fixed alphabet makes this portable to MySQL without database extensions.
    needed_letters = set(text)
    for variant, plain in _SQL_ACCENT_REPLACEMENTS:
        if needed_letters.intersection(plain):
            expression = db.func.replace(expression, variant, plain)
    return expression


def _smart_search_condition(columns, value, *, category=False):
    tokens = _smart_search_tokens(value)
    if not tokens:
        return or_(*(_contains(column, value) for column in columns))
    folded = [_fold_search_column(column, "".join(tokens)) for column in columns]
    conditions = []
    for token in tokens:
        matches = [_contains(column, token) for column in folded]
        if category:
            matches.append(Product.category.has(_contains(_fold_search_column(Category.name, token), token)))
        conditions.append(or_(*matches))
    return and_(*conditions)


def _smart_city_condition(columns, city):
    folded = _fold_search_text(city)
    return or_(*(_contains(_fold_search_column(column, folded), folded) for column in columns))


def _price_expression():
    # Same nearest approved promotion and cent rounding as services.pricing.
    # Rank once in SQL instead of rescanning promotions for every product/filter.
    promotions = db.session.query(
        Promo.product_id.label("product_id"), Promo.type.label("type"), Promo.value.label("value"),
        db.func.row_number().over(partition_by=Promo.product_id,
                                  order_by=(Promo.end_date.asc(), Promo.id.asc())).label("position"),
    ).filter(Promo.status == Promo.STATUS_APPROVED, Promo.end_date >= datetime.utcnow()).subquery()
    base = db.func.coalesce(Product.price_cents_value, 0)
    value_cents = cast(db.func.round(db.func.coalesce(promotions.c.value, 0) * 100), Integer)
    discounted = case(
        (promotions.c.type == "percentage", cast(db.func.round(base * (10000 - value_cents) / 10000.0), Integer)),
        (promotions.c.type == "fixed", base - value_cents), else_=base,
    )
    return case((discounted < 0, 0), else_=discounted), promotions


def _source_queries(filters, *, smart_search=False):
    if smart_search and (filters.q or filters.city):
        _prepare_smart_search()
    sources = {}
    rental_filters = bool(filters.listing_type or filters.property_type)
    if filters.universe in ("products", "services", "promotions", "search") and not rental_filters:
        kind = "service" if filters.universe == "services" else ("" if filters.universe == "search" else "physical")
        query, _, _, _, _ = _base_product_query(
            search_q="", category_id=filters.cat, kind=kind, min_price=None, max_price=None,
            promo_only="0", in_stock="1" if filters.stock else "0", shop_id=filters.shop,
        )
        query = query.filter(Product.kind.in_(("physical", "service")))
        price, promotions = _price_expression()
        query = query.outerjoin(promotions, and_(promotions.c.product_id == Product.id, promotions.c.position == 1))
        if filters.q:
            columns = (Product.name, Product.description, Shop.name)
            query = query.filter(_smart_search_condition(columns, filters.q, category=True) if smart_search else
                                 or_(*(_contains(column, filters.q) for column in columns)))
        if filters.city:
            query = query.filter(_smart_city_condition((Shop.address,), filters.city) if smart_search else
                                 _contains(Shop.address, filters.city))
        if filters.promo or filters.universe == "promotions":
            query = query.filter(price < Product.price_cents_value)
        if filters.min_price is not None:
            query = query.filter(price >= round(filters.min_price * 100))
        if filters.max_price is not None:
            query = query.filter(price <= round(filters.max_price * 100))
        sources["product"] = (Product, query, price)

    if filters.universe in ("locations", "search") and not (filters.cat or filters.promo or filters.stock):
        query = _public_location_query(
            search_q="", listing_type=filters.listing_type, property_type=filters.property_type,
            city_area="", min_price=filters.min_price, max_price=filters.max_price, shop_id=filters.shop,
        )
        if filters.q:
            columns = (RentalListing.title, RentalListing.description, RentalListing.city, RentalListing.area, Shop.name)
            if smart_search:
                columns += (RentalListing.property_type,)
            query = query.filter(_smart_search_condition(columns, filters.q) if smart_search else
                                 or_(*(_contains(column, filters.q) for column in columns)))
        if filters.city:
            columns = (RentalListing.city, RentalListing.area)
            query = query.filter(_smart_city_condition(columns, filters.city) if smart_search else
                                 or_(*(_contains(column, filters.city) for column in columns)))
        sources["location"] = (RentalListing, query, RentalListing.rent_cents)

    if (filters.universe in ("shops", "search") and not
            (filters.shop or filters.cat or filters.promo or filters.stock or rental_filters or
             filters.min_price is not None or filters.max_price is not None)):
        query = Shop.query.filter(Shop.is_active.is_(True))
        if filters.q:
            columns = (Shop.name, Shop.description)
            query = query.filter(_smart_search_condition(columns, filters.q) if smart_search else
                                 or_(*(_contains(column, filters.q) for column in columns)))
        if filters.city:
            query = query.filter(_smart_city_condition((Shop.address,), filters.city) if smart_search else
                                 _contains(Shop.address, filters.city))
        sources["shop"] = (Shop, query, cast(literal(None), Integer))
    return sources


def _city_key(value):
    return "".join(char for char in unicodedata.normalize("NFD", value.casefold())
                   if unicodedata.category(char) != "Mn")


def _shop_city(address):
    normalized = _city_key(address or "")
    return next((city for city in LOCAL_CITIES if _city_key(city) in normalized), "")


def _compute_facets(universe):
    sources = _source_queries(CatalogFilters(universe=universe))
    categories, cities, shop_selects = [], set(), []
    for source, (model, query, _) in sources.items():
        query = query.enable_eagerloads(False).order_by(None)
        shop_column = Shop.id if source == "shop" else model.shop_id
        shop_selects.append(query.with_entities(shop_column.label("shop_id")).statement)
        if source == "product":
            category_ids = query.with_entities(Product.category_id).statement
            categories = [{"id": category.id, "name": category.name} for category in
                          Category.query.filter(Category.id.in_(category_ids)).order_by(Category.name.asc(), Category.id.asc()).all()]
        if source == "location":
            cities.update(city.strip() for (city,) in query.with_entities(RentalListing.city).distinct().all() if city and city.strip())
    if not shop_selects:
        return {"categories": categories, "shops": [], "cities": sorted(cities)}
    ids = (union_all(*shop_selects) if len(shop_selects) > 1 else shop_selects[0]).subquery()
    shops = (Shop.query.filter(Shop.is_active.is_(True), Shop.id.in_(select(ids.c.shop_id)))
             .with_entities(Shop.id, Shop.name, Shop.address).order_by(Shop.name.asc(), Shop.id.asc()).all())
    if "product" in sources or "shop" in sources:
        cities.update(city for _, _, address in shops if (city := _shop_city(address)))
    return {"categories": categories, "shops": [{"id": sid, "name": name} for sid, name, _ in shops],
            "cities": sorted(cities, key=str.casefold)}


def _facets(universe):
    try:
        return get_catalog_cache(f"facets:{universe}", lambda: _compute_facets(universe), timeout=120)
    except Exception:
        return _compute_facets(universe)


def _image_url(raw, *, rental=False, shop=False, variant="thumb"):
    filename = str(raw or "").split("|")[0].strip().replace("\\", "/")
    if (not filename or filename.startswith("//") or ":" in filename or
            ".." in filename.split("/") or any(ord(char) < 32 for char in filename)):
        return url_for("static", filename="img/placeholders/shop.svg" if shop else "img/placeholders/product.svg")
    filename = filename.lstrip("/")
    if filename.startswith("static/"):
        filename = filename[7:]
    if filename.startswith("uploads/"):
        filename = filename[8:]
    if rental and not filename.startswith("rentals/"):
        filename = "rentals/" + filename
    elif not rental and not shop:
        try:
            filename = image_variant(filename, variant)
        except Exception:
            pass
    return url_for("static", filename="uploads/" + filename)


def _shop_is_open(shop):
    return bool(shop is None or (shop.is_open and (not shop.closed_until or shop.closed_until <= datetime.utcnow())))


def _product_video_url(raw):
    path = str(raw or "").strip().replace("\\", "/")
    if (not path or len(path) > 512 or path.startswith("//") or
            any(ord(char) < 32 for char in path) or any(char in path for char in ":%?#") or
            any(part in ("", ".", "..") for part in path.lstrip("/").split("/"))):
        return ""
    static_path = path.startswith(("/static/", "static/"))
    if path.startswith("/static/"):
        path = path[8:]
    elif path.startswith("static/"):
        path = path[7:]
    elif path.startswith("/"):
        return ""
    if path.startswith("uploads/product_videos/"):
        filename = path[len("uploads/product_videos/"):]
    elif path.startswith("product_videos/"):
        filename = path[len("product_videos/"):]
    elif "/" not in path and not static_path:
        filename = path
    else:
        return ""
    if not filename or "/" in filename:
        return ""
    return url_for("static", filename="uploads/product_videos/" + filename)


def _serialize(source, model, price):
    item = {"id": model.id, "item_type": source, "kind": source, "name": "", "description": model.description or "",
            "price": None, "final_price": None, "has_promo": False, "stock": None,
            "booking_url": None, "slug": "", "shop_id": None, "shop_name": "", "city": "", "listing_type": ""}
    if source == "product":
        service = model.kind == "service"
        base = model.price_cents
        item.update(item_type="service" if service else "product", kind=model.kind, name=model.name,
                    price=cents_to_money(base), final_price=cents_to_money(price), has_promo=price < base,
                    image_url=_image_url(model.image_file), url=url_for("shop.product_detail", pid=model.id),
                    image_preview_url=_image_url(model.image_file, variant="large"),
                    video_url=_product_video_url(model.video_file),
                    stock=model.stock or 0, booking_url=url_for("booking.book", pid=model.id) if service else None,
                    shop_id=model.shop_id, shop_name=model.shop.name if model.shop else "",
                    category_id=model.category_id, category=model.category.name if model.category else "",
                    city=_shop_city(model.shop.address) if model.shop else "",
                    available=_shop_is_open(model.shop) and (service or model.stock > 0))
    elif source == "location":
        sorted_media = sorted(model.media, key=lambda media: media.id)
        cover = next((media.file_path for media in sorted_media
                      if media.kind == "image" and media.file_path), "")
        video = next((media.file_path for media in sorted_media
                      if media.kind == "video" and media.file_path), "")
        item.update(name=model.title, slug=model.slug, price=cents_to_money(price), final_price=cents_to_money(price),
                    image_url=_image_url(cover, rental=True) if cover else "",
                    video_url=_image_url(video, rental=True) if video else "",
                    url=url_for("rentals.location_detail", slug=model.slug),
                    shop_id=model.shop_id, shop_name=model.shop.name, city=model.city, area=model.area or "",
                    listing_type=model.listing_type, property_type=model.property_type, status=model.status,
                    available=model.status == "active")
    else:
        item.update(name=model.name, slug=model.slug, description=clean_shop_description(model.description), image_url=_image_url(model.banner or model.logo, shop=True),
                    url=url_for("shops.shop_detail", shop_slug=model.slug), shop_id=model.id, shop_name=model.name,
                    city=_shop_city(model.address), address=model.address or "", available=_shop_is_open(model),
                    is_open=_shop_is_open(model), is_verified=bool(model.is_verified))
    return item


def get_public_catalog_item(item_type: str, item_id: int) -> dict | None:
    """Inspect one visible offer using the catalogue's prices and access rules."""
    universe = {"product": "products", "service": "services", "location": "locations", "shop": "shops"}.get(item_type)
    if universe is None or isinstance(item_id, bool) or not isinstance(item_id, int) or item_id < 1:
        return None
    source = "product" if item_type == "service" else item_type
    model, query, price = _source_queries(CatalogFilters(universe=universe))[source]
    query = query.filter(model.id == item_id)
    if source == "product":
        query = query.options(
            selectinload(Product.shop).load_only(Shop.id, Shop.name, Shop.address, Shop.is_open, Shop.closed_until),
            joinedload(Product.category),
        )
    elif source == "location":
        query = query.options(joinedload(RentalListing.shop), selectinload(RentalListing.media))
    row = query.add_columns(price.label("catalog_price")).first()
    return _serialize(source, row[0], row[1]) if row else None


def _has_discovery_media(source):
    """Determine media priority in SQL, without loading every offer or media."""
    if source == "product":
        return or_(db.func.trim(db.func.coalesce(Product.image_file, "")) != "",
                   db.func.trim(db.func.coalesce(Product.video_file, "")) != "")
    if source == "location":
        return RentalListing.media.any(and_(RentalMedia.kind.in_(("image", "video")),
                                          db.func.trim(db.func.coalesce(RentalMedia.file_path, "")) != ""))
    return literal(False)


def _discovery_query(merged, slot, per_page):
    # A fixed permutation followed by a circular rotation gives every offer a
    # turn, even in a small catalogue. A random SQL order or a per-request seed
    # would duplicate/skip offers when the visitor changes pages. Each media
    # group is rotated separately so pictures/videos always keep priority.
    identity = merged.c.id % 65521
    permutation = (identity * identity * 48271 + identity * 69621) % 2147483647
    ranked = db.session.query(
        merged,
        db.func.row_number().over(
            partition_by=merged.c.has_media,
            order_by=(permutation.asc(), merged.c.source.asc(), merged.c.id.asc()),
        ).label("rotation_position"),
        db.func.count().over(partition_by=merged.c.has_media).label("rotation_size"),
    ).subquery()
    # A full batch takes over when the group spans multiple pages; a smaller
    # group still changes its leading offer instead of rotating by its size.
    step = case((ranked.c.rotation_size > per_page, per_page), else_=1)
    return db.session.query(ranked).order_by(
        ranked.c.has_media.desc(),
        ((ranked.c.rotation_position - 1 + slot * step) % ranked.c.rotation_size).asc(),
        ranked.c.source.asc(), ranked.c.id.asc(),
    )


def build_public_catalog(filters, *, smart_search=False):
    discovery = filters.sort == "discover" and filters.universe in DISCOVERY_UNIVERSES
    rotation = None
    if discovery:
        now = time.time()
        slot = filters.rotation_slot if filters.rotation_slot is not None else int(now) // DISCOVERY_INTERVAL
        filters = replace(filters, rotation_slot=slot)
        refresh_at = (slot + 1) * DISCOVERY_INTERVAL
        rotation = {"slot": slot, "refresh_at": refresh_at, "interval": DISCOVERY_INTERVAL,
                    "refresh_in": max(0, refresh_at - now)}
    sources = _source_queries(filters, smart_search=smart_search or filters.smart)
    facets = _facets(filters.universe)
    statements = [query.enable_eagerloads(False).order_by(None).with_entities(
        model.id.label("id"), literal(source).label("source"), price.label("price"), model.created_at.label("created_at"),
        *([case((_has_discovery_media(source), 1), else_=0).label("has_media")] if discovery else []),
    ).statement for source, (model, query, price) in sources.items()]
    if statements:
        merged = (union_all(*statements) if len(statements) > 1 else statements[0]).subquery()
        total = db.session.query(db.func.count()).select_from(merged).scalar() or 0
    else:
        total = 0
    pages = (total + filters.per_page - 1) // filters.per_page
    page = min(filters.page, max(1, pages))
    rows = []
    if total:
        query = _discovery_query(merged, filters.rotation_slot, filters.per_page) if discovery else db.session.query(merged)
        if filters.sort in ("low", "high"):
            query = query.order_by(case((merged.c.price.is_(None), 1), else_=0),
                                   merged.c.price.asc() if filters.sort == "low" else merged.c.price.desc())
        if not discovery:
            query = query.order_by(merged.c.created_at.desc(), merged.c.source.asc(), merged.c.id.desc())
        rows = query.offset(
            (page - 1) * filters.per_page).limit(filters.per_page).all()
    models = {}
    for source in sources:
        ids = [row.id for row in rows if row.source == source]
        if not ids:
            continue
        model = sources[source][0]
        query = model.query.filter(model.id.in_(ids))
        if source == "product":
            query = query.options(joinedload(Product.shop), joinedload(Product.category))
        elif source == "location":
            query = query.options(joinedload(RentalListing.shop), selectinload(RentalListing.media))
        models[source] = {entry.id: entry for entry in query.all()}
    items = [_serialize(row.source, models[row.source][row.id], row.price) for row in rows]
    result = {"success": True, "items": items, "facets": facets,
            "pagination": {"page": page, "pages": pages, "total": total, "per_page": filters.per_page,
                           "has_next": page < pages, "has_prev": page > 1},
            "filters": {**asdict(filters), "page": page}}
    if rotation is not None:
        result["rotation"] = rotation
    return result
