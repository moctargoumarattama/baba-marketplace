# Routes

Ce document liste les routes Flask telles que configur?es dans `app/__init__.py` (pr?fixe d?enregistrement) et dans chaque blueprint (url_prefix local).

**Note** : certains blueprints ont un `url_prefix` **et** sont enregistr?s avec un `url_prefix` dans `app/__init__.py`. Le pr?fixe final est la concat?nation des deux.

## Routes globales (app/__init__.py)

| M?thodes | URL | Handler | Notes |
|---|---|---|---|
| GET | `/` | `landing` | Page d?accueil (catalogue + boutiques + promos). |
| GET | `/search` | `global_search` | Recherche globale (produits, boutiques, cat?gories). |
| GET | `/admin-access` | `admin_access_route` | Redirection vers admin si l?utilisateur est admin. |
| GET | `/admin/admin/` | `compat_admin_root_redirect` | Compat anciens liens admin. |
| GET | `/admin/admin/<path:subpath>` | `compat_admin_redirect` | Compat anciens liens admin (redirige vers `/admin/*`). |
| GET, POST, PUT, PATCH, DELETE, OPTIONS | `/api/api/` | `compat_api_root_redirect` | Compat anciens liens API (redirige vers `/api/`). |
| GET, POST, PUT, PATCH, DELETE, OPTIONS | `/api/api/<path:subpath>` | `compat_api_redirect` | Compat anciens liens API (redirige vers `/api/*`). |
| GET | `/shops` | `list_shops_fallback` | Fallback si le blueprint `shops` n?est pas charg?. |

## Acc?s / permissions (r?sum?)

| Zone | R?gle d?acc?s |
|---|---|
| Admin (`admin.py`, `admin_users.py`, `admin_categories.py`) | Login requis + r?le `admin` (via `before_request`). |
| Vendor (`vendor.py`) | Login requis + r?le `vendor` ou `admin` selon la route. |
| Public (`shop.py`, `shops.py`, `cart.py`, `auth.py`, `api.py`) | Public, avec CSRF pour les POST. |

## admin.py

Blueprint prefix: `/admin`  
Register prefix: `/ (aucun)`  
Pr?fixe final: `/admin`

| M?thodes | URL | Handler | Notes |
|---|---|---|---|
| GET | `/admin/deliveries` | `deliveries` |  |
| POST | `/admin/deliver/<int:oid>` | `mark_delivered` |  |
| POST | `/admin/order/<int:oid>/cancel` | `cancel_order` |  |
| GET | `/admin/orders` | `all_orders` |  |
| GET | `/admin/orders/notifications` | `orders_notifications` |  |
| GET | `/admin/orders/live` | `orders_live` |  |
| GET | `/admin/deliveries/live` | `deliveries_live` |  |
| GET | `/admin/order/<int:oid>` | `order_detail` |  |
| GET, POST | `/admin/pricing` | `pricing_settings` |  |

## admin_categories.py

Blueprint prefix: `/admin/categories`  
Register prefix: `/ (aucun)`  
Pr?fixe final: `/admin/categories`

| M?thodes | URL | Handler | Notes |
|---|---|---|---|
| GET | `/admin/categories/` | `index` |  |
| GET, POST | `/admin/categories/add` | `add_category` |  |
| GET, POST | `/admin/categories/edit/<int:cid>` | `edit_category` |  |
| POST | `/admin/categories/delete/<int:cid>` | `delete_category` |  |

## admin_users.py

Blueprint prefix: `/admin`  
Register prefix: `/ (aucun)`  
Pr?fixe final: `/admin`

