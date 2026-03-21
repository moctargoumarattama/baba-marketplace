# PERF FIXES

Date: 2026-03-05

## Lot 1 - Wrappers consolidation (SAFE)

Scope:
- `delivery_pricing.js`
- `pages/cart_page.js`
- `pages/checkout_page.js`
- `pages/product_detail_page.js`
- `pages/shop_detail_page.js`
- `pages/track_order_page.js`

What changed:
- Removed legacy local wrapper names (`requestJSON`, `requestText`, `withCsrfHeaders`) from these files.
- Unified calls to central core APIs when available:
  - `window.BMAjaxFetch.requestJSON/requestText`
  - `window.BMAjaxCSRF.addToHeaders`
- Kept minimal fallback fetch logic to preserve resilience.

Impact:
- Reduced wrapper-name duplication and maintenance overhead.
- No intended visual/UI behavior changes.
- Same endpoints and payload contracts.

## Lot 2 - Admin deliveries/fraud stabilization (SAFE)

Scope:
- `admin_table.js` (deliveries + fraud initializers)
- `admin_forms.js` (CSRF path)
- `ajax/core/bm_csrf.js` (API alias)

What changed:
- Added page guards:
  - `window.__ADM_DELIVERIES_INIT__` + `body.dataset.admDeliveriesInit`
  - `window.__ADM_FRAUD_INIT__` + `body.dataset.admFraudInit`
- Kept pagination robustness in admin table engine:
  - `AbortController`
  - `requestSeq` stale response protection
  - hard fallback navigation if AJAX swap fails
- Kept deliveries polling hidden-tab safe (existing adaptive polling logic remains active).
- Added `BMAjaxCSRF.withCsrfHeaders` alias and admin forms now prefer this central API.

Impact:
- Fewer duplicate init risks on admin pages.
- No visual change.
- Same filters/pager/forms behavior, with existing safe fallback preserved.
