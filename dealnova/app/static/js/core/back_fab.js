(function () {
  if (window.__BM_BACK_FAB__) return;
  window.__BM_BACK_FAB__ = true;

  var STORAGE_PREFIX = "bm:backfab:";

  function normalizeUrl(rawUrl) {
    if (!rawUrl) return null;
    try {
      return new URL(String(rawUrl), window.location.origin);
    } catch (_error) {
      return null;
    }
  }

  function samePage(url) {
    if (!url) return false;
    return url.pathname === window.location.pathname && url.search === window.location.search;
  }

  function isAllowedForScope(url, scope) {
    if (!url || url.origin !== window.location.origin || samePage(url)) return false;
    var path = url.pathname || "/";

    if (scope === "admin") {
      return path.indexOf("/admin") === 0;
    }
    if (scope === "owner_locations") {
      return path.indexOf("/owner/location") === 0 || path.indexOf("/owner/locations") === 0;
    }
    if (scope === "vendor") {
      return path.indexOf("/vendor") === 0 || path.indexOf("/owner/location") === 0 || path.indexOf("/owner/locations") === 0;
    }

    return true;
  }

  function storageKey(scope, slot) {
    return STORAGE_PREFIX + String(scope || "public") + ":" + String(slot || "current");
  }

  function readStoredUrl(scope, slot) {
    try {
      var raw = window.sessionStorage.getItem(storageKey(scope, slot));
      return normalizeUrl(raw);
    } catch (_error) {
      return null;
    }
  }

  function writeStoredUrl(scope, slot, url) {
    try {
      if (!url) {
        window.sessionStorage.removeItem(storageKey(scope, slot));
        return;
      }
      window.sessionStorage.setItem(storageKey(scope, slot), url.href);
    } catch (_error) {}
  }

  function rememberCurrentPage(scope) {
    var current = normalizeUrl(window.location.href);
    if (!isAllowedForScope(current, scope) && scope !== "public") return;

    var storedCurrent = readStoredUrl(scope, "current");
    if (storedCurrent && !samePage(storedCurrent) && isAllowedForScope(storedCurrent, scope)) {
      writeStoredUrl(scope, "last", storedCurrent);
    }
    writeStoredUrl(scope, "current", current);
  }

  function getStoredLastUrl(scope) {
    var storedLast = readStoredUrl(scope, "last");
    if (isAllowedForScope(storedLast, scope)) {
      return storedLast;
    }
    return null;
  }

  function resolveTarget(backBtn) {
    var scope = backBtn.getAttribute("data-back-scope") || "public";
    var body = document.body;
    var explicitTarget = normalizeUrl(
      backBtn.getAttribute("data-back-target") || (body ? body.getAttribute("data-back-target") : "") || ""
    );
    if (isAllowedForScope(explicitTarget, scope)) {
      return explicitTarget.href;
    }

    var previousUrl = normalizeUrl(document.referrer || "");
    if (isAllowedForScope(previousUrl, scope)) {
      return previousUrl.href;
    }

    var storedLast = getStoredLastUrl(scope);
    if (storedLast) {
      return storedLast.href;
    }

    var fallback = backBtn.getAttribute("data-fallback") || "/";
    var fallbackUrl = normalizeUrl(fallback);
    return fallbackUrl ? fallbackUrl.href : fallback;
  }

  function shouldShow(backBtn) {
    if (!backBtn) return false;
    if (backBtn.getAttribute("data-back-root") === "1") return false;
    var body = document.body;
    if (body && body.getAttribute("data-home-tabs") === "1") return false;
    if (!hasUsefulTarget(backBtn)) return false;
    if (hasInlineBackControl(backBtn)) return false;
    return true;
  }

  function hasUsefulTarget(backBtn) {
    if (!backBtn) return false;
    var scope = backBtn.getAttribute("data-back-scope") || "public";
    var previousUrl = normalizeUrl(document.referrer || "");
    if (window.history.length > 1 && isAllowedForScope(previousUrl, scope)) return true;
    if (getStoredLastUrl(scope)) return true;
    var fallback = backBtn.getAttribute("data-fallback") || "/";
    var fallbackUrl = normalizeUrl(fallback);
    if (!fallbackUrl) return false;
    if (fallbackUrl.origin !== window.location.origin) return false;
    return !samePage(fallbackUrl);
  }

  function hasInlineBackControl(backBtn) {
    var root = document.querySelector("main") || document.body;
    if (!root) return false;
    var candidates = root.querySelectorAll("a, button");
    for (var i = 0; i < candidates.length; i += 1) {
      var node = candidates[i];
      if (!node || node === backBtn || node.closest(".back-fab")) continue;
      var className = String(node.className || "");
      if (/back-to-top|scroll-top|adm-back-to-top/i.test(className)) continue;
      if (node.closest("footer")) continue;
      if (node.getAttribute("aria-hidden") === "true") continue;
      if (node.offsetParent === null && !node.getClientRects().length) continue;

      var text = String(node.textContent || "").trim().toLowerCase();
      var hasBackClass = /(^|\\s)(detail-back|back-link|btn-back|back-button|tp-back|vd-back|fp-back)(\\s|$)/i.test(className);
      var hasBackText = /(retour|back)/i.test(text);
      var hasArrowIcon = Boolean(node.querySelector(".bi-arrow-left, .bi-arrow-left-circle"));
      var relPrev = String(node.getAttribute("rel") || "").toLowerCase().indexOf("prev") >= 0;
      if (hasBackClass || hasBackText || hasArrowIcon || relPrev || node.hasAttribute("data-inline-back")) {
        return true;
      }
    }
    return false;
  }

  function bindBackFab(backBtn) {
    if (!backBtn || backBtn.dataset.backManaged === "1") return;
    backBtn.dataset.backManaged = "1";

    function syncVisibility() {
      backBtn.style.display = shouldShow(backBtn) ? "flex" : "none";
    }

    var scope = backBtn.getAttribute("data-back-scope") || "public";
    rememberCurrentPage(scope);

    backBtn.addEventListener("click", function (event) {
      event.preventDefault();

      var previousUrl = normalizeUrl(document.referrer || "");
      if (window.history.length > 1 && isAllowedForScope(previousUrl, scope)) {
        window.history.back();
        return;
      }

      if (window.BMPageNav && typeof window.BMPageNav.navigate === "function") {
        window.BMPageNav.navigate(resolveTarget(backBtn));
        return;
      }
      window.location.assign(resolveTarget(backBtn));
    });

    window.addEventListener("pageshow", function () {
      rememberCurrentPage(scope);
      syncVisibility();
    });
    syncVisibility();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      bindBackFab(document.querySelector(".back-fab"));
    }, { once: true });
  } else {
    bindBackFab(document.querySelector(".back-fab"));
  }
})();
