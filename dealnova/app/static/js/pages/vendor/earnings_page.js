(function () {
  "use strict";
  const form = document.getElementById("earningsFilterForm");
  const results = document.getElementById("earningsResultsRegion");
  const dialog = document.getElementById("earningsReceiptDialog");
  const receiptForm = document.getElementById("earningsReceiptForm");
  const workspace = window.BMVendorWorkspace;
  if (!form || !results || !dialog || !receiptForm || !workspace || form.dataset.bound ||
      typeof dialog.showModal !== "function" || typeof window.fetch !== "function" ||
      typeof window.AbortController !== "function" || typeof window.DOMParser !== "function") return;
  form.dataset.bound = "1";
  document.body.classList.add("earnings-enhanced");
  const search = document.getElementById("earningsSearchInput");
  const range = document.getElementById("earningsRange");
  const show = document.getElementById("earningsShow");
  const dates = form.querySelector("[data-earnings-dates]");
  const dateFrom = document.getElementById("earningsDateFrom");
  const dateTo = document.getElementById("earningsDateTo");
  const clear = form.querySelector("[data-earnings-clear]");
  const feedback = document.querySelector("[data-earnings-feedback]");
  const error = dialog.querySelector("[data-earnings-receipt-error]");
  const confirm = dialog.querySelector("[data-earnings-confirm]");
  const note = document.getElementById("earningsReceiptNote");
  const defaultRange = "month";
  const draftNotes = new Map();
  let controller = null;
  let sequence = 0;
  let timer = 0;
  let writing = false;
  let selected = null;
  let retryRead = null;
  let pendingRead = null;
  let uncertain = false;

  function localUrl(value) {
    try {
      const url = new URL(value, location.href);
      if (url.origin !== location.origin || url.pathname !== new URL(form.action).pathname) return null;
      url.hash = "";
      return url;
    } catch (_) { return null; }
  }
  function formUrl(page = 1) {
    const url = new URL(form.action, location.href);
    url.search = "";
    new FormData(form).forEach((value, key) => {
      value = String(value).trim();
      if (value && !(key === "show" && value === "all")) url.searchParams.set(key, value);
    });
    if (page > 1) url.searchParams.set("page", String(page));
    return url;
  }
  function overlayOpen() { return !!document.querySelector(".vd-choice-dialog[open]"); }
  function loading(value) { results.setAttribute("aria-busy", String(value)); }
  function message(text, failed = false, retry = false) {
    feedback.replaceChildren(document.createTextNode(text || ""));
    feedback.hidden = !text;
    feedback.classList.toggle("is-error", failed);
    feedback.setAttribute("role", failed ? "alert" : "status");
    if (retry) {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.earningsRetry = "1";
      button.textContent = "Réessayer";
      feedback.append(" ", button);
    }
  }
  function showError(text) { error.textContent = text; error.hidden = !text; }
  function stopRead() {
    clearTimeout(timer);
    timer = 0;
    ++sequence;
    controller?.abort();
    controller = null;
    loading(false);
  }
  function updateDates() {
    const custom = range.value === "custom";
    dates.hidden = !custom;
    dateFrom.disabled = dateTo.disabled = !custom;
    dateTo.min = dateFrom.value || "";
    dateFrom.max = dateTo.value || "";
    clear.hidden = !search.value;
  }
  function syncFilters(value) {
    const url = new URL(value, location.href);
    search.value = url.searchParams.get("q") || "";
    range.value = url.searchParams.get("range") || defaultRange;
    show.value = url.searchParams.get("show") || "all";
    if (url.searchParams.has("from")) dateFrom.value = url.searchParams.get("from");
    if (url.searchParams.has("to")) dateTo.value = url.searchParams.get("to");
    updateDates();
  }
  async function read(value, historyMode = "replace", options = {}) {
    const url = localUrl(value);
    if (!url) return false;
    if (writing || (overlayOpen() && !options.allowDialog)) {
      pendingRead = { url: url.href, mode: historyMode };
      return false;
    }
    controller?.abort();
    const active = new AbortController();
    const seq = ++sequence;
    controller = active;
    const timeout = setTimeout(() => active.abort(), 20000);
    retryRead = { url: url.href, mode: historyMode };
    loading(true);
    message("");
    try {
      const response = await fetch(url, { credentials: "same-origin", signal: active.signal, cache: "no-store", headers: { "X-Requested-With": "fetch", Accept: "text/html" } });
      const html = await response.text();
      if (seq !== sequence) return false;
      if (!response.ok || !response.headers.get("content-type")?.includes("text/html")) throw new Error("invalid_response");
      const doc = new DOMParser().parseFromString(html, "text/html");
      const incoming = doc.getElementById("earningsResultsRegion");
      const summary = doc.querySelector("[data-earnings-summary]");
      if (!incoming?.querySelector("[data-earnings-meta]") || !summary) throw new Error("invalid_document");
      if (overlayOpen() && !options.allowDialog) {
        pendingRead = { url: url.href, mode: historyMode };
        return false;
      }
      results.replaceChildren(...Array.from(incoming.childNodes));
      results.querySelectorAll("[data-earnings-receipt]").forEach((rowForm) => {
        const id = rowForm.querySelector(".pay-btn").dataset.order;
        if (draftNotes.has(id)) rowForm.elements.note.value = draftNotes.get(id);
      });
      document.querySelector("[data-earnings-summary]").replaceChildren(...Array.from(summary.childNodes));
      if (!dates.contains(document.activeElement)) {
        dateFrom.value = doc.getElementById("earningsDateFrom").value;
        dateTo.value = doc.getElementById("earningsDateTo").value;
        updateDates();
      }
      const page = Number(results.querySelector("[data-earnings-meta]").dataset.page || 1);
      if (page > 1) url.searchParams.set("page", String(page)); else url.searchParams.delete("page");
      if (historyMode) history[historyMode === "push" ? "pushState" : "replaceState"](Object.assign({}, history.state, { vendorEarnings: true }), "", url);
      else if (url.href !== location.href) history.replaceState(history.state, "", url);
      retryRead = null;
      return true;
    } catch (_) {
      if (seq === sequence) message("Impossible d’actualiser les encaissements. La liste affichée est conservée.", true, true);
      return false;
    } finally {
      clearTimeout(timeout);
      if (seq === sequence) { controller = null; loading(false); }
    }
  }
  function schedule(mode = "replace") {
    stopRead();
    updateDates();
    if (form.checkValidity()) timer = setTimeout(() => { timer = 0; read(formUrl(), mode); }, 300);
  }
  function resumeRead() {
    if (!pendingRead || writing || overlayOpen()) return;
    const next = pendingRead;
    pendingRead = null;
    read(next.url, next.mode);
  }
  search.addEventListener("input", (event) => {
    stopRead();
    clear.hidden = !search.value;
    if (!event.isComposing) schedule();
  });
  search.addEventListener("compositionend", () => schedule());
  clear.addEventListener("click", () => { search.value = ""; search.focus({ preventScroll: true }); schedule(); });
  form.addEventListener("change", () => { updateDates(); stopRead(); if (form.reportValidity()) read(formUrl(), "push"); });
  form.addEventListener("submit", (event) => { event.preventDefault(); stopRead(); if (form.reportValidity()) read(formUrl(), "push"); });
  feedback.addEventListener("click", (event) => {
    if (event.target.closest("[data-earnings-retry]") && retryRead) read(retryRead.url, retryRead.mode);
  });
  results.addEventListener("click", (event) => {
    const link = event.target.closest(".earnings-pagination a, [data-earnings-reset]");
    if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const url = localUrl(link.href);
    if (!url) return;
    event.preventDefault();
    stopRead();
    if (link.hasAttribute("data-earnings-reset")) syncFilters(url);
    read(url, "push");
  });
  results.addEventListener("submit", (event) => {
    const rowForm = event.target.closest("[data-earnings-receipt]");
    if (!rowForm) return;
    event.preventDefault();
    if (writing || overlayOpen()) return;
    if (controller || timer) pendingRead = { url: formUrl().href, mode: "replace" };
    stopRead();
    const trigger = rowForm.querySelector(".pay-btn");
    selected = { id: trigger.dataset.order, form: rowForm, trigger };
    receiptForm.action = rowForm.action;
    receiptForm.elements.csrf_token.value = rowForm.elements.csrf_token.value;
    note.value = draftNotes.get(selected.id) ?? rowForm.elements.note?.value ?? "";
    dialog.querySelector("[data-earnings-receipt-order]").textContent = "Commande #" + selected.id;
    dialog.querySelector("[data-earnings-receipt-amount]").textContent = trigger.dataset.amount;
    uncertain = false;
    confirm.textContent = "Encaissé";
    showError("");
    workspace.openDialog(dialog.id, trigger);
  });
  function setWriting(value) {
    writing = value;
    dialog.dataset.busy = value ? "1" : "0";
    receiptForm.setAttribute("aria-busy", String(value));
    dialog.querySelectorAll("button").forEach((button) => { button.disabled = value; });
    note.readOnly = value;
  }
  async function verifyReceipt() {
    const orderId = selected.id;
    dialog.dataset.busy = "1";
    dialog.querySelectorAll("button").forEach((button) => { button.disabled = true; });
    note.readOnly = true;
    const ok = await read(localUrl(location.href), "replace", { allowDialog: true });
    dialog.dataset.busy = "0";
    dialog.querySelectorAll("button").forEach((button) => { button.disabled = false; });
    note.readOnly = false;
    if (!dialog.open || selected?.id !== orderId) return;
    if (!ok) { showError("Impossible de vérifier pour le moment. Votre note est conservée."); return; }
    const row = results.querySelector('[data-order-id="' + orderId + '"]');
    if (row?.querySelector(".earnings-status-confirmed")) {
      workspace.closeDialog();
      message("Cet encaissement est enregistré.");
    } else {
      // A filtered row can disappear after confirmation; its absence is not proof.
      showError("La liste a été actualisée. Vérifiez l’état de cette commande avant une nouvelle confirmation.");
      workspace.closeDialog();
      message("La liste a été actualisée. Vérifiez l’état de la commande #" + orderId + ".");
    }
  }
  async function refreshCsrf(signal) {
    try {
      const response = await fetch(formUrl(), { credentials: "same-origin", cache: "no-store", signal, headers: { "X-Requested-With": "fetch", Accept: "text/html" } });
      const doc = new DOMParser().parseFromString(await response.text(), "text/html");
      const token = doc.querySelector('#earningsReceiptForm [name="csrf_token"]')?.value;
      if (!response.ok || !doc.getElementById("earningsResultsRegion") || !token) return false;
      document.querySelectorAll('[name="csrf_token"]').forEach((input) => { input.value = token; });
      document.querySelector('meta[name="csrf-token"]')?.setAttribute("content", token);
      return true;
    } catch (_) { return false; }
  }
  receiptForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (writing || !selected) return;
    if (uncertain) { await verifyReceipt(); return; }
    const data = new FormData(receiptForm);
    const url = receiptForm.action;
    setWriting(true);
    showError("");
    confirm.textContent = "Enregistrement…";
    const active = new AbortController();
    const timeout = setTimeout(() => active.abort(), 25000);
    let committed = false;
    try {
      const response = await fetch(url, { method: "POST", credentials: "same-origin", signal: active.signal, headers: { "X-Requested-With": "fetch", Accept: "application/json" }, body: data });
      const payload = response.headers.get("content-type")?.includes("application/json") ? await response.json() : null;
      if (response.status === 400 && payload?.error === "csrf") {
        const refreshed = await refreshCsrf(active.signal);
        throw { known: true, message: refreshed ? "Votre session a été actualisée. Confirmez à nouveau pour enregistrer." : "Votre session a expiré. Reconnectez-vous avant de confirmer. Votre note est conservée." };
      }
      if (response.status === 401 || (response.redirected && new URL(response.url).pathname !== new URL(url).pathname)) {
        throw { known: true, message: "Votre session a expiré. Reconnectez-vous avant de confirmer. Votre note est conservée." };
      }
      if (!response.ok || !payload?.success) {
        if (response.status >= 400 && response.status < 500 && payload) throw { known: true, message: payload.message || payload.error };
        throw new Error("uncertain_result");
      }
      committed = true;
    } catch (failure) {
      uncertain = !failure.known;
      showError(failure.known ? String(failure.message || "Impossible de confirmer cet encaissement.") : "La confirmation n’a pas pu être vérifiée. Votre note est conservée. Vérifiez la liste avant de recommencer.");
    } finally {
      clearTimeout(timeout);
      setWriting(false);
      confirm.textContent = uncertain ? "Vérifier la liste" : "Encaissé";
    }
    if (committed) {
      // Close only after the POST has completed; perform no automatic POST retry.
      const refresh = pendingRead || { url: formUrl(Number(results.querySelector("[data-earnings-meta]")?.dataset.page || 1)).href, mode: "replace" };
      pendingRead = null;
      workspace.closeDialog();
      const refreshed = await read(refresh.url, refresh.mode);
      if (refreshed) message("Encaissement enregistré.");
    }
  });
  dialog.addEventListener("vendor:workspace-dialog-closed", () => {
    if (selected) draftNotes.set(selected.id, note.value);
    if (selected?.form.isConnected) selected.form.elements.note.value = note.value;
    selected = null;
  });
  document.addEventListener("vendor:dashboard-dialog-opened", () => {
    if (controller || timer) pendingRead = { url: formUrl().href, mode: "replace" };
    stopRead();
  });
  document.addEventListener("vendor:dashboard-dialog-closed", resumeRead);
  window.addEventListener("popstate", () => {
    const url = localUrl(location.href);
    if (!url) return;
    stopRead();
    syncFilters(url);
    if (dialog.open && !writing) workspace.requestCloseDialog();
    read(url, "");
  });
  updateDates();
})();
