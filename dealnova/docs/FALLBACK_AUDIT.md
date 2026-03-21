# Fallback Audit (SAFE)

Date: 2026-03-04
Scope scanned:
- `dealnova/app/static/js/ajax/`
- `dealnova/app/static/js/ajax_pagination.js`
- `dealnova/app/static/js/pages/`
- `dealnova/app/static/js/vendor/`
- `dealnova/app/static/js/core/`

## Plan A loading proof
Core AJAX scripts are loaded globally before page scripts:
- `dealnova/app/templates/base.html:30-33` (`bm_csrf.js`, `bm_guard.js`, `bm_fetch.js`, `bm_swap.js`)
- `dealnova/app/templates/admin/base.html:766-769` (same core stack)
- `dealnova/app/templates/base.html:38` (`ajax_pagination.js`)
- `dealnova/app/templates/vendor/base.html:10` (`vendor_shell.js`)
- Page scripts:
  - `dealnova/app/templates/shop/home.html:552`
  - `dealnova/app/templates/search/results.html:628`
  - `dealnova/app/templates/vendor/dashboard.html:509`

## Inventory table
| File:line | Fallback type | Reachable? | Recommendation |
|---|---|---|---|
| `shop_home_page.js` old `fallbackRequest()` (removed) | fetch fallback | NON (core guaranteed) | REMOVE (done) |
| `shop_home_page.js` old `__BM_SHOP_HOME_DISABLE_AJAX_CORE__` (removed) | feature-flag fallback | NON (0 refs) | REMOVE (done) |
| `shop_home_page.js:83-84` | request-seq local fallback | OUI (stale cache edge) | KEEP_FALLBACK |
| `shop_home_page.js:466,472` | hard navigation fallback | OUI (AJAX/container failure) | KEEP |
| `shop_home_page.js:476-477,511-512` | swap fallback branch | OUI (swap failure edge) | KEEP |
| `search_results_page.js` old fetch fallback in `requestJSON` (removed) | fetch fallback | NON (core guaranteed) | REMOVE (done) |
| `search_results_page.js:47` | request-seq local fallback | OUI (stale cache edge) | KEEP_FALLBACK |
| `search_results_page.js:163` | `missing_ajax_core` safe return | OUI (rare stale-cache edge) | KEEP |
| `vendor/dashboard_page.js` old `fallbackRequest()` (removed) | fetch fallback | NON (core + vendor shell guaranteed) | REMOVE (done) |
| `vendor/dashboard_page.js:90,106` | `missing_ajax_core` safe return | OUI (rare edge) | KEEP |
| `vendor/dashboard_page.js:114-116` | request-seq fallback to `BMAjaxGuard` | OUI (VendorUI load-order edge) | KEEP_FALLBACK |
| `ajax_pagination.js` native `fetch` fallback in `fetchHtml` (removed) | fetch fallback | NON (core guaranteed) | REMOVE (done) |
| `ajax_pagination.js` DOM `replaceWith` fallback (removed) | swap fallback | NON (core guaranteed) | REMOVE (done) |
| `ajax_pagination.js:155` | local request-seq fallback | OUI (stale cache edge) | KEEP_FALLBACK |
| `ajax_pagination.js:177,183,214` | hard navigation fallback | OUI (cross-origin/network/invalid payload) | KEEP |
| `core/core_cart.js:27` | fallbackRequestJSON | OUI (core_cart not in this cleanup lot) | KEEP (next lot candidate) |
| `pages/cart_page.js:26` | fallbackRequest | OUI (cart not in this cleanup lot) | KEEP (next lot candidate) |
| `pages/shop_detail_page.js:34` | fallbackRequest | OUI (shop_detail not in this cleanup lot) | KEEP (next lot candidate) |

## Reachability checks used
- Script loading proof via template references (`base.html`, `admin/base.html`, `vendor/base.html`).
- 0-ref check (done):
  - `__BM_SHOP_HOME_DISABLE_AJAX_CORE__` had no references outside `shop_home_page.js` and was removed.

## Changes executed in this pass (Lot 1)
1. Removed duplicated native-fetch fallback wrappers in:
   - `dealnova/app/static/js/pages/shop_home_page.js`
   - `dealnova/app/static/js/pages/search_results_page.js`
   - `dealnova/app/static/js/pages/vendor/dashboard_page.js`
2. Removed duplicated native-fetch + direct-DOM swap fallback branches in:
   - `dealnova/app/static/js/ajax_pagination.js`
3. Kept only strategic fallbacks (`KEEP_FALLBACK`) for request sequencing and hard navigation safety.
