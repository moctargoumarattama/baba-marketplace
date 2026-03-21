# Interaction Flow

## Loader global

Le loader global suit maintenant quatre etats logiques:

1. `booting`
2. `dom-ready`
3. `interactive`
4. `complete`

L'etat courant est expose via `document.documentElement.dataset.bmReadyState`.

## Quand le loader se ferme

### Mode rapide actif

Condition par defaut:

```js
window.BM_PERF_FLAGS.fastLoader !== false
```

Flux:

1. Le DOM devient pret.
2. Le navigateur laisse passer le premier paint utile.
3. Le loader se ferme sans attendre les medias lourds.
4. Si `bm:page-interactive` arrive avant ou juste apres, la fermeture est immediate.
5. `window.load` reste un fallback.
6. Un timeout de securite evite tout blocage durable.

### Mode legacy

Si `window.BM_PERF_FLAGS.fastLoader = false`, le loader revient au schema precedent:

1. attente de `window.load`
2. fallback timeout

## Quand la page devient interactive

Le chargeur client de scripts envoie:

```js
document.dispatchEvent(new CustomEvent("bm:page-interactive"))
```

Ce signal part quand les assets critiques de la page ont fini de charger selon un plan safe.

### Plans critiques

- `/shop`: `shop_home_page.js`, `core_cart.js`, `ajax_pagination.js`
- `/shop/shops`: `shops_page.js`, `core_cart.js`, `ajax_pagination.js`
- `/locations`: `locations_index_page.js`, `core_cart.js`, `ajax_pagination.js`
- `/cart/checkout`: `delivery_pricing.js` puis `checkout_page.js`
- `/vendor/dashboard`: `core_live.js` puis `live.js` et les helpers vendor
- `/vendor/earnings`: `core_live.js` puis `live.js` et les helpers vendor

## Feedback immediat par type d'action

### Pagination AJAX generique

Fichier:

- `app/static/js/ajax_pagination.js`

Flux:

1. clic sur un lien de pagination
2. lien marque avec `data-bm-pending="1"`
3. listing marque `is-loading`
4. remplacement AJAX
5. nettoyage de l'etat pending

### `/shop/shops`

Fichiers:

- `app/static/js/shops_page.js`
- `app/static/css/pages/shops_page.css`

Flux:

1. saisie dans la recherche
2. formulaire passe en `is-pending` pendant la fenetre de debounce
3. clic recherche ou filtre type
4. resultat passe en `is-loading`
5. element declencheur marque `data-bm-pending="1"`
6. nettoyage sur `ajax:page-replaced`, `pageshow` ou `popstate`

### `/shop`

Fichiers:

- `app/static/js/pages/shop_home_page.js`
- `app/static/css/pages/shop_home_page.css`

Flux:

1. clic sur recherche, filtre, tri, pagination ou `load more`
2. le declencheur est marque `data-bm-pending="1"` immediatement
3. le grid produits passe en loading overlay ou inline selon l'action
4. le resultat HTML est remplace
5. nettoyage du pending seulement pour la requete encore courante

Note:

- `add-to-cart` gardait deja un flux optimiste avec compteur panier et bouton temporairement busy

### `/locations`

Fichier:

- `app/static/js/pages/locations_index_page.js`

Flux:

1. blur/enter sur filtre, changement de select, submit ou reset
2. le formulaire passe en `is-optimistic`
3. le declencheur est transmis a `AjaxPagination.navigate(...)`
4. les resultats passent en `is-loading` avec skeleton
5. nettoyage a la fin du swap AJAX ou sur `pageshow`

### `/vendor/dashboard`

Fichiers:

- `app/static/js/pages/vendor/dashboard_page.js`
- `app/static/css/vendor/vendor_dashboard.css`

Flux:

1. clic sur une categorie, pagination des listes du jour ou clear recherche
2. le declencheur est marque `data-bm-pending="1"`
3. overlay produit ou shimmer liste s'active selon l'action
4. remplacement du contenu ou refresh JSON
5. nettoyage du pending a la fin de la requete correspondante

### `/vendor/earnings`

Fichiers:

- `app/static/js/pages/vendor/earnings_page.js`
- `app/static/css/vendor/vendor_earnings_page.css`

Flux:

1. submit filtre, clic pagination ou bouton `Je suis paye`
2. racine `.earnings-page` passe en `is-loading`
3. declencheur marque `data-bm-pending="1"`
4. remplacement HTML AJAX
5. rebind des interactions
6. nettoyage du loading et du pending

Note:

- les auto-refresh `vendor/earnings` utilisent `feedback: false` pour eviter un clignotement visuel toutes les 60 secondes

### Pages conservees avec leur feedback existant

- `/cart/checkout`: loading livraison, geolocalisation et submit deja presents

## Rollback rapide

```js
window.BM_PERF_FLAGS.fastLoader = false;
window.BM_PERF_FLAGS.parallelPageLoader = false;
window.BM_PERF_FLAGS.interactionFeedback = false;
```

Ces flags permettent de revenir progressivement au comportement precedent, sans toucher aux routes ni a la DB.
