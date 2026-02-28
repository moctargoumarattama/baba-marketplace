#!/usr/bin/env python3
"""
Script to fix products with missing default.jpg image file.
Run this script from the dealnova directory.
"""

import sys
import os
# Add the parent directory to sys.path to import the app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.product import Product

def fix_default_images():
    # Create app context
    app = create_app()
    with app.app_context():
        # Find products with default.jpg
        products = Product.query.filter_by(image_file="default.jpg").all()

        if not products:
            print("✅ No products found with default.jpg image file.")
            return

        updated = 0
        for p in products:
            p.image_file = None
            updated += 1
            print(f"✅ Fixed product: {p.name}")

        # Commit changes
        db.session.commit()
        print(f"\n🎉 Successfully updated {updated} products!")

if __name__ == "__main__":
    fix_default_images()
