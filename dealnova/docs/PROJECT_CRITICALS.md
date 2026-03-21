# Project Criticals (Post ROI #3 / ROI #4)

## Scope audited
- Public flow: `shop/home`, `search/results`, `shop/product_detail`, `cart/checkout`
- Vendor flow: `vendor/dashboard`, `vendor/earnings`
- Admin flow: orders, deliveries, fraud, catalog/reconciliation pages already on `admin_table.js` / `admin_forms.js`

## 1) Top 10 probable technical risks
1. Double init risk on pages with mixed inline + external JS still not fully migrated.
2. Legacy popstate handlers can conflict when more than one pagination/navigation engine is active.
3. CSRF handling is not yet fully single-path on all legacy templates.
4. Some page scripts still depend on DOM selectors without explicit page root guards.
5. Polling branches can duplicate calls if page-specific and global pollers are both enabled.
6. Fallback logic complexity (core AJAX + native fallback) can hide rare edge bugs.
7. Heavy inline CSS still present on several non-migrated templates (cache efficiency loss).
8. Some mobile pages still perform broad DOM rebinding after HTML swaps.
9. Service worker + cached assets can mask stale JS/CSS if version bump is missed.
10. Existing large, dirty worktree increases regression risk when multiple refactors land together.

## 2) Perf and fluidity score (mobile-first)
- Public (`shop/search/cart`): **7.5 / 10**
- Vendor (`dashboard/earnings`): **7 / 10**
- Admin (`orders/deliveries/fraud`): **7.5 / 10**

### Notes
- Public improved with AJAX core wrappers and extracted page scripts, but a few heavy templates remain.
- Vendor improved on earnings extraction and guarded fetch path; dashboard remains large and should be reduced in controlled passes.
- Admin is safer after table/forms consolidation, but several pages still carry legacy inline logic.

## 3) SAFE action plan

### P0 (anti-bug / crash prevention)
- Enforce one init guard per critical page script.
- Keep one popstate owner per page context.
- Keep request abort + request sequence on all live search/pagination flows.
- Keep hard-navigation fallback for network/parser failures.

### P1 (mobile perf + caching)
- Continue extracting large inline CSS/JS into versioned static files.
- Replace remaining `transition: all` on heavy interactive blocks with explicit properties only.
- Pause/slow polling when `document.hidden` everywhere.

### P2 (duplication reduction)
- Move repeated UI helpers (loader, disable button, toast adapters) to shared AJAX/vendor/admin modules.
- Retire legacy fallbacks only with proof of guaranteed core loading.
- Keep quarantine-first strategy (`_archive_unused`) for uncertain deletions.

## 4) Fast validation checklist
1. `shop/product/<slug>`: add-to-cart, image gallery, related cards, no console errors.
2. `cart/checkout`: city change pricing, submit lock, WhatsApp redirect, retry message on network failure.
3. `vendor/earnings`: filters, pagination, receipt confirm, auto-refresh stability.
4. Back/forward navigation on paginated pages remains stable.
5. Mobile (iPhone + Android): fast typing, quick taps, scroll fluidity, no freeze.