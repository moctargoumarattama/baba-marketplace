# BabaMarket — pages publiques, catalogue et fenêtres

Livraison locale du 16 octobre 2026, dans la continuité de l’accueil validé. Les changements déjà présents dans le projet ont été conservés. Aucun déploiement, commit ou modification de la base originale n’a été effectué.

## Pages et parcours

- Connexion, inscription et récupération : cartes claires, champs lisibles, affichage du mot de passe, erreurs associées aux champs et accès vendeur secondaire. Les formulaires, protections CSRF et traitements d’authentification existants sont conservés.
- Boutiques et fiches boutique : couleurs, titres, cartes, filtres et états vides harmonisés. Les liens générés utilisent `/shops/<slug>` pour éviter les collisions avec les routes de connexion abrégées.
- Locations : catalogue, annonce et demande de visite harmonisés ; prix par jour ou par mois, prix sur demande et médias absents explicités. Le formulaire indique que les coordonnées accompagnent la demande.
- En-tête et navigation mobile communs : accueil, exploration, panier, compte, accès selon le rôle et langues. La présentation est limitée aux pages publiques concernées.

## Catalogue complet

Les résultats viennent de `GET /api/catalog`, avec filtrage, comptage, tri et pagination dans les requêtes SQL. Les 60 offres préchargées pour les anciennes fenêtres ne limitent plus le catalogue.

| Univers | Filtres proposés |
|---|---|
| Produits | Recherche, catégorie, boutique, ville/quartier, prix, stock, promotion |
| Services | Recherche, catégorie, boutique, ville/quartier, prix, promotion |
| Locations | Recherche, boutique, ville/quartier, durée, type de bien, prix |
| Bons plans | Recherche, catégorie, boutique, ville/quartier, prix, stock ; remise effective obligatoire |
| Boutiques | Recherche, ville/quartier |
| Recherche globale | Filtres des offres et des locations ; résultats compatibles avec les critères |

12 résultats par page dans l’interface, maximum serveur de 24. Tri par nouveauté ou prix effectif. Les filtres actifs sont visibles, retirables individuellement et conservés dans l’URL. La recherche dans une boutique ouvre ce même catalogue complet avec son filtre boutique, au-delà des six articles d’aperçu.

Le chargement affiche des cartes d’attente. Aucun résultat propose une réinitialisation. Une erreur réseau propose de réessayer. Les requêtes dépassées sont annulées ; un petit cache de 20 entrées, valable 20 secondes, accélère les retours.

## Fenêtres fluides

Ouverture et fermeture animées, transition principale de 240 ms. Les fenêtres deviennent inertes dès la fermeture et sont masquées après la transition. Sur mobile, une poignée permet de fermer par glissement ; la hauteur suit le viewport visible et les zones système.

Retour navigateur, Échap, confinement Tab, fermeture et restitution du focus restent coordonnés. Revenir d’une fiche au catalogue conserve les critères, la page et la position de défilement. Le réglage système de réduction des animations est respecté. Les requêtes de badges sont annulées quand on quitte une page.

## Vérification

**110 tests ciblés réussis**, couvrant catalogue, navigation publique, authentification, accueil, assistant, panier et commande WhatsApp existante. Deux avertissements de dépréciation Flask-WTF préexistants restent affichés.

Les scénarios navigateur persistants sont dans `dealnova/tests/browser/public_interface.cjs`. Ils passent dans **Chromium et WebKit** : filtres/prix, pagination jusqu’à la page 7, absence de doublons, retour depuis une fiche, aucun résultat/réinitialisation, erreur 503/réessai, recherche boutique, locations/demande de visite, panier, focus, fermeture et réduction des animations. Le glissement est vérifié avec Chromium.

Contrôles de mise en page : Chromium à **320, 390 et 1440 px**, WebKit à **320 et 390 px** sur les fiches boutique/location et le formulaire de visite. Aucun débordement horizontal ni erreur JavaScript constaté. Le [relevé navigateur](validation-navigateurs.json) conserve les résultats.

Les essais utilisent une copie SQLite temporaire, enrichie de **75 articles de validation** et d’une annonce fictive pour vérifier le catalogue au-delà de 60 offres et le parcours location. Les captures de location et les compteurs d’inventaire reflètent cette copie. Aucun compte, commande, e-mail, notification de visite ou message WhatsApp n’a été créé ou envoyé par les scénarios navigateur de cette livraison.

Les simulations Chromium/WebKit ne remplacent pas une validation sur téléphones physiques. Les photos marchandes existantes sont conservées ; certaines restent incohérentes avec leur annonce, comme relevé dans l’audit initial. Les traitements serveur des comptes ne font pas partie de cette harmonisation visuelle.

## Captures de l’application intégrée

| Page | Mobile | Ordinateur |
|---|---|---|
| Connexion | [Voir](harmonisation-connexion-mobile.png) | [Voir](harmonisation-connexion-desktop.png) |
| Inscription | [Voir](harmonisation-inscription-mobile.png) | [Voir](harmonisation-inscription-desktop.png) |
| Boutiques | [Voir](harmonisation-boutiques-mobile.png) | [Voir](harmonisation-boutiques-desktop.png) |
| Boutique | [Voir](harmonisation-boutique-mobile.png) | [Voir](harmonisation-boutique-desktop.png) |
| Catalogue | [Voir](harmonisation-catalogue-mobile.png) | [Voir](harmonisation-catalogue-desktop.png) |
| Locations | [Voir](harmonisation-locations-mobile.png) | [Voir](harmonisation-locations-desktop.png) |
| Annonce de validation | [Voir](harmonisation-location-mobile.png) | [Voir](harmonisation-location-desktop.png) |
| Demande de visite | [Voir](harmonisation-visite-mobile.png) | [Voir](harmonisation-visite-desktop.png) |

[Filtres du catalogue sur mobile](harmonisation-filtres-mobile.png)

## Fichiers principaux

- `app/services/public_catalog.py`, `app/routes/api.py` : requêtes et contrat du catalogue.
- `app/static/js/public_catalog.js`, `app/templates/partials/_catalog_panel.html`, `app/static/css/catalog_panel.css` : catalogue et filtres.
- `app/static/js/ui_home_single_hub.js`, `app/static/js/ui_shell.js` : fenêtres, navigation, aperçu boutique et cycle des requêtes.
- `app/templates/base.html`, `app/templates/partials/_public_header.html`, `app/templates/partials/_public_bottom_nav.html`, `app/static/css/public_refresh.css` : présentation commune.
- `app/templates/auth/`, `app/static/css/pages/auth_refresh.css` : formulaires de compte.
- `app/templates/shop/shops.html`, `app/templates/shop/shop_detail.html`, `app/templates/locations/`, `app/static/css/pages/public_listings_refresh.css` : boutiques et locations.

Les chemins applicatifs de cette liste sont relatifs à `dealnova/`.
