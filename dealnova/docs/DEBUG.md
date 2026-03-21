# DEBUG

Fast checklist when UI/cache bugs appear.

## 1) Confirm Asset Version

- Check rendered HTML has `?v=<app_static_version>` on CSS/JS URLs.
- If new code is not loaded, bump `APP_STATIC_VERSION` and reload.

## 2) Service Worker Checks

- Open browser devtools:
  - Application/Storage > Service Worker
  - confirm active SW matches current `sw.js?v=...`
- Confirm old caches were removed:
  - cache names should match current version only.
- If needed for diagnosis only:
  - unregister SW and reload once.

## 3) Network Verification

- In Network tab:
  - verify latest CSS/JS URLs include current `?v=...`
  - confirm no stale responses from old cache keys.

## 4) Console Verification

- Check console for:
  - JS syntax/runtime errors
  - missing function errors
  - blocked requests / 404 static assets

## 5) Page Flags / Live Behavior

- Inspect `<body data-page="...">` value.
- Public pages should not run admin heavy polling.
- Admin/courier pages should keep live features active.

## 6) i18n Performance Checks

- `i18n.js` observer should watch a scoped container (`main`), not full body.
- Observer should pause when tab is hidden.
- If CPU spikes, verify no runaway mutation loop.

## 7) Touch Reliability Checks

- Validate hitbox >= 44x44 for main touch actions.
- Confirm `touch-action: manipulation` and correct z-index.
- Test rapid taps on:
  - navbar cart/track icons
  - drawer close button

## 8) Last-Resort Recovery

- Hard refresh the page.
- Clear site storage only if strictly needed.
- Re-test after version bump to confirm cache invalidation path works.
