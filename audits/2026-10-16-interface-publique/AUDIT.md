# BabaMarket — audit frontend et expérience client publique

**État après corrections :** l’accueil a été intégré ([compte rendu](IMPLEMENTATION.md)). L’harmonisation des pages publiques, le catalogue paginé et les fenêtres animées sont maintenant intégrés et vérifiés ([détails et captures](HARMONISATION.md)). Les constats ci-dessous décrivent l’état initial de l’audit.

Les textes publics ont ensuite été relus et simplifiés : [nettoyage éditorial et exemples](NETTOYAGE_TEXTES.md).

Date : 16 octobre 2026. Audit réalisé avec trois agents : design iPhone/iOS, design Android et parcours client, puis vérification par rendu local.

## Périmètre et méthode

Examen des fichiers actuellement présents, y compris les modifications locales non commitées. Rendu de l'accueil, des rayons, de la fiche produit, des boutiques, de la connexion et de l'inscription. Vérification des entrées catalogue, promotions, locations et panier.

Contrôles dans Chromium : 360 × 800, 390 × 844 et 1440 × 900. Contrôle complémentaire de l'accueil et du rayon produits dans WebKit mobile 390 × 844. Les dimensions mobiles sont des simulations ; elles ne remplacent pas des tests sur iPhone/Android physiques.

L'application a été démarrée avec une copie SQLite isolée dans un dossier temporaire. Aucun fichier applicatif, paramètre métier ni donnée originale n'a été modifié. Seuls ce rapport et ses captures ont été ajoutés au dépôt. Aucune commande WhatsApp, inscription ou notification commerciale n'a été envoyée.

## Diagnostic

L'accueil présente surtout la marque et six raccourcis. Les produits, prix et commerçants restent cachés derrière des fenêtres. Cela explique une partie de l'impression « sèche » : peu de contenu marchand visible, peu de raisons concrètes de poursuivre et une hiérarchie très uniforme.

Le problème visuel des popups vient aussi de leur densité : petits textes, actions serrées, nombreuses bordures, gros fonds floutés et superposition de panneaux. Le parcours doit être simplifié avant d'ajouter des effets décoratifs.

Le vert de marque, l'accès WhatsApp et les six univers peuvent être conservés. Une refonte complète du backend n'est pas nécessaire pour améliorer cette expérience.

## Constats prioritaires

P1 = parcours ou confiance à corriger en premier. P2 = refonte visuelle et confort. P3 = consolidation technique.

