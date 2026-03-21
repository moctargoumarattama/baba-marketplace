(function () {
  if (window.__BM_OWNER_LOCATIONS_PAGE__) return;
  window.__BM_OWNER_LOCATIONS_PAGE__ = true;

  var PAGE_CONTENT_SELECTOR = "#pageContent";
  var OWNER_ROOT_SELECTORS = [".owner-shell", ".owner-archives-shell"];
  var isLoading = false;

  function getPageContent() {
    return document.querySelector(PAGE_CONTENT_SELECTOR);
  }

  function getOwnerRoot(scope) {
    var source = scope || document;
    for (var i = 0; i < OWNER_ROOT_SELECTORS.length; i += 1) {
      var found = source.querySelector(OWNER_ROOT_SELECTORS[i]);
      if (found) return found;
    }
    return null;
  }

  function isOwnerPage() {
    return !!getOwnerRoot();
  }

  function shouldHandleLink(link) {
    if (!link || link.target === "_blank" || link.hasAttribute("download")) return false;
    var href = link.getAttribute("href") || "";
    if (!href || href.charAt(0) === "#") return false;
    return href.indexOf("/owner/locations") !== -1 || href.indexOf("/owner/location/") !== -1;
  }

  function shouldHandleForm(form) {
    if (!form) return false;
    var action = form.getAttribute("action") || "";
    if (form.method && form.method.toLowerCase() === "get") {
      return form.classList.contains("owner-filter-form") || form.classList.contains("archives-filter");
    }
    return action.indexOf("/owner/location/") !== -1;
  }

  function buildFormUrl(form) {
    var method = (form.method || "get").toLowerCase();
    if (method !== "get") {
      return form.getAttribute("action") || window.location.href;
    }
    var action = form.getAttribute("action") || window.location.pathname;
    var url = new URL(action, window.location.origin);
    var formData = new FormData(form);
    formData.forEach(function (value, key) {
      if (value == null || value === "") return;
      url.searchParams.set(key, value);
    });
    return url.pathname + url.search;
  }

  function setLoading(active) {
    var root = getOwnerRoot();
    if (!root) return;
    root.classList.toggle("is-loading", !!active);
  }

  function injectHtml(html, nextUrl, historyMode) {
    var parser = new DOMParser();
    var doc = parser.parseFromString(html, "text/html");
    var incoming = doc.querySelector(PAGE_CONTENT_SELECTOR);
    var current = getPageContent();
    if (!incoming || !current) {
      window.location.href = nextUrl;
      return;
    }
    current.innerHTML = incoming.innerHTML;
    if (doc.title) {
      document.title = doc.title;
    }
    if (historyMode === "push") {
      window.history.pushState({ ownerLocations: true }, "", nextUrl);
    } else if (historyMode === "replace") {
      window.history.replaceState({ ownerLocations: true }, "", nextUrl);
    }
  }

  async function fetchAndSwap(url, options, historyMode) {
    if (isLoading) return;
    isLoading = true;
    setLoading(true);
    try {
      var response = await fetch(url, Object.assign({
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          "Accept": "text/html, */*;q=0.1"
        },
        credentials: "same-origin"
      }, options || {}));
      if (!response.ok) {
        window.location.href = url;
        return;
      }
      var html = await response.text();
      var nextUrl = response.url ? new URL(response.url).pathname + new URL(response.url).search : url;
      injectHtml(html, nextUrl, historyMode);
    } catch (error) {
      window.location.href = url;
    } finally {
      isLoading = false;
      setLoading(false);
    }
  }

  document.addEventListener("click", function (event) {
    if (!isOwnerPage()) return;
    var link = event.target.closest("a");
    if (!shouldHandleLink(link)) return;
    event.preventDefault();
    fetchAndSwap(link.href, { method: "GET", cache: "no-store" }, "push");
  });

  document.addEventListener("submit", function (event) {
    if (!isOwnerPage()) return;
    var form = event.target;
    if (!shouldHandleForm(form)) return;

    var confirmMessage = form.getAttribute("data-confirm-submit") || form.getAttribute("data-confirm");
    if (confirmMessage && !window.confirm(confirmMessage)) {
      event.preventDefault();
      return;
    }

    event.preventDefault();
    var method = (form.method || "get").toLowerCase();
    if (method === "get") {
      fetchAndSwap(buildFormUrl(form), { method: "GET", cache: "no-store" }, "push");
      return;
    }

    var submitter = event.submitter;
    if (submitter && submitter.name) {
      var submitData = new FormData(form);
      submitData.append(submitter.name, submitter.value || "");
      fetchAndSwap(form.action, { method: "POST", body: submitData, cache: "no-store" }, "replace");
      return;
    }
    fetchAndSwap(form.action, { method: "POST", body: new FormData(form), cache: "no-store" }, "replace");
  });

  window.addEventListener("popstate", function () {
    if (!isOwnerPage()) return;
    fetchAndSwap(window.location.href, { method: "GET", cache: "no-store" }, null);
  });
})();
