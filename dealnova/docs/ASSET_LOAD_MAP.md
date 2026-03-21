# Asset Load Map

Date: 2026-03-05
Scope: `templates/base.html`, `templates/admin/base.html`, `templates/vendor/base.html`
Mode: audit + sizing (bytes)

## 1) Assets Included by Shell

### base.html

| Type | Asset | Size (bytes) |
|---|---|---:|
| js | `js/core/core_dom.js` | 4,422 |
| js | `js/core/core_ui.js` | 4,929 |
| js | `js/ajax/core/bm_csrf.js` | 1,738 |
| js | `js/ajax/core/bm_guard.js` | 1,934 |
| js | `js/ajax/core/bm_fetch.js` | 5,002 |
| js | `js/ajax/core/bm_swap.js` | 1,603 |
| js | `js/core/page_loader.js` | 9,770 |
| js | `js/i18n.js` | 6,618 |
| js | `js/ui_drawer.js` | 4,345 |
| js | `js/ui_home_tabs.js` | 1,391 |
| js | `vendor/bootstrap/5.3.3/js/bootstrap.bundle.min.js` | 80,721 |
| js | `js/ui_shell.js` | 40,922 |
| css | `vendor/bootstrap/5.3.3/css/bootstrap.min.css` | 232,803 |
| css | `vendor/bootstrap-icons/1.11.1/font/bootstrap-icons.css` | 98,255 |
| css | `vendor/fontawesome/6.4.0/css/all.min.css` | 102,025 |
| css | `fonts/public.css` | 20,604 |
| css | `css/ui_shell.css` | 40,588 |
| asset | `manifest.json` | 373 |
| css | `css/ui_drawer_glass.css` | 8,811 |
| css | `css/ui_home_tabs.css` | 3,565 |

### admin.html

| Type | Asset | Size (bytes) |
|---|---|---:|
| js | `js/core/core_dom.js` | 4,422 |
| js | `js/core/core_ui.js` | 4,929 |
| js | `js/ajax/core/bm_csrf.js` | 1,738 |
| js | `js/ajax/core/bm_guard.js` | 1,934 |
| js | `js/ajax/core/bm_fetch.js` | 5,002 |
| js | `js/ajax/core/bm_swap.js` | 1,603 |
| js | `js/core/page_loader.js` | 9,770 |
| js | `vendor/bootstrap/5.1.3/js/bootstrap.bundle.min.js` | 78,129 |
| js | `js/admin/admin_helpers.js` | 6,027 |
| css | `vendor/bootstrap/5.1.3/css/bootstrap.min.css` | 163,873 |
| css | `vendor/bootstrap-icons/1.8.1/font/bootstrap-icons.css` | 80,510 |
| css | `fonts/admin.css` | 12,499 |
| css | `css/admin/admin_tokens.css` | 1,291 |
| css | `css/admin/admin_components.css` | 7,422 |

### vendor.html

| Type | Asset | Size (bytes) |
|---|---|---:|
| js | `js/vendor/vendor_shell.js` | 11,392 |
| css | `css/vendor/vendor_shell.css` | 1,314 |

## 2) Global Static References (Aggregated)

| Asset | Type | Size (bytes) | Loaded in | Suspicion |
|---|---|---:|---|---|
| `manifest.json` | asset | 373 | base | LOW |
| `vendor/bootstrap/5.3.3/css/bootstrap.min.css` | css | 232,803 | base | LOW (framework core) |
| `vendor/bootstrap/5.1.3/css/bootstrap.min.css` | css | 163,873 | admin | LOW (framework core) |
| `vendor/fontawesome/6.4.0/css/all.min.css` | css | 102,025 | base | LOW |
| `vendor/bootstrap-icons/1.11.1/font/bootstrap-icons.css` | css | 98,255 | base | LOW (framework core) |
| `vendor/bootstrap-icons/1.8.1/font/bootstrap-icons.css` | css | 80,510 | admin | LOW (framework core) |
| `css/ui_shell.css` | css | 40,588 | base | LOW |
| `fonts/public.css` | css | 20,604 | base | LOW |
| `fonts/admin.css` | css | 12,499 | admin | LOW |
| `css/ui_drawer_glass.css` | css | 8,811 | base | LOW |
| `css/admin/admin_components.css` | css | 7,422 | admin | LOW |
| `css/ui_home_tabs.css` | css | 3,565 | base | LOW |
| `css/vendor/vendor_shell.css` | css | 1,314 | vendor | LOW |
| `css/admin/admin_tokens.css` | css | 1,291 | admin | LOW |
| `vendor/bootstrap/5.3.3/js/bootstrap.bundle.min.js` | js | 80,721 | base | LOW (framework core) |
| `vendor/bootstrap/5.1.3/js/bootstrap.bundle.min.js` | js | 78,129 | admin | LOW (framework core) |
| `js/ui_shell.js` | js | 40,922 | base | LOW (global shell behavior) |
| `js/vendor/vendor_shell.js` | js | 11,392 | vendor | LOW |
| `js/core/page_loader.js` | js | 9,770 | admin, base | LOW-MEDIUM (shared script across shells) |
| `js/i18n.js` | js | 6,618 | base | LOW |
| `js/admin/admin_helpers.js` | js | 6,027 | admin | LOW |
| `js/ajax/core/bm_fetch.js` | js | 5,002 | admin, base | LOW-MEDIUM (shared script across shells) |
| `js/core/core_ui.js` | js | 4,929 | admin, base | LOW-MEDIUM (shared script across shells) |
| `js/core/core_dom.js` | js | 4,422 | admin, base | LOW-MEDIUM (shared script across shells) |
| `js/ui_drawer.js` | js | 4,345 | base | LOW |
| `js/ajax/core/bm_guard.js` | js | 1,934 | admin, base | LOW-MEDIUM (shared script across shells) |
| `js/ajax/core/bm_csrf.js` | js | 1,738 | admin, base | LOW-MEDIUM (shared script across shells) |
| `js/ajax/core/bm_swap.js` | js | 1,603 | admin, base | LOW-MEDIUM (shared script across shells) |
| `js/ui_home_tabs.js` | js | 1,391 | base | LOW |

