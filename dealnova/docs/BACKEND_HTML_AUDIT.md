# Backend HTML Audit (SAFE)

Date: 2026-03-10
Scope:
- `dealnova/app/__init__.py`
- `dealnova/app/services/traffic_stats.py`
- `dealnova/app/services/maintenance_mode.py`
- `dealnova/app/routes/shop.py`
- `dealnova/app/routes/cart.py`
- `dealnova/app/routes/booking.py`
- `dealnova/app/routes/delivery.py`
- `dealnova/app/routes/shops.py`
- `dealnova/app/routes/rentals.py`
- `dealnova/app/routes/vendor.py`
- `dealnova/app/routes/admin.py`

Goal:
- reduce fixed backend cost before HTML appears
- keep routes, design, and frontend contracts unchanged

## Global hooks audit

- `redirect_to_www` in `app/__init__.py`
  - Scope: all requests hitting `babamarket.ma`
  - Cost: low
  - Decision: kept as-is

- `set_language`
  - Scope: almost every request before this lot
  - Cost: cookie/session reads, possible session write
  - Risk found: it also ran for static-like requests where language state is useless

- `track_live_traffic`
  - Scope: almost every request before this lot
  - Cost: cache writes + IP hash + active visitor refresh
  - Risk found: AJAX, polling, and JSON requests were counted like page views

- `enforce_maintenance_mode`
  - Scope: all non-whitelisted requests
  - Cost: light in current form because `maintenance_mode.py` already has a 5 second in-process cache
  - Decision: no service-side refactor forced in this lot

- `enforce_vendor_private_mode`
  - Scope: authenticated vendor traffic only
  - Cost: already scoped
  - Decision: unchanged

- `csrf_protect`
  - Scope: non-GET methods only
  - Cost: not a primary HTML first-paint problem
  - Decision: unchanged

- `attach_csp_nonce` + `set_security_headers`
  - Scope: all requests, with HTML rewrite on HTML responses
  - Cost: nonce generation on every request, plus full-body regex rewrite on HTML responses
  - Risk found: useless token work on JSON/static responses

- `cleanup_request`
  - Scope: all requests
  - Cost: necessary cleanup
  - Decision: unchanged

- `inject_cart_count`
  - Scope: every template render
  - Cost: for anonymous visitors it could create a guest session token even with an empty cart
  - Risk found: unnecessary session mutation on normal page views

## CSP nonce path

- Previous logic:
  - generate a nonce in `before_request` for every request
  - rewrite the full HTML body in `after_request` with two regex passes

- Main issue:
  - fixed per-request work even when the response was JSON or static
  - HTML rewrite stayed necessary for CSP, but the nonce generation timing was not optimal

- Safe optimization boundary:
  - CSP must stay enabled
  - no template-wide nonce migration in this lot

- Safe path selected:
  - keep body rewrite for HTML responses
  - lazy-generate the nonce only when the response is actually HTML
  - precompile the regexes
  - skip rewrite entirely when the body has no `<script>` or `<style>` tag

## Maintenance and traffic stats

- `maintenance_mode.py`
  - existing state cache TTL is already 5 seconds
  - this keeps DB lookups out of the hot path for most requests
  - no safe additional gain justified a deeper change in this lot

- `traffic_stats.py`
  - previous behavior counted public page loads and internal background traffic the same way
  - active visitor state was refreshed on every qualifying request
  - admin metrics reads can be expensive when active visitor counting scans many keys

- Safe optimization opportunities identified:
  - ignore background AJAX/JSON requests for page-view style traffic metrics
  - throttle active visitor refreshes
  - microcache admin traffic snapshot reads briefly

## Priority HTML routes

- `/`
  - file: `app/__init__.py`
  - status: audited
  - main cost: many queries on cache miss, but payload already uses versioned catalog cache
  - decision: no safe SQL-side change forced in this lot

- `/shop`
  - file: `app/routes/shop.py`
  - main cost: main payload already cached, but shop open/closed dynamic status still triggered a DB query per request
  - decision: good candidate for short microcache

- `/shop/shops`
  - file: `app/routes/shops.py`
  - main cost: payload build on cache miss, but route already uses a 120 second catalog cache
  - decision: no backend change forced in this lot

- `/locations`
  - file: `app/routes/rentals.py`
  - main cost: list page loaded relationship data that the list template does not use
  - decision: remove unused relation load and restrict media columns

- `/vendor/dashboard`
  - file: `app/routes/vendor.py`
  - main cost: HTML route and `/vendor/dashboard/orders-live` repeated near-identical live-card work
  - decision: share the same short microcache payload

- `/vendor/earnings`
  - file: `app/routes/vendor.py`
  - main cost: full `VendorReceipt` objects were loaded for the whole filtered period even though only one page is rendered
  - decision: keep full-range confirmation detection, but hydrate receipt details only for the current page

- `/cart` and `/cart/checkout`
  - file: `app/routes/cart.py`
  - main costs found:
    - anonymous reads still created guest session state through `_cart_key()` and `setup_guest`
    - `/cart/checkout` POST precomputed subtotal/validation once, then delegated to `whatsapp_checkout()` which repeated the same work
    - hot cart helpers (`/api/summary`, nav status, checkout) loaded `shop` and `category` relations even when the caller did not use them
  - decision: good candidate for safe lazy guest session creation and narrower relation loading

- `/booking/<pid>` and `/booking/track/<token>`
  - file: `app/routes/booking.py`
  - main cost: lazy loads for `product.shop`, `booking.product`, and `booking.shop` on public HTML pages
  - decision: eager load only the fields used by templates and booking message flow

- `/delivery`
  - file: `app/routes/delivery.py`
  - main cost: `PlatformSettings.get()` was effectively paid twice on POST, once implicitly during price lookup and once again for fee computation
  - risk found: the first lookup was outside the existing `try`, so config lookup failures could still bubble into a 500
  - decision: fetch platform settings once and reuse them through the pricing path

- `/admin/*`
  - file: `app/routes/admin.py`
  - status: audited
  - main cost: route-specific queries dominate more than global hooks
  - decision: documented, not forced in this lot

## Risk notes

- Shop open/closed filter status can be stale for about 15 seconds.
- Dashboard live-card cache stays short at about 3 seconds.
- Admin live traffic metrics can appear lower because background AJAX/polling is no longer treated as page traffic.
- Cart guest session state is now created lazily on write paths instead of passive reads.
- Delivery pricing still keeps the existing route shape, including the compatibility `/delivery` endpoint overlap; this was documented but not refactored in this lot.
- No public route path was changed.
- No DB schema, DB queries structure, or frontend response contract was intentionally changed in a risky way.
