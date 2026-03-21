# CLEANUP LOG

Date: 2026-03-05
Mode: SAFE / preuve avant suppression

## Scope
- Audit des candidats suppression (archive, wrappers JS, templates, helpers Python)
- Suppression uniquement des candidats `low-risk` avec preuve `0 refs`

## 1) Inventaire candidats

### A. Fichiers déjà en `_archive_unused/`
- Résultat: **aucun dossier/fichier** `_archive_unused` détecté dans `dealnova/app`.
- Preuve:
```powershell
Get-ChildItem -Path dealnova -Recurse -Directory -Filter _archive_unused
```

### B. Dead code JS / wrappers / bridges
- Candidats revus: wrappers `requestJSON/requestText/withCsrfHeaders` dans `admin_*`, `shop_*`, `vendor_*`.
- Statut: **KEEP** (atteignables + utilisés), risque suppression: **medium/high**.
- Preuves principales:
```powershell
Select-String -Path dealnova/app/templates/base.html,dealnova/app/templates/admin/base.html,dealnova/app/templates/vendor/base.html -Pattern 'js/ajax/core/bm_fetch.js|js/ajax/core/bm_csrf.js|js/ajax/core/bm_swap.js'
rg -n "requestJSON\(|requestText\(|withCsrfHeaders\(" dealnova/app/static/js
```
- Raison KEEP: wrappers encore appelés et servent de couche de robustesse (erreur réseau/cache, ordre de chargement, isolation page).

### C. Dead templates
- Résultat: **aucun template candidat 0-ref confirmé** dans ce tour.
- Méthode utilisée: recherche de références par nom de fichier sur `app/scripts/docs`.

### D. Dead Python helpers
- Candidats détectés (marqués `UNUSED_CANDIDATE`) :
  1. `dealnova/app/routes/admin.py` -> `_open_order_period`
  2. `dealnova/app/routes/rentals.py` -> `_listing_whatsapp_url`
  3. `dealnova/app/routes/vendor.py` -> `_history_query`
- Preuve de non-usage (hors définition):
```powershell
rg -n "_open_order_period\(|_listing_whatsapp_url\(|_history_query\(" dealnova/app dealnova/scripts dealnova/docs
```
- Résultat: aucune référence d'appel réelle trouvée.
- Risque: **low**.

## 2) Suppressions effectuées (définitives, low-risk)

### Fichiers modifiés
- `dealnova/app/routes/admin.py`
- `dealnova/app/routes/rentals.py`
- `dealnova/app/routes/vendor.py`

### Blocs supprimés
- `_open_order_period` (unused)
- `_listing_whatsapp_url` (unused)
- `_history_query` (unused)

