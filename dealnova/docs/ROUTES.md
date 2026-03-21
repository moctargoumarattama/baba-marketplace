# ROUTES

Quick map of active route modules and main endpoints.

## Blueprint Modules

| Module | Blueprint | Main Prefix | Access |
|---|---|---|---|
| `app/__init__.py` | app routes | `/` | Public + admin checks on specific routes |
| `routes/auth.py` | `auth` | `/` | Public auth flows |
| `routes/shop.py` | `shop` | `/shop` | Public shop catalog |
| `routes/shops.py` | `shops` | `/` | Public shops listing/details |
| `routes/cart.py` | `cart` | `/cart` | Public cart/checkout/track |
| `routes/booking.py` | `booking` | `/booking` | Public booking flows |
| `routes/delivery.py` | `delivery_special` | `/delivery` | Public delivery request flow |
| `routes/rentals.py` | `rentals` | `/locations`, `/location/*` | Public rentals + owner/admin sections |
| `routes/vendor.py` | `vendor` | `/vendor` | Vendor/admin |
| `routes/courier.py` | `courier` | `/courier` | Courier/admin |
| `routes/admin.py` | `admin` | `/admin` | Admin only |
| `routes/admin_users.py` | `admin_users` | `/admin` | Admin only |
| `routes/admin_categories.py` | `admin_categories` | `/admin/categories` | Admin only |
| `routes/api.py` | `api` | `/api` | Public API endpoints |

## Core App Endpoints

| Endpoint | URL | Role |
|---|---|---|
| `landing` | `/` | Public |
| `global_search` | `/search` | Public |
| `set_language_route` | `/lang/<lang_code>` | Public |
| `service_worker` | `/sw.js` | Public |
| `health` | `/health` | Public |
| `admin_access_route` | `/admin-access` | Authenticated admin |

## Shop / Cart / Delivery / Rentals

| Area | Key URLs |
|---|---|
| Shop | `/shop/`, `/shop/product/<id>`, `/shops`, `/shop/<slug>` |
| Cart | `/cart/`, `/cart/checkout`, `/cart/suivi`, `/cart/track/<token>` |
| Delivery | `/delivery`, `/delivery/whatsapp` |
| Rentals | `/locations`, `/location/<slug>`, `/location/<slug>/inquiry` |

## Admin Key URLs

| Area | Key URLs |
|---|---|
| Orders | `/admin/orders`, `/admin/orders/live`, `/admin/orders/notifications` |
| Deliveries | `/admin/deliveries`, `/admin/deliveries/live` |
| Users/Shops | `/admin/users`, `/admin/user/<id>`, `/admin/shops`, `/admin/shop/<id>` |
| Monitoring | `/admin/logs`, `/admin/audit`, `/admin/fraud`, `/admin/catalog-quality` |

## Access Rules (Short)

- Admin blueprints enforce admin role via `before_request`.
- Vendor/courier spaces enforce authenticated role-specific access.
- Public pages stay open; POST routes rely on CSRF.
