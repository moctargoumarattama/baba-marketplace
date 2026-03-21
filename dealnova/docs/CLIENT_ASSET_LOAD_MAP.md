# Client Asset Load Map

Date: 2026-03-05
Scope: `/shop` home, `/cart/checkout`, `/shop/shops`, `/locations` index
Method: template include map (base + page template) + `page_loader_client` dynamic map

## shop_home

Template: `app/templates/shop/home.html`
Endpoint: `shop.home`

### Scripts

| Asset | Size (bytes) | Class | Source |
|---|---:|---|---|
| `js/core/core_dom.js` | 4,422 | SUSPECT | GLOBAL(base) |
| `js/core/core_ui.js` | 4,929 | SUSPECT | GLOBAL(base) |
| `js/ajax/core/bm_csrf.js` | 1,738 | GLOBAL | GLOBAL(base) |
| `js/ajax/core/bm_guard.js` | 1,934 | GLOBAL | GLOBAL(base) |
| `js/ajax/core/bm_fetch.js` | 5,002 | GLOBAL | GLOBAL(base) |
| `js/ajax/core/bm_swap.js` | 1,603 | GLOBAL | GLOBAL(base) |
| `js/core/page_loader_client.js` | 7,444 | GLOBAL | GLOBAL(base) |
| `js/i18n.js` | 6,618 | SUSPECT | GLOBAL(base) |
| `js/ui_drawer.js` | 4,345 | GLOBAL | GLOBAL(base) |
| `vendor/bootstrap/5.3.3/js/bootstrap.bundle.min.js` | 80,721 | GLOBAL | GLOBAL(base) |
| `js/ui_shell.js` | 40,922 | GLOBAL | GLOBAL(base) |
| `js/ui_home_tabs.js` | 1,391 | PAGE-ONLY | GLOBAL(base) |
| `js/core/core_cart.js` | 10,697 | GLOBAL | PAGE-LOADER |
| `js/ajax_pagination.js` | 8,416 | SUSPECT | PAGE-LOADER |
| `js/pages/shop_home_page.js` | 49,463 | PAGE-ONLY | PAGE-LOADER |

### Styles

| Asset | Size (bytes) | Class | Source |
|---|---:|---|---|
| `vendor/bootstrap/5.3.3/css/bootstrap.min.css` | 232,803 | GLOBAL | GLOBAL(base) |
| `vendor/bootstrap-icons/1.11.1/font/bootstrap-icons.css` | 98,255 | GLOBAL | GLOBAL(base) |
| `vendor/fontawesome/6.4.0/css/all.min.css` | 102,025 | SUSPECT | GLOBAL(base) |
| `fonts/public.css` | 20,604 | GLOBAL | GLOBAL(base) |
| `css/ui_shell.css` | 40,588 | GLOBAL | GLOBAL(base) |
| `manifest.json` | 373 | GLOBAL | GLOBAL(base) |
| `css/ui_drawer_glass.css` | 8,811 | GLOBAL | GLOBAL(base) |
| `css/ui_home_tabs.css` | 3,565 | PAGE-ONLY | GLOBAL(base) |
| `css/pages/shop_home_page.css` | 42,568 | PAGE-ONLY | PAGE-TEMPLATE |

## checkout

Template: `app/templates/cart/checkout.html`
Endpoint: `cart.checkout`

### Scripts

