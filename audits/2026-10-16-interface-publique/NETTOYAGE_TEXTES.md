# BabaMarket — nettoyage des textes publics

Les textes de l’accueil, du catalogue, des fenêtres, des boutiques, des produits, des locations, des réservations, des comptes, du panier et de l’aide ont été relus. Les pages d’erreur, de maintenance et hors connexion sont également concernées.

## Changements

- Suppression des slogans creux, descriptions de remplissage et promesses non documentées de rapidité, qualité ou disponibilité.
- Titres courts et boutons décrivant l’action : « Voir les produits », « Voir la boutique », « Ouvrir WhatsApp », « Préparer la demande ».
- Accents, pluriels, anciens noms de l’application et termes techniques visibles corrigés. Les erreurs des formulaires de compte sont en français.
- Commande, visite et réservation présentées comme des demandes restant à envoyer et à confirmer. Ouvrir WhatsApp ne signifie plus « Message envoyé ».
- États vides et erreurs indiquant l’action suivante, sans promettre une arrivée prochaine d’offres ou de photos. Les erreurs réseau du catalogue n’affichent plus le message technique du navigateur.
- Retrait de la progression de maintenance fictive, qui affichait 65 à 72 % sans mesure réelle.

| Avant | Après |
|---|---|
| Vos envies, vos commerces, tout près. | Repas et produits, services et locations. |
| Vitrine Boutique | Boutique |
| Modalit?s avec le commer?ant | Livraison à confirmer |
| Message WhatsApp envoyé | WhatsApp ouvert ; envoi à effectuer dans WhatsApp |
| Photo à venir | Sans photo |
| Résultats instantanés / mise à jour auto | Les résultats s’actualisent automatiquement. |

## Descriptions enregistrées

Quelques descriptions publiques étaient des valeurs manifestement factices : `CSS`, des suites de lettres et l’ancien placeholder « Boutique officielle de <adresse e-mail> ». Elles sont masquées uniquement à la présentation, dans les fiches, listes, fenêtres, API et résultats de l’assistant.

La fonction `dealnova/app/services/public_text.py` ne filtre que les valeurs précisément revues et le placeholder complet. Elle ne tente pas de deviner l’origine IA d’un texte. Les autres descriptions, noms et avis restent conservés mot pour mot. Aucun enregistrement de la base originale n’a été supprimé ou modifié.

## Vérification

**129 tests ciblés réussis** : suite publique de 128 tests et test de notification de réservation exécuté séparément. Les tests de libellés ont été actualisés tout en conservant leurs contrôles des formulaires, liens, sécurité et actions. Les 18 tests du filtre vérifient notamment la conservation des descriptions légitimes.

Scénarios navigateur réussis dans Chromium et WebKit : filtres, pagination, retour, fenêtres, erreurs/réessai, panier et accès aux formulaires. Contrôle complémentaire des textes à 320, 390 et 1440 px : aucun débordement horizontal ni erreur JavaScript constaté ; les descriptions factices revues sont absentes des pages et des réponses API.

Les contrôles navigateur utilisent une copie SQLite temporaire. Aucun compte, message WhatsApp, e-mail ou commande externe n’a été créé ou envoyé par ces scénarios. Les autres modifications locales ont été conservées.

- [Accueil mobile après nettoyage](textes-accueil-mobile.png)
- [Boutiques sur mobile](textes-boutiques-mobile.png)
- [Fiche boutique sur mobile](textes-boutique-mobile.png)
