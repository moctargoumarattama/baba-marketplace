# app/middleware/security.py - NOUVEAU FICHIER
from flask import redirect, url_for, flash
from flask_login import current_user
from functools import wraps

def order_access_required(f):
    """Décorateur pour vérifier l'accès aux commandes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from ..models.order import Order
        
        order_id = kwargs.get('oid') or kwargs.get('order_id')
        token = kwargs.get('token')
        
        if order_id:
            order = Order.query.get_or_404(order_id)
            
            # Vérifier les permissions
            if not order.can_view(current_user, token):
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
        
        if product_id and current_user.role == "vendor":
            product = Product.query.get_or_404(product_id)
            
            if product.vendor_id != current_user.id:
                flash("Ce produit ne vous appartient pas", "danger")
                return redirect(url_for("vendor.dashboard"))
        
        return f(*args, **kwargs)
    return decorated_function
