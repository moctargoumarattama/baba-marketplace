# Page Loader Map

Date: 2026-03-05
File: `app/static/js/core/page_loader.js`
Mode: SAFE (no visual change)

## 1) Always Global (kept in base shells)

These remain globally loaded in `base.html` / `admin/base.html`:
- `js/core/core_dom.js`
- `js/core/core_ui.js`
- `js/ajax/core/bm_csrf.js`
- `js/ajax/core/bm_guard.js`
- `js/ajax/core/bm_fetch.js`
- `js/ajax/core/bm_swap.js`
- `js/core/page_loader.js`

## 2) `data-page` -> dynamic scripts

| data-page | Scripts loaded |
|---|---|
| `shop.home` | `core_cart`, `core_live`, `live`, `ajax_pagination`, `features/pagination`, `features/forms`, `features/polling` |
| `global_search` | `core_cart`, `core_live`, `live`, `ajax_pagination`, `features/pagination`, `features/forms` |
| `shops.list_shops` | `core_cart`, `core_live`, `live`, `ajax_pagination`, `features/pagination`, `features/forms` |
| `shop.shop_detail` | `core_cart`, `core_live`, `live`, `ajax_pagination`, `features/pagination`, `features/forms`, `features/polling` |
| `shop.product_detail` | `core_cart`, `core_live`, `live`, `features/forms` |
| `cart.view` | `core_cart`, `core_live`, `live`, `features/forms` |
| `cart.checkout` | `core_cart`, `core_live`, `live`, `features/forms` |
| `cart.my_orders` | `core_cart`, `core_live`, `live`, `ajax_pagination`, `features/pagination`, `features/forms`, `features/polling` |
| `cart.track_by_phone` | `core_cart`, `core_live`, `live`, `features/forms` |
| `cart.track_verify_phone` | `core_cart`, `core_live`, `live`, `features/forms` |
| `shop.track_order` | `core_cart`, `core_live`, `live`, `features/forms`, `features/polling` |
| `vendor.dashboard` / `vendor.earnings` | `core_live`, `live`, `ajax_pagination`, `features/pagination`, `features/forms`, `features/polling` |
| `vendor.manage_shop` / `vendor.product_new` / `vendor.product_edit` / `vendor.security` | `core_live`, `live`, `features/forms` |
| `vendor.periods` | `core_live`, `live`, `ajax_pagination`, `features/pagination`, `features/forms`, `features/polling` |
| `admin.*` targeted pages (`all_orders`, `deliveries*`, `order_archives`) | `core_live`, `live`, `features/pagination`, `features/forms`, `features/polling`, `admin_table`, `admin_forms` |
| `admin_users.*` targeted pages (`fraud_monitor`, `catalog_quality`, `reconciliation`, `manage_shops`, `manage_users`, `view_logs`) | `core_live`, `live`, `features/pagination`, `features/forms`, `features/polling`, `admin_table`, `admin_forms` |
| `admin_categories.index`, `rentals.admin_locations`, `courier.panel_orders`, `courier.panel_deliveries` | `core_live`, `live`, `features/pagination`, `features/forms`, `features/polling`, `admin_table`, `admin_forms` |

## 3) `data-adm-page` -> dynamic scripts

| data-adm-page | Scripts loaded |
|---|---|
| `deliveries`, `fraud`, `shops`, `users`, `admin_locations`, `categories`, `logs`, `catalog_quality`, `reconciliation` | `core_live`, `live`, `features/pagination`, `features/forms`, `features/polling`, `admin_table`, `admin_forms` |

## 4) DOM-hint fallback rules

When page id is unknown, loader adds scripts by DOM hints:
- cart/track badges present -> `core_cart`
- AJAX forms present (`form[data-ajax="true"]`, `data-adm-action="post"`) -> `core_live`, `live`, `features/forms`
- AJAX/listing pager present (`data-ajax-pagination`, `data-adm-pager`, `data-adm-listing`) -> `ajax_pagination`, `features/pagination`
- polling hints present (`data-live`, `data-orders-live-url`, `data-notify-url`) -> `features/polling`

## 5) Guards and rollback

- Loader guard: `window.__BM_PAGE_LOADER_INIT__`
- Loaded-assets dedupe: `window.__BM_PAGE_LOADER_ASSETS__`
- Hard rollback flag: `window.__BM_DISABLE_PAGE_LOADER__ = true`
