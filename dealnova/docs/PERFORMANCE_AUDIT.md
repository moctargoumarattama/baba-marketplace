# PERFORMANCE AUDIT — Baba Market (dealnova)

Date: 2026-03-05  
Mode: Analyse uniquement (aucune modification métier/routes/DB/design)

## 1) Architecture actuelle

### Vue globale (mesures)
- Fichiers JS statiques: `38` fichiers, `463,387` bytes (~452.5 KB)
- Fichiers CSS statiques: `20` fichiers, `334,383` bytes (~326.5 KB)
- Templates: `85` fichiers
- Inline templates:
- Blocs `<style>`: `42` blocs, `247,595` bytes (~241.8 KB)
- Blocs `<script>` inline: `35` blocs, `74,572` bytes (~72.8 KB)
- Occurrences techniques:
- `fetch(`: `31`
- `AbortController`: `54`
- `setInterval(`: `13`
- listeners scroll: `9`
- `transition: all`: `85`
- `@media`: `168`

### Chargement global (layouts)
- `templates/base.html` charge `18` scripts + `7` CSS (hors scripts/CSS de page).
- `templates/admin/base.html` charge `16` scripts + `5` CSS.
- `templates/vendor/base.html` étend `base.html` et ajoute `vendor_shell.css` + `vendor_shell.js`.

### Taille custom chargée par socle (hors Bootstrap/fonts/CDN tiers)
- Public base JS custom: `120,917` bytes
- Admin base JS custom: `139,623` bytes
- Public base CSS custom (avec home tabs): `52,964` bytes
- Admin base CSS custom: `8,713` bytes

### Pages critiques (estimation DOM + charge front)
| Page | Tags HTML (template) | Scripts page | CSS page | Charge AJAX principale |
|---|---:|---|---|---|
| `/shop` (`shop/home.html`) | ~417 | `shop_home_page.js` | `shop_home_page.css` | pagination AJAX + live suggest (3 endpoints/debounce) + add-to-cart |
| `/shop/product/<id>` (`shop/product_detail.html`) | ~347 | `product_detail_page.js` | `product_detail_page.css` | add-to-cart AJAX |
| `/cart/checkout` (`cart/checkout.html`) | ~157 | `delivery_pricing.js` + `checkout_page.js` | `cart-checkout.css` | pricing livraison + submit checkout |
| `/vendor/dashboard` | ~465 | `vendor/dashboard_page.js` (+ `vendor_shell.js`) | `vendor_dashboard.css` (+ shell) | search, stats live, orders live, polling |
| `/admin/orders` (`admin/all_orders.html`) | ~380 (+ gros inline CSS) | via `admin/base` | inline + admin base CSS | notifications live + pagination/filters admin |

### Cartographie AJAX (principaux flux)
- Pagination AJAX: `static/js/ajax_pagination.js`, `static/js/admin/admin_table.js`
- Form AJAX global: `static/js/core/core_live.js`, `static/js/admin/admin_forms.js`
- Search live public:
- `shop_home_page.js` -> `/api/search/products`, `/api/search/shops`, `/api/search/locations`
- `search_results_page.js` -> + `/api/search/categories`
- Cart:
- `cart_page.js` -> `/cart/api/update/<id>`, `/cart/api/remove/<id>`, `/cart/api/clear`
- `shop_home_page.js` / `search_results_page.js` / `product_detail_page.js` -> `/cart/api/add/<id>`
- Checkout/livraison:
- `delivery_pricing.js`, `checkout_page.js` -> `/api/pricing/delivery`
- Vendor:
- `dashboard_page.js` -> `/vendor/products/search`, `/vendor/stats/live`, `/vendor/dashboard/orders-live`
- `earnings_page.js` -> endpoints earnings/history (via config page)
- Admin:
- notifications -> `/admin/orders/notifications` (body `data-notify-url`)
- deliveries count poll -> `/admin/deliveries/available-count`

## 2) Top 10 bugs probables (zones à risque)

1. **Double moteurs AJAX potentiels**: `ajax_pagination.js` + logiques page spécifiques (ex. `shop_home_page.js`, `shops_page.js`) avec `popstate`. Les guards existent, mais la complexité reste élevée.  
2. **Polling agressif admin global**: `admin/base.html` fixe `data-notify-interval="5000"`; cela lance des requêtes fréquentes même hors écran orders/deliveries.  
3. **Polling sans pause explicite sur certaines pages legacy**: `shop/track_order.html` utilise `setInterval(refreshStatus, 10000)` sans pause visible sur `document.hidden`.  
4. **Dépendance inline importante en admin**: gros CSS inline dans `admin/base.html` + styles inline de pages lourdes (`deliveries`, `fraud`, `all_orders`) augmentent risque de divergence.  
5. **`window.fetch` patché globalement dans `ui_shell.js`**: utile pour badges, mais peut compliquer debug/interop si d’autres wrappers existent.  
6. **Fallbacks multiples hétérogènes**: coexistence de branches “core AJAX garanti” et branches fallback legacy dans plusieurs pages; risque de comportement non uniforme.  
7. **Requêtes live search multipliées**: 3 requêtes/debounce sur `/shop`, 4 requêtes/debounce sur `/search`; en réseau lent mobile, latence perceptible.  
8. **Scripts features AJAX chargés mais API peu utilisée**: `ajax/features/pagination.js`, `forms.js`, `polling.js` surtout présents comme wrappers, faible valeur runtime actuelle.  
9. **`transition: all` très présent (`85` occurrences)**: peut dégrader fluidité GPU/CPU mobile sur interactions de masse.  
10. **Templates encore avec JS inline fetch (admin/categories/logs/locations, locations/index, courier/deliveries)**: risque de duplication de logique par rapport aux socles centralisés.

