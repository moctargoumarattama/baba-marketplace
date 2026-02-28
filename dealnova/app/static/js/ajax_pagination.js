(function () {
  const SCROLL_KEY_PREFIX = "__ajax_scroll__:";

  function qs(sel, root) {
    return (root || document).querySelector(sel);
  }

  function sameOrigin(url) {
    try {
      const parsed = new URL(url, window.location.href);
      return parsed.origin === window.location.origin;
    } catch (_err) {
      return false;
    }
  }

  function isAjaxPage(root) {
    return !!qs("[data-ajax-listing]", root || document) && !!qs("[data-ajax-pagination]", root || document);
  }

  function normalizeUrlForKey(url) {
    try {
      const parsed = new URL(url, window.location.href);
      return parsed.pathname + parsed.search;
    } catch (_err) {
      return window.location.pathname + window.location.search;
    }
  }

  function saveScrollForNextNavigation(url, scrollY) {
    try {
      const key = SCROLL_KEY_PREFIX + normalizeUrlForKey(url);
      sessionStorage.setItem(key, String(Math.max(0, Number(scrollY) || 0)));
    } catch (_err) {}
  }

  function restoreSavedScrollForCurrentPage() {
    try {
      const key = SCROLL_KEY_PREFIX + normalizeUrlForKey(window.location.href);
      const raw = sessionStorage.getItem(key);
      if (raw == null) return;
      sessionStorage.removeItem(key);
      const y = Math.max(0, parseInt(raw, 10) || 0);
      restoreScroll(y);
    } catch (_err) {}
  }

  function showLoading(container) {
    if (!container) return;
    container.setAttribute("aria-busy", "true");
    container.classList.add("is-loading");
  }

  function hideLoading(container) {
    if (!container) return;
    container.removeAttribute("aria-busy");
    container.classList.remove("is-loading");
  }

  async function fetchHtml(url, signal) {
    const res = await fetch(url, {
      method: "GET",
      headers: { "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
      cache: "no-store",
      signal: signal || null,
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
    return await res.text();
  }

  function replaceListing(html) {
    const parser = new DOMParser();
    const doc = parser.parseFromString(html, "text/html");

    const newListing = qs("[data-ajax-listing]", doc);
    const newPager = qs("[data-ajax-pagination]", doc);
    const curListing = qs("[data-ajax-listing]");
    const curPager = qs("[data-ajax-pagination]");

    if (!newListing || !newPager || !curListing || !curPager) {
      throw new Error("Missing listing/pagination containers in response");
    }

    curListing.replaceWith(newListing);
    curPager.replaceWith(newPager);
  }

  function scrollToListingTop() {
    const listing = qs("[data-ajax-listing]");
    if (!listing) return;
    const rect = listing.getBoundingClientRect();
    const y = window.scrollY + rect.top - 12;
    window.scrollTo({ top: Math.max(0, y), behavior: "auto" });
  }

  function restoreScroll(y) {
    const top = Math.max(0, Number(y) || 0);
    try {
      window.scrollTo({ top: top, behavior: "instant" });
    } catch (_err) {
      window.scrollTo(0, top);
    }
    requestAnimationFrame(function () {
      try {
        window.scrollTo({ top: top, behavior: "instant" });
      } catch (_err2) {
        window.scrollTo(0, top);
      }
    });
  }

  function resolveScrollMode() {
    const listing = qs("[data-ajax-listing]");
    const fromListing = listing ? (listing.getAttribute("data-ajax-scroll") || "").trim().toLowerCase() : "";
    if (fromListing === "top" || fromListing === "preserve") return fromListing;
    const fromBody = ((document.body && document.body.getAttribute("data-ajax-scroll")) || "").trim().toLowerCase();
    if (fromBody === "top" || fromBody === "preserve") return fromBody;
    return "preserve";
  }

  let inflightController = null;

  async function navigate(url, opts) {
    const options = opts || {};
    const push = options.push !== false;
    const startY = window.scrollY || 0;
    const scrollMode = options.scrollMode || resolveScrollMode();

    if (!sameOrigin(url)) {
      saveScrollForNextNavigation(url, startY);
      window.location.href = url;
      return false;
    }

    if (!isAjaxPage()) {
      saveScrollForNextNavigation(url, startY);
      window.location.href = url;
      return false;
    }

    const listing = qs("[data-ajax-listing]");
    showLoading(listing);

    try {
      if (inflightController) inflightController.abort();
      inflightController = new AbortController();

      const html = await fetchHtml(url, inflightController.signal);
      replaceListing(html);
      if (push) history.pushState({ url: url }, "", url);
      if (scrollMode === "top") {
        scrollToListingTop();
      } else {
        restoreScroll(startY);
      }
      document.dispatchEvent(new CustomEvent("ajax:page-replaced", { detail: { url: url } }));
      return true;
    } catch (err) {
      if (err && err.name === "AbortError") return false;
      console.error("AJAX pagination failed, fallback:", err);
      saveScrollForNextNavigation(url, startY);
      window.location.href = url;
      return false;
    } finally {
      hideLoading(qs("[data-ajax-listing]"));
    }
  }

  document.addEventListener("click", function (e) {
    if (e.defaultPrevented) return;
    const a = e.target.closest("a[href]");
    if (!a) return;

    const pager = a.closest("[data-ajax-pagination]");
    if (!pager) return;
    if (a.hasAttribute("data-no-ajax")) return;

    const href = a.getAttribute("href");
    if (!href || href.startsWith("#") || href.startsWith("javascript:")) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || a.target === "_blank") return;

    e.preventDefault();
    navigate(a.href, { push: true });
  });

  window.addEventListener("popstate", function (e) {
    if (!isAjaxPage()) return;
    const url = (e.state && e.state.url) ? e.state.url : window.location.href;
    navigate(url, { push: false });
  });

  window.AjaxPagination = {
    navigate: navigate,
    isAjaxPage: isAjaxPage,
    scrollToListingTop: scrollToListingTop,
    saveScrollForNextNavigation: saveScrollForNextNavigation,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", restoreSavedScrollForCurrentPage, { once: true });
  } else {
    restoreSavedScrollForCurrentPage();
  }
})();
