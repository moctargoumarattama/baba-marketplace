#!/usr/bin/env python3
"""
Script to create 10 categories and 50 products per category, totaling 500 products.
"""

import sys
import os
import random
# Add the parent directory to sys.path to import the app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.category import Category
from app.models.product import Product
from app.models.user import User
from werkzeug.security import generate_password_hash

def create_categories_and_products():
    # Create app context
    app = create_app()
    with app.app_context():
        # Define 10 categories
        categories_data = [
            {"name": "Electronics", "slug": "electronics", "description": "Electronic devices and gadgets", "base_price": 0, "commission_percent": 10.0},
            {"name": "Aesthetics", "slug": "aesthetics", "description": "Beauty and aesthetic products", "base_price": 0, "commission_percent": 10.0},
            {"name": "Clothing", "slug": "clothing", "description": "Apparel and fashion items", "base_price": 0, "commission_percent": 10.0},
            {"name": "Home Appliances", "slug": "home-appliances", "description": "Household appliances and tools", "base_price": 0, "commission_percent": 10.0},
            {"name": "Books", "slug": "books", "description": "Books and literature", "base_price": 0, "commission_percent": 10.0},
            {"name": "Sports", "slug": "sports", "description": "Sports equipment and accessories", "base_price": 0, "commission_percent": 10.0},
            {"name": "Beauty", "slug": "beauty", "description": "Cosmetics and personal care", "base_price": 0, "commission_percent": 10.0},
            {"name": "Toys", "slug": "toys", "description": "Toys and games for children", "base_price": 0, "commission_percent": 10.0},
            {"name": "Furniture", "slug": "furniture", "description": "Home and office furniture", "base_price": 0, "commission_percent": 10.0},
            {"name": "Automotive", "slug": "automotive", "description": "Car parts and accessories", "base_price": 0, "commission_percent": 10.0},
        ]

        # Create categories if they don't exist
        categories = []
        for cat_data in categories_data:
            existing_cat = Category.query.filter_by(slug=cat_data["slug"]).first()
            if existing_cat:
                categories.append(existing_cat)
            else:
                cat = Category(
                    name=cat_data["name"],
                    slug=cat_data["slug"],
                    description=cat_data["description"],
                    base_price=cat_data["base_price"],
                    commission_percent=cat_data["commission_percent"]
                )
                db.session.add(cat)
                categories.append(cat)

        db.session.commit()  # Commit to get IDs

        # Create a dummy vendor if none exists
        dummy_vendor = User.query.filter_by(username='dummy_vendor').first()
        if not dummy_vendor:
            dummy_vendor = User(
                username='dummy_vendor',
                email='dummy@example.com',
                password_hash=generate_password_hash('dummy'),
                role='vendor'
            )
            db.session.add(dummy_vendor)
            db.session.commit()

        # Now create 50 products per category
        product_templates = {
            "Electronics": ["Smartphone", "Laptop", "Tablet", "Headphones", "Smartwatch", "Camera", "Printer", "Router", "Mouse", "Keyboard"],
            "Aesthetics": ["Lipstick", "Foundation", "Mascara", "Perfume", "Nail Polish", "Hair Dye", "Moisturizer", "Sunscreen", "Blush", "Eyeshadow"],
            "Clothing": ["T-Shirt", "Jeans", "Dress", "Jacket", "Shoes", "Hat", "Socks", "Sweater", "Skirt", "Pants"],
            "Home Appliances": ["Blender", "Microwave", "Vacuum", "Washing Machine", "Refrigerator", "Toaster", "Coffee Maker", "Dishwasher", "Iron", "Fan"],
            "Books": ["Novel", "Biography", "Cookbook", "Textbook", "Comic", "Poetry", "History", "Science", "Fiction", "Non-Fiction"],
            "Sports": ["Ball", "Racket", "Dumbbells", "Bike", "Treadmill", "Yoga Mat", "Soccer Ball", "Basketball", "Tennis Racket", "Golf Club"],
            "Beauty": ["Shampoo", "Conditioner", "Body Wash", "Face Mask", "Serum", "Cleanser", "Toner", "Lotion", "Cream", "Oil"],
            "Toys": ["Doll", "Action Figure", "Puzzle", "Board Game", "Building Blocks", "Stuffed Animal", "Remote Car", "Drone", "Bike", "Scooter"],
            "Furniture": ["Chair", "Table", "Sofa", "Bed", "Desk", "Cabinet", "Shelf", "Lamp", "Mirror", "Rug"],
            "Automotive": ["Tire", "Battery", "Oil Filter", "Brake Pad", "Spark Plug", "Car Cover", "Seat Cover", "Air Filter", "Wiper Blade", "Engine Oil"]
        }

        for cat in categories:
            templates = product_templates[cat.name]
            for i in range(1, 51):  # 50 products
                base_name = random.choice(templates)
                name = f"{base_name} {i}"
                description = f"High-quality {base_name.lower()} for {cat.name.lower()} category."
                price = round(random.uniform(10.0, 1000.0), 2)
                stock = 50
                p = Product(
                    name=name,
                    description=description,
                    price=price,
                    stock=stock,
                    category_id=cat.id,
                    vendor_id=dummy_vendor.id,
                    is_active=True,
                    view_count=0
                )
                db.session.add(p)

        db.session.commit()
        print("✅ 10 categories and 500 products created successfully!")

if __name__ == "__main__":
    create_categories_and_products()
