# JS Wrappers Audit (SAFE)

Date: 2026-03-05
Scope: `dealnova/app/static/js` (pages, ajax, core, admin, vendor)
Mode: Analyse uniquement (aucune suppression)

## 1) Wrappers détectés

Wrappers/fallbacks recherchés:
- `requestJSON`
- `requestText`
- `withCsrfHeaders`
- `ajaxFetch`
- `safeFetch`
- `fetchWithTimeout`
- `fetchWrapper`
- fallback patterns: `if (window.BMAjaxFetch)`, `if (window.BMAjaxCSRF)`, `if (window.BMAjaxSwap)`, `window.location.href = url`

Définitions/bridges détectés (regex `function/const`): **32**
- Répartition:
  - `requestJSON`: 13 occurrences
  - `requestText`: 12 occurrences
  - `withCsrfHeaders`: 7 occurrences

Noms legacy recherchés sans définition:
- `ajaxFetch`: 0
- `safeFetch`: 0
- `fetchWithTimeout`: 0
- `fetchWrapper`: 0

## 2) Matrice KEEP / REMOVE / REVIEW

| Wrapper | Fichier | Utilisation | Décision |
|---|---|---:|---|
| requestText | `static/js/ajax/core/bm_fetch.js` | export core (0 usage interne) | KEEP |
| requestJSON | `static/js/ajax/core/bm_fetch.js` | export core (0 usage interne) | KEEP |
| requestText | `static/js/admin/admin_table.js` | 5 usages internes | KEEP |
| withCsrfHeaders | `static/js/admin/admin_forms.js` | 3 usages internes | KEEP |
| requestJSON | `static/js/admin/admin_forms.js` | 1 usage interne | KEEP |
| requestText | `static/js/admin/admin_forms.js` | 4 usages internes | KEEP |
| requestJSON | `static/js/core/core_cart.js` | 2 usages internes | KEEP |
| requestText | `static/js/vendor/vendor_shell.js` | 1 usage interne | KEEP |
| requestJSON | `static/js/vendor/vendor_shell.js` | 1 usage interne | KEEP |
| withCsrfHeaders | `static/js/pages/shop_home_page.js` | 1 usage interne | KEEP |
| requestJSON | `static/js/pages/shop_home_page.js` | 5 usages internes | KEEP |
| requestText | `static/js/pages/shop_home_page.js` | 2 usages internes | KEEP |
| withCsrfHeaders | `static/js/pages/search_results_page.js` | 1 usage interne | KEEP |
| requestJSON | `static/js/pages/search_results_page.js` | 6 usages internes | KEEP |
| requestJSON | `static/js/pages/vendor/dashboard_page.js` | 3 usages internes | KEEP |
| requestText | `static/js/pages/vendor/dashboard_page.js` | 1 usage interne | KEEP |
| withCsrfHeaders | `static/js/delivery_pricing.js` | 2 usages internes | REVIEW |
| requestJSON | `static/js/delivery_pricing.js` | 2 usages internes | REVIEW |
| withCsrfHeaders | `static/js/pages/cart_page.js` | 4 usages internes | REVIEW |
| requestJSON | `static/js/pages/cart_page.js` | 4 usages internes | REVIEW |
| requestText | `static/js/pages/cart_page.js` | 1 usage interne | REVIEW |
| withCsrfHeaders | `static/js/pages/checkout_page.js` | 2 usages internes | REVIEW |
| requestJSON | `static/js/pages/checkout_page.js` | 2 usages internes | REVIEW |
| withCsrfHeaders | `static/js/pages/product_detail_page.js` | 2 usages internes | REVIEW |
| requestJSON | `static/js/pages/product_detail_page.js` | 2 usages internes | REVIEW |
| requestJSON | `static/js/pages/shop_detail_page.js` | 2 usages internes | REVIEW |
| requestText | `static/js/pages/shop_detail_page.js` | 1 usage interne | REVIEW |
| requestJSON | `static/js/pages/track_order_page.js` | 2 usages internes | REVIEW |
| requestText | `static/js/pages/admin_logs_page.js` | 2 usages internes | REVIEW |
| requestText | `static/js/pages/admin_locations_page.js` | 2 usages internes | REVIEW |
| requestText | `static/js/pages/courier_deliveries_page.js` | 2 usages internes | REVIEW |
| requestText | `static/js/pages/vendor/earnings_page.js` | 3 usages internes | REVIEW |
| ajaxFetch | (global search) | 0 occurrence | REMOVE (candidate dead code) |
| safeFetch | (global search) | 0 occurrence | REMOVE (candidate dead code) |
| fetchWithTimeout | (global search) | 0 occurrence | REMOVE (candidate dead code) |
| fetchWrapper | (global search) | 0 occurrence | REMOVE (candidate dead code) |

