#!/usr/bin/env python3
"""
Script to create an admin user account.
Run this script from the dealnova directory.
"""

import sys
import os
# Add the parent directory to sys.path to import the app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.user import User

def create_admin():
    # Create app context
    app = create_app()
    with app.app_context():
        # Check if admin user already exists
        existing_admin = User.query.filter_by(email="moctargouma@gmail.com").first()
        if existing_admin:
            print("❌ Admin user with email moctargouma@gmail.com already exists.")
            return

        # Create new admin user
        admin_user = User(
            username="moctargouma",
            email="moctargouma@gmail.com",
            role="admin"
        )
        admin_user.set_password("12345678")

        db.session.add(admin_user)
        db.session.commit()

        print("✅ Admin user created successfully!")
        print("Email: moctargouma@gmail.com")
        print("Password: 12345678")
        print("Role: admin")

if __name__ == "__main__":
    create_admin()
