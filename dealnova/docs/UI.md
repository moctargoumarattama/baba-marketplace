# UI

Current UI components and ownership map.

## Public Shell

- Layout/nav/global UI:
  - CSS: `app/static/css/ui_shell.css`
  - JS: `app/static/js/ui_shell.js`
- Global design tokens:
  - CSS: `app/static/css/tokens.css` (loaded before shell)

## Drawer Glass (mobile menu)

- CSS source of truth:
  - `app/static/css/ui_drawer_glass.css`
- JS behavior:
  - `app/static/js/ui_drawer.js`
- Scope:
  - Mobile drawer/collapse/overlay interactions only.

## Home Bottom Tabs

- CSS source of truth:
  - `app/static/css/ui_home_tabs.css`
- JS behavior:
  - `app/static/js/ui_home_tabs.js`
- Compatible classes:
  - `.home-bottom-tabs` + `.bm-home-tabs`
  - `.home-tab` + `.bm-home-tab`

## Home Page Shell

- CSS:
  - `app/static/css/home_shell.css`
- JS:
  - `app/static/js/home_shell.js`
- Scope:
  - Home hero, cards, home-only layout polish.

## Live/Core JS

- `app/static/js/core/core_dom.js`:
  - DOM helpers, shared page helpers.
- `app/static/js/core/core_ui.js`:
  - toasts, confirms, UI utilities.
- `app/static/js/core/core_cart.js`:
  - cart/nav badges, notify polling.
- `app/static/js/core/core_live.js`:
  - adaptive polling + ajax form handlers.
  - heavy polling gated by `data-page` and page context.
- `app/static/js/live.js`:
  - compatibility bootstrap wrapper.

## Naming Rule

- New UI classes must be prefixed:
  - `bm-` or `bmui-`
- Reference:
  - `docs/ui_naming.md`
