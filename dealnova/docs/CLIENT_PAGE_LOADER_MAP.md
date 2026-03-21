# Client Page Loader Map

Date: 2026-03-05
Loader file: `app/static/js/core/page_loader_client.js`

## data-page mapping (client targets)

| data-page | Dynamic scripts |
|---|---|
| `shop_home` | `js/core/core_cart.js`, `js/ajax_pagination.js`, `js/pages/shop_home_page.js` |
| `checkout` | `js/core/core_cart.js`, `js/delivery_pricing.js`, `js/pages/checkout_page.js` |
| `shops` | `js/core/core_cart.js`, `js/ajax_pagination.js`, `js/shops_page.js` |
| `locations_index` | `js/core/core_cart.js`, `js/ajax_pagination.js`, `js/pages/locations_index_page.js` |

## Compatibility aliases
- `shop.home` -> `shop_home` stack
- `cart.checkout` -> `checkout` stack
- `shops.list_shops` -> `shops` stack
- `rentals.locations_home` -> `locations_index` stack

## Guard / rollback
- Guard: `window.__BM_PAGE_LOADER_CLIENT_INIT__`
- Dedupe set: `window.__BM_PAGE_LOADER_CLIENT_ASSETS__`
- Rollback flag: `window.__BM_DISABLE_PAGE_LOADER__ = true`
