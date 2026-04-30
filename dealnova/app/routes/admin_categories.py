from flask import Blueprint, flash, redirect, render_template, request, url_for, current_app
from flask_login import current_user, login_required
from slugify import slugify
import time

from ..extensions import db
from ..models.category import CATEGORY_TYPE_LABELS, Category, normalize_category_type
from ..models.product import Product  # ✅ AJOUT pour vérifier avant suppression
from ..services.cache import invalidate_category_cache
from ..services.pagination import page_from_args
from ..services.audit import log_access
from sqlalchemy.exc import SQLAlchemyError  # ✅ AJOUT

bp = Blueprint("admin_categories", __name__, url_prefix="/admin/categories")


@bp.before_request
@login_required
def restrict_admin():
    role = (getattr(current_user, "role", "") or "").lower()
    if role in {"admin", "manager"}:
        return None
    flash("Acces reserve aux administrateurs", "danger")
    return redirect(url_for("shop.home"))


def _build_unique_slug(name: str, current_id: int | None = None) -> str:
    """Génère un slug unique pour une catégorie."""
    slug = slugify(name) or "categorie"
    base_slug = slug
    suffix = 1
    max_attempts = 1000

    while suffix <= max_attempts:
        query = Category.query.filter_by(slug=slug)
        if current_id is not None:
            query = query.filter(Category.id != current_id)
        if not query.first():
            return slug
        slug = f"{base_slug}-{suffix}"
        suffix += 1

    return f"{base_slug}-{int(time.time())}"


def _category_exists(name: str, exclude_id: int | None = None) -> bool:
    """Vérifie si une catégorie avec ce nom existe déjà."""
    query = Category.query.filter_by(name=name)
    if exclude_id:
        query = query.filter(Category.id != exclude_id)
    return query.first() is not None


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
        name = (request.form.get("name") or "").strip()[:100]
        category_type = normalize_category_type(request.form.get("category_type")) or "products"

        if not name:
            flash("Le nom de la categorie est requis.", "danger")
            return redirect(url_for("admin_categories.add_category"))

        if len(name) < 2:
            flash("Le nom doit contenir au moins 2 caracteres.", "warning")
            return redirect(url_for("admin_categories.add_category"))

        if _category_exists(name):
            flash(f"Une categorie avec le nom '{name}' existe deja.", "warning")
            return redirect(url_for("admin_categories.add_category"))

        try:
            category = Category(
                name=name,
                slug=_build_unique_slug(name),
                base_price=0,
                category_type=category_type,
            )
            db.session.add(category)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception(
                "add_category.db_error — name=%s type=%s", name, category_type
            )
            flash("Erreur lors de la creation de la categorie. Merci de reessayer.", "danger")
            return redirect(url_for("admin_categories.add_category"))

        # Invalidation du cache
        invalidate_category_cache()

        # Log d'audit (non bloquant)
        try:
            log_access(
                "create_category",
                "category",
                category.id,
                success=True,
                changes={"name": name, "type": category_type}
            )
        except Exception:
            pass

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
        name = (request.form.get("name") or "").strip()[:100]
        category_type = normalize_category_type(request.form.get("category_type")) or "products"

        if not name:
            flash("Le nom de la categorie est requis.", "danger")
            return redirect(url_for("admin_categories.edit_category", cid=cid))

        if len(name) < 2:
            flash("Le nom doit contenir au moins 2 caracteres.", "warning")
            return redirect(url_for("admin_categories.edit_category", cid=cid))

        if name != category.name and _category_exists(name, exclude_id=cid):
            flash(f"Une categorie avec le nom '{name}' existe deja.", "warning")
            return redirect(url_for("admin_categories.edit_category", cid=cid))

        old_name = category.name
        old_type = category.category_type

        try:
            category.name = name
            category.category_type = category_type
            category.slug = _build_unique_slug(name, current_id=category.id)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception(
                "edit_category.db_error — cid=%s name=%s", cid, name
            )
            flash("Erreur lors de la mise a jour de la categorie. Merci de reessayer.", "danger")
            return redirect(url_for("admin_categories.edit_category", cid=cid))

        # Invalidation du cache
        invalidate_category_cache()

        # Log d'audit (non bloquant)
        try:
            log_access(
                "update_category",
                "category",
                category.id,
                success=True,
                changes={
                    "old_name": old_name,
                    "new_name": name,
                    "old_type": old_type,
                    "new_type": category_type,
                }
            )
        except Exception:
            pass

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
    name = category.name

    # ✅ Vérification : des produits utilisent-ils cette catégorie ?
    try:
        products_count = Product.query.filter_by(category_id=cid).count()
    except Exception:
        products_count = 0

    if products_count > 0:
        flash(
            f"Impossible de supprimer '{name}' : {products_count} produit(s) utilisent cette categorie.",
            "danger"
        )
        return redirect(url_for("admin_categories.index"))

    try:
        db.session.delete(category)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception(
            "delete_category.db_error — cid=%s name=%s", cid, name
        )
        flash("Erreur lors de la suppression de la categorie. Merci de reessayer.", "danger")
        return redirect(url_for("admin_categories.index"))

    # Invalidation du cache
    invalidate_category_cache()

    # Log d'audit (non bloquant)
    try:
        log_access(
            "delete_category",
            "category",
            cid,
            success=True,
            changes={"name": name}
        )
    except Exception:
        pass

    flash(f"Categorie {name} supprimee.", "info")
    return redirect(url_for("admin_categories.index"))