| M?thodes | URL | Handler | Notes |
|---|---|---|---|
| GET | `/admin/` | `admin_dashboard` | Dashboard admin principal |
| GET | `/admin/users` | `manage_users` | Gérer tous les utilisateurs |
| GET | `/admin/user/<int:user_id>` | `user_detail` | Détail d'un utilisateur |
| POST | `/admin/user/<int:user_id>/update` | `update_user` | Mettre ? jour un utilisateur |
| POST | `/admin/user/<int:user_id>/reset-password` | `reset_user_password` | Réinitialiser le mot de passe d'un utilisateur |
| POST | `/admin/user/<int:user_id>/toggle-active` | `toggle_user_active` | Activer/désactiver un utilisateur |
| POST | `/admin/user/<int:user_id>/delete` | `delete_user` | Supprimer un utilisateur |
| GET, POST | `/admin/user/create` | `create_user` | Créer un nouvel utilisateur |
| GET | `/admin/shops` | `manage_shops` | Gérer toutes les boutiques |
| GET | `/admin/shop/<int:shop_id>` | `shop_detail` | Detail d'une boutique |
| POST | `/admin/shop/<int:shop_id>/update` | `update_shop` | Mettre à jour une boutique |
| POST | `/admin/shop/<int:shop_id>/toggle` | `toggle_shop` | Activer/d?sactiver une boutique |
| POST | `/admin/shop/<int:shop_id>/delete` | `delete_shop` | Supprimer une boutique |
| GET, POST | `/admin/shop/create` | `create_shop` | Créer une nouvelle boutique pour un vendeur existant |
| GET | `/admin/logs` | `view_logs` | Voir les logs d'activité |
| GET | `/admin/audit` | `audit_logs` | Voir les logs d'audit |
| GET | `/admin/activity` | `activity_log` | Vue activite marketplace (ops). |
| GET | `/admin/reconciliation` | `reconciliation` | Abonnements vendeurs (mensuel) |
| POST | `/admin/reconciliation/mark-subscription/<int:user_id>` | `mark_subscription_paid` | Encaisser abonnement |
| POST | `/admin/reconciliation/free-vendor/<int:user_id>` | `subscription_free_vendor` | Mode free pour un vendeur |
| POST | `/admin/reconciliation/settings` | `subscription_settings` | Paramètres abonnement |
| POST | `/admin/reconciliation/block-vendor/<int:user_id>` | `subscription_block_vendor` | Bloquer vendeur |
| POST | `/admin/reconciliation/unblock-vendor/<int:user_id>` | `subscription_unblock_vendor` | Débloquer vendeur |
| POST | `/admin/reconciliation/mark-paid/<int:payout_id>` | `mark_vendor_paid` | (Legacy) Paiement vendeur sur commande |
| GET | `/admin/fraud` | `fraud_monitor` |  |
| POST | `/admin/fraud/block` | `fraud_block` |  |
| POST | `/admin/fraud/unblock/<int:block_id>` | `fraud_unblock` |  |
| GET | `/admin/catalog-quality` | `catalog_quality` |  |
| POST | `/admin/catalog-quality/toggle/<int:product_id>` | `catalog_toggle_product` |  |
| POST | `/admin/catalog-quality/hide-out-of-stock` | `catalog_hide_out_of_stock` |  |
| GET | `/admin/api/stats` | `api_stats` | API pour les statistiques admin |
| GET | `/admin/api/user/<int:user_id>/quick-info` | `api_user_quick_info` | Info rapide sur un utilisateur |

## api.py

Blueprint prefix: `/api`  
Register prefix: `/ (aucun)`  
Pr?fixe final: `/api`

| M?thodes | URL | Handler | Notes |
|---|---|---|---|
| GET | `/api/search/products` | `search_products` |  |
| GET | `/api/search/shops` | `search_shops` |  |
| GET | `/api/search/categories` | `search_categories` |  |
| POST | `/api/cart/add/<int:pid>` | `add_to_cart` |  |
| GET | `/api/cart/summary` | `cart_summary` |  |

## auth.py

Blueprint prefix: `/ (aucun)`  
Register prefix: `/ (aucun)`  
Pr?fixe final: `/`

| M?thodes | URL | Handler | Notes |
|---|---|---|---|
| GET, POST | `/register` | `register` |  |
| GET, POST | `/login` | `login` |  |
| POST | `/logout` | `logout` |  |
| GET, POST | `/forgot-password` | `forgot_password` | Demande de réinitialisation de mot de passe |
| GET, POST | `/reset-password/<token>` | `reset_password` | Réinitialisation du mot de passe avec token |

