(function () {
  "use strict";
  const form = document.getElementById("catalogFilterForm");
  const results = document.getElementById("catalogResultsRegion");
  if (!form || !results || form.dataset.bound === "1") return;
  form.dataset.bound = "1";
  document.body.classList.add("catalog-enhanced");
  const search = document.getElementById("catalogSearchInput");
  const category = document.getElementById("catalogCategorySelect");
  const clear = document.getElementById("catalogSearchClear");
  const feedback = document.querySelector("[data-catalog-feedback]");
  const deleteDialog = document.getElementById("catalogDeleteDialog");
  const deleteConfirm = deleteDialog.querySelector("[data-catalog-delete-confirm]");
  const deleteError = deleteDialog.querySelector("[data-catalog-delete-error]");
  let timer = 0;
  let controller = null;
  let sequence = 0;
  let writing = false;
  let pendingRead = null;
  let retryRead = null;
  let pendingDelete = null;
  let verifyDelete = false;

  function cleanUrl(value) {
    const url = new URL(value, location.href);
    ["new", "edit_product", "edit_location"].forEach((key) => url.searchParams.delete(key));
    url.hash = "";
    return url;
  }
  function localUrl(value) {
    try {
      const url = cleanUrl(value);
      return url.origin === location.origin && url.pathname === new URL(form.action).pathname ? url : null;
    } catch (_error) { return null; }
  }
  function formUrl(page = 1) {
    const url = new URL(form.action, location.href);
    url.search = "";
    new FormData(form).forEach((value, key) => {
      value = String(value).trim();
      if (value && value !== "all" && !(key === "sort" && value === "recent") && !(key === "per_page" && value === "24")) url.searchParams.set(key, value);
    });
    if (Number(page) > 1) url.searchParams.set("page", String(page));
    return url;
  }
  function currentPage() { return Number(results.querySelector("[data-catalog-meta]")?.dataset.page || 1); }
  function overlayOpen() { return !!document.querySelector("#vendorProductDialog[open], .vd-choice-dialog[open]") || !!history.state?.bmVendorProductCreate; }
  function loading(active) { results.classList.toggle("is-loading", active); results.setAttribute("aria-busy", String(active)); }
  function message(text, error = false, retry = false) {
    feedback.replaceChildren(document.createTextNode(text || ""));
    feedback.hidden = !text;
    feedback.classList.toggle("is-error", error);
    feedback.setAttribute("role", error ? "alert" : "status");
    if (retry) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "catalog-retry";
      button.dataset.catalogRetry = "1";
      button.textContent = "Réessayer";
      feedback.append(" ", button);
    }
  }
  function cancelRead() {
    clearTimeout(timer);
    timer = 0;
    ++sequence;
    controller?.abort();
    controller = null;
    loading(false);
  }
  function syncImages(scope = results) {
    scope.querySelectorAll("img[data-catalog-image]").forEach((image) => {
      if (image.dataset.bound) return;
      image.dataset.bound = "1";
      function fallback() {
        if (image.dataset.fallbackSrc && !image.dataset.originalTried) {
          image.dataset.originalTried = "1";
          image.src = image.dataset.fallbackSrc;
        } else {
          image.hidden = true;
          image.closest(".catalog-media")?.classList.add("has-image-error");
          image.removeEventListener("error", fallback);
        }
      }
      image.addEventListener("error", fallback);
      if (image.complete && !image.naturalWidth) fallback();
    });
  }
  function syncSummary(data) {
    if (data.summary) document.querySelectorAll("[data-catalog-summary]").forEach((node) => {
      const value = data.summary[node.dataset.catalogSummary];
      if (Number.isFinite(Number(value))) node.textContent = String(Number(value));
      if (["physical", "service"].includes(node.dataset.catalogSummary) && node.nextSibling?.nodeType === Node.TEXT_NODE) {
        const label = node.dataset.catalogSummary === "physical" ? "produit" : "service";
        node.nextSibling.textContent = " " + label + (Number(value) === 1 ? "" : "s");
      }
    });
    if (Array.isArray(data.categories)) {
      const selected = data.selected_category_id == null ? "" : String(data.selected_category_id);
      const options = [new Option("Toutes les catégories", "")];
      data.categories.forEach((row) => options.push(new Option(String(row.name) + " (" + Number(row.count) + ")", String(row.id))));
      category.replaceChildren(...options);
      category.value = selected;
    }
    clear.hidden = !search.value;
  }
  async function readCatalogue(value, historyMode = "replace") {
    const url = localUrl(value);
    if (!url) return;
    if (writing || overlayOpen()) { pendingRead = { url: url.href, mode: historyMode }; return; }
    if (controller) controller.abort();
    const active = new AbortController();
    controller = active;
    const seq = ++sequence;
    const timeout = setTimeout(() => active.abort(), 20000);
    retryRead = { url: url.href, mode: historyMode };
    loading(true);
    message("");
    try {
      const response = await fetch(url, { signal: active.signal, credentials: "same-origin", cache: "no-store",
        headers: { "X-Requested-With": "fetch", "X-Catalog-Partial": "1", Accept: "application/json" } });
      const data = response.headers.get("content-type")?.includes("application/json") ? await response.json() : null;
      if (seq !== sequence) return;
      if (!response.ok || !data?.success || typeof data.html !== "string") throw new Error("invalid_response");
      if (overlayOpen()) { pendingRead = { url: url.href, mode: historyMode }; return; }
      const doc = new DOMParser().parseFromString(data.html, "text/html");
      if (!doc.querySelector("[data-catalog-meta]")) throw new Error("invalid_fragment");
      results.replaceChildren(...Array.from(doc.body.childNodes));
      syncSummary(data);
      syncImages();
      if (Number(data.page) > 1) url.searchParams.set("page", String(data.page));
      else url.searchParams.delete("page");
      if (data.selected_category_id == null) url.searchParams.delete("category_id");
      if (historyMode) {
        const state = Object.assign({}, history.state, { vendorCatalog: true });
        delete state.bmVendorProductCreate;
        history[historyMode === "push" ? "pushState" : "replaceState"](state, "", url);
      } else if (url.href !== cleanUrl(location.href).href) history.replaceState(history.state, "", url);
      message("");
      const liveCount = document.getElementById("catalogVisibleCount");
      if (liveCount) liveCount.parentElement.setAttribute("aria-live", "polite");
      retryRead = null;
    } catch (_error) {
      if (seq === sequence) message("Impossible d’actualiser le catalogue. Vos résultats sont conservés.", true, true);
    } finally {
      clearTimeout(timeout);
      if (seq === sequence) { controller = null; loading(false); }
    }
  }
  function resumeRead() {
    if (!pendingRead || writing || overlayOpen()) return;
    const next = pendingRead;
    pendingRead = null;
    readCatalogue(next.url, next.mode);
  }
  function pauseRead() {
    if (controller || timer) pendingRead = { url: formUrl(timer ? 1 : currentPage()).href, mode: "replace" };
    cancelRead();
  }
  function resetFilters(event) {
    event.preventDefault();
    cancelRead();
    search.value = "";
    category.value = "";
    form.querySelectorAll('input[type="hidden"]').forEach((field) => { if (field.name !== "csrf_token") field.value = ""; });
    clear.hidden = true;
    readCatalogue(formUrl().href, "push");
    search.focus({ preventScroll: true });
  }
  search.addEventListener("input", (event) => {
    cancelRead();
    clear.hidden = !search.value;
    if (event.isComposing) return;
    timer = setTimeout(() => { timer = 0; readCatalogue(formUrl().href, "replace"); }, 300);
  });
  search.addEventListener("compositionend", () => {
    cancelRead();
    timer = setTimeout(() => { timer = 0; readCatalogue(formUrl().href, "replace"); }, 300);
  });
  clear.addEventListener("click", () => {
    cancelRead(); search.value = ""; clear.hidden = true;
    readCatalogue(formUrl().href, "replace"); search.focus({ preventScroll: true });
  });
  category.addEventListener("change", () => { cancelRead(); readCatalogue(formUrl().href, "push"); });
  form.addEventListener("submit", (event) => { event.preventDefault(); cancelRead(); readCatalogue(formUrl().href, "replace"); });

  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (target.closest("[data-catalog-reset]")) { resetFilters(event); return; }
    const pageLink = target.closest("[data-catalog-page-link]");
    if (pageLink && !pageLink.hasAttribute("aria-disabled") && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey && event.button === 0) {
      event.preventDefault(); cancelRead(); readCatalogue(pageLink.href, "push");
    }
    if (target.closest("[data-catalog-retry]") && retryRead) readCatalogue(retryRead.url, retryRead.mode);
    results.querySelectorAll("details[data-catalog-menu][open]").forEach((menu) => { if (!menu.contains(target)) menu.open = false; });
  });
  document.addEventListener("toggle", (event) => {
    const menu = event.target;
    if (!menu.matches?.("details[data-catalog-menu]") || !menu.open) return;
    results.querySelectorAll("details[data-catalog-menu][open]").forEach((other) => { if (other !== menu) other.open = false; });
  }, true);
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    results.querySelectorAll("details[data-catalog-menu][open]").forEach((menu) => { menu.open = false; menu.querySelector("summary").focus(); });
  });
  document.addEventListener("submit", (event) => {
    const candidate = event.target;
    if (!(candidate instanceof HTMLFormElement) || !candidate.matches("[data-catalog-delete]")) return;
    if (!window.BMVendorWorkspace || typeof deleteDialog.showModal !== "function") return;
    event.preventDefault();
    if (writing) return;
    pendingDelete = candidate;
    verifyDelete = false;
    deleteConfirm.textContent = "Retirer";
    deleteError.hidden = true;
    deleteDialog.querySelector("[data-catalog-delete-name]").textContent = candidate.closest("[data-catalog-card]")?.querySelector(".catalog-card-title")?.textContent.trim() || "";
    window.BMVendorWorkspace.openDialog("catalogDeleteDialog", event.submitter);
  });
  deleteConfirm.addEventListener("click", async () => {
    if (writing || !pendingDelete?.isConnected) return;
    if (verifyDelete) {
      pendingRead = { url: formUrl(currentPage()).href, mode: "replace" };
      window.BMVendorWorkspace.closeDialog();
      return;
    }
    const action = new URL(pendingDelete.action, location.href);
    if (action.origin !== location.origin || !/^\/vendor\/product\/\d+\/delete$/.test(action.pathname)) return;
    const body = new FormData(pendingDelete);
    writing = true;
    deleteDialog.dataset.busy = "1";
    deleteConfirm.disabled = true;
    deleteConfirm.textContent = "Enregistrement…";
    deleteDialog.querySelectorAll("[data-catalog-delete-cancel]").forEach((node) => { node.disabled = true; });
    deleteError.hidden = true;
    cancelRead();
    const active = new AbortController();
    const timeout = setTimeout(() => active.abort(), 30000);
    try {
      const response = await fetch(action, { method: "POST", body, signal: active.signal, credentials: "same-origin", cache: "no-store",
        headers: { "X-Requested-With": "XMLHttpRequest", Accept: "application/json" } });
      const data = response.headers.get("content-type")?.includes("application/json") ? await response.json() : null;
      if (!response.ok || !data?.success) throw new Error("save_failed");
      pendingRead = { url: formUrl(currentPage()).href, mode: "replace" };
      window.BMVendorWorkspace.closeDialog();
      window.VendorUI?.toast?.(data.message || "Offre retirée.", "success");
    } catch (_error) {
      verifyDelete = true;
      deleteError.textContent = "L’action n’a pas pu être confirmée. Vérifiez la liste avant de réessayer.";
      deleteError.hidden = false;
    } finally {
      clearTimeout(timeout);
      writing = false;
      deleteDialog.dataset.busy = "0";
      deleteConfirm.disabled = false;
      deleteConfirm.textContent = verifyDelete ? "Vérifier la liste" : "Retirer";
      deleteDialog.querySelectorAll("[data-catalog-delete-cancel]").forEach((node) => { node.disabled = false; });
      resumeRead();
    }
  });
  document.addEventListener("vendor:form-opened", pauseRead);
  document.addEventListener("vendor:dashboard-dialog-opened", pauseRead);
  document.addEventListener("vendor:form-closed", resumeRead);
  document.addEventListener("vendor:dashboard-dialog-closed", resumeRead);
  ["vendor:product-created", "vendor:product-updated"].forEach((name) => document.addEventListener(name, () => {
    pendingRead = { url: formUrl(currentPage()).href, mode: "replace" };
  }));
  window.addEventListener("popstate", () => {
    if (overlayOpen()) return;
    cancelRead();
    if (pendingRead) { resumeRead(); return; }
    const url = localUrl(location.href);
    if (!url) return;
    Array.from(form.elements).forEach((field) => { if (field.name) field.value = url.searchParams.get(field.name) || ""; });
    clear.hidden = !search.value;
    readCatalogue(url.href, null);
  });
  syncImages();
})();
