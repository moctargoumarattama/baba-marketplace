(function () {
  var SAFE_PROBE_ID = "bm-home-tabs-safe-probe";

  function onReady(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
    } else {
      fn();
    }
  }

  function normalizePath(raw) {
    try {
      var url = new URL(raw, window.location.origin);
      return (url.pathname || "/").replace(/\/+$/, "") || "/";
    } catch (_err) {
      return "/";
    }
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function ensureSafeProbe() {
    var probe = document.getElementById(SAFE_PROBE_ID);
    if (probe) return probe;

    probe = document.createElement("div");
    probe.id = SAFE_PROBE_ID;
    probe.setAttribute("aria-hidden", "true");
    probe.style.cssText = [
      "position:fixed",
      "left:-9999px",
      "bottom:0",
      "width:0",
      "height:env(safe-area-inset-bottom, 0px)",
      "pointer-events:none",
      "visibility:hidden",
      "z-index:-1"
    ].join(";");
    document.body.appendChild(probe);
    return probe;
  }

  function isStandaloneMode() {
    try {
      if (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) return true;
    } catch (_err) {}
    return !!(window.navigator && window.navigator.standalone);
  }

  function updateDockMetrics(tabs) {
    if (!tabs) return;

    var viewport = window.visualViewport || null;
    var viewportWidth = Math.round((viewport && viewport.width) || window.innerWidth || document.documentElement.clientWidth || 390);
    var viewportHeight = Math.round((viewport && viewport.height) || window.innerHeight || document.documentElement.clientHeight || 844);
    var safeProbe = ensureSafeProbe();
    var safeBottom = safeProbe ? Math.max(0, Math.round(safeProbe.getBoundingClientRect().height || 0)) : 0;
    var standalone = isStandaloneMode();

    var compactness = clamp(((430 - viewportWidth) / 170) + ((820 - viewportHeight) / 420), 0, 1);
    var dockGap = safeBottom > 0 ? clamp(4 + safeBottom * 0.04, 4, 8) : (standalone ? 6 : 8);
    var safeExtension = safeBottom > 0 ? clamp(safeBottom - 4, 10, 30) : (standalone ? 10 : 0);
    var itemHeight = Math.round(clamp(48 - compactness * 4.5, 42, 48));
    var wideItemHeight = Math.round(clamp(itemHeight + 2, 44, 50));
    var tabsWidth = Math.max(264, Math.round(tabs.getBoundingClientRect().width || viewportWidth));
    var tabWidth = Math.max(88, Math.floor(tabsWidth / 3));
    var iconSize = clamp(tabWidth * 0.15, 15, 17.5);
    var labelSize = clamp(tabWidth * 0.082, 8.6, 10.4);

    tabs.style.setProperty("--bm-home-tabs-gap", dockGap + "px");
    tabs.style.setProperty("--bm-home-tabs-safe-extension", safeExtension + "px");
    tabs.style.setProperty("--bm-home-tabs-item-height", itemHeight + "px");
    tabs.style.setProperty("--bm-home-tabs-wide-item-height", wideItemHeight + "px");
    tabs.style.setProperty("--bm-home-tabs-icon-size", iconSize.toFixed(2) + "px");
    tabs.style.setProperty("--bm-home-tabs-label-size", labelSize.toFixed(2) + "px");
  }

  onReady(function () {
    var tabs = document.querySelector("[data-home-bottom-tabs]");
    if (!tabs) return;

    var links = Array.prototype.slice.call(tabs.querySelectorAll(".home-tab[href], .bm-home-tab[href]"));
    if (!links.length) return;

    var currentPath = normalizePath(window.location.pathname);

    links.forEach(function (link) {
      var targetPath = normalizePath(link.getAttribute("href") || "/");
      var active = targetPath === currentPath;
      link.classList.toggle("is-active", active);

      var pressOn = function () { link.classList.add("is-pressed"); };
      var pressOff = function () { link.classList.remove("is-pressed"); };
      link.addEventListener("pointerdown", pressOn, { passive: true });
      link.addEventListener("pointerup", pressOff, { passive: true });
      link.addEventListener("pointercancel", pressOff, { passive: true });
      link.addEventListener("blur", pressOff, { passive: true });
    });

    var rafId = 0;
    function scheduleMetricsUpdate() {
      if (rafId) return;
      rafId = window.requestAnimationFrame(function () {
        rafId = 0;
        updateDockMetrics(tabs);
      });
    }

    updateDockMetrics(tabs);
    window.addEventListener("resize", scheduleMetricsUpdate, { passive: true });
    window.addEventListener("orientationchange", scheduleMetricsUpdate, { passive: true });
    if (window.visualViewport) {
      window.visualViewport.addEventListener("resize", scheduleMetricsUpdate, { passive: true });
      window.visualViewport.addEventListener("scroll", scheduleMetricsUpdate, { passive: true });
    }
  });
})();