| Asset | Size (bytes) | Class | Source |
|---|---:|---|---|
| `js/core/core_dom.js` | 4,422 | SUSPECT | GLOBAL(base) |
| `js/core/core_ui.js` | 4,929 | SUSPECT | GLOBAL(base) |
| `js/ajax/core/bm_csrf.js` | 1,738 | GLOBAL | GLOBAL(base) |
| `js/ajax/core/bm_guard.js` | 1,934 | GLOBAL | GLOBAL(base) |
| `js/ajax/core/bm_fetch.js` | 5,002 | GLOBAL | GLOBAL(base) |
| `js/ajax/core/bm_swap.js` | 1,603 | GLOBAL | GLOBAL(base) |
| `js/core/page_loader_client.js` | 7,444 | GLOBAL | GLOBAL(base) |
| `js/i18n.js` | 6,618 | SUSPECT | GLOBAL(base) |
| `js/ui_drawer.js` | 4,345 | GLOBAL | GLOBAL(base) |
| `vendor/bootstrap/5.3.3/js/bootstrap.bundle.min.js` | 80,721 | GLOBAL | GLOBAL(base) |
| `js/ui_shell.js` | 40,922 | GLOBAL | GLOBAL(base) |
| `js/core/core_cart.js` | 10,697 | GLOBAL | PAGE-LOADER |
| `js/delivery_pricing.js` | 6,020 | PAGE-ONLY | PAGE-LOADER |
| `js/pages/checkout_page.js` | 14,352 | PAGE-ONLY | PAGE-LOADER |

### Styles

| Asset | Size (bytes) | Class | Source |
|---|---:|---|---|
| `vendor/bootstrap/5.3.3/css/bootstrap.min.css` | 232,803 | GLOBAL | GLOBAL(base) |
| `vendor/bootstrap-icons/1.11.1/font/bootstrap-icons.css` | 98,255 | GLOBAL | GLOBAL(base) |
| `vendor/fontawesome/6.4.0/css/all.min.css` | 102,025 | SUSPECT | GLOBAL(base) |
| `fonts/public.css` | 20,604 | GLOBAL | GLOBAL(base) |
| `css/ui_shell.css` | 40,588 | GLOBAL | GLOBAL(base) |
| `manifest.json` | 373 | GLOBAL | GLOBAL(base) |
| `css/ui_drawer_glass.css` | 8,811 | GLOBAL | GLOBAL(base) |
| `css/cart-checkout.css` | 7,935 | PAGE-ONLY | PAGE-TEMPLATE |

## shops

Template: `app/templates/shop/shops.html`
Endpoint: `shops.list_shops`

### Scripts

| Asset | Size (bytes) | Class | Source |
|---|---:|---|---|
| `js/core/core_dom.js` | 4,422 | SUSPECT | GLOBAL(base) |
| `js/core/core_ui.js` | 4,929 | SUSPECT | GLOBAL(base) |
| `js/ajax/core/bm_csrf.js` | 1,738 | GLOBAL | GLOBAL(base) |
| `js/ajax/core/bm_guard.js` | 1,934 | GLOBAL | GLOBAL(base) |
| `js/ajax/core/bm_fetch.js` | 5,002 | GLOBAL | GLOBAL(base) |
| `js/ajax/core/bm_swap.js` | 1,603 | GLOBAL | GLOBAL(base) |
| `js/core/page_loader_client.js` | 7,444 | GLOBAL | GLOBAL(base) |
| `js/i18n.js` | 6,618 | SUSPECT | GLOBAL(base) |
| `js/ui_drawer.js` | 4,345 | GLOBAL | GLOBAL(base) |
| `vendor/bootstrap/5.3.3/js/bootstrap.bundle.min.js` | 80,721 | GLOBAL | GLOBAL(base) |
| `js/ui_shell.js` | 40,922 | GLOBAL | GLOBAL(base) |
| `js/core/core_cart.js` | 10,697 | GLOBAL | PAGE-LOADER |
| `js/ajax_pagination.js` | 8,416 | SUSPECT | PAGE-LOADER |
| `js/shops_page.js` | 5,521 | PAGE-ONLY | PAGE-LOADER |

### Styles

