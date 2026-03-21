# ADMIN UI Map

## Scope
- Templates scanned: `dealnova/app/templates/admin/*.html` + `dealnova/app/templates/admin/partials/*.html`
- Global base: `dealnova/app/templates/admin/base.html`
- Existing helper JS: `dealnova/app/static/js/admin/admin_helpers.js`

## Page Asset Snapshot
| Page | Inline CSS | Inline JS | Main role |
|---|---:|---:|---|
| `admin/all_orders.html` | 1 | 0 (migrated to `admin_table.js`) | Orders list + AJAX pagination |
| `admin/deliveries.html` | 1 | 1 | Delivery ops + filters + AJAX pagination |
| `admin/catalog_quality.html` | 1 | 1 | Catalog QA + AJAX actions + AJAX pagination |
| `admin/reconciliation.html` | 1 | 1 | Reconciliation + scroll memory + AJAX pagination |
| `admin/logs.html` | 1 | 1 (+ JSON script tags) | Logs + AJAX pagination |
| `admin/fraud.html` | 1 | 1 | Fraud monitor + local pager |
| `admin/pricing.html` | 1 | 1 | Pricing settings + back-to-top + scroll memory |
| `admin/shops.html` | 1 | 0 | Shops overview |
| `admin/users.html` | 1 | 0 | Users overview |
| `admin/base.html` | 1 | 1 large global script | Global shell + common behavior |

## Component -> Pages -> CSS/JS Logic
| Component | Pages using it | Repeated CSS patterns | Repeated JS logic |
|---|---|---|---|
| Hero panel | `all_orders`, `deliveries`, `catalog_quality`, `reconciliation`, `shops`, `users` | gradient background, rounded shell, border, subtle shadow | none/low |
| Stat cards | `all_orders`, `shops`, `users`, `catalog_quality`, `reconciliation` | card shell, icon tile, value/title typography | live stat refresh in some pages |
| Table shell | `all_orders`, `deliveries`, `catalog_quality`, `logs`, `locations`, `maintenance` | white container, header bar, responsive table/list | AJAX partial swap + rebind |
| Filter bar | `all_orders`, `deliveries`, `fraud`, `reconciliation`, `maintenance` | wrapped controls, spacing, form-select sizes | submit/reset patterns |
| Status/badge pills | `all_orders`, `deliveries`, `order_archives`, `deliveries_archives` | rounded badges, semantic colors | state toggles via forms |
| Pagination | almost all list pages | same paginator sizing + mobile wrapping | click intercept + fetch + replace + history |
| Back-to-top | `all_orders`, `deliveries`, `catalog_quality`, `fraud`, `pricing`, `reconciliation` | fixed circular FAB + show/hide | scroll threshold + click scrollTo |
| Scroll memory | `fraud`, `pricing`, `reconciliation`, `catalog_quality`, `categories`, `locations`, `logs` | none | save/restore Y or percentage |
| Confirm actions | global via `base.html` + some local handlers | none | confirm submit/click before mutating actions |
| Disable-on-submit | several pages locally | button visual state | prevent double-submit |

## Top 10 Duplications (and expected gain)
1. AJAX pagination fetch/DOM swap repeated in 5+ pages.
   Gain: one `admin_table.js` API for bind/swap/rebind.
2. Back-to-top duplicated UI + JS in 6 pages.
   Gain: one component class + one helper init.
3. Scroll memory strategies repeated with small variants.
   Gain: shared helper usage (`AdminHelpers.initScrollMemory`) + page configs.
4. Hero shells reimplemented per page.
   Gain: common `adm-hero-shell` class.
5. Stat card shells/icons repeated.
   Gain: common `adm-stat-grid` and `adm-stat-card` classes.
6. Table container/header repeated.
   Gain: common `adm-table-shell` and `adm-table-header`.
7. Filter bar layout repeated.
   Gain: `adm-filter-bar` utility.
8. Badge/pill visual styles repeated.
   Gain: shared `adm-pill`/status utilities.
9. Form confirm and button lock logic repeated between base and pages.
   Gain: `admin_forms.js` helpers for opt-in migration.
10. Inline CSS volume high on many pages.
    Gain: progressive extraction to `admin_components.css` with rollback-friendly page-by-page migration.

## Migration Strategy (SAFE)
1. Add non-breaking shared tokens/components + shared admin JS modules.
2. Keep inline CSS/JS initially (fallback retained).
3. Migrate one page at a time to shared module calls.
4. Validate: pagination, filters, back-to-top, scroll restore, console clean.
5. Only then remove page-local duplicated blocks.

## POC Target Completed in this step
- `admin/all_orders.html` moved to shared JS init from `admin_table.js`.
- Shared CSS classes added without changing visual design.

## Next 3 Pages (recommended)
1. `admin/deliveries.html` (same AJAX pagination + back-to-top pattern).
2. `admin/catalog_quality.html` (AJAX actions + table refresh + paginator).
3. `admin/reconciliation.html` (pagination + heavy scroll-memory logic).