## cart.py

Blueprint prefix: `/cart`  
Register prefix: `/ (aucun)`  
Pr?fixe final: `/cart`

| M?thodes | URL | Handler | Notes |
|---|---|---|---|
| GET | `/cart/` | `view` |  |
| POST | `/cart/add/<int:pid>` | `add` |  |
| POST | `/cart/remove/<int:pid>` | `remove` |  |
| POST | `/cart/increase/<int:pid>` | `increase` |  |
| POST | `/cart/decrease/<int:pid>` | `decrease` |  |
| POST | `/cart/update_qty/<int:pid>` | `update_qty` |  |
| POST | `/cart/api/add/<int:pid>` | `add_ajax` | Ajouter un produit via AJAX |
| POST | `/cart/api/remove/<int:pid>` | `remove_ajax` | Supprimer un produit via AJAX |
| POST | `/cart/api/update/<int:pid>` | `update_qty_ajax` | Mettre à jour la quantité via AJAX |
| POST | `/cart/api/clear` | `clear_ajax` | Vider le panier via AJAX |
| GET | `/cart/api/summary` | `cart_summary` | Obtenir le résumé du panier via AJAX |
| GET, POST | `/cart/checkout` | `checkout` |  |
| GET | `/cart/shipping/<city>` | `ajax_shipping` |  |
| POST | `/cart/whatsapp` | `whatsapp_checkout` |  |
| GET | `/cart/track/<token>` | `track` |  |
| GET | `/cart/track/<token>/status` | `track_status` |  |
| GET, POST | `/cart/suivi` | `track_by_phone` |  |
| GET | `/cart/mes-commandes` | `my_orders` |  |
| POST | `/cart/clear` | `clear` |  |

## shop.py

Blueprint prefix: `/ (aucun)`  
Register prefix: `/shop`  
Pr?fixe final: `/shop`

| M?thodes | URL | Handler | Notes |
|---|---|---|---|
| GET | `/shop/` | `home` |  |
| GET | `/shop/product/<int:pid>` | `product_detail` |  |
| POST | `/shop/product/<int:pid>/review` | `review` |  |
| GET | `/shop/track/<token>` | `track_order` |  |
| GET | `/shop/suivi` | `suivi_redirect` |  |

## shops.py

Blueprint prefix: `/ (aucun)`  
Register prefix: `/ (aucun)`  
Pr?fixe final: `/`

| M?thodes | URL | Handler | Notes |
|---|---|---|---|
| GET | `/shops` | `list_shops` | Liste toutes les boutiques actives |
| GET | `/shop/<string:shop_slug>` | `shop_detail` | Détail d'une boutique avec ses produits |

## vendor.py

Blueprint prefix: `/ (aucun)`  
Register prefix: `/vendor`  
Pr?fixe final: `/vendor`

| M?thodes | URL | Handler | Notes |
|---|---|---|---|
| GET | `/vendor/dashboard` | `dashboard` |  |
| GET, POST | `/vendor/product/new` | `product_new` |  |
| GET, POST | `/vendor/product/<int:pid>/edit` | `product_edit` |  |
| POST | `/vendor/product/<int:pid>/delete` | `product_delete` |  |
| GET | `/vendor/shop/manage` | `manage_shop` | Page de gestion de la boutique |
| GET, POST | `/vendor/shop/create` | `create_shop` | Créer une boutique |
| GET, POST | `/vendor/shop/edit` | `edit_shop` | Modifier la boutique |
| POST | `/vendor/shop/toggle` | `toggle_shop_status` | Activer/desactiver la boutique |
| GET | `/vendor/orders` | `orders` |  |
| GET | `/vendor/order/<int:oid>` | `order_detail` |  |
| GET | `/vendor/earnings` | `earnings` |  |
| GET | `/vendor/api/shop/stats` | `shop_stats_api` | API pour les statistiques de la boutique |
| GET | `/vendor/api/products/stock` | `products_stock_api` | API pour la gestion des stocks |
| GET | `/vendor/shop/setup` | `setup_shop_redirect` | Redirection pour compatibilité (ancienne route) |