| Priorité | Constat | Effet client et correction proposée | Preuve |
|---|---|---|---|
| P1 | Les entrées `/cart/` et `/cart/checkout` redirigent vers le rayon produits. | Le client qui demande son panier ou la finalisation n'obtient pas la destination attendue. Préserver `cart` et `checkout` pendant les redirections. | Les deux URL reproduites en navigateur ; `app/routes/cart.py:628`, `:1173`, `app/routes/shop.py:448`. |
| P1 | La recherche via `/search?q=…` perd le terme saisi pendant la redirection. | La recherche du header peut ouvrir le rayon générique. Préserver la requête et les filtres jusqu'à l'affichage des résultats. | Reproduit avec `/search?q=beurre` ; `app/__init__.py:1044`, puis `app/routes/shop.py:452` ignore les paramètres. |
| P1 | L'ajout panier affiche « Ajouté ! » avant la réponse et ne vérifie ni le statut HTTP ni `success`. | Un refus pour stock insuffisant ou boutique fermée peut être présenté comme un succès. Afficher le succès après confirmation ; restituer l'erreur serveur et conserver un badge exact. | Reproduit avec une réponse HTTP 400 simulée : « Ajouté ! » reste affiché et l'erreur n'apparaît pas. `app/static/js/ui_home_single_hub.js:1611`, `:1628` ; erreurs réelles prévues dans `app/routes/cart.py:696`, `:705`. |
| P1 | La recherche de l'accueil ouvre une fenêtre après deux caractères, en conservant le focus sur le champ derrière. | La saisie déplace le contexte pendant que le client tape. Conserver un seul champ actif, puis afficher les résultats dans un écran ou panneau correctement focalisé. | Reproduit : saisie `be`, panneau ouvert, élément actif `homeSearchInput` ; `app/static/js/ui_home_single_hub.js:1364`. |
| P1 | Le retour navigateur ne ferme pas les fenêtres dans l'ordre de consultation. | Lors du test depuis une page neuve, Retour quitte l'application au lieu de fermer le rayon. Donner une URL/entrée d'historique cohérente aux étapes principales. | Reproduit dans Chromium ; gestionnaire `app/static/js/ui_home_single_hub.js:133`. |
| P1 | Les six cartes de l'accueil ne s'activent pas avec Entrée. Les modales ne déplacent pas le focus à l'ouverture. | Navigation clavier et technologies d'assistance insuffisamment prises en charge. Utiliser boutons/liens natifs et un comportement de dialogue centralisé. | Entrée testée sans ouverture ; focus resté sur la carte après ouverture au clic. `app/templates/home.html:107`, `app/static/js/ui_home_single_hub.js:133`. |
| P1 | Les articles du rayon « Bons Plans » reçoivent le badge PROMO sans condition de réduction. | Une offre ordinaire peut être présentée comme une promotion. Filtrer sur une remise active et afficher ancien prix, nouveau prix et réduction réelle. | Le rendu local montre les mêmes six articles que le rayon produits. Condition du template limitée au type de produit ; `app/templates/home.html:408`. |
| P1 | Le message d'inscription annonce l'envoi du mot de passe par e-mail. Le service construit effectivement ce contenu. | Mauvais signal de confiance pour un compte client. Retirer le mot de passe du message et prévoir une récupération sécurisée. Aucun envoi testé. | `app/templates/auth/register.html:242`, `app/routes/auth.py:221`, `app/services/email_service.py:81`. |
| P2 | Le visuel d'accueil mesure 290 px de haut sur mobile et environ 555 px sur ordinateur à 1440 × 900. | Beaucoup d'espace sert à répéter le nom de marque. Mettre zone de livraison et recherche plus haut, puis des offres et commerces réels. | Mesuré en navigateur ; `app/static/css/ui_home_single_hub.css:37`. |
| P2 | Sur ordinateur, la même photo est utilisée en fond et dans une grande carte superposée. Le contenu reste limité à environ 820 px. | Répétition visuelle, fond flouté chargé et larges marges latérales. Créer une composition desktop propre, avec contenu marchand visible. | Capture `accueil-desktop.png` ; `app/templates/home.html:38`, `:59`, `app/static/css/ui_home_single_hub.css:22`. |
| P2 | Le bandeau des garanties déborde réellement de l'écran mobile. | Début de « Paiement à la livraison » et fin du support sont coupés. Autoriser le retour à la ligne ou afficher des garanties séparées. | À 390 px, premier élément commence à x = −16,6 px et le dernier finit à x = 406,6 px. `app/static/css/ui_home_single_hub.css:398`. |
| P2 | Beaucoup de libellés sont minuscules : champ accueil 13,5 px à 390 px, 12,6 px à 360 px ; badges et descriptions plus petits encore. | Lecture difficile, impression de miniature. Viser une base de texte 15–16 px, des informations secondaires lisibles et des prix plus affirmés. | Valeurs calculées par le navigateur ; `app/static/css/ui_home_single_hub.css:161`, `:355`, `:772`. |
| P2 | Fermetures de 32 × 32 px et actions de cartes compactes. La poignée des fenêtres ne permet pas de glisser. | Utilisation au pouce peu confortable et geste suggéré mais absent. Viser des cibles de 44–48 px et rendre la poignée fonctionnelle ou la retirer. | `app/static/css/ui_home_single_hub.css:577`, `:628` ; `app/templates/home.html:209`. |
| P2 | Les petits textes blancs des boutons utilisent des verts peu contrastés. | Blanc sur `#10b981` : 2,54:1 ; blanc sur `#25d366` : 1,98:1. Assombrir les surfaces des actions ou adapter la couleur du texte. | Calcul sRGB sur les couleurs déclarées ; `app/static/css/ui_home_single_hub.css:850`, `:885`. |
| P2 | Plusieurs fenêtres peuvent rester ouvertes sous la fiche produit. | Fond très assombri, empilement visuel et profondeur difficile à comprendre. Réserver les panneaux aux actions courtes ; ouvrir catalogue et fiche comme écrans navigables. | Univers et fiche simultanément `is-open` pendant le test ; `app/templates/home.html:474`. |
| P2 | L'assistant chevauche une partie du menu dans le rendu Chromium neuf. | Un contrôle d'aide concurrence une fonction essentielle. Fixer une zone de placement qui exclut le header. | Reproduit Chromium desktop et mobile ; absent sur la capture WebKit. Cause précise à investiguer, ne pas généraliser à tous les appareils. |
| P2 | La connexion client commence par un grand encart « Accès vendeur ». | Une action secondaire prend le pas sur le formulaire attendu. Remonter e-mail, mot de passe et connexion ; rendre l'accès vendeur discret et séparé. | Capture `connexion-mobile.png` ; `app/templates/auth/login.html:423`. |
| P2 | Les pages n'emploient pas une même direction graphique. | Accueil sobre, cartes boutiques avec dégradés et nombreux badges, fiche produit plus dense. Harmoniser typographie, surfaces, boutons, espacements et statuts. | Captures accueil, rayon, boutiques et connexion. |
| P2 | Le titre de la page Boutiques devient un rectangle en dégradé sans texte lisible dans le rendu Chromium. | Le titre principal disparaît visuellement. La surcharge `background` doit préserver le découpage du fond au texte ou être remplacée par un titre de couleur unie. | Capture `boutiques-mobile.png` ; `app/static/css/pages/shops_page.css:56`, puis surcharge `:1250`. |
| P3 | Plusieurs générations de styles et de composants coexistent. | Risque de régressions lors des retouches. Consolider les composants actifs avant de poursuivre les surcharges CSS. | `home_shell.css` et `ui_home_single_hub.css` chargés ensemble ; règles répétées et nombreux `!important`. |

