from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from slugify import slugify

from ..extensions import db
from ..models.category import CATEGORY_TYPE_LABELS, Category, normalize_category_type
from ..services.cache import invalidate_category_cache
from ..services.pagination import page_from_args

bp = Blueprint("admin_categories", __name__, url_prefix="/admin/categories")


@bp.before_request
@login_required
def restrict_admin():
    role = (getattr(current_user, "role", "") or "").lower()
    if role == "admin":
        return None
    if role == "courier":
        return render_template("errors/403.html"), 403
    flash("Acces reserve aux administrateurs", "danger")
    return redirect(url_for("shop.home"))


def _build_unique_slug(name: str, current_id: int | None = None) -> str:
    slug = slugify(name) or "categorie"
    base_slug = slug
    suffix = 1

    while True:
        query = Category.query.filter_by(slug=slug)
        if current_id is not None:
            query = query.filter(Category.id != current_id)
        if not query.first():
            return slug
        slug = f"{base_slug}-{suffix}"
        suffix += 1


@bp.route("/")
def index():
    q = (request.args.get("q") or "").strip()
    type_filter = (request.args.get("cat_type") or "").strip()
    page = page_from_args(request.args)
    per_page = 20

    query = Category.query.order_by(Category.category_type.asc(), Category.name.asc())

    if q:
        like = f"%{q}%"
        query = query.filter(Category.name.ilike(like) | Category.slug.ilike(like))
    if type_filter:
        query = query.filter(Category.category_type == type_filter)

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return render_template(
        "admin/categories.html",
        categories=pagination.items,
        pagination=pagination,
        category_type_labels=CATEGORY_TYPE_LABELS,
        q=q,
        type_filter=type_filter,
        total=pagination.total,
    )


@bp.route("/add", methods=["GET", "POST"])
def add_category():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        category_type = normalize_category_type(request.form.get("category_type")) or "products"

        if not name:
            flash("Le nom de la categorie est requis.", "danger")
            return redirect(url_for("admin_categories.add_category"))

        category = Category(
            name=name,
            slug=_build_unique_slug(name),
            base_price=0,
            category_type=category_type,
        )
        db.session.add(category)
        db.session.commit()
        invalidate_category_cache()
        flash(f"Categorie {name} creee.", "success")
        return redirect(url_for("admin_categories.index"))

    return render_template(
        "admin/category_form.html",
        category_type_labels=CATEGORY_TYPE_LABELS,
    )


@bp.route("/edit/<int:cid>", methods=["GET", "POST"])
def edit_category(cid):
    category = Category.query.get_or_404(cid)
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        category_type = normalize_category_type(request.form.get("category_type")) or "products"

        if not name:
            flash("Le nom de la categorie est requis.", "danger")
            return redirect(url_for("admin_categories.edit_category", cid=cid))

        category.name = name
        category.category_type = category_type
        category.slug = _build_unique_slug(name, current_id=category.id)
        db.session.commit()
        invalidate_category_cache()
        flash(f"Categorie {category.name} mise a jour.", "success")
        return redirect(url_for("admin_categories.index"))

    return render_template(
        "admin/category_form.html",
        category=category,
        category_type_labels=CATEGORY_TYPE_LABELS,
    )


@bp.route("/delete/<int:cid>", methods=["POST"])
def delete_category(cid):
    category = Category.query.get_or_404(cid)
    db.session.delete(category)
    db.session.commit()
    invalidate_category_cache()
    flash(f"Categorie {category.name} supprimee.", "info")
    return redirect(url_for("admin_categories.index"))
