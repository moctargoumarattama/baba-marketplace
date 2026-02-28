# app/services/guest_session.py
from flask import session
import secrets
from datetime import datetime


class GuestSessionManager:
    """Gere les sessions des utilisateurs sans compte"""

    @staticmethod
    def can_access_order(order):
        """Verifie si le guest_token de la session correspond a celui de la commande."""
        guest_token = session.get("guest_token")
        if guest_token and order.guest_token == guest_token:
            return True

        order_tokens = session.get("guest_order_tokens", [])
        return order.guest_token in order_tokens

    @staticmethod
    def get_or_create_guest_token():
        """Recupere ou cree un token de session pour un guest"""
        if "guest_token" not in session:
            session["guest_token"] = secrets.token_urlsafe(16)
            session["guest_created"] = datetime.utcnow().isoformat()

        return session["guest_token"]

    @staticmethod
    def get_guest_identifier():
        """Retourne un identifiant unique pour le guest"""
        token = GuestSessionManager.get_or_create_guest_token()
        return f"guest_{token[:8]}"

    @staticmethod
    def clear_guest_data():
        """Nettoie les donnees guest (apres paiement/conversion)"""
        keys_to_remove = ["guest_token", "guest_created", "booking_cart", "guest_order_tokens"]
        for key in keys_to_remove:
            session.pop(key, None)

    @staticmethod
    def remember_order_token(token, max_tokens=20):
        """Enregistre un token de commande pour l'accès invité."""
        tokens = session.get("guest_order_tokens", [])
        if token not in tokens:
            tokens.append(token)
            session["guest_order_tokens"] = tokens[-max_tokens:]

    @staticmethod
    def is_guest_session():
        """Verifie si c'est une session guest"""
        from flask_login import current_user
        return "guest_token" in session and not current_user.is_authenticated
