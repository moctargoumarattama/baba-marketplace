(function () {
  "use strict";
  const form = document.getElementById("archiveFilterForm");
  const region = document.getElementById("archiveResultsRegion");
  const summary = document.getElementById("archiveSummary");
  const feedback = document.getElementById("archiveFeedback");
  const search = document.getElementById("archiveSearchInput");
  const dialog = document.getElementById("archiveDetailDialog");
  const dialogBody = document.getElementById("archiveDetailBody");
  if (!form || !region || !summary || !search || !window.fetch || !window.AbortController) return;
  document.body.classList.add("archives-enhanced");
  let controller = null;
  let sequence = 0;
  let debounce = null;
  let composing = false;
  let pendingSnapshot = null;
  let detailOrigin = null;
  let retryURL = null;

  function hasOpenDialog() { return !!document.querySelector("dialog[open]"); }
  function setBusy(value) { region.setAttribute("aria-busy", String(value)); }
  function hideFeedback() { feedback.hidden = true; feedback.replaceChildren(); }
  function showFailure(url) {
    retryURL = url;
    feedback.replaceChildren(document.createTextNode("Impossible de mettre la liste à jour. "));
    const retry = document.createElement("button");
    retry.type = "button";
    retry.dataset.archiveRetry = "";
    retry.textContent = "Réessayer";
    feedback.append(retry);
    feedback.hidden = false;
  }
  function enhanceDetails() {
    if (!dialog || typeof dialog.showModal !== "function" || !window.BMVendorWorkspace) return;
    region.querySelectorAll("[data-archive-details]").forEach((trigger) => {
      trigger.setAttribute("aria-haspopup", "dialog");
      trigger.setAttribute("aria-controls", "archiveDetailDialog");
    });
  }
  function formURL() {
    const url = new URL(form.action, location.href);
    new FormData(form).forEach((value, key) => {
      const text = String(value).trim();
      if (text) url.searchParams.set(key, text);
    });
    return url;
  }
  function syncForm(url) {
    ["q", "status", "shop"].forEach((name) => {
      const field = form.elements.namedItem(name);
      if (!field) return;
      const value = url.searchParams.get(name) || "";
      field.value = value;
      if (field instanceof HTMLSelectElement && field.selectedIndex < 0) field.value = "";
    });
  }
  function applySnapshot(snapshot) {
    if (snapshot.sequence !== sequence) return;
    if (hasOpenDialog()) { pendingSnapshot = snapshot; return; }
    pendingSnapshot = null;
    region.replaceChildren(...Array.from(snapshot.results.childNodes));
    summary.replaceChildren(...Array.from(snapshot.summary.childNodes));
    const meta = region.querySelector("[data-archive-page]");
    const page = Number(meta?.dataset.archivePage || 1);
    if (page > 1) snapshot.url.searchParams.set("page", String(page));
    else snapshot.url.searchParams.delete("page");
    if (snapshot.push && snapshot.url.href !== location.href) history.pushState({}, "", snapshot.url);
    else if (!snapshot.push && snapshot.url.href !== location.href) history.replaceState(history.state, "", snapshot.url);
    enhanceDetails();
    setBusy(false);
    hideFeedback();
    if (snapshot.scroll) region.scrollIntoView({ block: "start", behavior: "instant" });
  }
  async function load(url, options = {}) {
    clearTimeout(debounce);
    const requested = new URL(url, location.href);
    if (requested.origin !== location.origin || requested.pathname !== new URL(form.action).pathname) return;
    controller?.abort();
    controller = new AbortController();
    const requestController = controller;
    const requestSequence = ++sequence;
    let timedOut = false;
    const timeout = setTimeout(() => { timedOut = true; requestController.abort(); }, 20000);
    pendingSnapshot = null;
    setBusy(true);
    hideFeedback();
    try {
      const response = await fetch(requested, {
        method: "GET", credentials: "same-origin", signal: requestController.signal,
        headers: { "X-Requested-With": "XMLHttpRequest", "Accept": "text/html" },
        cache: "no-store"
      });
      if (!response.ok) throw new Error("archive_request_failed");
      const markup = await response.text();
      if (requestSequence !== sequence) return;
      const parsed = new DOMParser().parseFromString(markup, "text/html");
      const nextResults = parsed.getElementById("archiveResultsRegion");
      const nextSummary = parsed.getElementById("archiveSummary");
      if (!nextResults || !nextSummary) throw new Error("archive_response_invalid");
      applySnapshot({ results: nextResults, summary: nextSummary, url: requested,
        sequence: requestSequence, push: options.push !== false, scroll: !!options.scroll });
    } catch (error) {
      if (requestSequence !== sequence || (error.name === "AbortError" && !timedOut)) return;
      setBusy(false);
      showFailure(requested);
    } finally {
      clearTimeout(timeout);
    }
  }
  function searchLater() {
    clearTimeout(debounce);
    // A response for the previous input must not update the list during the
    // debounce or an IME composition for a newer query.
    controller?.abort();
    sequence += 1;
    pendingSnapshot = null;
    setBusy(false);
    hideFeedback();
    retryURL = null;
    if (!composing) debounce = setTimeout(() => load(formURL()), 300);
  }
  form.addEventListener("submit", (event) => { event.preventDefault(); load(formURL()); });
  form.addEventListener("change", (event) => {
    if (event.target instanceof HTMLSelectElement) load(formURL());
  });
  search.addEventListener("compositionstart", () => { composing = true; searchLater(); });
  search.addEventListener("compositionend", () => { composing = false; searchLater(); });
  search.addEventListener("input", searchLater);
  document.addEventListener("click", (event) => {
    if (!(event.target instanceof Element)) return;
    const retry = event.target.closest("[data-archive-retry]");
    if (retry && retryURL) { event.preventDefault(); load(retryURL); return; }
    const reset = event.target.closest("[data-archive-reset]");
    const pageLink = event.target.closest(".archive-pagination a");
    if (reset || pageLink) {
      if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      const target = reset || pageLink;
      const url = new URL(target.href, location.href);
      event.preventDefault();
      if (reset) syncForm(url);
      load(url, { scroll: !!pageLink });
      return;
    }
    const trigger = event.target.closest("[data-archive-details]");
    if (!trigger || !region.contains(trigger) || !dialog || typeof dialog.showModal !== "function" || !window.BMVendorWorkspace || hasOpenDialog()) return;
    const details = trigger.closest("details");
    const content = details?.querySelector("[data-archive-detail-content]");
    if (!content) return;
    event.preventDefault();
    details.open = false;
    detailOrigin = details;
    dialogBody.replaceChildren(content);
    window.BMVendorWorkspace.openDialog("archiveDetailDialog", trigger);
  });
  dialog?.addEventListener("vendor:workspace-dialog-closed", () => {
    const content = dialogBody.querySelector("[data-archive-detail-content]");
    if (content && detailOrigin?.isConnected) detailOrigin.append(content);
    detailOrigin = null;
    dialogBody.replaceChildren();
  });
  document.addEventListener("vendor:dashboard-dialog-closed", () => {
    if (pendingSnapshot && !hasOpenDialog()) applySnapshot(pendingSnapshot);
  });
  window.addEventListener("popstate", () => {
    clearTimeout(debounce);
    if (hasOpenDialog()) window.BMVendorWorkspace?.requestCloseDialog();
    const url = new URL(location.href);
    syncForm(url);
    load(url, { push: false });
  });
  enhanceDetails();
})();
