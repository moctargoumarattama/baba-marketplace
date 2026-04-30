(function () {
  "use strict";

  if (window.__ADM_TABLE_INIT__ && window.AdminTable) {
    window.AdminTable.autoInit();
    return;
  }
  window.__ADM_TABLE_INIT__ = true;
  var makeRequestSeq =
    window.BMCoreDom && typeof window.BMCoreDom.makeRequestSeq === "function"
      ? window.BMCoreDom.makeRequestSeq
      : window.BMAjaxGuard.makeRequestSeq.bind(window.BMAjaxGuard);
  var requestText =
    window.BMCoreDom && typeof window.BMCoreDom.requestText === "function"
      ? window.BMCoreDom.requestText
      : window.BMAjaxFetch.requestText.bind(window.BMAjaxFetch);

  function swapHtml(targetEl, html, mode, useCoreSwap) {
    if (!targetEl) return false;

    var swapMode = mode === "replace" ? "replace" : "inner";
    if (useCoreSwap && window.BMAjaxSwap && typeof window.BMAjaxSwap.swapHTML === "function") {
      var result = window.BMAjaxSwap.swapHTML({
        targetEl: targetEl,
        html: html,
        mode: swapMode,
      });
      return !!(result && result.ok);
    }

    if (swapMode === "replace") {
      var template = document.createElement("template");
      template.innerHTML = String(html || "").trim();
      if (template.content.childElementCount === 1) {
        targetEl.replaceWith(template.content.firstElementChild);
        return true;
      }
    }

    targetEl.innerHTML = html;
    return true;
  }

  function parseSection(doc, selector) {
    try {
      return doc.querySelector(selector);
    } catch (_err) {
      return null;
    }
  }

  function parseDocument(html) {
    try {
      return new DOMParser().parseFromString(String(html || ""), "text/html");
    } catch (_err) {
      return null;
    }
  }

  function dispatchPageReplaced(detail) {
    try {
      document.dispatchEvent(
        new CustomEvent("ajax:page-replaced", {
          detail: Object.assign({}, detail || {}),
        })
      );
    } catch (_err) {}
  }

  function restoreInstantScroll(y) {
    if (window.AdminHelpers && typeof window.AdminHelpers.restoreInstantScroll === "function") {
      window.AdminHelpers.restoreInstantScroll(y);
      return;
    }

    var target = Math.max(Number(y || 0), 0);
    requestAnimationFrame(function () {
      try {
        window.scrollTo({ top: target, left: 0, behavior: "instant" });
      } catch (_err) {
        window.scrollTo(0, target);
      }
    });
  }

  function normalizePageName(value) {
    return String(value || "")
      .trim()
      .toLowerCase();
  }

  function getBodyPageName() {
    return normalizePageName(document.body && document.body.getAttribute("data-adm-page"));
  }

  function getPageInitAttr(pageName) {
    return "data-admPageInit-" + normalizePageName(pageName);
  }

  function getPageDatasetKey(pageName) {
    return "admTableInit_" + normalizePageName(pageName);
  }

  function isPageInitialized(pageName) {
    var body = document.body;
    if (!body) return false;
    var attrReady = body.getAttribute(getPageInitAttr(pageName)) === "1";
    var dataReady = body.dataset && body.dataset[getPageDatasetKey(pageName)] === "1";
    return !!(attrReady || dataReady);
  }

  function markPageInitialized(pageName) {
    var body = document.body;
    if (!body) return;
    body.setAttribute("data-admInit", "1");
    body.setAttribute(getPageInitAttr(pageName), "1");
    body.setAttribute("data-admTableInit", "1");
    body.setAttribute("data-admTableInit-" + normalizePageName(pageName), "1");
    if (body.dataset) {
      body.dataset.admTableInit = "1";
      body.dataset[getPageDatasetKey(pageName)] = "1";
    }
  }

  function initAdminBaseRuntime() {
    var body = document.body;
    if (!body) return null;
    if (window.__ADM_BASE_INIT__) return null;

    window.__ADM_BASE_INIT__ = true;
    body.setAttribute("data-admBaseInit", "1");
    if (body.dataset) {
      body.dataset.admBaseInit = "1";
    }

    var reduceMotion = false;
    try {
      reduceMotion = !!window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch (_err) {
      reduceMotion = false;
    }

    var ADMIN_THEME_KEY = "admin-theme-mode";
    var themeBtn = document.getElementById("adminThemeToggle");
    var currentTheme = function () {
      var theme = document.documentElement.getAttribute("data-admin-theme");
      return theme === "noc" ? "noc" : "default";
    };
    var applyTheme = function (theme) {
      var mode = theme === "noc" ? "noc" : "default";
      document.documentElement.setAttribute("data-admin-theme", mode);
      try {
        localStorage.setItem(ADMIN_THEME_KEY, mode);
      } catch (_err) {}

      if (!themeBtn) return;
      if (mode === "noc") {
        themeBtn.innerHTML = '<i class="bi bi-sun"></i> Clair';
      } else {
        themeBtn.innerHTML = '<i class="bi bi-moon-stars"></i> NOC';
      }
    };
    applyTheme(currentTheme());
    if (themeBtn && themeBtn.dataset.admThemeBound !== "1") {
      themeBtn.dataset.admThemeBound = "1";
      themeBtn.addEventListener("click", function () {
        applyTheme(currentTheme() === "noc" ? "default" : "noc");
      });
    }

    window.__adminGlobalScrollLock = true;
    var yKey = "admin:scroll:lastY";
    var pendingKey = "admin:scroll:pending";
    var saveScroll = function () {
      try {
        var y = Math.max(window.scrollY || 0, 0);
        sessionStorage.setItem(yKey, String(y));
        sessionStorage.setItem(pendingKey, "1");
      } catch (_err) {}
    };
    var restoreScroll = function () {
      try {
        if (sessionStorage.getItem(pendingKey) !== "1") return;
        var raw = sessionStorage.getItem(yKey);
        if (raw == null) return;
        var y = parseInt(raw, 10);
        if (Number.isNaN(y)) return;
        requestAnimationFrame(function () {
          try {
            window.scrollTo({ top: y, left: 0, behavior: "instant" });
          } catch (_err) {
            window.scrollTo(0, y);
          }
        });
        sessionStorage.removeItem(pendingKey);
      } catch (_err) {}
    };
    if ("scrollRestoration" in history) {
      history.scrollRestoration = "manual";
    }
    window.addEventListener("beforeunload", saveScroll, { capture: true });
    document.addEventListener("submit", saveScroll, true);
    document.addEventListener(
      "click",
      function (event) {
        var link = event.target && event.target.closest ? event.target.closest("a[href]") : null;
        if (!link) return;
        if (link.target === "_blank" || link.hasAttribute("download")) return;
        var href = link.getAttribute("href") || "";
        if (!href || href.indexOf("#") === 0 || href.indexOf("javascript:") === 0) return;
        saveScroll();
      },
      true
    );
    window.addEventListener("pageshow", restoreScroll);
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", restoreScroll, { once: true });
    } else {
      restoreScroll();
    }

    try {
      if (!reduceMotion && window.matchMedia("(pointer:fine) and (min-width: 1024px)").matches) {
        var rafId = null;
        document.addEventListener("pointermove", function (event) {
          if (rafId) return;
          rafId = requestAnimationFrame(function () {
            var x = (event.clientX / window.innerWidth) * 100;
            var y = (event.clientY / window.innerHeight) * 100;
            document.documentElement.style.setProperty("--mx", String(x.toFixed(2)) + "%");
            document.documentElement.style.setProperty("--my", String(y.toFixed(2)) + "%");
            rafId = null;
          });
        });
      }
    } catch (_err) {}

    var menuToggle = document.getElementById("menuToggle");
    var sidebar = document.getElementById("sidebar");
    var sidebarBackdrop = document.getElementById("sidebarBackdrop");
    var sidebarMenu = sidebar ? sidebar.querySelector(".nav-menu") : null;
    var sidebarScrollEl = sidebarMenu || sidebar;
    var SIDEBAR_SCROLL_KEY = "admin:sidebar:scroll";

    var saveSidebarScroll = function () {
      if (!sidebarScrollEl) return;
      try {
        sessionStorage.setItem(SIDEBAR_SCROLL_KEY, String(Math.max(sidebarScrollEl.scrollTop || 0, 0)));
      } catch (_err) {}
    };
    var restoreSidebarScroll = function () {
      if (!sidebarScrollEl) return;
      try {
        var raw = sessionStorage.getItem(SIDEBAR_SCROLL_KEY);
        if (raw === null) return;
        var value = parseInt(raw, 10);
        if (!Number.isNaN(value)) {
          sidebarScrollEl.scrollTop = value;
        }
      } catch (_err) {}
    };
    var openSidebar = function () {
      if (!sidebar) return;
      sidebar.classList.add("show");
      if (sidebarBackdrop) sidebarBackdrop.classList.add("show");
      if (menuToggle) menuToggle.setAttribute("aria-expanded", "true");
      document.body.style.overflow = "hidden";
    };
    var closeSidebar = function () {
      if (!sidebar) return;
      sidebar.classList.remove("show");
      if (sidebarBackdrop) sidebarBackdrop.classList.remove("show");
      if (menuToggle) menuToggle.setAttribute("aria-expanded", "false");
      document.body.style.overflow = "";
    };

    if (menuToggle && sidebar && menuToggle.dataset.admSidebarBound !== "1") {
      menuToggle.dataset.admSidebarBound = "1";
      menuToggle.addEventListener("click", function () {
        if (sidebar.classList.contains("show")) {
          closeSidebar();
          return;
        }
        openSidebar();
      });
    }

    if (sidebarBackdrop && sidebarBackdrop.dataset.admSidebarBound !== "1") {
      sidebarBackdrop.dataset.admSidebarBound = "1";
      sidebarBackdrop.addEventListener("click", closeSidebar);
    }

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeSidebar();
    });
    window.addEventListener("resize", function () {
      if (window.innerWidth > 768) closeSidebar();
    });

    if (sidebarScrollEl && sidebarScrollEl.dataset.admSidebarScrollBound !== "1") {
      sidebarScrollEl.dataset.admSidebarScrollBound = "1";
      window.addEventListener("beforeunload", saveSidebarScroll, { capture: true });
      sidebarScrollEl.addEventListener(
        "scroll",
        function () {
          if (sidebarScrollEl.dataset.scrollTicking === "1") return;
          sidebarScrollEl.dataset.scrollTicking = "1";
          requestAnimationFrame(function () {
            saveSidebarScroll();
            sidebarScrollEl.dataset.scrollTicking = "0";
          });
        },
        { passive: true }
      );
      document.addEventListener(
        "click",
        function (event) {
          var navLink =
            event.target && event.target.closest ? event.target.closest(".sidebar .nav-link") : null;
          if (navLink) saveSidebarScroll();
        },
        true
      );
      window.addEventListener("pageshow", function () {
        requestAnimationFrame(restoreSidebarScroll);
      });
      if (document.readyState === "loading") {
        document.addEventListener(
          "DOMContentLoaded",
          function () {
            requestAnimationFrame(restoreSidebarScroll);
          },
          { once: true }
        );
      } else {
        requestAnimationFrame(restoreSidebarScroll);
      }
    }

    if (!reduceMotion) {
      document.querySelectorAll(".nav-link").forEach(function (link) {
        if (link.dataset.admRippleBound === "1") return;
        link.dataset.admRippleBound = "1";
        link.addEventListener("click", function (event) {
          var rect = link.getBoundingClientRect();
          var ripple = document.createElement("span");
          ripple.className = "nav-ripple";
          ripple.style.left = String(event.clientX - rect.left) + "px";
          ripple.style.top = String(event.clientY - rect.top) + "px";
          link.appendChild(ripple);
          window.setTimeout(function () {
            ripple.remove();
          }, 520);
        });
      });
    }

    var backBtn = document.querySelector(".back-fab");
    if (backBtn && backBtn.dataset.admBackFabBound !== "1" && backBtn.dataset.backManaged !== "1") {
      backBtn.dataset.admBackFabBound = "1";
      backBtn.addEventListener("click", function (event) {
        event.preventDefault();
        var fallback = backBtn.getAttribute("data-fallback") || "/";
        if (window.history.length > 1) {
          window.history.back();
          return;
        }
        window.location.href = fallback;
      });
    }

    var offlineBanner = document.getElementById("offlineBanner");
    var updateOfflineBanner = function () {
      if (!offlineBanner) return;
      offlineBanner.classList.toggle("show", !navigator.onLine);
    };
    window.addEventListener("online", updateOfflineBanner);
    window.addEventListener("offline", updateOfflineBanner);
    updateOfflineBanner();

    return {
      body: body,
    };
  }

  function resolvePageRoot(pageName) {
    var selector = '[data-adm-page="' + pageName + '"]';
    return document.querySelector(selector) || document.body;
  }

  function resolveListingElement(pageRoot, pageName) {
    if (!pageRoot || !pageRoot.querySelector) return null;
    return (
      pageRoot.querySelector('[data-adm-listing="' + pageName + '"]') ||
      pageRoot.querySelector(".adm-listing") ||
      pageRoot.querySelector("[data-ajax-listing]")
    );
  }

  function resolvePagerElement(pageRoot, pageName) {
    if (!pageRoot || !pageRoot.querySelector) return null;
    return (
      pageRoot.querySelector('[data-adm-pager="' + pageName + '"]') ||
      pageRoot.querySelector(".adm-pager") ||
      pageRoot.querySelector("[data-ajax-pagination]")
    );
  }

  function resolveSearchElement(pageRoot) {
    if (!pageRoot || !pageRoot.querySelector) return null;
    return pageRoot.querySelector(".adm-search");
  }

  function resolveFiltersElement(pageRoot) {
    if (!pageRoot || !pageRoot.querySelector) return null;
    return pageRoot.querySelector(".adm-filters");
  }

  function getListingSelector(listingEl, pageName) {
    if (listingEl && listingEl.getAttribute("data-adm-listing")) {
      return '[data-adm-listing="' + listingEl.getAttribute("data-adm-listing") + '"]';
    }
    if (listingEl && listingEl.id) {
      return "#" + listingEl.id;
    }
    if (pageName) {
      return '[data-adm-listing="' + pageName + '"]';
    }
    return ".adm-listing";
  }

  function getPagerSelector(pagerEl, pageName) {
    if (pagerEl && pagerEl.getAttribute("data-adm-pager")) {
      return '[data-adm-pager="' + pagerEl.getAttribute("data-adm-pager") + '"]';
    }
    if (pagerEl && pagerEl.id) {
      return "#" + pagerEl.id;
    }
    if (pageName) {
      return '[data-adm-pager="' + pageName + '"]';
    }
    return ".adm-pager";
  }

  function initGenericListPage(options) {
    var cfg = options || {};
    var pageName = normalizePageName(cfg.pageName || getBodyPageName());
    if (!pageName) return null;

    var pageRoot = resolvePageRoot(pageName);
    if (!pageRoot) return null;
    if (isPageInitialized(pageName)) return null;

    var listingEl = resolveListingElement(pageRoot, pageName);
    var pagerEl = resolvePagerElement(pageRoot, pageName);
    var searchInput = resolveSearchElement(pageRoot);
    var filtersEl = resolveFiltersElement(pageRoot);
    if (!listingEl && !pagerEl && !searchInput && !filtersEl) return null;

    markPageInitialized(pageName);

    var seq = makeRequestSeq();
    var activeController = null;
    var loadingLock = false;
    var historyMode = normalizePageName(cfg.historyMode || "replace");

    function getCurrentListing() {
      return resolveListingElement(pageRoot, pageName);
    }

    function getCurrentPager() {
      return resolvePagerElement(pageRoot, pageName);
    }

    function getCurrentFilters() {
      return resolveFiltersElement(pageRoot);
    }

    function isAjaxNavigableLink(link) {
      if (!link || !link.getAttribute) return false;
      var href = String(link.getAttribute("href") || "").trim();
      if (!href || href.charAt(0) === "#") return false;
      if (link.hasAttribute("download")) return false;
      if (link.target && String(link.target).toLowerCase() === "_blank") return false;
      var lowerHref = href.toLowerCase();
      if (lowerHref.indexOf("javascript:") === 0) return false;
      if (lowerHref.indexOf("mailto:") === 0 || lowerHref.indexOf("tel:") === 0) return false;
      return true;
    }

    function filterListingRows() {
      if (!searchInput) return;
      var listing = getCurrentListing();
      if (!listing) return;
      var query = normalizePageName(searchInput.value);
      var rows = Array.prototype.slice.call(listing.querySelectorAll("tbody tr"));
      if (!rows.length) return;

      rows.forEach(function (row) {
        var text = normalizePageName(row.textContent);
        row.style.display = !query || text.indexOf(query) !== -1 ? "" : "none";
      });
    }

    async function fetchAndSwap(url) {
      if (!url || loadingLock) return;
      loadingLock = true;
      var keepY = window.scrollY || 0;

      if (activeController && typeof activeController.abort === "function") {
        try {
          activeController.abort();
        } catch (_err) {}
      }
      activeController = typeof AbortController !== "undefined" ? new AbortController() : null;

      try {
        var requestId = seq.next();
        var response = await requestText(url, {
          headers: { "X-Requested-With": "XMLHttpRequest" },
          signal: activeController ? activeController.signal : undefined,
        });

        if (!seq.isLatest(requestId)) {
          return;
        }

        if (!response.ok) {
          if (!response.aborted) {
            window.location.href = url;
          }
          return;
        }

        var doc = parseDocument(response.data);
        if (!doc) {
          window.location.href = url;
          return;
        }

        var currentListing = getCurrentListing();
        var currentPager = getCurrentPager();
        var currentFilters = getCurrentFilters();
        var listingSelector = getListingSelector(currentListing || listingEl, pageName);
        var pagerSelector = getPagerSelector(currentPager || pagerEl, pageName);
        var nextListing = parseSection(doc, listingSelector);
        var nextPager = parseSection(doc, pagerSelector);
        var nextFilters = currentFilters ? parseSection(doc, ".adm-filters") : null;

        if (!currentListing || !nextListing) {
          window.location.href = url;
          return;
        }

        if (!swapHtml(currentListing, nextListing.innerHTML)) {
          window.location.href = url;
          return;
        }

        currentPager = getCurrentPager();
        if (
          currentPager &&
          nextPager &&
          !currentListing.contains(currentPager) &&
          !swapHtml(currentPager, nextPager.innerHTML)
        ) {
          window.location.href = url;
          return;
        }

        currentFilters = getCurrentFilters();
        if (
          currentFilters &&
          nextFilters &&
          !currentListing.contains(currentFilters) &&
          !swapHtml(currentFilters, nextFilters.innerHTML)
        ) {
          window.location.href = url;
          return;
        }

        try {
          if (historyMode === "push" && window.history && typeof window.history.pushState === "function") {
            window.history.pushState({}, "", url);
          } else {
            window.history.replaceState({}, "", url);
          }
        } catch (_err) {}

        if (typeof window.initAdminContent === "function") {
          window.initAdminContent(pageRoot);
        }

        filterListingRows();
        restoreInstantScroll(keepY);
        dispatchPageReplaced({ url: url, page: pageName, target: getCurrentListing() || pageRoot });
      } catch (_err) {
        window.location.href = url;
      } finally {
        loadingLock = false;
      }
    }

    function getFormRequestUrl(form) {
      if (!form) return null;
      var formAction = String(form.getAttribute("action") || window.location.pathname || "").trim();
      var params = new URLSearchParams(new FormData(form));
      try {
        var urlObj = new URL(formAction || window.location.pathname, window.location.href);
        urlObj.search = params.toString();
        return urlObj.pathname + (urlObj.search || "") + (urlObj.hash || "");
      } catch (_err) {
        var hasQuery = formAction.indexOf("?") !== -1;
        var query = params.toString();
        if (!query) return formAction;
        return formAction + (hasQuery ? "&" : "?") + query;
      }
    }

    var navBoundAttr = "data-adm-nav-bound-" + pageName;
    if (pageRoot.getAttribute(navBoundAttr) !== "1") {
      pageRoot.setAttribute(navBoundAttr, "1");
      pageRoot.addEventListener("click", function (event) {
        var target = event.target;
        if (!target || !target.closest) return;

        var pagerLink = target.closest(".page-link");
        var pager = getCurrentPager();
        if (pagerLink && pager && pager.contains(pagerLink)) {
          var pagerHref = pagerLink.getAttribute("href");
          var parent = pagerLink.closest(".page-item");
          if (!pagerHref || (parent && parent.classList.contains("disabled")) || !isAjaxNavigableLink(pagerLink)) {
            return;
          }
          event.preventDefault();
          fetchAndSwap(pagerHref);
          return;
        }

        var filterLink = target.closest("[data-adm-filter-link], .adm-filters a[href]");
        if (!filterLink || !isAjaxNavigableLink(filterLink)) return;
        var filters = getCurrentFilters();
        var insideFilters = filters && filters.contains(filterLink);
        if (!insideFilters && !filterLink.hasAttribute("data-adm-filter-link")) return;
        event.preventDefault();
        fetchAndSwap(filterLink.getAttribute("href"));
      });
    }

    var submitBoundAttr = "data-adm-submit-bound-" + pageName;
    if (pageRoot.getAttribute(submitBoundAttr) !== "1") {
      pageRoot.setAttribute(submitBoundAttr, "1");
      pageRoot.addEventListener("submit", function (event) {
        var form = event.target;
        if (!form || !form.matches || !form.matches("form.adm-filters")) return;
        var method = normalizePageName(form.getAttribute("method") || "get");
        if (method && method !== "get") return;
        if (!pageRoot.contains(form)) return;
        event.preventDefault();
        var requestUrl = getFormRequestUrl(form);
        if (!requestUrl) return;
        fetchAndSwap(requestUrl);
      });
    }

    if (searchInput && searchInput.dataset.admQuickSearchBound !== "1") {
      searchInput.dataset.admQuickSearchBound = "1";
      searchInput.addEventListener("input", filterListingRows);
    }

    filterListingRows();
    return {
      pageName: pageName,
      pageRoot: pageRoot,
    };
  }

  function initOrdersPage(options) {
    var cfg = options || {};
    var pageRoot = document.querySelector(cfg.pageRootSelector || '[data-orders-page="true"]');
    if (!pageRoot) return null;
    if (pageRoot.dataset.admOrdersInit === "1") return null;
    pageRoot.dataset.admOrdersInit = "1";
    markPageInitialized("orders");

    var sectionSelector = cfg.sectionSelector || ".orders-table";
    var tableSelector = cfg.tableSelector || "#ordersTable tbody .order-row";
    var quickSearchSelector = cfg.quickSearchSelector || "#ordersQuickSearch";
    var quickMetaSelector = cfg.quickMetaSelector || "#ordersQuickMeta";
    var loadingSelector = cfg.loadingSelector || "#positionLoading";
    var backToTopSelector = cfg.backToTopSelector || "#backToTop";
    var paginationLinkSelector = cfg.paginationLinkSelector || ".orders-table .page-link";

    var quickSearchInput = document.querySelector(quickSearchSelector);
    var quickMeta = document.querySelector(quickMetaSelector);
    var loadingIndicator = document.querySelector(loadingSelector);
    var backToTopBtn = document.querySelector(backToTopSelector);
    var seq = makeRequestSeq();
    var activeController = null;

    function setLoading(on) {
      if (!loadingIndicator) return;
      loadingIndicator.classList.toggle("show", !!on);
    }

    function initQuickSearch() {
      if (!quickSearchInput) return;
      var rows = Array.prototype.slice.call(document.querySelectorAll(tableSelector));
      if (!rows.length) {
        if (quickMeta) quickMeta.textContent = "";
        return;
      }

      var query = String(quickSearchInput.value || "").trim().toLowerCase();
      var visible = 0;

      rows.forEach(function (row) {
        var text = String(row.textContent || "").toLowerCase();
        var match = !query || text.indexOf(query) !== -1;
        row.style.display = match ? "" : "none";
        if (match) visible += 1;
      });

      if (quickMeta) {
        quickMeta.textContent = query ? (visible + "/" + rows.length + " visibles") : "";
      }
    }

    async function onPaginationClick(event) {
      var link = event.target && event.target.closest ? event.target.closest(paginationLinkSelector) : null;
      if (!link || !pageRoot.contains(link)) return;

      var href = link.getAttribute("href");
      var parent = link.closest(".page-item");
      if (!href || (parent && parent.classList.contains("disabled"))) return;

      event.preventDefault();

      var keepY = window.scrollY || 0;
      setLoading(true);

      if (activeController && typeof activeController.abort === "function") {
        try {
          activeController.abort();
        } catch (_err) {}
      }
      activeController = typeof AbortController !== "undefined" ? new AbortController() : null;

      var requestId = seq.next();
      var response = await requestText(href, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
        signal: activeController ? activeController.signal : undefined,
      });

      if (!seq.isLatest(requestId)) {
        setLoading(false);
        return;
      }

      if (!response.ok) {
        setLoading(false);
        if (!response.aborted) {
          window.location.href = href;
        }
        return;
      }

      var parsed = parseDocument(response.data);
      var nextSection = parsed ? parseSection(parsed, sectionSelector) : null;
      var currentSection = document.querySelector(sectionSelector);
      if (!nextSection || !currentSection) {
        setLoading(false);
        window.location.href = href;
        return;
      }

      var swapped = swapHtml(currentSection, nextSection.innerHTML);
      if (!swapped) {
        setLoading(false);
        window.location.href = href;
        return;
      }

      try {
        window.history.replaceState({}, "", href);
      } catch (_err) {}

      if (typeof window.initAdminContent === "function") {
        window.initAdminContent(currentSection);
      }

      initQuickSearch();
      restoreInstantScroll(keepY);
      dispatchPageReplaced({ url: href, page: "orders", target: currentSection });
      setLoading(false);
    }

    pageRoot.addEventListener("click", function (event) {
      onPaginationClick(event).catch(function () {
        var link = event.target && event.target.closest ? event.target.closest(paginationLinkSelector) : null;
        if (link && link.getAttribute("href")) {
          window.location.href = link.getAttribute("href");
        }
        setLoading(false);
      });
    });

    if (quickSearchInput && quickSearchInput.dataset.admQuickSearchBound !== "1") {
      quickSearchInput.dataset.admQuickSearchBound = "1";
      quickSearchInput.addEventListener("input", initQuickSearch);
    }

    initQuickSearch();

    if (
      backToTopBtn &&
      window.AdminHelpers &&
      typeof window.AdminHelpers.initBackToTop === "function" &&
      backToTopBtn.dataset.admBackTopBound !== "1"
    ) {
      backToTopBtn.dataset.admBackTopBound = "1";
      window.AdminHelpers.initBackToTop({
        button: backToTopBtn,
        threshold: Number(backToTopBtn.getAttribute("data-threshold") || 320),
        behavior: "smooth",
      });
    }

    return {
      refreshQuickSearch: initQuickSearch,
    };
  }

  function initDeliveriesPage(options) {
    var cfg = options || {};
    var pageName = "deliveries";
    var body = document.body;
    var pageRoot = document.querySelector(cfg.pageRootSelector || '[data-deliveries-page="true"]');
    if (!pageRoot) return null;
    if (pageRoot.dataset.admDeliveriesInit === "1") return null;
    if (window.__ADM_DELIVERIES_INIT__) return null;
    if (body && body.dataset && body.dataset.admDeliveriesInit === "1") return null;

    window.__ADM_DELIVERIES_INIT__ = true;
    pageRoot.dataset.admDeliveriesInit = "1";
    if (body) {
      body.setAttribute("data-admDeliveriesInit", "1");
      if (body.dataset) {
        body.dataset.admDeliveriesInit = "1";
      }
    }
    markPageInitialized(pageName);

    var seq = makeRequestSeq();
    var activeController = null;
    var loading = false;
    var loadingEl = pageRoot.querySelector("#filterLoading");
    var backToTopBtn = pageRoot.querySelector("#backToTop");
    var listingSelector = '[data-adm-listing="deliveries-history"]';
    var pagerSelector = '[data-adm-pager="deliveries-history"]';

    function setLoading(on) {
      if (!loadingEl) return;
      loadingEl.classList.toggle("show", !!on);
    }

    function getCurrentListing() {
      return pageRoot.querySelector(listingSelector) || pageRoot.querySelector(".deliveries-section:last-child");
    }

    function getCurrentPager() {
      return pageRoot.querySelector(pagerSelector);
    }

    async function fetchAndSwap(url, pushState) {
      if (!url || loading) return;
      loading = true;
      setLoading(true);
      var keepY = window.scrollY || 0;
      try {
        if (activeController && typeof activeController.abort === "function") {
          try {
            activeController.abort();
          } catch (_err) {}
        }
        activeController = typeof AbortController !== "undefined" ? new AbortController() : null;

        var requestId = seq.next();
        var response = await requestText(url, {
          headers: {
            "X-Requested-With": "XMLHttpRequest",
          },
          signal: activeController ? activeController.signal : undefined,
        });

        if (!seq.isLatest(requestId)) {
          return;
        }

        if (!response.ok) {
          if (!response.aborted) {
            window.location.href = url;
          }
          return;
        }

        var doc = parseDocument(response.data);
        var currentListing = getCurrentListing();
        var nextListing = doc ? parseSection(doc, listingSelector) : null;
        if (!nextListing) {
          nextListing = doc ? parseSection(doc, ".deliveries-section:last-child") : null;
        }
        if (!currentListing || !nextListing) {
          window.location.href = url;
          return;
        }

        var listingSwapped = swapHtml(currentListing, nextListing.innerHTML, "inner", true);
        if (!listingSwapped) {
          window.location.href = url;
          return;
        }

        var currentPager = getCurrentPager();
        var nextPager = doc ? parseSection(doc, pagerSelector) : null;
        if (currentPager && nextPager && !currentListing.contains(currentPager)) {
          if (!swapHtml(currentPager, nextPager.innerHTML, "inner", true)) {
            window.location.href = url;
            return;
          }
        }

        if (pushState && window.history && typeof window.history.pushState === "function") {
          try {
            window.history.pushState({}, "", url);
          } catch (_err) {}
        }

        if (typeof window.initAdminContent === "function") {
          window.initAdminContent(currentListing);
        }

        restoreInstantScroll(keepY);
        dispatchPageReplaced({ url: url, page: pageName, target: getCurrentListing() || pageRoot });
      } catch (_err) {
        window.location.href = url;
      } finally {
        loading = false;
        setLoading(false);
      }
    }

    pageRoot.addEventListener("click", function (event) {
      var link = event.target && event.target.closest ? event.target.closest(".page-link") : null;
      if (link && getCurrentPager() && getCurrentPager().contains(link)) {
        var href = link.getAttribute("href");
        var parent = link.closest(".page-item");
        if (!href || (parent && parent.classList.contains("disabled"))) return;
        event.preventDefault();
        fetchAndSwap(href, true).catch(function () {
          window.location.href = href;
        });
        return;
      }

      var resetBtn = event.target && event.target.closest ? event.target.closest("#resetFilters") : null;
      if (!resetBtn || !pageRoot.contains(resetBtn)) return;
      var resetHref = resetBtn.getAttribute("href");
      if (!resetHref) return;
      event.preventDefault();
      fetchAndSwap(resetHref, true).catch(function () {
        window.location.href = resetHref;
      });
    });

    pageRoot.addEventListener("submit", function (event) {
      var form = event.target;
      if (!form || !form.matches || !form.matches("form.adm-filters")) return;
      if (!pageRoot.contains(form)) return;
      event.preventDefault();

      var params = new URLSearchParams(new FormData(form));
      var baseUrl = form.getAttribute("action") || window.location.pathname;
      var url = baseUrl + (params.toString() ? "?" + params.toString() : "");
      fetchAndSwap(url, true).catch(function () {
        window.location.href = url;
      });
    });

    if (
      backToTopBtn &&
      window.AdminHelpers &&
      typeof window.AdminHelpers.initBackToTop === "function" &&
      backToTopBtn.dataset.admBackTopBound !== "1"
    ) {
      backToTopBtn.dataset.admBackTopBound = "1";
      window.AdminHelpers.initBackToTop({
        button: backToTopBtn,
        threshold: Number(backToTopBtn.getAttribute("data-threshold") || 320),
        behavior: "smooth",
      });
    }

    return {
      pageName: pageName,
      pageRoot: pageRoot,
    };
  }

  function initFraudPage(options) {
    var cfg = options || {};
    var pageName = "fraud";
    var body = document.body;
    var pageRoot = document.querySelector(cfg.pageRootSelector || "#fraudContent");
    if (!pageRoot) return null;
    if (pageRoot.dataset.admFraudInit === "1") return null;
    if (window.__ADM_FRAUD_INIT__) return null;
    if (body && body.dataset && body.dataset.admFraudInit === "1") return null;

    window.__ADM_FRAUD_INIT__ = true;
    pageRoot.dataset.admFraudInit = "1";
    if (body) {
      body.setAttribute("data-admFraudInit", "1");
      if (body.dataset) {
        body.dataset.admFraudInit = "1";
      }
    }
    markPageInitialized(pageName);

    var backToTopBtn = pageRoot.querySelector("#backToTop");
    var soundToggle = pageRoot.querySelector("#soundToggle");
    var filterForm = pageRoot.querySelector("#fraudFiltersForm");
    var cleanBtn = pageRoot.querySelector("#fraudCleanTwoDays");
    var stampEl = pageRoot.querySelector("#fraudLastUpdated");

    if (
      backToTopBtn &&
      window.AdminHelpers &&
      typeof window.AdminHelpers.initBackToTop === "function" &&
      backToTopBtn.dataset.admBackTopBound !== "1"
    ) {
      backToTopBtn.dataset.admBackTopBound = "1";
      window.AdminHelpers.initBackToTop({
        button: backToTopBtn,
        threshold: Number(backToTopBtn.getAttribute("data-threshold") || 300),
        behavior: "smooth",
      });
    }

    if (soundToggle && soundToggle.dataset.admSoundBound !== "1") {
      soundToggle.dataset.admSoundBound = "1";
      var soundEnabled = localStorage.getItem("adminFraudSound") !== "0";
      var syncSoundLabel = function () {
        soundToggle.innerHTML = soundEnabled
          ? '<i class="bi bi-volume-up"></i> Son: On'
          : '<i class="bi bi-volume-mute"></i> Son: Off';
      };
      syncSoundLabel();
      soundToggle.addEventListener("click", function () {
        soundEnabled = !soundEnabled;
        localStorage.setItem("adminFraudSound", soundEnabled ? "1" : "0");
        syncSoundLabel();
      });
    }

    if (window.AdminHelpers && typeof window.AdminHelpers.initScrollMemory === "function") {
      var scrollMemory = window.AdminHelpers.initScrollMemory({
        key: "fraud_page_position",
        maxAgeMs: 10 * 60 * 1000,
        saveDebounceMs: 500,
        behavior: "smooth",
        restoreDelayMs: 100,
        getContext: function () {
          return Object.fromEntries(new URLSearchParams(window.location.search));
        },
        saveOnSelectors: ['a:not([href^="#"])', 'button[type="submit"]'],
      });
      if (scrollMemory) {
        scrollMemory.bind();
        scrollMemory.restore();
      }
    }

    function initFraudTablePager(table, index) {
      if (!table || table.dataset.admPagerBound === "1") return;
      table.dataset.admPagerBound = "1";
      var pageSize = Number(table.getAttribute("data-page-size") || 10);
      if (!Number.isFinite(pageSize) || pageSize <= 0) return;

      var tbody = table.tBodies && table.tBodies[0];
      if (!tbody) return;

      var rows = Array.prototype.slice
        .call(tbody.rows || [])
        .filter(function (row) {
          return !row.querySelector(".fraud-empty");
        });

      var wrap = table.closest(".table-responsive");
      if (!wrap) return;

      var existingPager = wrap.nextElementSibling;
      if (existingPager && existingPager.classList.contains("fraud-pager")) {
        existingPager.remove();
      }

      if (rows.length <= pageSize) {
        rows.forEach(function (row) {
          row.style.display = "";
        });
        return;
      }

      var currentPage = 1;
      var totalPages = Math.ceil(rows.length / pageSize);

      var pager = document.createElement("div");
      pager.className = "fraud-pager adm-pager";
      pager.setAttribute("data-adm-pager", "fraud-" + String(index + 1));

      var prevBtn = document.createElement("button");
      prevBtn.type = "button";
      prevBtn.innerHTML = '<i class="bi bi-chevron-left"></i> Pr\u00e9c\u00e9dent';

      var nextBtn = document.createElement("button");
      nextBtn.type = "button";
      nextBtn.innerHTML = 'Suivant <i class="bi bi-chevron-right"></i>';

      var info = document.createElement("span");
      info.className = "fraud-page-info";

      pager.appendChild(prevBtn);
      pager.appendChild(info);
      pager.appendChild(nextBtn);
      wrap.insertAdjacentElement("afterend", pager);

      function render() {
        var start = (currentPage - 1) * pageSize;
        var end = start + pageSize;

        rows.forEach(function (row, rowIndex) {
          row.style.display = rowIndex >= start && rowIndex < end ? "" : "none";
        });

        info.textContent = "Page " + currentPage + "/" + totalPages + " - " + rows.length + " \u00e9l\u00e9ments";
        prevBtn.disabled = currentPage <= 1;
        nextBtn.disabled = currentPage >= totalPages;
      }

      prevBtn.addEventListener("click", function () {
        if (currentPage <= 1) return;
        currentPage -= 1;
        render();
      });

      nextBtn.addEventListener("click", function () {
        if (currentPage >= totalPages) return;
        currentPage += 1;
        render();
      });

      render();
    }

    pageRoot.querySelectorAll(".fraud-table").forEach(initFraudTablePager);

    if (cleanBtn && cleanBtn.dataset.admBound !== "1") {
      cleanBtn.dataset.admBound = "1";
      cleanBtn.addEventListener("click", function () {
        if (!filterForm) return;
        var daysInput = filterForm.querySelector('input[name="days"]');
        if (daysInput) daysInput.value = 2;
        filterForm.submit();
      });
    }

    if (stampEl && stampEl.dataset.admTickerBound !== "1") {
      stampEl.dataset.admTickerBound = "1";
      var stampTimerId = null;
      var updateStamp = function () {
        var now = new Date();
        var year = now.getFullYear();
        var month = String(now.getMonth() + 1).padStart(2, "0");
        var day = String(now.getDate()).padStart(2, "0");
        var hours = String(now.getHours()).padStart(2, "0");
        var minutes = String(now.getMinutes()).padStart(2, "0");
        var seconds = String(now.getSeconds()).padStart(2, "0");
        stampEl.textContent = year + "-" + month + "-" + day + " " + hours + ":" + minutes + ":" + seconds;
      };

      var stopTicker = function () {
        if (!stampTimerId) return;
        window.clearInterval(stampTimerId);
        stampTimerId = null;
      };

      var startTicker = function () {
        if (stampTimerId || document.hidden) return;
        updateStamp();
        stampTimerId = window.setInterval(updateStamp, 1000);
      };

      var onVisibilityChange = function () {
        if (document.hidden) {
          stopTicker();
          return;
        }
        startTicker();
      };

      document.addEventListener("visibilitychange", onVisibilityChange);
      window.addEventListener(
        "beforeunload",
        function () {
          stopTicker();
          document.removeEventListener("visibilitychange", onVisibilityChange);
        },
        { once: true }
      );
      startTicker();
    }

    return {
      pageName: pageName,
      pageRoot: pageRoot,
    };
  }

  function initCatalogQualityPage(options) {
    var cfg = options || {};
    var pageName = "catalog_quality";
    var pageRoot = document.querySelector(cfg.pageRootSelector || ".cat-wrap");
    if (!pageRoot) return null;
    if (pageRoot.dataset.admCatalogQualityInit === "1") return null;
    pageRoot.dataset.admCatalogQualityInit = "1";

    var genericState = initGenericListPage({
      pageName: pageName,
      historyMode: "replace",
    });

    var backToTopBtn = pageRoot.querySelector("#backToTop");
    if (
      backToTopBtn &&
      window.AdminHelpers &&
      typeof window.AdminHelpers.initBackToTop === "function" &&
      backToTopBtn.dataset.admBackTopBound !== "1"
    ) {
      backToTopBtn.dataset.admBackTopBound = "1";
      window.AdminHelpers.initBackToTop({
        button: backToTopBtn,
        threshold: Number(backToTopBtn.getAttribute("data-threshold") || 300),
        behavior: "smooth",
      });
    }

    if (
      window.AdminHelpers &&
      typeof window.AdminHelpers.initScrollMemory === "function" &&
      pageRoot.dataset.admScrollMemoryBound !== "1"
    ) {
      pageRoot.dataset.admScrollMemoryBound = "1";
      var scrollMemory = window.AdminHelpers.initScrollMemory({
        key: "catalog_page_position",
        useLocalScroll: !window.__adminGlobalScrollLock,
        maxAgeMs: 5 * 60 * 1000,
        saveDebounceMs: 200,
        behavior: "smooth",
        restoreDelayMs: 100,
        getContext: function () {
          var urlParams = new URLSearchParams(window.location.search);
          return {
            page: urlParams.get("page") || "1",
            no_image: urlParams.get("no_image"),
            no_desc: urlParams.get("no_desc"),
            out_of_stock: urlParams.get("out_of_stock"),
            inactive: urlParams.get("inactive"),
          };
        },
        saveOnSelectors: [".page-link", ".filter-form .btn-primary", ".btn-outline-secondary"],
      });
      if (scrollMemory) {
        scrollMemory.bind();
        scrollMemory.restore();
      }
    }

    if (pageRoot.dataset.admRowHoverBound !== "1") {
      pageRoot.dataset.admRowHoverBound = "1";
      pageRoot.addEventListener("mouseover", function (event) {
        var row = event.target && event.target.closest ? event.target.closest(".cat-table tbody tr") : null;
        if (!row || !pageRoot.contains(row)) return;
        row.style.backgroundColor = "#F9FAFB";
      });
      pageRoot.addEventListener("mouseout", function (event) {
        var row = event.target && event.target.closest ? event.target.closest(".cat-table tbody tr") : null;
        if (!row || !pageRoot.contains(row)) return;
        var next = event.relatedTarget;
        if (next && row.contains(next)) return;
        row.style.backgroundColor = "";
      });
    }

    if (pageRoot.dataset.admToggleSyncBound !== "1") {
      pageRoot.dataset.admToggleSyncBound = "1";
      document.addEventListener("bm:ajax-form-success", function (event) {
        var detail = (event && event.detail) || {};
        var form = detail.form;
        if (!form || !form.matches || !form.matches(".toggle-form")) return;
        if (!pageRoot.contains(form)) return;

        var row = form.closest("tr");
        if (!row) return;
        row.classList.add("row-updated");

        var statusCell = row.querySelector('td[data-label="Actif"] .badge');
        if (statusCell) {
          var currentlyActive = statusCell.classList.contains("bg-success");
          if (currentlyActive) {
            statusCell.className = "badge bg-secondary";
            statusCell.innerHTML = '<i class="bi bi-x-circle"></i> Non';
          } else {
            statusCell.className = "badge bg-success";
            statusCell.innerHTML = '<i class="bi bi-check-circle"></i> Oui';
          }
        }

        window.setTimeout(function () {
          row.classList.remove("row-updated");
        }, 1000);
      });
    }

    return genericState || { pageName: pageName, pageRoot: pageRoot };
  }

  function initReconciliationPage(options) {
    var cfg = options || {};
    var pageName = "reconciliation";
    var pageRoot = document.querySelector(cfg.pageRootSelector || ".subs-wrap");
    if (!pageRoot) return null;
    if (pageRoot.dataset.admReconciliationInit === "1") return null;
    pageRoot.dataset.admReconciliationInit = "1";

    var genericState = initGenericListPage({
      pageName: pageName,
      historyMode: "replace",
    });

    var backToTopBtn = pageRoot.querySelector("#backToTop");
    if (
      backToTopBtn &&
      window.AdminHelpers &&
      typeof window.AdminHelpers.initBackToTop === "function" &&
      backToTopBtn.dataset.admBackTopBound !== "1"
    ) {
      backToTopBtn.dataset.admBackTopBound = "1";
      window.AdminHelpers.initBackToTop({
        button: backToTopBtn,
        threshold: Number(backToTopBtn.getAttribute("data-threshold") || 300),
        behavior: "smooth",
      });
    }

    if (
      window.AdminHelpers &&
      typeof window.AdminHelpers.initScrollMemory === "function" &&
      pageRoot.dataset.admScrollMemoryBound !== "1"
    ) {
      pageRoot.dataset.admScrollMemoryBound = "1";
      var scrollMemory = window.AdminHelpers.initScrollMemory({
        key: "subscriptions_page_position",
        useLocalScroll: !window.__adminGlobalScrollLock,
        maxAgeMs: 5 * 60 * 1000,
        saveDebounceMs: 200,
        behavior: "smooth",
        restoreDelayMs: 100,
        getContext: function () {
          var urlParams = new URLSearchParams(window.location.search);
          return {
            page: urlParams.get("page") || "1",
            status: urlParams.get("status") || "",
          };
        },
        saveOnSelectors: [".page-link", ".filter-links a", ".adm-filters a"],
      });
      if (scrollMemory) {
        scrollMemory.bind();
        scrollMemory.restore();
      }
    }

    if (pageRoot.dataset.admRowHoverBound !== "1") {
      pageRoot.dataset.admRowHoverBound = "1";
      pageRoot.addEventListener("mouseover", function (event) {
        var row = event.target && event.target.closest ? event.target.closest(".subs-table tbody tr") : null;
        if (!row || !pageRoot.contains(row)) return;
        row.style.backgroundColor = "#F9FAFB";
      });
      pageRoot.addEventListener("mouseout", function (event) {
        var row = event.target && event.target.closest ? event.target.closest(".subs-table tbody tr") : null;
        if (!row || !pageRoot.contains(row)) return;
        var next = event.relatedTarget;
        if (next && row.contains(next)) return;
        row.style.backgroundColor = "";
      });
    }

    if (pageRoot.dataset.admFilterClickBound !== "1") {
      pageRoot.dataset.admFilterClickBound = "1";
      pageRoot.addEventListener("click", function (event) {
        var btn = event.target && event.target.closest ? event.target.closest(".filter-links .btn") : null;
        if (!btn || !pageRoot.contains(btn)) return;
        if (btn.classList.contains("active")) return;
        btn.style.transform = "scale(0.95)";
        window.setTimeout(function () {
          btn.style.transform = "";
        }, 150);
      });
    }

    return genericState || { pageName: pageName, pageRoot: pageRoot };
  }

  function autoInit() {
    initAdminBaseRuntime();

    var pageName = getBodyPageName();
    if (document.querySelector('[data-orders-page="true"]')) {
      initOrdersPage();
      return;
    }

    if (pageName === "deliveries") {
      initDeliveriesPage({ pageRootSelector: '[data-deliveries-page="true"]' });
      return;
    }

    if (pageName === "fraud") {
      initFraudPage({ pageRootSelector: "#fraudContent" });
      return;
    }

    if (pageName === "catalog_quality") {
      initCatalogQualityPage({ pageRootSelector: ".cat-wrap" });
      return;
    }

    if (pageName === "reconciliation") {
      initReconciliationPage({ pageRootSelector: ".subs-wrap" });
      return;
    }

    if (pageName === "shops" || pageName === "users" || pageName === "locations" || pageName === "categories") {
      initGenericListPage({ pageName: pageName });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", autoInit, { once: true });
  } else {
    autoInit();
  }

  document.addEventListener("ajax:page-replaced", function () {
    autoInit();
  });

  window.AdminTable = {
    initAdminBaseRuntime: initAdminBaseRuntime,
    initOrdersPage: initOrdersPage,
    initGenericListPage: initGenericListPage,
    initDeliveriesPage: initDeliveriesPage,
    initFraudPage: initFraudPage,
    initCatalogQualityPage: initCatalogQualityPage,
    initReconciliationPage: initReconciliationPage,
    autoInit: autoInit,
  };
})();

