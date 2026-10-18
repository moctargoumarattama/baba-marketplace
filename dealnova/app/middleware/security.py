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