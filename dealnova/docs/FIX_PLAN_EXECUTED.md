# Fix Plan Executed (SAFE)

Date: 2026-03-05

## Scope
Stability/performance/robustness fixes were applied without intentional visual changes, without route/DB/business changes.

## Files Modified
- `dealnova/app/static/js/ajax_pagination.js`
- `dealnova/app/templates/shop/home.html`
- `dealnova/app/static/js/pages/shop_home_page.js`
- `dealnova/app/templates/admin/base.html`
- `dealnova/app/static/js/core/core_cart.js`
- `dealnova/app/static/js/core/core_live.js`
- `dealnova/app/static/js/ajax/features/polling.js`
- `dealnova/app/static/js/ajax/core/bm_fetch.js`
- `dealnova/app/static/js/ui_shell.js`
- `dealnova/app/templates/shop/track_order.html`
- `dealnova/app/static/js/pages/vendor/dashboard_page.js`
- `dealnova/app/static/js/pages/vendor/earnings_page.js`
- `dealnova/app/static/js/home_shell.js`
- `dealnova/app/static/js/pages/search_results_page.js`
- `dealnova/app/static/js/pages/product_detail_page.js`
- `dealnova/docs/AJAX_ARCHITECTURE.md`
- `dealnova/docs/FIX_PLAN_EXECUTED.md`

## Double AJAX Engine Neutralization
- Convention added and documented: `data-ajax-owner="page"` means page controller owns navigation/popstate.
- Applied on shop home body (`shop/home.html`).
- `ajax_pagination.js` now exits early when body owner is `page`/`off`.
- `shop_home_page.js` also checks body owner before using global popstate engine.

## Polling Gating / Pause Applied
- Admin order notification polling is now gated by page in `core_cart.js`:
  - Uses `data-notify-pages` (explicit list) or safe fallback matching (`all_orders`, `deliveries`, `fraud`, courier pages).
  - No polling on unrelated admin pages.
- `admin/base.html` now exposes explicit `data-notify-pages`.
- `core_live.js` adaptive poll now supports true hidden pause (timers cleared when hidden, resume on visible).
- `ajax/features/polling.js` migrated from `setInterval` to adaptive `setTimeout` loop with hidden pause/resume.
- Legacy polling update:
  - `shop/track_order.html` polling migrated from raw `setInterval` to adaptive polling (`BMAjaxPolling` if available + safe fallback loop).
  - Vendor fallback pollers (`dashboard_page.js`, `earnings_page.js`) migrated from `setInterval` to hidden-safe adaptive loops.

## Global Fetch Patch Risk Neutralized
- Removed nav-badge monkey patch of `window.fetch` in `ui_shell.js`.
- Replaced with:
  - `bm:ajax:response` event listener (emitted by `bm_fetch.js`)
  - existing functional events (`cart:changed`, `track:changed`, `bm:ajax-form-success`)
  - adaptive background nav refresh polling (hidden-safe)

## Search / Request Robustness
- Safe native-fetch fallback restored where missing:
  - `shop_home_page.js`
  - `search_results_page.js`
  - `vendor/dashboard_page.js`
- Existing AbortController + request sequence protections kept for live search and live panels.

## Guards Added / Enforced
- `window.__BM_AJAX_PAGINATION_DISABLED__` (set when page-owned AJAX navigation is active)
- Existing guards kept and relied on:
  - `window.__BM_AJAX_PAGINATION_INIT__`
  - `window.__BM_CORE_CART_INIT__`
  - `window.__BM_VENDOR_DASHBOARD_PAGE_INIT__`
  - `window.__BM_VENDOR_EARNINGS_INIT__`
  - `window.__BM_VENDOR_EARNINGS_PAGE_INIT__`
  - `window.__BM_SHOP_HOME_INIT__`

## Manual Test Checklist (10 min)
1. `/shop`: type quickly in search, paginate, browser back/forward.
2. `/search`: type quickly, ensure no stale result overwrite.
3. `/cart`: add/update/remove and verify nav badges update.
4. `/shop/track/<token>`: live refresh works; switch tab hidden then visible.
5. `/vendor/dashboard`: stats/orders polling pauses hidden and resumes visible.
6. `/vendor/earnings`: auto refresh pauses hidden and resumes visible.
7. `/admin/all_orders`: notifications/pagination stable.
8. `/admin/deliveries`: notifications + page polling stable, no duplicate requests.
9. `/admin/fraud`: no global admin notify polling when not in allowlist.
10. Console/Network: no red errors, no duplicate popstate behavior.