## Points iPhone et Android à valider sur appareils

- Les déclarations `88dvh` puis `88vh` font gagner l'ancienne unité dans la cascade. Même problème sur plusieurs panneaux : corriger l'ordre, puis tester les barres de navigateur et le clavier. Source : `app/static/css/ui_home_single_hub.css:538`, `:928`, `:1768`.
- Les actions en bas des panneaux ne réservent pas explicitement la zone de sécurité de l'iPhone. Tester Safari, PWA et paysage ; les variables de safe area existent déjà dans le shell.
- Les champs mobiles inférieurs à 16 px présentent un risque de zoom Safari au focus. Le gestionnaire de clavier existant n'est pas branché sur le hub. L'assistant dispose déjà de son propre traitement du clavier.
- Tester VoiceOver, TalkBack, texte agrandi, fermeture au clavier, retour Android et retour au bon emplacement après consultation d'un article.
- La permission de notifications est sollicitée à la première interaction lorsque le navigateur la prend en charge. La déplacer après une demande explicite utile au client. Source : `app/static/js/client_welcome_notification.js:74`.

## Contenus et confiance

Dans les données locales, certaines photos ne correspondent pas aux produits : karité illustré par un personnage devant des écrans, machine à laver illustrée par un poisson. Certaines descriptions de boutiques contiennent du texte de test. Ces anomalies dégradent fortement le rendu, mais ne prouvent pas un défaut de mapping du frontend ni un problème identique en production. Nettoyer les données de démonstration avant validation visuelle.

La note `4.9` du hero est écrite dans le template et le badge « Livraison express 24h » de la fiche est statique. Les horaires du footer affichent à la fois 8 h–2 h et livraison 24 h/24. Remplacer ces affirmations par des informations justifiées, cohérentes et adaptées au commerçant ou au service.

