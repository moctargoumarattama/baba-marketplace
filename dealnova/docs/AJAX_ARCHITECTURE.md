<!--
Mini inventaire AJAX (phase 0)
| Zone | Fichiers principaux | Role |
| --- | --- | --- |
| Global public | static/js/ajax_pagination.js, static/js/core/core_live.js, static/js/core/core_cart.js, static/js/ui_shell.js | Navigation/listings, formulaires AJAX, cart/nav badge, live helpers |
| Pages public | static/js/pages/shop_home_page.js, static/js/pages/shop_detail_page.js, static/js/pages/search_results_page.js | Recherche live, filtres, pagination locale, ajouts panier |
| Vendor | static/js/pages/vendor/dashboard_page.js, static/js/pages/vendor/earnings_page.js | Polling dashboard, stats live, recherche products |
| Admin/Courier inline | templates/admin/*.html, templates/courier/deliveries.html | Pagination/filter AJAX inline, actions metier |
| Core AJAX central (nouveau) | static/js/ajax/core/*, static/js/ajax/features/* | CSRF, fetch robuste, guard sequence, swap, wrappers progressifs |
-->

# AJAX Architecture

## Pourquoi ce dossier existe
Le dossier `dealnova/app/static/js/ajax/` centralise les primitives AJAX reutilisables:
- CSRF
- fetch robuste
- anti double-click / anti reponse obsolete
- swap HTML securise
- wrappers pagination/forms/polling

Objectif: reduire la duplication et preparer une migration progressive sans casser le comportement existant.

## Ou chercher selon le bug
- Pagination bug: `static/js/ajax_pagination.js` puis `static/js/ajax/features/pagination.js`
- Cart bug: `static/js/core/core_cart.js`, `static/js/home_shell.js`, templates `cart/*.html`
- Search bug: `static/js/pages/search_results_page.js`, `static/js/pages/shop_home_page.js`
- Admin swap bug: scripts inline `templates/admin/*.html`, `static/js/core/core_live.js`
- Form AJAX bug: `static/js/core/core_live.js` + `static/js/ajax/features/forms.js`

## Fichiers centralises

### Core
- `static/js/ajax/core/bm_csrf.js`
- `static/js/ajax/core/bm_guard.js`
- `static/js/ajax/core/bm_fetch.js`
- `static/js/ajax/core/bm_swap.js`

### Features
- `static/js/ajax/features/pagination.js`
- `static/js/ajax/features/forms.js`
- `static/js/ajax/features/polling.js`

## Convention
- Toute nouvelle logique AJAX doit utiliser `window.BMAjaxFetch`.
- Toute requete mutatrice doit passer par `BMAjaxCSRF.addToHeaders(...)` (ou via `BMAjaxFetch` qui le fait deja).
- Toute recherche live doit utiliser:
  - `AbortController`
  - `BMAjaxGuard.makeRequestSeq()`
  - verification `seq.isLatest(id)` avant rendu DOM.
- Tout remplacement de listing doit passer par `BMAjaxSwap.swapHTML(...)` et ecouter `ajax:page-replaced`.
- Ownership pagination (anti double moteur):
  - `data-ajax-owner="page"` sur `<body>` si le controller page gere `popstate`.
  - `ajax_pagination.js` s'auto-desactive sur ces pages.
  - sans owner explicite, le moteur global peut rester actif.

## Checklist debug rapide
1. Console: verifier erreurs JS et `AbortError` en boucle.
2. Network: verifier `X-CSRFToken` sur POST AJAX.
3. Verifier l'evenement `ajax:page-replaced` apres swap listing/pager.
4. Confirmer qu'une seule requete est active pour la meme recherche (abort + request sequence).
5. En cas de doute cache: verifier `?v={{ app_static_version }}` charge bien les nouveaux fichiers.
