# Accueil BabaMarket — intégration de la maquette validée

Le nouvel accueil est intégré au projet Flask existant, pour ordinateur et mobile. Les produits, prix, disponibilités et boutiques viennent des données actuelles. Aucun changement de base, de compte ou de commande n'a été effectué sur les données originales.

## Interface

- En-tête clair avec recherche, panier, accès compte et langues ; accès vendeur/administrateur préservés selon le rôle.
- Bandeau compact, palette émeraude et ivoire, six catégories photographiques.
- Produits visibles sur l'accueil, promotions réellement actives, boutiques et services disponibles.
- Navigation mobile Accueil, Explorer, Panier et Compte, avec marge pour la zone système.
- Fenêtres harmonisées : taille du texte, boutons, contrastes, fermeture, focus et hauteur du panier.

Les images des produits et boutiques n'ont pas été remplacées : certaines données locales contiennent des photos incohérentes avec les noms, comme relevé dans l'audit.

## Parcours corrigés

- Les URL panier et finalisation conservent la destination demandée.
- La requête de recherche est conservée ; la saisie seule n'ouvre plus un panneau.
- Retour, Échap et Tab suivent les fenêtres ; l'arrière-plan devient inerte et le focus revient au déclencheur.
- Un ajout panier n'est annoncé comme réussi qu'après confirmation du serveur. Les refus sont affichés.
- Les offres ordinaires ne sont plus étiquetées comme promotions dans le rayon Bons Plans.

## Fichiers principaux

- `dealnova/app/templates/partials/_home_storefront.html` : composants de l'accueil.
- `dealnova/app/templates/home.html` : branchement de l'accueil et conservation des panneaux existants.
- `dealnova/app/static/css/home_refresh.css` : présentation limitée à l'accueil public.
- `dealnova/app/static/js/home_refresh.js` : compte, menus et images indisponibles.
- `dealnova/app/static/js/ui_home_single_hub.js` : comportement des panneaux, historique et panier.
- `dealnova/app/routes/shop.py` : redirections des parcours existants.
- `dealnova/app/__init__.py` : bannière de boutique incluse dans le payload déjà mis en cache.
- `dealnova/app/templates/base.html` : absence de loader de navigation pour les liens ouvrant un panneau local.

Les changements déjà présents avant l'intervention ont été conservés. Les anciens styles restent disponibles pour les autres usages ; l'accueil ne charge plus l'ancien runtime `home_shell`.

## Visuels

Créés avec l'outil intégré **imagegen**, puis encodés en WebP sans recadrage :

- `dealnova/app/static/images/home-refresh/hero.webp` : 1774 × 887, environ 204 Ko.
- `dealnova/app/static/images/home-refresh/categories.webp` : atlas 3 × 2, 1774 × 887, environ 338 Ko.

Brief des prompts : photographie chaleureuse de riz et poisson sénégalais, ingrédients et sac kraft sans texte, espace clair à gauche pour les textes HTML ; six scènes coordonnées sans texte pour repas/épicerie, services, maison, boutique, colis et promotion. Les visuels illustrent le bandeau et les catégories ; ils ne remplacent pas les photos des annonces.

## Vérification

**42 tests ciblés réussis** : rendu avec catalogue vide et rempli, compte invité et vendeur, prix/promotions/stock, liens produits et boutiques, redirections, assistant et commande WhatsApp existante. Un ancien test de l'assistant a été actualisé : il attendait son inclusion dans un ancien template de catalogue déjà remplacé par une redirection avant cette intervention.

Contrôles navigateur sur copie SQLite temporaire :

- Chromium : 320, 360, 390 et 1440 px ; WebKit mobile : 320 et 390 px.
- Aucun débordement horizontal ni erreur JavaScript constaté.
- Recherche, six univers, panneaux et compte vérifiés.
- Ajout panier réel sur session invitée de la copie de test, puis affichage du panier et de la finalisation.
- Refus HTTP 400 simulé : pas de faux succès et badge conservé.
- Retour entre panier/finalisation, fiche/boutique/produit, Échap et confinement Tab vérifiés.

Aucun message WhatsApp ni commande externe envoyé. Les tests ne remplacent pas une validation sur téléphones physiques et avec leurs lecteurs d'écran. La totalité de l'ancien audit, notamment les sujets de sécurité des comptes, ne fait pas partie de cette intégration d'accueil.

## Captures du rendu intégré

- [Accueil mobile](apres-accueil-mobile.png)
- [Accueil ordinateur](apres-accueil-desktop.png)
- [Panier mobile](apres-panier-mobile.png)
- [Finalisation mobile](apres-finalisation-mobile.png)