## 3) Top 10 optimisations performance (SAFE, sans redesign)

1. Réduire le polling admin global (gating par `data-page` avant démarrage).  
2. Passer les boucles `setInterval` critiques vers polling adaptatif (`setTimeout` + hidden backoff).  
3. Unifier search live en endpoint agrégé ou conserver multi-endpoints avec priorité stricte + budget réseau.  
4. Continuer externalisation CSS inline admin/pages lourdes pour maximiser cache navigateur.  
5. Remplacer `transition: all` sur composants lourds par propriétés ciblées (`transform`, `opacity`, `box-shadow`).  
6. Vérifier tous les listeners scroll en `passive:true` (notamment scripts inline legacy).  
7. Mutualiser les helpers AJAX restants dans noyau unique (`BMAjaxFetch`/`BMAjaxCSRF`) pour réduire branches.  
8. Limiter coûts de repaint sur listes longues (virtualisation légère ou pagination plus stricte côté admin).  
9. Réduire les scripts globaux sur pages qui n’en ont pas besoin (chargement conditionnel par `data-page`).  
10. Rendre local les dépendances CDN critiques (libphonenumber/infinite-scroll) pour robustesse offline/réseau faible.

## 4) Code inutile potentiel (estimation)

### Constat
- Aucun fichier JS/CSS static clairement orphelin détecté via recherche de références globale.
- En revanche, plusieurs couches legacy/wrappers restent présentes pour compatibilité.

### Candidats “réduction sans casse” (après preuve ciblée)
- `ajax/features/pagination.js`, `ajax/features/forms.js`, `ajax/features/polling.js`:
- chargés globalement, mais leurs méthodes `init/start` sont peu appelées explicitement.
- Branches fallback “core garanti” conservées dans certains scripts pages.
- Inline CSS/JS encore massif dans plusieurs templates admin et quelques pages legacy.

### Estimation supprimable/réductible
- **JS**: `~10% à 16%` (branches fallback redondantes + wrappers non utilisés + duplication inline legacy)
- **CSS**: `~12% à 22%` (inline admin + répétitions composants/table/filter/pills)
- Estimation globale possible sans changer le rendu: **10% à 20%** (cohérent avec votre objectif).

## 5) Risques de scaling (10k users / 100k products / 1000 shops)

1. `ILIKE "%q%"` sur recherches (`api.py`, `shop.py`, `shops.py`, `vendor.py`) devient coûteux sans index/FTS.  
2. Multi-requêtes search live côté front (3 à 4 endpoints par saisie) amplifient charge backend.  
3. Polling fréquent admin/vendeur multiplie QPS même sans action utilisateur.  
4. Endpoints “stats/live” avec agrégations répétées peuvent saturer DB en heure de pointe.  
5. Plusieurs `.count()` dans dashboards/filters augmentent latence sous forte volumétrie.  
6. Pages admin lourdes (deliveries/fraud/logs) avec beaucoup de filtres + tables volumineuses.  
7. Risque N+1 partiellement maîtrisé (`selectinload` présent), mais encore des chemins query complexes à auditer finement.  
8. Pas de stratégie explicite de cache applicatif pour recherche/live stats (dans ce périmètre observé).  
9. Dépendance à polling plutôt qu’event push (WebSocket/SSE) pour live updates à grande échelle.  
10. SW met beaucoup de routes sensibles en network-only (sûr), mais pas de réduction de charge backend associée.

## 6) Optimisation mobile

### Mesure rapide
- Images templates: `42` tags `<img>`, `28` avec `loading="lazy"`, `17` avec `decoding="async"`.
- Bon usage d’`AbortController` (`54` occurrences) et guards init (`__BM_*`, `__ADM_*`).
- Points à surveiller: `transition: all`, polling, scripts globaux lourds chargés partout.

### Score fluidité mobile
- **7.4 / 10**

## 7) Score global projet

- Beauté code: **7.6 / 10**  
- Performance: **7.1 / 10**  
- Robustesse: **8.0 / 10**  
- Mobile: **7.4 / 10**

## 8) Plan d’amélioration (SAFE, progressif)

### Phase 1 — Stabilité (P0)
- Gater strictement les pollings par page et visibilité (`document.hidden` + page flags).
- Finaliser un moteur unique pagination/popstate par zone.
- Réduire scripts inline AJAX legacy (admin categories/logs/locations/courier/locations index).
- Uniformiser erreurs réseau non bloquantes (toast + retry discret).

### Phase 2 — Performance (P1)
- Externaliser inline CSS admin restants et harmoniser composants communs.
- Réduire `transition: all` sur composants lourds.
- Rationaliser search live (agrégation ou orchestration “request budget”).
- Limiter scripts globaux via chargement conditionnel par endpoint.

### Phase 3 — Scaling (P2)
- Introduire index adaptés et/ou FTS pour recherches texte.
- Mettre en cache réponses read-heavy (search popular, stats snapshots).
- Remplacer une partie du polling par stratégie push (SSE/WebSocket) sur zones critiques.
- Consolider monitoring per-endpoint (latence P95, QPS, erreurs).

## 9) Notes opérationnelles test rapide (5 minutes)

1. `/shop`: saisie rapide + pagination + back/forward + add-to-cart.  
2. `/search`: saisie rapide + stabilité résultats + add-to-cart.  
3. `/shop/<slug>`: infinite scroll sans doublons ni flash incohérent.  
4. `/vendor/dashboard`: polling stats/orders + onglet caché/visible.  
5. `/admin/orders` et `/admin/deliveries`: pagination/filtres + console sans erreurs rouges.