## 3) Preuves ripgrep (ligne par ligne)

### 3.1 Définitions wrappers (extrait)
```bash
rg -n "async function requestJSON\b|function requestJSON\b|const requestJSON\s*=|async function requestText\b|function requestText\b|const requestText\s*=|function withCsrfHeaders\b|const withCsrfHeaders\s*=" dealnova/app/static/js/pages dealnova/app/static/js/ajax dealnova/app/static/js/core dealnova/app/static/js/admin dealnova/app/static/js/vendor dealnova/app/static/js/delivery_pricing.js dealnova/app/static/js/ui_shell.js dealnova/app/static/js/ajax_pagination.js
```
Résultat: **32** lignes (définitions/bridges).

### 3.2 Usage global `requestJSON(`
```bash
rg -n "requestJSON\(" dealnova/app/static/js
```
Résultat: **46** occurrences, dans 14 fichiers (`pages`, `admin`, `core`, `vendor`, `ajax/core`).

### 3.3 Usage global `requestText(`
```bash
rg -n "requestText\(" dealnova/app/static/js
```
Résultat: **37** occurrences, dans 13 fichiers.

### 3.4 Usage global `withCsrfHeaders(`
```bash
rg -n "withCsrfHeaders\(" dealnova/app/static/js
```
Résultat: **22** occurrences, dans 7 fichiers.

### 3.5 Fallback/bridges détectés
```bash
rg -n "if\s*\(\s*window\.BMAjaxFetch|if\s*\(\s*window\.BMAjaxCSRF|if\s*\(\s*window\.BMAjaxSwap|window\.location\.href\s*=\s*url" dealnova/app/static/js/pages dealnova/app/static/js/ajax dealnova/app/static/js/core dealnova/app/static/js/admin
```
Résultats:
- `if (window.BMAjaxFetch...)`: **17**
- `if (window.BMAjaxCSRF...)`: **1**
- `if (window.BMAjaxSwap...)`: **2**
- `window.location.href = url`: **17** (fallback hard-nav)

## 4) Vérification chargement noyau AJAX

Commandes:
```bash
Select-String -Path dealnova/app/templates/base.html,dealnova/app/templates/admin/base.html,dealnova/app/templates/vendor/base.html -Pattern 'js/ajax/core/bm_fetch.js|js/ajax/core/bm_csrf.js|js/ajax/core/bm_guard.js|js/ajax/core/bm_swap.js'
Select-String -Path dealnova/app/templates/vendor/base.html -Pattern '{% extends "base.html" %}'
```

Constat:
- `base.html` charge `bm_csrf`, `bm_guard`, `bm_fetch`, `bm_swap`
- `admin/base.html` charge aussi les mêmes 4 scripts
- `vendor/base.html` étend `base.html` => héritage du même noyau AJAX

Conclusion: le noyau AJAX est bien centralisé et chargé sur les shells principaux.

## 5) Wrappers morts (100% dead candidates)

Preuves `0 match`:
```bash
rg -n "\bajaxFetch\b" dealnova/app
rg -n "\bsafeFetch\b" dealnova/app
rg -n "\bfetchWithTimeout\b" dealnova/app
rg -n "\bfetchWrapper\b" dealnova/app
```
Résultat: **0 occurrence** pour les 4 noms.

## 6) Suppression potentielle (estimation)

Sans suppression immédiate (SAFE), les gains potentiels sont:
- **REMOVE candidates** (4 noms dead): gain faible (quasi nul, noms absents)
- **REVIEW wrappers** (16 entrées page-specific): consolidation potentielle vers noyau/shared helpers estimée **~180 à 320 lignes** selon stratégie

Recommandation SAFE:
1. Ne supprimer maintenant que les vrais `REMOVE` avec preuve 0 refs (déjà morts).
2. Traiter les `REVIEW` par lots (public -> vendor -> admin), avec tests manuels après chaque lot.
3. Conserver tous les `KEEP` (critiques pour robustesse/fallback).