| Asset | Size (bytes) | Class | Source |
|---|---:|---|---|
| `vendor/bootstrap/5.3.3/css/bootstrap.min.css` | 232,803 | GLOBAL | GLOBAL(base) |
| `vendor/bootstrap-icons/1.11.1/font/bootstrap-icons.css` | 98,255 | GLOBAL | GLOBAL(base) |
| `vendor/fontawesome/6.4.0/css/all.min.css` | 102,025 | SUSPECT | GLOBAL(base) |
| `fonts/public.css` | 20,604 | GLOBAL | GLOBAL(base) |
| `css/ui_shell.css` | 40,588 | GLOBAL | GLOBAL(base) |
| `manifest.json` | 373 | GLOBAL | GLOBAL(base) |
| `css/ui_drawer_glass.css` | 8,811 | GLOBAL | GLOBAL(base) |
| `css/pages/shops_page.css` | 20,286 | PAGE-ONLY | PAGE-TEMPLATE |

## locations_index

Template: `app/templates/locations/index.html`
Endpoint: `rentals.locations_home`

### Scripts

| Asset | Size (bytes) | Class | Source |
|---|---:|---|---|
| `js/core/core_dom.js` | 4,422 | SUSPECT | GLOBAL(base) |
| `js/core/core_ui.js` | 4,929 | SUSPECT | GLOBAL(base) |
| `js/ajax/core/bm_csrf.js` | 1,738 | GLOBAL | GLOBAL(base) |
| `js/ajax/core/bm_guard.js` | 1,934 | GLOBAL | GLOBAL(base) |
| `js/ajax/core/bm_fetch.js` | 5,002 | GLOBAL | GLOBAL(base) |
| `js/ajax/core/bm_swap.js` | 1,603 | GLOBAL | GLOBAL(base) |
| `js/core/page_loader_client.js` | 7,444 | GLOBAL | GLOBAL(base) |
| `js/i18n.js` | 6,618 | SUSPECT | GLOBAL(base) |
| `js/ui_drawer.js` | 4,345 | GLOBAL | GLOBAL(base) |
| `vendor/bootstrap/5.3.3/js/bootstrap.bundle.min.js` | 80,721 | GLOBAL | GLOBAL(base) |
| `js/ui_shell.js` | 40,922 | GLOBAL | GLOBAL(base) |
| `js/core/core_cart.js` | 10,697 | GLOBAL | PAGE-LOADER |
| `js/ajax_pagination.js` | 8,416 | SUSPECT | PAGE-LOADER |
| `js/pages/locations_index_page.js` | 8,675 | PAGE-ONLY | PAGE-LOADER |

### Styles

| Asset | Size (bytes) | Class | Source |
|---|---:|---|---|
| `vendor/bootstrap/5.3.3/css/bootstrap.min.css` | 232,803 | GLOBAL | GLOBAL(base) |
| `vendor/bootstrap-icons/1.11.1/font/bootstrap-icons.css` | 98,255 | GLOBAL | GLOBAL(base) |
| `vendor/fontawesome/6.4.0/css/all.min.css` | 102,025 | SUSPECT | GLOBAL(base) |
| `fonts/public.css` | 20,604 | GLOBAL | GLOBAL(base) |
| `css/ui_shell.css` | 40,588 | GLOBAL | GLOBAL(base) |
| `manifest.json` | 373 | GLOBAL | GLOBAL(base) |
| `css/ui_drawer_glass.css` | 8,811 | GLOBAL | GLOBAL(base) |

## Top 20 JS (unique across target pages)

