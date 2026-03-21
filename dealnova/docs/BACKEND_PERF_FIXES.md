# Backend Performance Fixes (SAFE)

Date: 2026-03-10
Lot: Backend HTML

Files touched:
- `dealnova/app/__init__.py`
- `dealnova/app/services/traffic_stats.py`
- `dealnova/app/routes/shop.py`
- `dealnova/app/routes/cart.py`
- `dealnova/app/routes/booking.py`
- `dealnova/app/routes/delivery.py`
- `dealnova/app/routes/rentals.py`
- `dealnova/app/routes/vendor.py`
- `dealnova/docs/BACKEND_HTML_AUDIT.md`
- `dealnova/docs/BACKEND_PERF_FIXES.md`

## Applied changes

### 1) Global HTML path

- `app/__init__.py`
  - `set_language` now skips static-like requests
  - `track_live_traffic` now skips static-like requests before calling the stats service
  - CSP nonce generation moved to the HTML response path instead of every request
  - CSP regexes are precompiled
  - HTML nonce injection short-circuits when there is no `<script>` or `<style>` tag
  - `inject_cart_count` no longer creates an empty guest session/cart key on anonymous page views

Result:
- less fixed work on every request
- less useless session churn on anonymous HTML pages

### 2) Traffic stats

- `app/services/traffic_stats.py`
  - AJAX/JSON/background requests are ignored by `track_request_hit`
  - active visitor refresh is throttled to one touch per IP hash every 45 seconds
  - `get_live_traffic_metrics()` now uses a short 10 second in-process snapshot cache

Result:
- fewer cache writes during live polling and filter requests
- lower admin traffic-metrics read cost

### 3) `/shop`

- `app/routes/shop.py`
  - shop filter dynamic open/closed status now uses a short 15 second cache

Result:
- removes one repeated DB status query from hot `/shop` page loads

### 4) `/locations`

- `app/routes/rentals.py`
  - removed the unused `RentalListing.shop` eager load from the public listing page
  - limited `RentalListing.media` eager load to the columns used by the listing cards

Result:
- lighter relationship loading on each `/locations` page render

### 5) `/cart` and `/cart/checkout`

- `app/routes/cart.py`
  - guest cart/session identifiers are now created lazily on write paths instead of passive cart reads
  - cart data cache now loads `shop` or `category` relations only when the calling path actually needs them
  - `/cart/checkout` POST now delegates immediately to `whatsapp_checkout()` instead of precomputing the same cart validation/subtotal path twice
  - checkout GET no longer builds an unused `items` payload for the template

Result:
- less session churn on anonymous cart page loads
- lighter ORM work for cart summary/nav-status style reads
- less duplicate backend work before checkout submission

### 6) Booking public HTML

- `app/routes/booking.py`
  - `/booking/<pid>` now loads product + shop fields needed by the booking form in one targeted query
  - `/booking/track/<token>` now eager-loads the booking product and shop used by the tracking template

Result:
- fewer lazy ORM fetches during booking form and booking tracking renders

### 7) `/delivery`

- `app/routes/delivery.py`
  - `PlatformSettings` is now fetched once and reused for city pricing + fee computation
  - pricing config lookup is now inside the guarded error path instead of partly outside it

Result:
- one fewer settings lookup per delivery POST
- lower risk of an avoidable 500 during delivery pricing

### 8) `/vendor/dashboard`

- `app/routes/vendor.py`
  - added a shared helper for dashboard live-card payload generation
  - HTML dashboard and `/vendor/dashboard/orders-live` now share the same 3 second microcache payload

Result:
- avoids repeating the same live-card SQL work between initial HTML render and immediate polling

### 9) `/vendor/earnings`

- `app/routes/vendor.py`
  - full-range receipt detection now loads only `VendorReceipt.order_id`
  - receipt details are loaded only for the current paginated page
  - order pagination uses `load_only(...)` on `Order`, `OrderItem`, and `Product` for the fields used by the template

Result:
- less ORM hydration for large earnings periods
- same HTML output, less wasted backend work

## Before / after logic

- Before:
  - CSP nonce token created for every request
  - anonymous HTML could create guest session state even with an empty cart
  - live traffic counted background fetches and polling
  - cart reads could create guest session state and broad relation loads even before any mutation
  - `/cart/checkout` POST did an HTML-side prepass before entering the real checkout logic
  - booking public pages relied on lazy product/shop fetches
  - delivery pricing could read platform settings twice
  - `/vendor/dashboard` and `/vendor/dashboard/orders-live` duplicated near-identical work
  - `/vendor/earnings` loaded receipt objects for the whole result set

- After:
  - nonce work is focused on real HTML responses
  - empty cart pages do not create guest cart state
  - live traffic is closer to real page traffic
  - cart guest state is created only on write paths, and cart relation loading matches the caller path
  - checkout POST enters the order creation path directly
  - booking public HTML gets its product/shop data in one pass
  - delivery POST reuses one settings load for pricing and fees
  - dashboard HTML and live endpoint reuse the same short-lived payload
  - earnings keeps full-range totals but loads receipt details only for visible rows

## Risks and rollback

- Risks:
  - `/shop` open/closed status can lag by about 15 seconds
  - dashboard live cards can lag by about 3 seconds
  - admin live traffic numbers can be lower because background requests are no longer counted as page views
  - CSP optimization assumes templates do not require `g.csp_nonce` during render; current codebase audit matched that assumption
  - cart relation loading now depends on the caller path; future cart templates that access `product.shop` or `product.category` must request the right shape in `cart.py`

- Rollback:
  - revert the isolated blocks in:
    - `app/__init__.py`
    - `app/services/traffic_stats.py`
    - `app/routes/shop.py`
    - `app/routes/cart.py`
    - `app/routes/booking.py`
    - `app/routes/delivery.py`
    - `app/routes/rentals.py`
    - `app/routes/vendor.py`
  - no migration rollback is needed
  - no route rename rollback is needed

## Verification

- Parsed successfully with Python `ast.parse()`:
  - `app/__init__.py`
  - `app/services/traffic_stats.py`
  - `app/routes/shop.py`
  - `app/routes/cart.py`
  - `app/routes/booking.py`
  - `app/routes/delivery.py`
  - `app/routes/rentals.py`
  - `app/routes/vendor.py`

- Not executed here:
  - real browser validation
  - runtime checks on `/shop`, `/shop/shops`, `/locations`, `/cart/checkout`, `/booking/<pid>`, `/delivery`, `/vendor/dashboard`, `/vendor/earnings`
  - visual regression check
