# Fenêtre de livraison

- Un seul titre « Livraison de colis » et une croix de fermeture.
- Bloc « Zones desservies » : Rabat, Salé, Kénitra et Témara.
- Texte court sur la demande de tarif et de délai.
- Une seule action « Demander un tarif sur WhatsApp », avec un message prérempli et le numéro de livraison configuré.
- Suppression du titre répété, du badge « Livraison locale » et de la barre de boutons en bas pour ce panneau.
- Hauteur ajustée au contenu ; largeur de 480 px sur ordinateur et panneau en bas de l'écran sur mobile.
- La recherche, les filtres et le pied du catalogue réapparaissent dans les autres catégories.

## Vérification

- 45 tests réussis : accueil, catalogue et parcours WhatsApp existant.
- Chromium et WebKit : affichage à 320, 390, 430, 768 et 1280 px, navigation au clavier, retour du focus, fermeture et lien direct vérifiés.
- Vérification en écran court (568 × 320 px) : le contenu reste défilable et le bouton accessible.
- L'ouverture WhatsApp a été interceptée localement dans le navigateur de test ; aucun message envoyé.
- Aperçu exécuté sur une copie temporaire de la base de données.
- Capture : `livraison-propre-mobile.png`.
