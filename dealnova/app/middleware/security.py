# app/middleware/security.py
from flask import redirect, url_for, flash
from flask_login import current_user
from functools import wraps
from ..services.logging_service import logging_service


def _log_access_denied(resource_type, resource_id, user):
    """Log un accès refusé."""
    logging_service.log_activity(
        "security",
        "access_denied",
        user=user if user.is_authenticated else None,
        resource_type=resource_type,
        resource_id=resource_id,
        level="WARNING",
        message=f"Accès refusé à {resource_type} #{resource_id}"
    )


def order_access_required(f):
    """Décorateur pour vérifier l'accès aux commandes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from ..models.order import Order
        
        order_id = kwargs.get('oid') or kwargs.get('order_id')
        token = kwargs.get('token')
        
        if order_id:
            order = Order.query.get_or_404(order_id)
            
            # Les admins ont toujours accès
            if current_user.is_authenticated and current_user.role == "admin":
                return f(*args, **kwargs)
            
            if not order.can_view(current_user, token):
                _log_access_denied("order", order_id, current_user)
                flash("Accès non autorisé à cette commande", "danger")
                return redirect(url_for("shop.home"))
        
        return f(*args, **kwargs)
    return decorated_function


def vendor_product_required(f):
    """Décorateur pour vérifier que le vendeur possède le produit"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from ..models.product import Product
        
        product_id = kwargs.get('pid')
        
        if product_id:
            # Les admins ont toujours accès
            if current_user.is_authenticated and current_user.role == "admin":
                return f(*args, **kwargs)
            
            if current_user.is_authenticated and current_user.role == "vendor":
                product = Product.query.get_or_404(product_id)
                
                if product.vendor_id != current_user.id:
                    _log_access_denied("product", product_id, current_user)
                    flash("Ce produit ne vous appartient pas", "danger")
                    return redirect(url_for("vendor.dashboard"))
        
        return f(*args, **kwargs)
    return decorated_function


def permission_required(resource_type, owner_field="vendor_id"):
    """Décorateur générique pour vérifier les permissions."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            from ..models.product import Product
            from ..models.order import Order
            
            # Déterminer l'ID selon le type
            resource_id = None
            if resource_type == "product":
                resource_id = kwargs.get('pid')
            elif resource_type == "order":
                resource_id = kwargs.get('oid') or kwargs.get('order_id')
            
            if resource_id:
                # Charger la ressource
                if resource_type == "product":
                    resource = Product.query.get_or_404(resource_id)
                elif resource_type == "order":
                    resource = Order.query.get_or_404(resource_id)
                else:
                    return f(*args, **kwargs)
                
                # Les admins ont toujours accès
                if current_user.is_authenticated and current_user.role == "admin":
                    return f(*args, **kwargs)
                
                # Vérifier le propriétaire
                owner_id = getattr(resource, owner_field, None)
                user_id = current_user.id if current_user.is_authenticated else None
                
                if owner_id and owner_id != user_id:
                    _log_access_denied(resource_type, resource_id, current_user)
                    flash(f"Accès non autorisé à cette {resource_type}", "danger")
                    
                    # Redirection appropriée
                    if resource_type == "product":
                        return redirect(url_for("vendor.dashboard"))
                    else:
                        return redirect(url_for("shop.home"))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator