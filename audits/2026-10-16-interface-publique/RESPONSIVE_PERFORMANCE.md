# Accueil fluide et performances locales

## Affichage

Suppression des limites de 1 264 et 1 328 px sur le contenu et l'en-tête. L'accueil remplit la largeur disponible avec des marges de 12 à 48 px selon l'écran. Les colonnes de recherche et de navigation peuvent se rétrécir sans pousser le contenu hors de l'écran.

Les catégories restent sur trois colonnes jusqu'à 768 px et six colonnes au-delà. Les formulaires d'authentification et les fenêtres de dialogue gardent des largeurs adaptées à leur contenu.

Chromium et WebKit : 17 largeurs vérifiées de 280 à 3 840 px, dont les seuils 768/769 et 1100/1101 px. Vérification du débordement réel avec le masquage horizontal de la racine désactivé, des libellés et des commandes des trois bannières. Défilement, pause et ouverture du catalogue également vérifiés par le test existant `home_hero.cjs`.

Captures : `accueil-responsive-390.png`, `accueil-responsive-1920.png`, `accueil-responsive-2560.png`.

## Optimisations

- Même logo, dérivé WebP de 168 px : 10 076 octets au lieu de 1 079 507 octets. L'original est conservé.
- Même adresse pour l'image des catégories utilisée dans le CSS et dans la bannière : une seule requête au lieu de deux.
- L'accueil ne calcule plus les 60 offres, les boutiques, les compteurs et les sélections tournantes qui ne sont plus affichés.
- La sélection de promotions encore présente conserve son alimentation et son cache de 60 secondes. Le catalogue complet reste chargé à la demande.

## Mesures et portée

Mesures sur le serveur Flask local, copie temporaire SQLite, sans service worker. Six requêtes successives avec cache actif : médiane avant 34,5 ms, après 24,8 ms (après : 22,5 à 32,1 ms). Ce petit échantillon indique un fonctionnement local ; il ne prouve pas la capacité en production.

Navigation neuve après optimisation, en local à 1920 × 1080 : environ 1,17 Mo de ressources encodées, 36 ressources, chargement à 1,12 s et premier octet à 509 ms. La première navigation inclut l'initialisation à froid ; ces chiffres ne sont pas comparables aux requêtes avec cache actif ci-dessus.

45 tests existants réussis sur le rendu de l'accueil, le catalogue et le cache. Aucun essai de concurrence ou de réseau mobile effectué ; capacité sous charge et latence du serveur réel non mesurées. Données brutes : `performance-responsive.json`.
