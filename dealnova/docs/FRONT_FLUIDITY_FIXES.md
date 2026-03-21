# Front Fluidity Fixes

Date: March 10, 2026

## Rollback

This lot is gated by a front flag added in `base.html`:

- `window.BM_PERF_FLAGS.frontFluidity`

Default:

- `true`

Rollback:

- set `frontFluidity: false` in `window.BM_PERF_FLAGS` defaults in `dealnova/app/templates/base.html`
- or override `window.BM_PERF_FLAGS.frontFluidity = false` before page scripts run

## Files Touched

- `dealnova/app/templates/base.html`
- `dealnova/app/static/js/pages/search_results_page.js`
- `dealnova/app/static/js/pages/shop_home_page.js`
- `dealnova/app/static/js/ui_shell.js`
- `dealnova/app/static/js/ajax/features/polling.js`
- `dealnova/app/static/js/vendor/vendor_shell.js`
- `dealnova/app/static/js/pages/vendor/dashboard_page.js`
- `dealnova/app/static/js/pages/vendor/earnings_page.js`

## Corrections Applied

### 1. Global rollback flag

File:

- `dealnova/app/templates/base.html`

Before:

- LOT 2 changes had no dedicated front fluidity flag.

After:

- added `frontFluidity: true` to `window.BM_PERF_FLAGS`

### 2. `/search` live search tightened

File:

- `dealnova/app/static/js/pages/search_results_page.js`

Before:

- 4 branches could fire from 2 characters
- direct result DOM commits
- per-pill listeners
- 300 ms debounce

After:

- products still query from 2 characters
- shops, categories and locations now wait for 3 characters
- one RAF-batched DOM commit per result cycle
- stale requests still aborted/ignored
- search pills now use one delegated listener
- debounce reduced to 240 ms under the fluidity flag

Net effect:

- less network work
- fewer useless result swaps
- less chance of stale UI catching up after fast typing

### 3. `/shop` listing swaps made more targeted

File:

- `dealnova/app/static/js/pages/shop_home_page.js`

Before:

- full parsed HTML was re-serialized back into container HTML
- product events were rebound by rescanning the page after listing updates
- pagination clicks were bound per link
- 2 separate scroll listeners on the page
- live search debounce was 350 ms

After:

- parsed HTML is reused directly
- only `#productsGrid` and `#paginationContainer` are replaced/updated
- append mode now appends cards through a fragment
- product add-to-cart submit and card navigation are delegated from `#productsContainer`
- pagination click is delegated from `#paginationContainer`
- duplicated category chip binding is guarded
- the page uses one merged scroll listener for scroll-top + page badge
- live search debounce reduced to 250 ms under the fluidity flag

Net effect:

- less DOM churn after filters/search/pagination
- fewer listeners on large product lists
- slightly faster live search feedback

### 4. Global offline-required scan cached

File:

- `dealnova/app/static/js/ui_shell.js`

Before:

- every refresh of offline-required UI rescanned all candidate anchors/forms/buttons

After:

- candidate nodes are cached
- cache is invalidated on `ajax:page-replaced`
- nav badge polling now uses strict `when` gating on its badge root

Net effect:

- less global DOM traversal on pages using AJAX replacement

### 5. Shared polling helpers now support strict gating

Files:

- `dealnova/app/static/js/ajax/features/polling.js`
- `dealnova/app/static/js/vendor/vendor_shell.js`

Before:

- polling helpers handled timing and hidden tabs, but not page/container eligibility

After:

- added optional `when()` gating
- added inactive reschedule path when polling is not eligible

Net effect:

- no work is done when the required page/container is gone

### 6. `/vendor/dashboard` render work reduced

File:

- `dealnova/app/static/js/pages/vendor/dashboard_page.js`

Before:

- category chip click bindings were per-chip
- category refresh always rebuilt dynamic chips
- product search could replace identical HTML
- stats always rewrote KPI values
- orders refresh rewrote lists/pagers even when content was unchanged
- pollings were not explicitly page/container gated

After:

- category chips now use one delegated container listener
- category refresh uses a fragment and skips identical category payloads
- product search skips full DOM replacement when returned HTML is unchanged
- stats refresh skips identical KPI payloads
- orders/pagers use batched DOM commits and signature guards to skip no-op rewrites
- dashboard search delay drops to 240 ms under the fluidity flag
- stats, stock and orders pollings are explicitly gated by page + container readiness
- fallback pollers use the same gating logic

Net effect:

- lighter live dashboard refresh
- less no-op rendering during polling

### 7. `/vendor/earnings` touch and polling work reduced

File:

- `dealnova/app/static/js/pages/vendor/earnings_page.js`

Before:

- touch feedback attached listeners to every matching tile/item after each root bind
- auto refresh was hidden-safe but not explicitly page gated

After:

- touch feedback is delegated from the page root
- auto refresh is explicitly gated by current page/root readiness
- fallback timer path respects the same gate

Net effect:

- less listener churn on repeated root swaps
- safer auto refresh behavior

## Counts

- Pollings gated: `5`
- Listener groups reduced or delegated: `7`
- Swaps/renders made more targeted: `2`

How the counts were measured:

- Pollings gated
  - `ui-shell-nav-badges`
  - `vendor-dashboard-stats`
  - `vendor-dashboard-stock`
  - `vendor-dashboard-orders`
  - `vendor-earnings-refresh`
- Listener groups reduced/delegated
  - `/search` pills
  - `/shop` merged scroll handling
  - `/shop` product submit delegation
  - `/shop` product card click delegation
  - `/shop` pagination click delegation
  - `/vendor/dashboard` category chip delegation
  - `/vendor/earnings` touch delegation
- Swaps/renders targeted
  - `/shop` grid + pagination targeted update
  - `/vendor/dashboard` categories block fragment refresh

## Risks / Limits

- `/shop` still fetches HTML because backend changes were forbidden.
- `/vendor/dashboard` product search still consumes server-rendered HTML.
- `/vendor/earnings` still swaps its root because a partial contract would be riskier.
- No backend or DB optimization was done in this lot.

## Verification Status

Not executed here:

- browser/manual checklist on `/shop`
- browser/manual checklist on `/shop/shops`
- browser/manual checklist on `/locations`
- browser/manual checklist on `/vendor/dashboard`
- browser/manual checklist on `/vendor/earnings`
- browser console audit for `0` red errors

Environment limitation:

- `node` unavailable, so no JS syntax check via `node --check`