### Vérification post-suppression
```powershell
python -m py_compile dealnova/app/routes/admin.py dealnova/app/routes/rentals.py dealnova/app/routes/vendor.py
```
Résultat: OK (pas d'erreur de syntaxe).

## 3) Quarantaine
- Aucun nouveau fichier placé en quarantaine dans ce tour (pas de candidat fichier 0-ref suffisamment prouvé).

## 4) Checklist test manuel (10 minutes)

### Public
1. `/shop` : recherche live + pagination + back
2. `/search` : recherche live + add-to-cart
3. `/cart` : update qty/remove/clear
4. `/checkout` : prix livraison + submit
5. `/track_order` : polling visible/caché

### Vendor
6. `/vendor/dashboard` : live cards + pagination sections
7. `/vendor/earnings` : filtres + pagination + retour haut

### Admin
8. `/admin/all_orders` : pagination/filter/swap
9. `/admin/deliveries` : pagination + compteur dispo
10. `/admin/fraud`, `/admin/categories`, `/admin/logs`, `/admin/locations` : pager + filtres + actions

Critères globaux: pas de freeze, back navigateur cohérent, console sans erreur rouge.

## 5) Décision SAFE pour la suite
- Maintenir les wrappers JS tant que tout le parc de pages n'est pas validé en prod (stale-cache + ordre de chargement).
- Prochaine suppression candidate: uniquement après 2e passe de preuves `0 refs` + validation de la checklist ci-dessus.

---

Date: 2026-03-05 (Lot 1 wrappers consolidation)

## Scope
- Consolidation des wrappers locaux AJAX sur 6 fichiers publics/suivi.
- Aucun changement d'UX/design/routes.

## Files touched
- `dealnova/app/static/js/delivery_pricing.js`
- `dealnova/app/static/js/pages/cart_page.js`
- `dealnova/app/static/js/pages/checkout_page.js`
- `dealnova/app/static/js/pages/product_detail_page.js`
- `dealnova/app/static/js/pages/shop_detail_page.js`
- `dealnova/app/static/js/pages/track_order_page.js`
- `dealnova/docs/CLEANUP_PLAN.md`
- `dealnova/docs/PERF_FIXES.md`

## Approx cleanup
- Local wrapper definitions removed/renamed from hot paths: ~12 blocks (`requestJSON`/`requestText`/`withCsrfHeaders`).
- Old wrapper names removed from these 6 files (proof via `rg` in CLEANUP_PLAN).

## Validation notes
- `python -m py_compile` on python routes: OK.
- JS proof checks done with `rg` before/after.

---

Date: 2026-03-05 (Lot 2 admin: deliveries + fraud)

## Files touched
- `dealnova/app/static/js/admin/admin_table.js`
- `dealnova/app/static/js/admin/admin_forms.js`
- `dealnova/app/static/js/ajax/core/bm_csrf.js`
- `dealnova/docs/CLEANUP_PLAN.md`
- `dealnova/docs/PERF_FIXES.md`

## Approx cleanup / hardening
- Added explicit anti double-init guards for admin pages (`deliveries`, `fraud`) with `window` + `body.dataset`.
- Consolidated CSRF header path on admin forms to prefer central core API.
- No inline script removal needed in `deliveries.html` / `fraud.html` (already `NO_MATCH` for `<script`).

## Fallback hard-nav kept
- Yes. `window.location.href = url` is still present in `admin_table.js` for swap/pagination failures.

---

Date: 2026-03-05 (P1/P2 PERF - page loader without bundler)

## Files touched
- `dealnova/app/templates/base.html`
- `dealnova/app/templates/admin/base.html`
- `dealnova/app/static/js/core/page_loader.js` (new)
- `dealnova/docs/ASSET_LOAD_MAP.md` (new)
- `dealnova/docs/PAGE_LOADER_MAP.md` (new)

## What changed
- Removed heavy runtime scripts from global shell loading in `base.html` and `admin/base.html`:
  - `core_cart`, `core_live`, `live`, `ajax_pagination`, `ajax/features/*`, `admin_table`, `admin_forms`
- Added dynamic loader:
  - `js/core/page_loader.js` now loads these scripts by `data-page`, `data-adm-page`, and DOM hints.
- Kept core AJAX globally loaded everywhere:
  - `bm_csrf`, `bm_guard`, `bm_fetch`, `bm_swap`.
- Added `data-static-root` and `data-static-version` attributes for versioned dynamic loading.

## Archive/delete status
- No file archived/deleted in this pass (SAFE rollout first).

## Proof quick checks
- `base.html` now references `page_loader.js` and no longer references removed heavy globals directly.
- `admin/base.html` now references `page_loader.js`; `admin_table.js` and `admin_forms.js` removed from direct global includes.

---

Date: 2026-03-05 (Client PERF P1/P2 - 4 target pages)

## Files touched
- `dealnova/app/templates/base.html`
- `dealnova/app/templates/shop/home.html`
- `dealnova/app/templates/cart/checkout.html`
- `dealnova/app/templates/shop/shops.html`
- `dealnova/app/templates/locations/index.html`
- `dealnova/app/static/js/core/page_loader_client.js` (new)
- `dealnova/app/static/js/pages/shop_home_page.js`
- `dealnova/docs/CLIENT_ASSET_LOAD_MAP.md` (new)
- `dealnova/docs/CLIENT_PAGE_LOADER_MAP.md` (new)
- `dealnova/docs/CLIENT_PERF_FIXES.md` (new)

## Proofs (`rg`)
- No direct page script tags remain in target templates:
  - `rg -n \"shop_home_page\\.js|delivery_pricing\\.js|checkout_page\\.js|shops_page\\.js|locations_index_page\\.js\" ...`
  - Result: `NO_DIRECT_PAGE_SCRIPT_MATCH`
- Public base now points to client loader:
  - `base.html` includes `js/core/page_loader_client.js`
  - `admin/base.html` remains on `js/core/page_loader.js`
- `data-page` standardized:
  - `shop_home`, `checkout`, `shops`, `locations_index`

## Archive / deletion
- No `_archive_unused` move and no deletion in this pass (SAFE rollout first).
