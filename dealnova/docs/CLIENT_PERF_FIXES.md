# Client Perf Fixes

Date: 2026-03-05
Scope: `/shop` home, `/cart/checkout`, `/shop/shops`, `/locations`
Mode: SAFE (no visual changes, no route/DB/business changes)

## 1) Loader / payload reductions

- Added dynamic client loader: `app/static/js/core/page_loader_client.js`.
- `base.html` now loads `page_loader_client.js` (public shell), keeping AJAX core globally loaded.
- Removed direct page script tags from target templates:
  - `shop/home.html`
  - `cart/checkout.html`
  - `shop/shops.html`
  - `locations/index.html`
- Standardized `data-page` on those 4 pages:
  - `shop_home`, `checkout`, `shops`, `locations_index`

## 2) Live search fan-out hardening (`shop_home_page.js`)

- Kept `AbortController` + `requestSeq` stale-response guard.
- Kept debounce (`350ms`) and minimum query for live search (`>=2`).
- Added secondary threshold for heavier endpoints:
  - `shops` + `locations` now fetch only when `query >= 3`.
- Added batched UI render in one animation frame (`renderSuggestionsBatch`) to avoid multi-paint updates.

## 3) Listener / execution optimizations

- `shop_home_page.js`: `resize` updates are now RAF-throttled.
- Existing `scroll` listeners remain passive on home page.
- No network polling introduced on client target pages.
- Existing carousel interval in `locations_index_page.js` remains UI-only and is hidden-tab aware (`visibilitychange`).

## 4) Fallback / safety

- Loader rollback: set `window.__BM_DISABLE_PAGE_LOADER__ = true` to disable dynamic loading.
- Admin shell untouched in this pass (`admin/base.html` not migrated here).
- Core AJAX globals remain loaded everywhere:
  - `bm_csrf`, `bm_guard`, `bm_fetch`, `bm_swap`.

## 5) Validation focus

1. `/shop`: fast typing, pagination, add-to-cart.
2. `/shop/shops`: search/kind filters + pagination + back/forward.
3. `/locations`: filters + pagination.
4. `/cart/checkout`: delivery pricing + submit (double click guard).
5. Console clean on slow network.