## 3) Top 15 JS Loaded by Shells

| # | Asset | Size (bytes) | Loaded in | Suspicion |
|---:|---|---:|---|---|
| 1 | `vendor/bootstrap/5.3.3/js/bootstrap.bundle.min.js` | 80,721 | base | LOW (framework core) |
| 2 | `vendor/bootstrap/5.1.3/js/bootstrap.bundle.min.js` | 78,129 | admin | LOW (framework core) |
| 3 | `js/ui_shell.js` | 40,922 | base | LOW (global shell behavior) |
| 4 | `js/vendor/vendor_shell.js` | 11,392 | vendor | LOW |
| 5 | `js/core/page_loader.js` | 9,770 | admin, base | LOW-MEDIUM (shared script across shells) |
| 6 | `js/i18n.js` | 6,618 | base | LOW |
| 7 | `js/admin/admin_helpers.js` | 6,027 | admin | LOW |
| 8 | `js/ajax/core/bm_fetch.js` | 5,002 | admin, base | LOW-MEDIUM (shared script across shells) |
| 9 | `js/core/core_ui.js` | 4,929 | admin, base | LOW-MEDIUM (shared script across shells) |
| 10 | `js/core/core_dom.js` | 4,422 | admin, base | LOW-MEDIUM (shared script across shells) |
| 11 | `js/ui_drawer.js` | 4,345 | base | LOW |
| 12 | `js/ajax/core/bm_guard.js` | 1,934 | admin, base | LOW-MEDIUM (shared script across shells) |
| 13 | `js/ajax/core/bm_csrf.js` | 1,738 | admin, base | LOW-MEDIUM (shared script across shells) |
| 14 | `js/ajax/core/bm_swap.js` | 1,603 | admin, base | LOW-MEDIUM (shared script across shells) |
| 15 | `js/ui_home_tabs.js` | 1,391 | base | LOW |

## 4) Top 15 CSS Loaded by Shells

| # | Asset | Size (bytes) | Loaded in | Suspicion |
|---:|---|---:|---|---|
| 1 | `vendor/bootstrap/5.3.3/css/bootstrap.min.css` | 232,803 | base | LOW (framework core) |
| 2 | `vendor/bootstrap/5.1.3/css/bootstrap.min.css` | 163,873 | admin | LOW (framework core) |
| 3 | `vendor/fontawesome/6.4.0/css/all.min.css` | 102,025 | base | LOW |
| 4 | `vendor/bootstrap-icons/1.11.1/font/bootstrap-icons.css` | 98,255 | base | LOW (framework core) |
| 5 | `vendor/bootstrap-icons/1.8.1/font/bootstrap-icons.css` | 80,510 | admin | LOW (framework core) |
| 6 | `css/ui_shell.css` | 40,588 | base | LOW |
| 7 | `fonts/public.css` | 20,604 | base | LOW |
| 8 | `fonts/admin.css` | 12,499 | admin | LOW |
| 9 | `css/ui_drawer_glass.css` | 8,811 | base | LOW |
| 10 | `css/admin/admin_components.css` | 7,422 | admin | LOW |
| 11 | `css/ui_home_tabs.css` | 3,565 | base | LOW |
| 12 | `css/vendor/vendor_shell.css` | 1,314 | vendor | LOW |
| 13 | `css/admin/admin_tokens.css` | 1,291 | admin | LOW |

## 5) Cibles Rapides (P1/P2)

| Asset | Loaded in | Why target |
|---|---|---|

## 6) Notes
- Core AJAX (`bm_csrf`, `bm_guard`, `bm_fetch`, `bm_swap`) stays globally loaded.
- Conditional loader is the preferred path for heavy runtime scripts (live/pagination/forms/admin table).
