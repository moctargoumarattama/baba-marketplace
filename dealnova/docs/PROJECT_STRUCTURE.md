# Project Structure (Quick Guide)

Ce document donne une vue rapide des dossiers et fichiers importants pour comprendre le projet.

## Racine
- `run.py` : point d’entrée de l’application (Flask). Lance l’app.
- `requirements.txt` : dépendances Python.
- `.env` : variables d’environnement (config sensible).
- `upgrade_db.py` : utilitaire de migration/upgrade DB.
- `docs/` : documentation interne.
- `migrations/` : migrations Alembic (si utilisées).
- `instance/` : fichiers d’instance (ex: SQLite).
- `logs/` : logs applicatifs.
- `scripts/` : scripts utilitaires (ex: création admin).
- `venv/` : environnement virtuel local.

## `app/` (cœur de l’application)
### Fichiers principaux
- `app/__init__.py` : factory Flask, enregistrement des blueprints, middlewares, sécurité, routes globales.
- `app/config.py` : configuration (DB, cache, sécurité, etc.).
- `app/extensions.py` : extensions Flask (db, login, cache, mail, etc.).

### `app/routes/` (contrôleurs/blueprints)
- `admin.py` : livraisons, commandes admin, notifications, pricing.
- `admin_users.py` : dashboard admin, users, shops, logs, audit, fraude, catalog, reports.
- `admin_categories.py` : CRUD catégories admin.
- `auth.py` : login/register/logout/password reset.
- `cart.py` : panier, checkout, suivi commandes, WhatsApp.
- `shop.py` : pages boutique côté client (home / produit / avis / suivi).
- `shops.py` : listing boutiques + détail boutique.
- `vendor.py` : espace vendeur (produits, boutique, commandes, revenus).
- `api.py` : endpoints API publics (recherche, panier).
- `forms.py` : formulaires WTForms utilisés par `auth`.

### `app/models/` (modèles SQLAlchemy)
- `user.py` : utilisateurs (admin/vendor/client), auth.
- `shop.py` : boutiques.
- `product.py` : produits.
- `order.py` : commandes + items.
- `vendor_payout.py` : paiements vendeurs.
- `platform_settings.py` : paramètres plateforme.
- `category.py` : catégories.
- `promo.py` : promos/réductions.
- `review.py` : avis produits.
- `audit.py` : logs d’audit.
- `blocked.py` : blocage IP/téléphone pour fraude.

### `app/services/` (logique métier/utilitaires)
- `pricing.py` : prix, commissions, promos.
- `cache.py` : cache catalogue + invalidation.
- `image.py` : traitement images (upload/variants).
- `logging_service.py` : logs applicatifs.
- `audit.py` : audit/traçabilité.
- `alerts.py` : alertes/monitoring (si activé).
- `guest_session.py` : sessions clients sans compte.
- `pagination.py` : pagination simple.
- `migration.py` : helpers de migration DB.

### `app/middleware/`
- `security.py` : protections (headers, etc.).
- `rate_limit.py` : rate limiting.

### `app/templates/`
- `base.html` : layout public.
- `admin/` : layouts et pages admin.
- `vendor/` : pages vendeur.
- `shop/` : pages boutique/public.
- `errors/` : pages d’erreur.

### `app/static/`
- `js/` : scripts frontend (ex: `live.js`).
- `css/` : styles personnalisés.
- `vendor/` : assets locaux (bootstrap, icons, fontawesome).
- `fonts/` : polices locales + CSS.
- `images/` / `uploads/` : médias.
- `manifest.json`, `offline.html` : PWA/offline.

## `docs/`
- `SECURITY_MONITORING.md` : sécurité/monitoring.
- `ROUTES.md` : documentation routes (généré).
- `PROJECT_STRUCTURE.md` : ce fichier.

## `scripts/`
- `create_admin.py` : création admin initial.

## Notes rapides
- Les routes admin/vendeur utilisent `login_required` + rôle.
- Le CSP et les headers sécurité sont définis dans `app/__init__.py`.
- Les assets (bootstrap/fonts) sont maintenant locaux dans `app/static/`.
