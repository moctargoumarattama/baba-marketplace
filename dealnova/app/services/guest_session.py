# app/services/guest_session.py
from flask import session
import secrets
from datetime import datetime


class GuestSessionManager:
    """Gere les sessions des utilisateurs sans compte"""

    @staticmethod
    def get_or_create_guest_token():
        """Recupere ou cree un token de session pour un guest"""
        if "guest_token" not in session:
            session["guest_token"] = secrets.token_urlsafe(16)
            session["guest_created"] = datetime.utcnow().isoformat()

        return session["guest_token"]

