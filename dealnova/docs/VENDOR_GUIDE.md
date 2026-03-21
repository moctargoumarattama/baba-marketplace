# Vendor Guide

## 1) Where vendor CSS lives
- Shared vendor CSS shell:
  - `dealnova/app/static/css/vendor/vendor_shell.css`
- Page-specific CSS:
  - `dealnova/app/static/css/vendor/vendor_earnings_page.css` (used by `vendor/earnings.html`)
  - Inline `<style>` blocks may still exist on non-migrated vendor pages

Current rollout:
- `vendor_shell.css` is wired through `dealnova/app/templates/vendor/base.html`.
- `vendor/dashboard.html`, `vendor/earnings.html`, and `vendor/manage_shop.html` already extend `vendor/base.html`.
- `vendor/earnings.html` now uses page JS: `dealnova/app/static/js/pages/vendor/earnings_page.js`.
- `vendor/earnings.html` now loads page CSS from `dealnova/app/static/css/vendor/vendor_earnings_page.css`.
- `vendor/manage_shop.html` now uses page JS: `dealnova/app/static/js/pages/vendor/manage_shop_page.js`.

## 2) Where vendor JS lives
- Shared vendor JS shell:
  - `dealnova/app/static/js/vendor/vendor_shell.js`
- Page-specific JS:
  - Inline `<script>` blocks in non-migrated vendor templates
  - Future target: `dealnova/app/static/js/pages/vendor/<page>_page.js`
  - Active examples:
    - `dealnova/app/static/js/pages/vendor/earnings_page.js`
    - `dealnova/app/static/js/pages/vendor/manage_shop_page.js`

Current shell globals:
- `window.VendorUI.initOnce()`
- `window.VendorUI.toast(message, type)`
- `window.VendorUI.setLoadingState(node, active, className?)`
- `window.VendorUI.bindConfirmForms(root?)`
- `window.VendorUI.startAdaptivePoll(key, fn, options?)`
- `window.VendorUI.stopAdaptivePoll(key)`
- `window.VendorUI.rafThrottle(fn)`

## 3) How to add a vendor feature safely
1. Keep business logic in routes/services; UI behavior only in vendor JS.
2. If reusable on 2+ vendor pages, place it in `vendor_shell.js` / `vendor_shell.css`.
3. If page-specific, keep it in page-level script (or move to `pages/vendor/...`).
4. Use null guards for DOM nodes.
5. For server config in JS, use JSON-safe injection (`|tojson`) in template.
6. Avoid global selectors when a page root is available.

## 4) Debug checklist for vendor bugs
1. Console:
   - Check for `ReferenceError`, duplicate init, or missing global API calls.
2. Network:
   - Confirm versioned assets (`?v={{ app_static_version }}`) are loaded.
3. Cache/SW:
   - If stale behavior appears, verify current static version and SW cache rotation.
4. Init flags:
   - Validate `window.__BM_VENDOR_INIT__` and `window.VendorUI`.
5. Dynamic content:
   - Re-bind interactions after AJAX/HTML replacement when needed.
6. Mobile:
   - Ensure scroll listeners are passive or RAF-throttled.
7. Earnings page specific:
   - Confirm `vendor_earnings_page.css` is loaded in Network.
   - Confirm `window.__BM_VENDOR_EARNINGS_INIT__ === true` after page load.
   - If pagination/filter ajax fails, ensure `window.BMAjaxFetch` is available; otherwise native fetch fallback is used.

## 5) Conventions (vendor)
- Shared/global vendor layer:
  - `vendor_shell.css`
  - `vendor_shell.js`
- Page layer:
  - `js/pages/vendor/<page>_page.js` (active pattern)
- Template config:
  - `<script type="application/json" id="...">{{ ...|tojson }}</script>`
- Naming:
  - Prefer vendor-scoped naming for new classes (`vendor-*` or `bm-vendor-*`).
- Safety:
  - No aggressive refactor in one pass; migrate page-by-page with rollback path.
