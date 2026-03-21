# ASSETS

Stable asset loading and cache policy.

## Versioning Rule

- Always load local static assets with:
  - `url_for('static', filename='...', v=app_static_version)`
- `app_static_version` is injected globally from Flask context.
- Do not hardcode asset versions in templates.

## Public Template Load Order

Source: `app/templates/base.html`

1. CSS vendor/fonts:
   - Bootstrap
   - Bootstrap Icons
   - Font Awesome
   - `fonts/public.css`
2. CSS app:
   - `css/tokens.css`
   - `css/ui_shell.css`
   - `css/ui_drawer_glass.css`
   - `css/ui_home_tabs.css` (home tabs only)
3. JS core (defer):
   - `js/core/core_dom.js`
   - `js/core/core_ui.js`
   - `js/core/core_cart.js`
   - `js/core/core_live.js`
   - `js/live.js`
   - `js/i18n.js`
   - `js/ajax_pagination.js`
   - `js/ui_drawer.js`
   - `js/ui_home_tabs.js` (home tabs only)
4. Bottom scripts:
   - Bootstrap bundle
   - `js/ui_shell.js`

## Admin Template Load Order

Source: `app/templates/admin/base.html`

1. CSS:
   - Bootstrap
   - Bootstrap Icons
   - `fonts/admin.css`
2. JS core (defer):
   - `js/core/core_dom.js`
   - `js/core/core_ui.js`
   - `js/core/core_cart.js`
   - `js/core/core_live.js`
   - `js/live.js`
3. Bottom scripts:
   - Bootstrap bundle
   - `js/admin/admin_helpers.js`

## Service Worker Rules

Source: `app/static/sw.js`

- Cache key uses static version from SW URL:
  - `CACHE_VERSION = dealnova-<v>`
- Old caches are removed on `activate`.
- Network-only (never cached): `/admin`, `/api`, `/courier`, `/vendor`, `/cart`, `/delivery`, auth routes, tracking routes.
- Critical static assets use network-first fallback.
- Browse-only public pages use network-first with cache fallback.
- Offline fallback page: `/static/offline.html`.
