(function () {
  "use strict";
  const shell = document.querySelector(".vd-shell");
  if (!shell || shell.dataset.layoutBound) return;
  shell.dataset.layoutBound = "1";
  shell.classList.add("vd-enhanced");
  const tabs = Array.from(shell.querySelectorAll("[data-vd-tab]"));
  const panels = Array.from(shell.querySelectorAll(".vd-tab-panel"));
  const dialogs = Array.from(document.querySelectorAll("dialog.vd-choice-dialog"));
  let activeDialog = null;
  let opener = null;
  let scrollLock = null;

  function selectTab(name, focus) {
    const selected = tabs.find((tab) => tab.dataset.vdTab === name) || tabs[0];
    if (!selected) return;
    tabs.forEach((tab) => {
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-controls", "vd-panel-" + tab.dataset.vdTab);
      tab.setAttribute("aria-selected", String(tab === selected));
      tab.tabIndex = tab === selected ? 0 : -1;
    });
    panels.forEach((panel) => {
      panel.setAttribute("role", "tabpanel");
      panel.tabIndex = 0;
      panel.hidden = panel.id !== "vd-panel-" + selected.dataset.vdTab;
    });
    if (focus) selected.focus({ preventScroll: true });
  }
  shell.querySelector(".vd-tabs")?.setAttribute("role", "tablist");
  const initial = location.hash.match(/^#vd-panel-(recent|prepare|bookings)$/)?.[1];
  selectTab(initial || shell.querySelector("[data-vd-initial-tab]")?.dataset.vdInitialTab);
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", (event) => { event.preventDefault(); selectTab(tab.dataset.vdTab); });
    tab.addEventListener("keydown", (event) => {
      let next;
      if (event.key === "ArrowRight") next = tabs[(index + 1) % tabs.length];
      else if (event.key === "ArrowLeft") next = tabs[(index + tabs.length - 1) % tabs.length];
      else if (event.key === "Home") next = tabs[0];
      else if (event.key === "End") next = tabs[tabs.length - 1];
      if (next) { event.preventDefault(); selectTab(next.dataset.vdTab, true); }
    });
  });

  function lockPage() {
    if (scrollLock) return;
    const body = document.body;
    const keys = ["position", "top", "left", "width", "paddingRight"];
    scrollLock = { x: scrollX, y: scrollY, overflow: document.documentElement.style.overflow, styles: {} };
    keys.forEach((key) => { scrollLock.styles[key] = body.style[key]; });
    const gap = innerWidth - document.documentElement.clientWidth;
    const padding = parseFloat(getComputedStyle(body).paddingRight) || 0;
    body.style.position = "fixed";
    body.style.top = -scrollLock.y + "px";
    body.style.left = -scrollLock.x + "px";
    body.style.width = "100%";
    if (gap > 0) body.style.paddingRight = padding + gap + "px";
    document.documentElement.style.overflow = "hidden";
  }
  function unlockPage() {
    if (!scrollLock) return;
    const saved = scrollLock;
    scrollLock = null;
    Object.keys(saved.styles).forEach((key) => { document.body.style[key] = saved.styles[key]; });
    document.documentElement.style.overflow = saved.overflow;
    window.scrollTo({ left: saved.x, top: saved.y, behavior: "instant" });
  }
  function closeDialog(force = false) {
    if (!activeDialog) return;
    if (activeDialog.dataset.busy === "1" && !force) return;
    if (!force && !activeDialog.dispatchEvent(new CustomEvent("vendor:workspace-dialog-before-close", { cancelable: true }))) return;
    const previous = activeDialog;
    activeDialog = null;
    previous.close();
    previous.dispatchEvent(new CustomEvent("vendor:workspace-dialog-closed"));
    unlockPage();
    if (opener?.isConnected) opener.focus({ preventScroll: true });
    document.dispatchEvent(new CustomEvent("vendor:dashboard-dialog-closed"));
  }
  function openDialog(target, trigger) {
    if (!target || typeof target.showModal !== "function" || activeDialog) return;
    opener = trigger;
    activeDialog = target;
    lockPage();
    target.showModal();
    target.querySelector("[data-vd-close]")?.focus({ preventScroll: true });
    target.dispatchEvent(new CustomEvent("vendor:workspace-dialog-opened"));
    document.dispatchEvent(new CustomEvent("vendor:dashboard-dialog-opened"));
  }
  // Capture before the shared form manager: close the chooser and release its
  // scroll lock in the same click before the actual editor takes ownership.
  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const createLink = target.closest("[data-vendor-product-create], [data-vendor-location-create]");
    if (createLink && activeDialog?.contains(createLink)) closeDialog();
    const trigger = target.closest("[data-vd-dialog]");
    if (trigger) {
      event.preventDefault();
      openDialog(document.getElementById(trigger.dataset.vdDialog), trigger);
    }
    if (target.closest("[data-vd-close]")) { event.preventDefault(); closeDialog(); }
    const jump = target.closest("[data-vd-show-tab]");
    if (jump) {
      event.preventDefault();
      selectTab(jump.dataset.vdShowTab, true);
      shell.querySelector(".vd-tasks")?.scrollIntoView({ block: "start", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
    }
  }, true);
  dialogs.forEach((dialog) => {
    dialog.addEventListener("cancel", (event) => { event.preventDefault(); closeDialog(); });
    let backdropPressed = false;
    dialog.addEventListener("pointerdown", (event) => { backdropPressed = event.target === dialog; });
    dialog.addEventListener("click", (event) => { if (event.target === dialog && backdropPressed) closeDialog(); backdropPressed = false; });
    dialog.addEventListener("pointerdown", (event) => {
      if (event.pointerType === "touch" && event.target.closest("[data-vd-close]")) event.preventDefault();
    });
  });
  document.querySelectorAll("[data-vd-dialog]").forEach((button) => {
    button.setAttribute("aria-haspopup", "dialog");
    button.setAttribute("aria-controls", button.dataset.vdDialog);
  });
  window.BMVendorWorkspace = {
    openDialog(id, trigger) { openDialog(document.getElementById(id), trigger); },
    closeDialog() { closeDialog(true); },
    requestCloseDialog() { closeDialog(); }
  };
  const bookingCount = document.getElementById("todayBookingsCount");
  if (bookingCount) new MutationObserver(() => {
    shell.querySelectorAll("[data-vd-booking-count]").forEach((node) => { node.textContent = bookingCount.textContent; });
  }).observe(bookingCount, { childList: true, characterData: true, subtree: true });
})();
