# Front Fluidity Audit

Date: March 10, 2026

## Scope

Pages analyzed in priority for LOT 2:

- `/shop`
- `/shop/shops`
- `/locations`
- `/search`
- `/vendor/dashboard`
- `/vendor/earnings`

Files audited in detail:

- `dealnova/app/static/js/pages/shop_home_page.js`
- `dealnova/app/static/js/pages/search_results_page.js`
- `dealnova/app/static/js/pages/locations_index_page.js`
- `dealnova/app/static/js/pages/vendor/dashboard_page.js`
- `dealnova/app/static/js/pages/vendor/earnings_page.js`
- `dealnova/app/static/js/ui_shell.js`
- `dealnova/app/static/js/ajax/features/polling.js`
- `dealnova/app/static/js/vendor/vendor_shell.js`

## Main Causes Found

### 1. `/search` did too much work per keystroke

- Product, shops, categories and locations requests were launched together as soon as the query reached 2 characters.
- Secondary branches were still queried when they were not useful yet.
- Result rendering was committed directly with `innerHTML` after each request cycle instead of batching to one visual commit.
- Search pills used one listener per pill.

Impact:

- Extra network and parsing load.
- More frequent DOM replacement than needed.
- Higher chance of stale visual work when typing quickly.

### 2. `/shop` still did expensive HTML listing swaps

- Listing refresh parsed a full HTML response, then re-serialized and replaced the listing container content.
- Product and pagination handlers were rebound by rescanning the document after each listing refresh.
- Product cards and add-to-cart forms used per-element listeners.
- Two window `scroll` listeners were active for the same page.
- Live search debounce was still high at 350 ms.

Impact:

- Extra parsing and DOM work after filter/search/pagination.
- More listeners than needed on a page with many cards.
- Perceived latency on live search and paging.

### 3. Global offline UI scans in `ui_shell.js` were broad

- `refreshOnlineRequiredUI()` rescanned all `[data-requires-online]`, all anchors, and all forms each time it ran.
- The scan was repeated even when the set of relevant nodes had not changed.

Impact:

- Broad document queries from a global script.
- Unnecessary DOM traversal on pages using AJAX replacement.

### 4. Vendor dashboard updated more DOM than necessary

- Category chips were bound one by one.
- Category refresh removed and recreated dynamic chips without any equality check.
- Product search could fully replace the HTML even when the response did not change.
- Live orders refresh updated counters, three lists and three pagers every cycle, even when the payload was effectively identical.
- Stats refresh rewrote KPI text even when values stayed the same.

Impact:

- Repeated render cost on a page that also polls.
- More event listeners than necessary.
- More layout/repaint work during live refreshes.

### 5. Vendor earnings added many touch listeners per refresh

- Touch feedback was attached to each `.stat-tile`, `.product-pill`, and `.pagination-item`.
- The page root is replaced on AJAX navigation/refresh, so this binding work repeated after each swap.

Impact:

- Avoidable listener churn on mobile.

### 6. Pollings were hidden-safe but not explicitly page/container gated

Pollings audited:

- `ui_shell.js`: nav badges
- `vendor/dashboard_page.js`: stats
- `vendor/dashboard_page.js`: stock checks
- `vendor/dashboard_page.js`: live orders
- `vendor/earnings_page.js`: auto refresh

Observed issue:

- They already paused on hidden tabs in most cases.
- They were not all explicitly guarded by current page identity plus required container presence.

Impact:

- Safe today because scripts are page-scoped in practice, but stricter gating was still missing.

## Listeners Audit

High-signal listener groups reviewed:

- `shop_home_page.js`
  - `window.scroll`
  - `window.resize`
  - delegated product/search interactions
  - pagination click bindings
- `search_results_page.js`
  - search `input`
  - per-pill click bindings
- `ui_shell.js`
  - global click
  - global submit
  - `online` / `offline`
  - `visibilitychange`
- `vendor/dashboard_page.js`
  - category chip click bindings
  - dashboard pager delegation
- `vendor/earnings_page.js`
  - touch feedback bindings
  - `scroll` / `resize`
  - `visibilitychange`

## Pollings Audit

Logical pollings identified:

1. `ui-shell-nav-badges`
2. `vendor-dashboard-stats`
3. `vendor-dashboard-stock`
4. `vendor-dashboard-orders`
5. `vendor-earnings-refresh`

## Swaps / Rendering Audit

### Heavy or broad swaps found

- `/shop`: listing refresh consumed a full HTML page response and replaced listing content after extra serialization.
- `/vendor/dashboard`: categories block was rebuilt with repeated append operations; orders/stats were re-rendered without value/signature checks.
- `/vendor/earnings`: root replacement is intentional and was kept because partial refactor would be riskier in this lot.

### Already intentionally left unchanged

- `/shop/shops` and `/locations` already rely on targeted AJAX listing/pagination swaps from the shared listing layer.
- `/vendor/earnings` still swaps the page root because there is no lighter safe partial contract in this lot.
- `/shop` listing still fetches HTML, not JSON, because backend endpoints were out of scope by rule.

## Risk Notes

Not forced in this lot because risk was higher than value:

- Converting `/shop` listing fetch from HTML to JSON.
- Refactoring `/vendor/earnings` to partial block refreshes.
- Refactoring `/vendor/dashboard` product search endpoint away from HTML.
- Removing global `ui_shell.js` interception listeners that enforce offline and confirmation safety.

## Test Status

No browser test run in this environment.

Not verified here:

- mobile tap feel on a real phone
- browser console red errors
- back/forward behavior on all target pages

`node` was not available here, so no `node --check` validation was possible.
