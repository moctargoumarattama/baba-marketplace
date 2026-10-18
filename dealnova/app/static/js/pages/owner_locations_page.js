(function () {
  "use strict";
  if (window.__BM_OWNER_LOCATIONS_PAGE__) return;
  window.__BM_OWNER_LOCATIONS_PAGE__ = true;
  document.body.classList.add("owner-enhanced");

  const rootSelector = ".owner-shell, .owner-archives-shell";
  let readController = null;
  let readSeq = 0;
  let searchTimer = 0;
  let writing = false;
  let queuedRead = null;
  let resumeAfterModal = null;
  let retryUrl = window.location.href;

  function root() { return document.querySelector(rootSelector); }
  function modalOpen() { return !!document.querySelector("#vendorProductDialog[open]"); }
  function cleanUrl(value) {
    const url = new URL(value, window.location.href);
    url.searchParams.delete("new");
    url.searchParams.delete("edit_location");
    return url;
  }
  function localListUrl(value) {
    try {
      const url = cleanUrl(value);
      return url.origin === location.origin && ["/owner/locations", "/owner/locations/archives"].includes(url.pathname) ? url : null;
    } catch (_error) { return null; }
  }
  function feedback(message, error) {
    const area = root();
    if (!area) return;
    let node = area.querySelector("[data-owner-status]");
    if (!node) {
      node = document.createElement("p");
      node.dataset.ownerStatus = "1";
      node.className = "owner-feedback";
      area.prepend(node);
    }
    node.replaceChildren(document.createTextNode(message || ""));
    node.setAttribute("role", error ? "alert" : "status");
    node.classList.toggle("is-error", !!error);
    if (error) {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.dataset.ownerRetry = "1";
      retry.className = "owner-retry";
      retry.textContent = "Actualiser la liste";
      node.append(" ", retry);
    }
  }
  function loading(active) {
    const area = root();
    if (!area) return;
    area.classList.toggle("is-loading", active);
    area.setAttribute("aria-busy", String(active));
  }
  function syncPhotos(scope) {
    (scope || document).querySelectorAll("img[data-owner-photo]").forEach((image) => {
      if (image.dataset.fallbackBound) return;
      image.dataset.fallbackBound = "1";
      function fallback() {
        if (image.dataset.fallbackSrc && image.dataset.originalTried !== "1") {
          image.dataset.originalTried = "1";
          image.src = image.dataset.fallbackSrc;
          return;
        }
        image.hidden = true;
        image.style.display = "none";
        image.parentElement.classList.add("has-image-error");
        image.removeEventListener("error", fallback);
      }
      image.addEventListener("error", fallback);
      if (image.complete && !image.naturalWidth) fallback();
    });
  }
  function fieldValues(form) {
    return Array.from(new FormData(form).entries());
  }
  function formUrl(form) {
    const url = new URL(form.getAttribute("action") || location.pathname, location.origin);
    url.search = "";
    fieldValues(form).forEach(([key, value]) => { if (String(value).trim()) url.searchParams.set(key, value); });
    return url;
  }
  function injectHtml(html, nextUrl, historyMode) {
    const doc = new DOMParser().parseFromString(html, "text/html");
    const incoming = doc.querySelector(rootSelector);
    const current = root();
    if (!incoming || !current) throw new Error("invalid_response");
    // Keep the search input and its keyboard mounted while refreshing results.
    const results = current.querySelector("[data-owner-results]");
    const incomingResults = incoming.querySelector("[data-owner-results]");
    if (results && incomingResults && current.classList.contains("owner-refresh")) {
      results.replaceChildren(...Array.from(incomingResults.childNodes));
      const stats = current.querySelector("[data-owner-stats], .owner-refresh-stats, .owner-stats");
      const nextStats = incoming.querySelector("[data-owner-stats], .owner-refresh-stats, .owner-stats");
      if (stats && nextStats) stats.replaceChildren(...Array.from(nextStats.childNodes));
      const count = current.querySelector("[data-owner-list-count]");
      const nextCount = incoming.querySelector("[data-owner-list-count]");
      if (count && nextCount) count.textContent = nextCount.textContent;
      const pills = current.querySelector("[data-owner-status-filters]");
      const nextPills = incoming.querySelector("[data-owner-status-filters]");
      if (pills && nextPills) pills.replaceChildren(...Array.from(nextPills.childNodes));
      const currentForm = current.querySelector(".owner-filter-form");
      const nextForm = incoming.querySelector(".owner-filter-form");
      if (currentForm && nextForm) {
        ["q", "status", "shop"].forEach((name) => {
          const field = currentForm.elements.namedItem(name);
          const nextField = nextForm.elements.namedItem(name);
          if (field && nextField && field !== document.activeElement) field.value = nextField.value;
        });
      }
    } else current.replaceWith(incoming);
    if (doc.title) document.title = doc.title;
    if (historyMode) {
      const state = Object.assign({}, history.state, { ownerLocations: true });
      delete state.bmVendorProductCreate;
      history[historyMode === "push" ? "pushState" : "replaceState"](state, "", nextUrl);
    }
    const flash = Array.from(doc.querySelectorAll("#pageContent > .alert")).map((node) => node.textContent.replace(/\s+/g, " ").trim()).filter(Boolean);
    feedback(flash.join(" "), false);
    syncPhotos(root());
  }

  async function readList(value, historyMode) {
    const url = localListUrl(value);
    if (!url || !root()) return;
    if (writing) { queuedRead = [url.href, historyMode]; return; }
    if (readController) readController.abort();
    const controller = new AbortController();
    readController = controller;
    const seq = ++readSeq;
    const timeout = setTimeout(() => controller.abort(), 20000);
    retryUrl = url.href;
    loading(true);
    try {
      const response = await fetch(url, { credentials: "same-origin", cache: "no-store", signal: controller.signal,
        headers: { "X-Requested-With": "XMLHttpRequest", Accept: "text/html" } });
      if (!response.ok) throw new Error("http_error");
      const html = await response.text();
      if (seq !== readSeq) return;
      if (modalOpen()) {
        resumeAfterModal = [url.href, historyMode];
        return;
      }
      const next = localListUrl(response.url);
      if (!next) throw new Error("session_expired");
      injectHtml(html, next.href, historyMode);
    } catch (_error) {
      if (seq === readSeq) feedback("Impossible d’actualiser les annonces. Vérifiez votre connexion puis réessayez.", true);
    } finally {
      clearTimeout(timeout);
      if (seq === readSeq) { loading(false); readController = null; }
    }
  }

  async function writeAction(form, submitter) {
    if (writing || form.dataset.ownerBusy === "1") return;
    writing = true;
    form.dataset.ownerBusy = "1";
    clearTimeout(searchTimer);
    ++readSeq;
    if (readController) readController.abort();
    loading(false);
    const button = submitter || form.querySelector('[type="submit"]');
    const wasDisabled = button && button.disabled;
    const body = new FormData(form);
    if (submitter?.name) body.append(submitter.name, submitter.value || "");
    if (button) button.disabled = true;
    form.setAttribute("aria-busy", "true");
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 120000);
    try {
      const response = await fetch(form.action, { method: "POST", credentials: "same-origin", cache: "no-store",
        body, signal: controller.signal, headers: { "X-Requested-With": "XMLHttpRequest", Accept: "text/html" } });
      if (!response.ok) throw new Error("http_error");
      const html = await response.text();
      const next = localListUrl(response.url);
      if (!next) throw new Error("session_expired");
      injectHtml(html, next.href, "replace");
    } catch (_error) {
      // A mutation may already have reached the server. Retry only a GET, never the POST.
      feedback("L’action n’a pas pu être confirmée. Actualisez la liste pour vérifier son résultat avant de réessayer.", true);
    } finally {
      clearTimeout(timeout);
      writing = false;
      form.dataset.ownerBusy = "0";
      form.removeAttribute("aria-busy");
      if (button) button.disabled = !!wasDisabled;
      if (queuedRead) {
        const next = queuedRead;
        queuedRead = null;
        readList(next[0], next[1]);
      }
    }
  }

  document.addEventListener("click", (event) => {
    if (!root() || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
    const retry = event.target.closest("[data-owner-retry]");
    if (retry) { event.preventDefault(); readList(retryUrl, null); return; }
    const link = event.target.closest("a[href]");
    if (!link || link.target === "_blank" || link.hasAttribute("download") || link.hasAttribute("data-stop-nav")) return;
    const url = localListUrl(link.href);
    // Archives have their own assets; normal navigation loads their complete shell.
    if (!url || url.pathname !== location.pathname) return;
    event.preventDefault();
    clearTimeout(searchTimer);
    if (link.closest("[data-owner-status-filters]")) {
      const form = root().querySelector(".owner-filter-form");
      if (form) {
        const value = url.searchParams.get("status") || "";
        const field = form.elements.namedItem("status");
        if (field) field.value = value;
        const current = formUrl(form);
        url.search = current.search;
        url.searchParams.delete("page");
      }
    }
    readList(url.href, "push");
  });
  document.addEventListener("submit", (event) => {
    if (!root() || event.defaultPrevented) return;
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || form.id === "vendorCreateForm" || !root().contains(form)) return;
    if (form.matches(".owner-filter-form, .archives-filter")) {
      event.preventDefault();
      clearTimeout(searchTimer);
      readList(formUrl(form).href, "push");
      return;
    }
    if (form.method.toLowerCase() !== "post") return;
    const action = new URL(form.action, location.origin);
    if (action.origin !== location.origin || !/^\/owner\/location\/\d+\/(close|delete)$/.test(action.pathname)) return;
    event.preventDefault();
    writeAction(form, event.submitter);
  });
  document.addEventListener("input", (event) => {
    const form = event.target.closest(".owner-filter-form");
    if (!form || event.target.name !== "q") return;
    clearTimeout(searchTimer);
    ++readSeq;
    if (readController) readController.abort();
    loading(false);
    searchTimer = setTimeout(() => {
      searchTimer = 0;
      readList(formUrl(form).href, "replace");
    }, 350);
  });
  document.addEventListener("change", (event) => {
    const form = event.target.closest(".owner-filter-form");
    if (!form || !["shop", "status"].includes(event.target.name)) return;
    clearTimeout(searchTimer);
    readList(formUrl(form).href, "push");
  });
  function resumeModalRead() {
    if (!resumeAfterModal || modalOpen() || history.state?.bmVendorProductCreate) return false;
    const next = resumeAfterModal;
    resumeAfterModal = null;
    readList(next[0], next[1]);
    return true;
  }
  document.addEventListener("vendor:form-opened", () => {
    const form = root()?.querySelector(".owner-filter-form");
    if (!form) return;
    if (readController || searchTimer) resumeAfterModal = [formUrl(form).href, "replace"];
    clearTimeout(searchTimer);
    searchTimer = 0;
    ++readSeq;
    if (readController) readController.abort();
    readController = null;
    loading(false);
  });
  document.addEventListener("vendor:form-closed", resumeModalRead);
  function refreshAfterSave(event) {
    if (!root()) return;
    const form = root().querySelector(".owner-filter-form");
    const url = form ? formUrl(form) : cleanUrl(location.href);
    if (event.type === "vendor:location-created") url.searchParams.delete("page");
    else if (new URL(location.href).searchParams.has("page")) url.searchParams.set("page", new URL(location.href).searchParams.get("page"));
    // The dialog first restores its base history entry, then the list can update it.
    resumeAfterModal = [url.href, "replace"];
  }
  document.addEventListener("vendor:location-created", refreshAfterSave);
  document.addEventListener("vendor:location-updated", refreshAfterSave);
  document.addEventListener("toggle", (event) => {
    const menu = event.target;
    if (!menu.matches?.("details.owner-rental-more") || !menu.open) return;
    document.querySelectorAll("details.owner-rental-more[open]").forEach((other) => { if (other !== menu) other.open = false; });
  }, true);
  document.addEventListener("click", (event) => {
    document.querySelectorAll("details.owner-rental-more[open]").forEach((menu) => { if (!menu.contains(event.target)) menu.open = false; });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") document.querySelectorAll("details.owner-rental-more[open]").forEach((menu) => { menu.open = false; menu.querySelector("summary").focus(); });
  });
  window.addEventListener("popstate", () => {
    if (!root() || modalOpen() || history.state?.bmVendorProductCreate) return;
    clearTimeout(searchTimer);
    if (resumeModalRead()) return;
    readList(location.href, null);
  });
  syncPhotos();
})();
