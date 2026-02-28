# Plan de Monitoring & Alertes

## Logs
- **Base de données**: le modèle `ActivityLog` stocke les événements (auth, admin, sécurité).
- **Fichier**: `logs/dealnova.log` (créé via `LoggingService.setup_logging()`).

## Alertes (webhook)
- Configurez `SECURITY_ALERT_WEBHOOK_URL` dans `.env` pour recevoir les alertes critiques.
- Les alertes déclenchées incluent actuellement:
  - Dépassement de rate-limit (bruteforce / abus).

## Recommandations
- Mettre en place une rotation de logs (ex: `logrotate`) pour `logs/dealnova.log`.
- Centraliser les logs (ELK, Loki, Datadog) pour la corrélation.
- Ajouter des dashboards:
  - Tentatives de login échouées
  - Taux d’erreurs 4xx/5xx
  - Actions admin sensibles

## WAF / DDoS
- **Cloudflare**: activez WAF + rate limiting côté edge.
- **AWS WAF**: règles OWASP + throttling sur `/auth/*`, `/cart/*`, `/admin/*`.

## Chiffrement
- **Transit**: forcer HTTPS (HSTS activé en prod).
- **Repos**: activer le chiffrement disque/DB (RDS/KMS, LUKS, etc.).
