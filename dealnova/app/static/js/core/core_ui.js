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

  function showInlineToast(options) {
    const opts = options || {};
    const message = String(opts.message || "").trim();
    if (!message) return false;

    const toast = document.getElementById(opts.toastId || "toast");
    const messageEl = document.getElementById(opts.messageId || "toast-message");
    if (!toast || !messageEl) {
      showToast(message, opts.type || "success");
      return false;
    }

    const type = String(opts.type || "success");
    const baseClass = String(opts.baseClass || "toast").trim() || "toast";
    const closeEl = opts.closeId ? document.getElementById(opts.closeId) : null;
    const iconEl = opts.iconId ? document.getElementById(opts.iconId) : null;
    const iconMap = Object.assign(
      {
        success: "bi bi-check-circle",
        error: "bi bi-x-circle",
        danger: "bi bi-x-circle",
        info: "bi bi-info-circle",
        warning: "bi bi-exclamation-triangle",
      },
      opts.iconMap || {}
    );

    toast.className = baseClass;
    toast.classList.add(type);
    messageEl.textContent = message;
    toast.style.display = opts.display || "flex";

    if (iconEl) {
      iconEl.className = iconMap[type] || iconMap.success;
    }

    if (toast.__bmInlineToastTimer) {
      window.clearTimeout(toast.__bmInlineToastTimer);
      toast.__bmInlineToastTimer = null;
    }

    if (closeEl) {
      closeEl.onclick = function () {
        if (toast.__bmInlineToastTimer) {
          window.clearTimeout(toast.__bmInlineToastTimer);
          toast.__bmInlineToastTimer = null;
        }
        toast.style.display = "none";
      };
    }

    toast.__bmInlineToastTimer = window.setTimeout(() => {
      toast.style.display = "none";
      toast.__bmInlineToastTimer = null;
    }, Math.max(0, Number(opts.durationMs) || 3000));

    return true;
  }

  function showBootstrapToast(options) {
    const opts = options || {};
    const message = String(opts.message || "").trim();
    if (!message) return false;

    const toast = document.getElementById(opts.toastId || "cartToast");
    const messageEl = document.getElementById(opts.messageId || "toastMessage");
    if (!toast || !messageEl) {
      showToast(message, opts.type || "success");
      return false;
    }

    const type = String(opts.type || "success");
    const baseClass =
      String(opts.baseClass || "toast align-items-center text-white border-0").trim() ||
      "toast align-items-center text-white border-0";
    const classMap = Object.assign(
      {
        success: "bg-success",
        info: "bg-info",
        warning: "bg-warning",
        error: "bg-danger",
        danger: "bg-danger",
      },
      opts.classMap || {}
    );

    toast.className = baseClass;
    String(classMap[type] || classMap.success || "bg-success")
      .split(/\s+/)
      .filter(Boolean)
      .forEach((cls) => toast.classList.add(cls));
    messageEl.textContent = message;

    const toastApi = window.bootstrap && window.bootstrap.Toast;
    if (toastApi) {
      const instance =
        typeof toastApi.getOrCreateInstance === "function"
          ? toastApi.getOrCreateInstance(toast)
          : new toastApi(toast);
      if (instance && typeof instance.show === "function") {
        instance.show();
        return true;
      }
    }

    toast.style.display = "block";
    if (toast.__bmBootstrapToastTimer) {
      window.clearTimeout(toast.__bmBootstrapToastTimer);
      toast.__bmBootstrapToastTimer = null;
    }
    toast.__bmBootstrapToastTimer = window.setTimeout(() => {
      toast.style.display = "none";
      toast.__bmBootstrapToastTimer = null;
    }, Math.max(0, Number(opts.durationMs) || 3000));
    return true;
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

  function bindMobileKeyboardGuard(options) {
    const opts = options || {};
    const fieldSelector = String(opts.fieldSelector || "input, select, textarea").trim() || "input, select, textarea";
    const bodyClass = String(opts.bodyClass || "").trim();
    const threshold = Number(opts.threshold);
    const keyboardThreshold = Number.isFinite(threshold) ? threshold : 110;
    const focusDelay = Number.isFinite(Number(opts.focusDelay)) ? Number(opts.focusDelay) : 90;
    const blurDelay = Number.isFinite(Number(opts.blurDelay)) ? Number(opts.blurDelay) : 120;
    const orientationDelay = Number.isFinite(Number(opts.orientationDelay)) ? Number(opts.orientationDelay) : 120;
    const mobileQuery = String(opts.mobileQuery || "(max-width: 767.98px)").trim() || "(max-width: 767.98px)";
    const getRoot =
      typeof opts.getRoot === "function"
        ? opts.getRoot
        : () => {
            if (!opts.rootSelector) return null;
            return document.querySelector(String(opts.rootSelector));
          };

    let baseViewportHeight = window.visualViewport ? window.visualViewport.height : window.innerHeight;

    function getActiveField() {
      const root = getRoot();
      const active = document.activeElement;
      if (!root || !active || !active.matches || !active.matches(fieldSelector)) {
        return null;
      }
      return root.contains(active) ? active : null;
    }

    function hasActiveField() {
      return !!getActiveField();
    }

    function lockHorizontalPosition() {
      if (!hasActiveField()) return;
      if (window.scrollX || document.documentElement.scrollLeft || document.body.scrollLeft) {
        window.scrollTo(0, window.scrollY);
        document.documentElement.scrollLeft = 0;
        document.body.scrollLeft = 0;
      }
    }

    function refreshBaseViewportHeight() {
      baseViewportHeight = window.visualViewport ? window.visualViewport.height : window.innerHeight;
    }

    function syncKeyboardViewport() {
      if (!document.body) return false;
      const root = getRoot();
      if (!root) {
        if (bodyClass) document.body.classList.remove(bodyClass);
        return false;
      }

      const viewportHeight = window.visualViewport ? window.visualViewport.height : window.innerHeight;
      if (viewportHeight > baseViewportHeight) {
        baseViewportHeight = viewportHeight;
      }

      const keyboardOpen = hasActiveField() && viewportHeight < baseViewportHeight - keyboardThreshold;
      if (bodyClass) {
        document.body.classList.toggle(bodyClass, keyboardOpen);
      }
      lockHorizontalPosition();
      return keyboardOpen;
    }

    function handleFocusIn(event) {
      const field = event && event.target;
      if (!field || !field.matches || !field.matches(fieldSelector)) return;
      const root = getRoot();
      if (!root || !root.contains(field)) return;

      if (window.matchMedia && window.matchMedia(mobileQuery).matches) {
        field.style.fontSize = "16px";
      }

      window.requestAnimationFrame(syncKeyboardViewport);
      window.setTimeout(() => {
        syncKeyboardViewport();
        lockHorizontalPosition();
      }, focusDelay);
    }

    function handleFocusOut() {
      window.setTimeout(syncKeyboardViewport, blurDelay);
    }

    function handleOrientationChange() {
      refreshBaseViewportHeight();
      window.setTimeout(syncKeyboardViewport, orientationDelay);
    }

    function handlePageShow() {
      refreshBaseViewportHeight();
      syncKeyboardViewport();
    }

    document.addEventListener("focusin", handleFocusIn, true);
    document.addEventListener("focusout", handleFocusOut, true);

    if (window.visualViewport) {
      window.visualViewport.addEventListener("resize", syncKeyboardViewport);
      window.visualViewport.addEventListener("scroll", syncKeyboardViewport);
    }

    window.addEventListener("orientationchange", handleOrientationChange);
    window.addEventListener("pageshow", handlePageShow);

    syncKeyboardViewport();

    return {
      getActiveField,
      hasActiveField,
      lockHorizontalPosition,
      refreshBaseViewportHeight,
      sync: syncKeyboardViewport,
      destroy() {
        document.removeEventListener("focusin", handleFocusIn, true);
        document.removeEventListener("focusout", handleFocusOut, true);
        if (window.visualViewport) {
          window.visualViewport.removeEventListener("resize", syncKeyboardViewport);
          window.visualViewport.removeEventListener("scroll", syncKeyboardViewport);
        }
        window.removeEventListener("orientationchange", handleOrientationChange);
        window.removeEventListener("pageshow", handlePageShow);
        if (bodyClass && document.body) {
          document.body.classList.remove(bodyClass);
        }
      },
    };
  }

  bindModalCleanup();

  window.BMCoreUI = {
    showToast,
    showAlert,
    showInlineToast,
    showBootstrapToast,
    setButtonLoading,
    buildIconHtml,
    applyToggleState,
    updateBadge,
    removeClosest,
    cleanupStuckModalState,
    bindModalCleanup,
    bindMobileKeyboardGuard,
    __ready: true,
  };
})();

