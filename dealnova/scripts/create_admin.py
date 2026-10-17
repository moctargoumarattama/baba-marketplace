#!/usr/bin/env python3
"""Create an administrator with explicit identity and a privately entered password.

Usage: python scripts/create_admin.py --username NAME --email ADDRESS
"""

import argparse
from getpass import GetPassWarning, getpass
from pathlib import Path
import re
import sys
import warnings


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Creer un nouveau compte administrateur.")
    parser.add_argument("--username", required=True, help="Nom de connexion (80 caracteres maximum).")
    parser.add_argument("--email", required=True, help="Adresse e-mail de l'administrateur.")
    args = parser.parse_args(argv)
    args.username = args.username.strip()
    args.email = args.email.strip().lower()
    if not args.username or len(args.username) > 80 or any(ch.isspace() for ch in args.username):
        parser.error("Le nom de connexion doit contenir 1 a 80 caracteres sans espace.")
    if len(args.email) > 120 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", args.email):
        parser.error("Saisissez une adresse e-mail valide de 120 caracteres maximum.")
    return args


def _load_runtime():
    # Importing the CLI or requesting --help must not initialize the application.
    app_dir = str(Path(__file__).resolve().parents[1])
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    from app import create_app
    from app.extensions import db
    from app.models.user import User

    return create_app, db, User


def _create_admin(username, email, password):
    from sqlalchemy import func, or_

    create_app, db, User = _load_runtime()
    app = create_app()
    with app.app_context():
        existing = User.query.filter(or_(
            func.lower(User.username) == username.lower(),
            func.lower(User.email) == email.lower(),
        )).first()
        if existing is not None:
            print("Creation refusee : ce nom ou cet e-mail appartient deja a un compte.", file=sys.stderr)
            return 1

        try:
            user = User(username=username, email=email, role="admin")
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
        except Exception:
            db.session.rollback()
            print("Le compte n'a pas pu etre cree. Aucune modification n'a ete validee.", file=sys.stderr)
            return 1

    print("Compte administrateur cree.")
    return 0


def main(argv=None):
    args = _parse_args(argv)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", GetPassWarning)
            password = getpass("Mot de passe (12 caracteres minimum) : ")
            confirmation = getpass("Confirmer le mot de passe : ")
    except (EOFError, KeyboardInterrupt, GetPassWarning):
        print("Creation annulee. Utilisez un terminal permettant une saisie masquee.", file=sys.stderr)
        return 2

    if len(password) < 12 or not password.strip():
        print("Le mot de passe doit contenir au moins 12 caracteres.", file=sys.stderr)
        return 2
    if password != confirmation:
        print("Les mots de passe ne correspondent pas.", file=sys.stderr)
        return 2

    try:
        return _create_admin(args.username, args.email, password)
    except Exception:
        print("Creation impossible. Verifiez la configuration de l'application.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
