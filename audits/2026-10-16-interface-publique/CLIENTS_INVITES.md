# Clients en mode invité

- Suppression du formulaire d'inscription client, de son modèle HTML et des liens « Créer mon compte ».
- L'ancienne adresse `/register` redirige vers l'accueil ; aucun compte n'est créé en GET ou POST.
- Connexion réservée aux vendeurs, administrateurs et gestionnaires, y compris lorsqu'une adresse de retour est fournie.
- Les anciennes sessions clients deviennent anonymes. Le panier de session est transféré au panier invité sans cumuler les doublons.
- Les anciens enregistrements et leurs historiques sont conservés en base.
- Navigation publique : « Vendeur » et « Espace vendeur » ; connexion et inscription vendeur conservées.
- Suppression du bloc copyright / Devenir vendeur / Support sous la connexion et sous « Mot de passe oublié ».

## Vérification

- 8 tests du mode invité réussis : inscription désactivée, connexion client refusée, connexions vendeur et équipe, ancienne session et panier, suppression du cookie de reconnexion demandée.
- 45 tests associés réussis : accueil, formulaires, e-mail vendeur, résilience des sessions et panier WhatsApp.
- Tests de données exécutés exclusivement dans SQLite en mémoire ; aperçu sur une copie temporaire de la base.
- Chromium et WebKit : absence d'inscription dans les pages publiques, accès vendeur conservé, redirection de l'ancienne inscription, ajout au panier invité et absence du pied de page sous « Mot de passe oublié » vérifiés.
