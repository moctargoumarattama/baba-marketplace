# Latency Perception Fixes

## Scope

Lot 1 cible la latence percue et la fluidite, sans modifier les routes metier ni la base de donnees.

Contraintes respectees:

- Pas de changement sur les routes Flask ni sur les requetes SQL.
- Pas de redesign.
- Changements limits, avec rollback simple via flags JS.

## Causes corrigees

### 1. Loader global trop long

Avant:

- Le loader principal attendait `window.load`.
- Les images, videos et autres medias pouvaient prolonger l'ecran blanc alors que le DOM etait deja pret.

Apres:

- Le loader se ferme des que le DOM est pret et qu'un premier paint utile a eu lieu.
- Si les assets critiques de page finissent avant, l'etat `page interactive` force la fermeture immediatement.
- `window.load` reste un filet de securite.
- Un timeout de securite garde un comportement fail-safe.

Fichier:

- `app/templates/base.html`

### 2. Chargement de scripts de page trop sequentiel

Avant:

- `page_loader_client.js` chargeait les scripts un par un sur toutes les pages ciblees.

Apres:

- Les pages prioritaires utilisent des plans de chargement par phases.
- Les phases sans dependances directes sont chargees en parallele.
- Les dependances sensibles gardent un ordre safe.

Exemples:

- `checkout`: `delivery_pricing.js` avant `checkout_page.js`
- `vendor.*`: `core_live.js` avant `live.js`

Fichier:

- `app/static/js/core/page_loader_client.js`

### 3. Feedback visuel immediat manquant sur certaines actions

Avant:

- Certaines actions avaient bien un fetch AJAX, mais peu ou pas de retour visuel avant la reponse.

Apres:

- Pagination AJAX generique: le lien clique passe en pending tout de suite.
- `/shop`: recherche, filtres, pagination et `load more` marquent le declencheur instantanement avant le chargement.
- `/shop/shops`: la recherche et les filtres marquent l'interface comme pending avant la navigation AJAX.
- `/locations`: filtres, selects et reset transmettent le declencheur a la navigation AJAX.
- `/vendor/dashboard`: categories, pagination des listes du jour et reset de recherche marquent le declencheur immediatement.
- `/vendor/earnings`: filtre, pagination et confirmation de paiement passent par un etat loading/pending visible.

Fichiers:

- `app/static/js/ajax_pagination.js`
- `app/static/js/pages/shop_home_page.js`
- `app/static/css/pages/shop_home_page.css`
- `app/static/js/shops_page.js`
- `app/static/js/pages/locations_index_page.js`
- `app/static/js/pages/vendor/dashboard_page.js`
- `app/static/js/pages/vendor/earnings_page.js`
- `app/static/css/ui_shell.css`
- `app/static/css/pages/shops_page.css`
- `app/static/css/vendor/vendor_dashboard.css`
- `app/static/css/vendor/vendor_earnings_page.css`

## Pages impactees

Benefice direct:

- `/shop`
- `/shop/shops`
- `/locations`
- `/cart/checkout`
- `/vendor/dashboard`
- `/vendor/earnings`

Renforcement specifique du feedback:

- `/shop`
- `/shop/shops`
- `/locations`
- `/vendor/dashboard`
- `/vendor/earnings`

Pages deja equipees en loading state et conservees telles quelles:

- `/cart/checkout`

## Rollback

Les flags sont centralises dans `app/templates/base.html` via `window.BM_PERF_FLAGS`.

### Retour loader legacy

```js
window.BM_PERF_FLAGS.fastLoader = false;
```

Effet:

- retour au comportement base sur `window.load`

### Retour page loader sequentiel

```js
window.BM_PERF_FLAGS.parallelPageLoader = false;
```

Effet:

- retour a l'ordre historique de chargement des scripts dynamiques

### Desactiver le feedback pending ajoute

```js
window.BM_PERF_FLAGS.interactionFeedback = false;
```

Effet:

- conserve le fonctionnel
- retire les marqueurs visuels `data-bm-pending` et certains etats pending locaux

## Verification attendue

- Pas de changement metier.
- Pas d'impact DB.
- Console sans erreur rouge.
- Les pages deviennent visibles plus tot.
- Les clics importants donnent un retour immediat meme si la reponse serveur prend encore un peu de temps.

## Notes de prudence

- Le loader rapide traite la latence percue, pas la vitesse backend reelle.
- Le checkout garde un chargement par phases car `checkout_page.js` depend de `DeliveryPricing`.
- Les refresh automatiques de `vendor/earnings` restent silencieux pour eviter un clignotement visuel periodique.