Le rayon locations était vide dans la copie locale. Ce résultat seul ne prouve pas une anomalie fonctionnelle. Prévoir dans tous les cas un état vide utile, des critères modifiables et un accès à d'autres offres.

Le feed convertit correctement les locations vers les champs attendus par le template. En revanche, les rayons de l'accueil filtrent un ensemble de 60 offres maximum, sans pagination dans ces sections. Tester avec un catalogue plus grand pour vérifier que toutes les offres restent découvrables. Sources : `app/__init__.py:884`, `app/templates/home.html:249`, `:291`, `:333`.

## Direction visuelle recommandée

Une marketplace locale chaleureuse, lisible et vivante : fond ivoire très léger, vert émeraude plus sombre sur les boutons principaux, texte presque noir et photographies soignées. Garder une seule famille de texte et limiter les effets de verre aux endroits où ils servent réellement la lecture.

Ordre proposé pour l'accueil mobile :

1. Header compact avec ville ou zone de livraison.
2. Recherche large, immédiatement accessible.
3. Message commercial court et concret.
4. Six catégories expressives, sans accumulation de petits badges.
5. Produits populaires et bons plans réels, avec prix visibles.
6. Boutiques locales puis services et locations selon le contexte.
7. Réassurance lisible et accès aux informations pratiques.

Navigation mobile proposée : Accueil, Explorer, Panier, Compte. Adapter l'expérience aux usages du pouce, au retour natif et au clavier de chaque plateforme. Conserver le modèle de commande WhatsApp ; ne pas laisser entendre qu'un clic de contact confirme automatiquement une commande.

Un seul système de panneaux pour filtres, options et aperçu rapide : titre clair, fermeture facile, fond léger, contenu aéré, action principale visible, état vide/erreur, focus correct et retour prévisible. Les catalogues, fiches et boutiques doivent pouvoir être repris et partagés par une URL cohérente.

## Ordre de travail recommandé

1. Corriger les parcours cassés : panier, redirections de recherche/filtres, retour et gestion du focus ; assainir les promotions et les messages de confiance.
2. Construire le socle visuel commun : textes, couleurs, espacements, boutons, cartes et panneaux.
3. Recomposer l'accueil avec du contenu marchand réel, puis harmoniser fiche produit, boutiques et panier.
4. Valider sur Chrome Android et Safari iPhone physiques : petits écrans, clavier ouvert, navigation arrière et texte agrandi.

Critères de validation : panier accessible par son URL, recherche conservée au retour, aucun texte coupé à 360/390 px, fermeture accessible, contraste suffisant, rayon vide explicite, aucun badge promotion sans remise, aucune action masquée par l'assistant ou la zone système.

## Captures

- [Accueil mobile — WebKit](accueil-mobile-webkit.png)
- [Accueil mobile — Chromium](accueil-mobile-chromium.png)
- [Accueil ordinateur](accueil-desktop.png)
- [Rayon produits — WebKit](rayon-produits-mobile.png)
- [Boutiques](boutiques-mobile.png)
- [Connexion](connexion-mobile.png)

## Références et limites

Les tailles tactiles natives sont des repères ergonomiques ; un bouton web de 32 px n'est pas automatiquement une violation WCAG. Pour le texte courant, la cible de contraste AA est de 4,5:1. Voir [Android — accessibilité](https://developer.android.com/guide/topics/ui/accessibility/apps), [Apple — boutons](https://developer.apple.com/design/human-interface-guidelines/buttons), [W3C — dialogues modaux](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/) et [W3C — contraste](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html).

Aucun score Lighthouse, test de charge, mesure sur réseau mobile réel ni validation complète des lecteurs d'écran n'a été réalisé. Les tests automatisés existants de l'ancien accueil ne suffisent pas à valider la structure actuelle. Les captures concernent la version locale et ses données, pas le site de production.
