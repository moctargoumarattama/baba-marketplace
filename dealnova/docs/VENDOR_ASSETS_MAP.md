# Vendor Assets Map

## Scope
Inventory generated for:
- `dealnova/app/templates/vendor/*.html`
- `dealnova/app/templates/vendor/partials/*.html`

This map is focused on CSS/JS loading, inline blocks, and safe migration candidates.

## Global Asset Order (loaded via `templates/base.html`)
All vendor pages that extend `base.html` (or `vendor/base.html`) load these assets in this order:

### CSS (head)
1. `vendor/bootstrap/5.3.3/css/bootstrap.min.css`
2. `vendor/bootstrap-icons/1.11.1/font/bootstrap-icons.css`
3. `vendor/fontawesome/6.4.0/css/all.min.css`
4. `fonts/public.css`
5. `css/ui_shell.css`
6. `css/ui_drawer_glass.css`

Notes:
- `css/ui_home_tabs.css` is conditional and not loaded on vendor routes.
- Vendor pages mostly rely on inline `<style>`.

### JS (head, `defer`)
1. `js/core/core_dom.js`
2. `js/core/core_ui.js`
3. `js/core/core_cart.js`
4. `js/core/core_live.js`
5. `js/live.js`
6. `js/i18n.js`
7. `js/ajax_pagination.js`
8. `js/ui_drawer.js`

### JS (end of body)
9. `vendor/bootstrap/5.3.3/js/bootstrap.bundle.min.js`
10. `js/ui_shell.js`
11. Page block scripts (usually inline)

## Pages -> Assets -> Inline
| Template | Main route(s) | Extra CSS file(s) | Extra JS file(s) | Inline `<style>` | Inline `<script>` | Notes |
|---|---|---|---|---:|---:|---|
| `vendor/dashboard.html` | `/vendor/dashboard` | none | none | 1 block (~1459 lines) | 1 block (~411 lines) | Includes `vendor/partials/_product_grid.html`; AJAX search + polling |
| `vendor/manage_shop.html` | `/vendor/shop/manage` | none | none | 1 block (~856 lines) | 1 block (~251 lines) | Large UI logic (search/filter, geolocation, ripple, counters) |
| `vendor/earnings.html` | `/vendor/earnings` | `css/vendor/vendor_shell.css` (via `vendor/base.html`) | `js/vendor/vendor_shell.js`, `js/pages/vendor/earnings_page.js` | 1 block (~1161 lines) | 0 (migrated to page JS) | Toast + auto-refresh + quick search + scroll memory |
| `vendor/product_form.html` | `/vendor/product/new`, `/vendor/product/<id>/edit` | none | none | 1 block (~619 lines) | 1 block (~328 lines) | Complex form behavior in inline JS |
| `vendor/order_detail.html` | `/vendor/order/<id>` | none | none | 1 block (~314 lines) | 0 | CSS-only customizations |
| `vendor/edit_shop.html` | `/vendor/shop/edit` | none | none | 1 block (~148 lines) | 0 | CSS-only page styles |
| `vendor/periods.html` | `/vendor/periods` | none | none | 1 block (~72 lines) | 0 | CSS-only page styles |
| `vendor/period_close_confirm.html` | `/vendor/periods/close/<id>?confirm=1` | none | none | 1 block (~45 lines) | 0 | CSS-only page styles |
| `vendor/security.html` | `/vendor/security` | none | none | 1 block (~53 lines) | 0 | CSS-only page styles |
| `vendor/create_shop.html` | `/vendor/shop/create` | none | none | 0 | 0 | Uses global styles only |
| `vendor/partials/_product_grid.html` | Included by dashboard + `/vendor/products/search` response | none | none | 0 | 1 block (~9 lines) | Image placeholder fallback binding |

## Duplications and Centralization Candidates

### CSS selector overlaps (same class names in multiple vendor pages)
- `.search-input` -> `dashboard.html`, `earnings.html`
- `.search-clear` -> `dashboard.html`, `earnings.html`
- `.stat-card` -> `dashboard.html`, `manage_shop.html`
- `.stats-grid` / `.stat-value` / `.stat-label` -> `dashboard.html`, `earnings.html`
- `.form-card` / `.form-label` / `.btn-back` -> `edit_shop.html`, `product_form.html`

Risk:
- Medium. Same selector names with different declarations can diverge behavior between pages and complicate maintenance.

### JS logic overlaps (behavior-level)
- Confirm submit behavior around `form[data-confirm]` appears in dashboard logic and repeated across vendor forms.
- Search/filter loops are implemented independently in dashboard, manage_shop, and earnings.
- Periodic refresh appears in dashboard and earnings with separate timer logic.
- Toast-like feedback is page-specific (dashboard stock toast vs earnings toast), but structurally similar.

Risk:
- Medium. Similar behavior is maintained in multiple places; bug fixes can drift.

### Inline-heavy hotspots
- `vendor/dashboard.html`, `vendor/manage_shop.html`, `vendor/product_form.html` carry most inline CSS/JS volume.
- `vendor/earnings.html` still carries a large inline CSS block, but JS has been migrated to page script.

Risk:
- High for maintainability, medium for runtime regressions.

### Specific functional risk observed
- `vendor/partials/_product_grid.html` contains inline script with `DOMContentLoaded`; when this partial is injected via `innerHTML` after AJAX search, that script may not execute in some flows.

Risk:
- Medium. Can cause inconsistent image fallback behavior after dynamic refresh.

## Safe migration candidates (first wave)
- Shared CSS shell candidates:
  - Empty state (`.empty-state`, `.empty-icon`, `.empty-title`, `.empty-text`)
  - Loading overlay (`.loading-overlay`, `.spinner`)
- Shared JS shell candidates:
  - `form[data-confirm]` binding
  - Loading state toggler
  - Adaptive polling helper (pause/reduce cadence when page hidden)

## Migration status (POC)
- `vendor/dashboard.html`: migrated to `vendor/base.html` + uses `vendor_shell` helpers.
- `vendor/earnings.html`: migrated to `vendor/base.html` + dedicated page script `js/pages/vendor/earnings_page.js`.