| # | Asset | Size (bytes) |
|---:|---|---:|
| 1 | `vendor/bootstrap/5.3.3/js/bootstrap.bundle.min.js` | 80,721 |
| 2 | `js/pages/shop_home_page.js` | 49,463 |
| 3 | `js/ui_shell.js` | 40,922 |
| 4 | `js/pages/checkout_page.js` | 14,352 |
| 5 | `js/core/core_cart.js` | 10,697 |
| 6 | `js/pages/locations_index_page.js` | 8,675 |
| 7 | `js/ajax_pagination.js` | 8,416 |
| 8 | `js/core/page_loader_client.js` | 7,444 |
| 9 | `js/i18n.js` | 6,618 |
| 10 | `js/delivery_pricing.js` | 6,020 |
| 11 | `js/shops_page.js` | 5,521 |
| 12 | `js/ajax/core/bm_fetch.js` | 5,002 |
| 13 | `js/core/core_ui.js` | 4,929 |
| 14 | `js/core/core_dom.js` | 4,422 |
| 15 | `js/ui_drawer.js` | 4,345 |
| 16 | `js/ajax/core/bm_guard.js` | 1,934 |
| 17 | `js/ajax/core/bm_csrf.js` | 1,738 |
| 18 | `js/ajax/core/bm_swap.js` | 1,603 |
| 19 | `js/ui_home_tabs.js` | 1,391 |

## Top 20 CSS (unique across target pages)

| # | Asset | Size (bytes) |
|---:|---|---:|
| 1 | `vendor/bootstrap/5.3.3/css/bootstrap.min.css` | 232,803 |
| 2 | `vendor/fontawesome/6.4.0/css/all.min.css` | 102,025 |
| 3 | `vendor/bootstrap-icons/1.11.1/font/bootstrap-icons.css` | 98,255 |
| 4 | `css/pages/shop_home_page.css` | 42,568 |
| 5 | `css/ui_shell.css` | 40,588 |
| 6 | `fonts/public.css` | 20,604 |
| 7 | `css/pages/shops_page.css` | 20,286 |
| 8 | `css/ui_drawer_glass.css` | 8,811 |
| 9 | `css/cart-checkout.css` | 7,935 |
| 10 | `css/ui_home_tabs.css` | 3,565 |
| 11 | `manifest.json` | 373 |

## Execution Audit (auto init, listeners, pollings)

| Script | Auto-init at load | Global listeners (scroll/resize/visibilitychange/popstate) | setInterval | setTimeout |
|---|---|---|---:|---:|
| `js/ajax/core/bm_csrf.js` | no | - | 0 | 0 |
| `js/ajax/core/bm_fetch.js` | no | - | 0 | 1 |
| `js/ajax/core/bm_guard.js` | yes | - | 0 | 1 |
| `js/ajax/core/bm_swap.js` | no | - | 0 | 0 |
| `js/ajax_pagination.js` | yes | popstate | 0 | 0 |
| `js/core/core_cart.js` | yes | visibilitychange | 0 | 1 |
| `js/core/core_dom.js` | no | - | 0 | 0 |
| `js/core/core_ui.js` | no | - | 0 | 3 |
| `js/core/page_loader_client.js` | yes | - | 0 | 0 |
| `js/delivery_pricing.js` | yes | - | 0 | 1 |
| `js/i18n.js` | no | visibilitychange | 0 | 1 |
| `js/pages/checkout_page.js` | yes | - | 0 | 1 |
| `js/pages/locations_index_page.js` | yes | visibilitychange | 1 | 1 |
| `js/pages/shop_home_page.js` | yes | popstate, resize, scroll | 0 | 7 |
| `js/shops_page.js` | yes | popstate | 0 | 2 |
| `js/ui_drawer.js` | yes | resize | 0 | 2 |
| `js/ui_home_tabs.js` | yes | - | 0 | 0 |
| `js/ui_shell.js` | yes | scroll, visibilitychange | 1 | 9 |
| `vendor/bootstrap/5.3.3/js/bootstrap.bundle.min.js` | yes | resize, scroll | 1 | 7 |

### Quick findings
- `shop_home_page.js` has two `scroll` listeners, both passive, and live search (abort+requestSeq).
- `locations_index_page.js` uses `setInterval` for card carousel autoplay (UI animation, not network polling) and pauses on `visibilitychange`.
- `core_cart.js` contains adaptive polling but is gated by `data-notify-url` and page allow-list, so client target pages do not start admin polling.
- `ajax_pagination.js` binds `popstate`; owner guards (`data-ajax-owner`) prevent double ownership where configured.
