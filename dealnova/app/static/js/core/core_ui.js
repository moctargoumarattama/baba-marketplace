(() => {
  const existing = window.BMCoreUI || {};
  if (existing.__ready) return;

  function showToast(message, type) {
    if (!message || !document.body) return;
    const toast = document.createElement("div");
    const isError = type === "error" || type === "danger";
    const isInfo = type === "info";
    toast.textContent = message;
    toast.style.cssText = [
      "position:fixed",
      "right:20px",
      "bottom:20px",
      "z-index:9999",
      "max-width:320px",
      "background:" + (isError ? "#DC2626" : isInfo ? "#2563EB" : "#16A34A"),
      "color:#fff",
      "padding:12px 16px",
      "border-radius:12px",
      "box-shadow:0 18px 36px rgba(15,23,42,0.25)",
      "font-size:0.95rem",
      "opacity:0",
      "transform:translateY(10px)",
      "transition:all .18s ease",
    ].join(";");
    document.body.appendChild(toast);
    requestAnimationFrame(() => {
      toast.style.opacity = "1";
      toast.style.transform = "translateY(0)";
    });
    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translateY(8px)";
      setTimeout(() => toast.remove(), 200);
    }, 3000);
  }

  function showAlert(message, type) {
    if (!message) return;
    if (document.body) {
      showToast(message, type || "error");
      return;
    }
    window.alert(message);
  }

  function setButtonLoading(btn, loading) {
    if (!btn) return;
    if (loading) {
      btn.dataset.originalText = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML =
        btn.dataset.loadingText ||
        '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>Chargement';
      return;
    }
    if (btn.dataset.originalText) btn.innerHTML = btn.dataset.originalText;
    btn.disabled = false;
  }

  function buildIconHtml(iconClass) {
    if (!iconClass) return "";
    return `<i class="${iconClass}"></i>`;
  }

  function applyToggleState(btn, isActive) {
    if (!btn) return;
    const activeText = btn.dataset.activeText;
    const inactiveText = btn.dataset.inactiveText;
    const activeIcon = btn.dataset.activeIcon;
    const inactiveIcon = btn.dataset.inactiveIcon;
    const activeClass = btn.dataset.activeClass;
    const inactiveClass = btn.dataset.inactiveClass;

    if (activeClass || inactiveClass) {
      if (activeClass) btn.classList.remove(activeClass);
      if (inactiveClass) btn.classList.remove(inactiveClass);
      const cls = isActive ? activeClass : inactiveClass;
      if (cls) btn.classList.add(cls);
    }

    const text = isActive ? activeText : inactiveText;
    const icon = isActive ? activeIcon : inactiveIcon;
    if (text || icon) {
      const html = `${buildIconHtml(icon)}${text ? " " + text : ""}`.trim();
      if (html) btn.innerHTML = html;
    }
  }

  function updateBadge(badge, isActive) {
    if (!badge) return;
    const activeText = badge.dataset.activeText || "Actif";
    const inactiveText = badge.dataset.inactiveText || "Inactif";
    const activeClass = badge.dataset.activeClass || "bg-success";
    const inactiveClass = badge.dataset.inactiveClass || "bg-secondary";

    badge.textContent = isActive ? activeText : inactiveText;
    badge.classList.remove(activeClass, inactiveClass);
    badge.classList.add(isActive ? activeClass : inactiveClass);
  }

  function removeClosest(el, selector) {
    if (!el) return;
    const target = el.closest(selector || "tr");
    if (target) target.remove();
  }

  function cleanupStuckModalState() {
    const hasModal = !!document.querySelector(".modal.show");
    if (hasModal) return;

    document.querySelectorAll(".modal-backdrop").forEach((el) => el.remove());

    const sidebar = document.getElementById("sidebar");
    const sidebarBackdrop = document.getElementById("sidebarBackdrop");
    const sidebarIsOpen = !!(sidebar && sidebar.classList.contains("show"));
    if (sidebarBackdrop && !sidebarIsOpen) {
      sidebarBackdrop.classList.remove("show");
    }

    if (!document.body) return;
    document.body.classList.remove("modal-open");
    if (!sidebarIsOpen) {
      document.body.style.overflow = "";
      document.body.style.paddingRight = "";
    }
  }

  function bindModalCleanup() {
    if (window.__bmModalCleanupBound) return;
    window.__bmModalCleanupBound = true;

    document.addEventListener("hidden.bs.modal", () => {
      setTimeout(cleanupStuckModalState, 50);
    });

    document.addEventListener("show.bs.modal", (e) => {
      const modalEl = e && e.target;
      if (!modalEl || !document.body) return;
      if (modalEl.parentElement !== document.body) {
        document.body.appendChild(modalEl);
      }
    });
  }

  bindModalCleanup();

  window.BMCoreUI = {
    showToast,
    showAlert,
    setButtonLoading,
    buildIconHtml,
    applyToggleState,
    updateBadge,
    removeClosest,
    cleanupStuckModalState,
    bindModalCleanup,
    __ready: true,
  };
})();

