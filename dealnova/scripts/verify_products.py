#!/usr/bin/env python3
"""
Script to verify that 50 products were created.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.models.product import Product

def verify_products():
    app = create_app()
    with app.app_context():
        products = Product.query.all()
        print(f"Total products in database: {len(products)}")
        if len(products) >= 50:
            print("✅ Successfully created 50+ products!")
            print("\nFirst 5 products:")
            for p in products[:5]:
                print(f"- {p.name}: ${p.price}, Stock: {p.stock}, Vendor: {p.vendor_id}")
            print("\nLast 5 products:")
            for p in products[-5:]:
                print(f"- {p.name}: ${p.price}, Stock: {p.stock}, Vendor: {p.vendor_id}")
        else:
            print("❌ Less than 50 products found.")

if __name__ == "__main__":
    verify_products()
