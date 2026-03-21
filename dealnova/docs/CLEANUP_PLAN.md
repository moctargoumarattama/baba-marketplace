# CLEANUP PLAN (P2 SAFE)

Date: 2026-03-05
Lot: 1 (Public checkout/cart/product_detail/shop_detail/track_order + delivery_pricing)
Mode: SAFE / zero UX change / no route-DB-business modifications

## Scope (Lot 1)
Files consolidated:
1. `dealnova/app/static/js/delivery_pricing.js`
2. `dealnova/app/static/js/pages/cart_page.js`
3. `dealnova/app/static/js/pages/checkout_page.js`
4. `dealnova/app/static/js/pages/product_detail_page.js`
5. `dealnova/app/static/js/pages/shop_detail_page.js`
6. `dealnova/app/static/js/pages/track_order_page.js`

## What was removed (local wrappers)
Removed local wrapper definitions named:
- `requestJSON`
- `requestText`
- `withCsrfHeaders`

Replaced by compact bridge-style locals:
- `bmFetchJSON`
- `bmAddCsrfHeaders`
- (`bmFetchText` removed from `shop_detail_page.js` because unused)

Calls now use centralized core where present:
- `window.BMAjaxFetch.requestJSON`
- `window.BMAjaxFetch.requestText` (when needed)
- `window.BMAjaxCSRF.addToHeaders` (or token fallback)

## Proofs (before/after)

### Before (snapshot captured before refactor)
Command executed:
```bash
rg -n "function requestJSON|const requestJSON|function requestText|const requestText|withCsrfHeaders" \
  dealnova/app/static/js/delivery_pricing.js \
  dealnova/app/static/js/pages/cart_page.js \
  dealnova/app/static/js/pages/checkout_page.js \
  dealnova/app/static/js/pages/product_detail_page.js \
  dealnova/app/static/js/pages/shop_detail_page.js \
  dealnova/app/static/js/pages/track_order_page.js
```
Result (excerpt): matches existed in all 6 files (wrappers detected).
Captured examples before refactor:
- `.../track_order_page.js:24: async function requestJSON(url, options) {`
- `.../shop_detail_page.js:63: async function requestJSON(url, options) {`
- `.../shop_detail_page.js:81: async function requestText(url, options) {`
- `.../cart_page.js:9: function withCsrfHeaders(headers, formEl) {`
- `.../checkout_page.js:268: async function requestJSON(url, options) {`
- `.../product_detail_page.js:52: async function requestJSON(url, options) {`

### After
Command executed:
```bash
rg -n "function requestJSON|const requestJSON|function requestText|const requestText|withCsrfHeaders" \
  dealnova/app/static/js/delivery_pricing.js \
  dealnova/app/static/js/pages/cart_page.js \
  dealnova/app/static/js/pages/checkout_page.js \
  dealnova/app/static/js/pages/product_detail_page.js \
  dealnova/app/static/js/pages/shop_detail_page.js \
  dealnova/app/static/js/pages/track_order_page.js
```
Result: **no match** (exit code 1).

Verification command:
```bash
rg -n "BMAjaxFetch|BMAjaxBridge" \
  dealnova/app/static/js/delivery_pricing.js \
  dealnova/app/static/js/pages/cart_page.js \
  dealnova/app/static/js/pages/checkout_page.js \
  dealnova/app/static/js/pages/product_detail_page.js \
  dealnova/app/static/js/pages/shop_detail_page.js \
  dealnova/app/static/js/pages/track_order_page.js
```
Result: `BMAjaxFetch` references present in all 6 files.

## Risk assessment
- Risk: **Low**
- Why low:
  - same endpoints, same payloads
  - same request flow (AbortController / requestSeq kept)
  - no template/CSS/base-shell changes in this lot

## Rollback
Simple rollback paths:
1. `git checkout -- <file>` for each of the 6 files
2. or cherry-pick/restore this lot only if split into separate commit

---

Date: 2026-03-05
Lot: 2 (Admin deliveries + fraud)
Mode: SAFE / zero UX change / no route-DB-business modifications

## Analysis table (page -> features)

| Page | Features found | Covered by |
|---|---|---|
| `admin/deliveries.html` | filters form, AJAX pager swap, back-to-top, available couriers polling, order action forms | `admin_table.js` + `admin_forms.js` + `core_live.js` |
| `admin/fraud.html` | filters form, local table paging, back-to-top, sound toggle, scroll memory, POST forms | `admin_table.js` + `admin_forms.js` |

## Lot 2 changes

- Added explicit page guards in `admin_table.js`:
  - `window.__ADM_DELIVERIES_INIT__`
  - `window.__ADM_FRAUD_INIT__`
  - `document.body.dataset.admDeliveriesInit = "1"`
  - `document.body.dataset.admFraudInit = "1"`
- Kept existing hard-navigation fallback (`window.location.href = url`) on admin table AJAX failures.
- Kept ownership rule already present in templates:
  - `data-ajax-owner="admin"` on `deliveries.html` and `fraud.html`.
- Updated admin CSRF bridge path:
  - `admin_forms.js` now prefers `window.BMAjaxCSRF.withCsrfHeaders` and falls back to `addToHeaders`.
  - `bm_csrf.js` now exposes `withCsrfHeaders` alias.

## Proofs (rg)

Commands/results:

```bash
rg -n "<script" dealnova/app/templates/admin/deliveries.html dealnova/app/templates/admin/fraud.html
# NO_MATCH (before and after)

rg -n "requestJSON|requestText|withCsrfHeaders" dealnova/app/templates/admin/deliveries.html dealnova/app/templates/admin/fraud.html
# NO_MATCH (before and after)

rg -n "data-ajax-owner" dealnova/app/templates/admin/deliveries.html dealnova/app/templates/admin/fraud.html
# deliveries:4, fraud:5

rg -n "adm-" dealnova/app/templates/admin/deliveries.html dealnova/app/templates/admin/fraud.html
# matches present for adm-listing/adm-filters/adm-pager/adm-back-to-top

rg -n "admin_table\\.js|admin_forms\\.js" dealnova/app/templates/admin/base.html
# admin/base.html:910-911
```

## Risk and rollback

- Risk: low (no HTML structure or route changes).
- Rollback:
  1. `git checkout -- dealnova/app/static/js/admin/admin_table.js`
  2. `git checkout -- dealnova/app/static/js/admin/admin_forms.js`
  3. `git checkout -- dealnova/app/static/js/ajax/core/bm_csrf.js`
