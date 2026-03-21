# UI Naming Rules (Anti-Collision)

Purpose: prevent future CSS collisions with Bootstrap and existing global styles.

## Core Rule
- Every new UI class must be prefixed with `bm-` (or `bmui-`).

## Mandatory
- Use prefixed classes for any new component, utility, or state class.
- Scope Bootstrap overrides under a project wrapper when needed.
- Keep existing legacy classes unchanged unless a migration is explicitly requested.

## Forbidden
- Do not create new generic classes like:
  - `.card`, `.navbar`, `.btn`, `.badge`, `.tabs`, `.menu`, `.overlay`, `.panel`, `.grid`
- Do not redefine `.navbar` globally for a new feature.
- Do not add unscoped overrides that can affect all pages.

## Safe Bootstrap Override Pattern
- Preferred:
  - `.bm-shell .navbar { ... }`
  - `.bm-orders .btn { ... }`
- Avoid:
  - `.navbar { ... }` (for new feature styling)

## 10 Examples
1. `bm-drawer-close`
2. `bm-install-banner`
3. `bm-toast`
4. `bm-home-tabs`
5. `bm-home-tab`
6. `bm-order-row`
7. `bm-filter-panel`
8. `bm-empty-state`
9. `bm-status-pill`
10. `bm-quick-action`

## Notes
- Existing classes remain valid.
- This naming rule applies to all new CSS/HTML/JS UI work from now on.
