(function () {
  "use strict";

  var root = document.getElementById("bmAssistant");
  if (!root) return;

  var bootstrapUrl = root.getAttribute("data-bootstrap-url") || "";
  var messageUrl = root.getAttribute("data-message-url") || "";
  if (!bootstrapUrl || !messageUrl) return;

  var toggleBtn = document.getElementById("bmAssistantToggle");
  var closeBtn = document.getElementById("bmAssistantClose");
  var panel = document.getElementById("bmAssistantPanel");
  var hintBtn = document.getElementById("bmAssistantHint");
  var contentBox = document.getElementById("bmAssistantContent");
  var messagesBox = document.getElementById("bmAssistantMessages");
  var quickBox = document.getElementById("bmAssistantQuick");
  var pending = document.getElementById("bmAssistantPending");
  var form = document.getElementById("bmAssistantForm");
  var input = document.getElementById("bmAssistantInput");
  var sendBtn = document.getElementById("bmAssistantSend");

  var hydrated = false;
  var bootstrapPromise = null;
  var initialPayload = null;
  var freshConversation = true;
  var requestInFlight = false;
  var lastQuickReplies = [];
  var lastQuickLayout = "";
  var pendingTimer = null;
  var bodyOverflowBeforeOpen = "";
  var viewportBound = false;
  var suppressToggleClick = false;
  var hintTimer = null;

  var POSITION_STORAGE_KEY = "bm_assistant_position_v2";
  var HINT_TEXT = root.getAttribute("data-welcome-hint") || "Comment puis-je vous aider ?";
  var MOBILE_BREAKPOINT = 768;

  try {
    var initialNode = document.getElementById("bmAssistantInitial");
    var initialData = initialNode ? JSON.parse(initialNode.textContent) : null;
    if (initialData && initialData.response && typeof initialData.response === "object") {
      initialPayload = initialData;
    }
  } catch (_error) {
    // Older cached documents can still initialize through the bootstrap URL.
  }

  var dragState = {
    active: false,
    moved: false,
    startX: 0,
    startY: 0,
    originLeft: 0,
    originTop: 0,
  };

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function readNumber(value, fallback) {
    var parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function getPoint(event) {
    return { x: readNumber(event.clientX, 0), y: readNumber(event.clientY, 0) };
  }

  function isPanelOpen() {
    return !!panel && !panel.hidden;
  }

  function isMobileViewport() {
    return (window.innerWidth || document.documentElement.clientWidth || 0) <= MOBILE_BREAKPOINT;
  }

  function hideHint() {
    if (!hintBtn) return;
    hintBtn.hidden = true;
    if (hintTimer) {
      window.clearTimeout(hintTimer);
      hintTimer = null;
    }
  }

  function getBottomDockInset() {
    var viewportHeight = window.visualViewport
      ? readNumber(window.visualViewport.height, window.innerHeight || 0)
      : window.innerHeight || document.documentElement.clientHeight || 0;
    var tabs = document.querySelector("[data-home-bottom-tabs]");
    if (!tabs) return 0;
    var rect = tabs.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return 0;
    return Math.max(0, viewportHeight - rect.top) + 8;
  }

  function getViewportRect() {
    if (window.visualViewport) {
      var vv = window.visualViewport;
      var width = readNumber(vv.width, window.innerWidth || 0);
      var height = readNumber(vv.height, window.innerHeight || 0);
      var left = readNumber(vv.offsetLeft, 0);
      var top = readNumber(vv.offsetTop, 0);
      return {
        width: width,
        height: height,
        left: left,
        top: top,
        right: left + width,
        bottom: top + height,
      };
    }
    var fallbackWidth = window.innerWidth || document.documentElement.clientWidth || 0;
    var fallbackHeight = window.innerHeight || document.documentElement.clientHeight || 0;
    return {
      width: fallbackWidth,
      height: fallbackHeight,
      left: 0,
      top: 0,
      right: fallbackWidth,
      bottom: fallbackHeight,
    };
  }

  function getBounds() {
    var viewport = getViewportRect();
    var toggleWidth = toggleBtn ? toggleBtn.offsetWidth || 56 : 56;
    var toggleHeight = toggleBtn ? toggleBtn.offsetHeight || 56 : 56;
    var dockInset = getBottomDockInset();
    var pad = 8;
    return {
      minLeft: viewport.left + pad,
      maxLeft: Math.max(viewport.left + pad, viewport.right - toggleWidth - pad),
      minTop: viewport.top + pad,
      maxTop: Math.max(viewport.top + pad, viewport.bottom - dockInset - toggleHeight - pad),
    };
  }

  function currentLeftTop() {
    var rect = root.getBoundingClientRect();
    return {
      left: readNumber(rect.left, 0),
      top: readNumber(rect.top, 0),
    };
  }

  function updatePanelPlacement() {
    if (!toggleBtn) return;
    root.classList.remove("is-panel-left", "is-panel-bottom");
    if (root.classList.contains("is-mobile-open")) return;

    var viewport = getViewportRect();
    var toggleRect = toggleBtn.getBoundingClientRect();

    var panelWidth = panel && !panel.hidden ? panel.offsetWidth || 360 : 360;
    var panelHeight = panel && !panel.hidden ? panel.offsetHeight || 460 : 460;
    var spaceLeft = toggleRect.right;
    var spaceRight = viewport.width - toggleRect.left;
    var spaceAbove = toggleRect.top;
    var spaceBelow = viewport.height - toggleRect.bottom;

    if (spaceLeft < panelWidth + 8 && spaceRight > spaceLeft) {
      root.classList.add("is-panel-left");
    }
    if (spaceAbove < panelHeight + 8 && spaceBelow > spaceAbove) {
      root.classList.add("is-panel-bottom");
    }
  }

  function applyPosition(left, top) {
    root.style.left = Math.round(left) + "px";
    root.style.top = Math.round(top) + "px";
    root.style.right = "auto";
    root.style.bottom = "auto";
    updatePanelPlacement();
  }

  function defaultPosition() {
    var bounds = getBounds();
    return { left: bounds.maxLeft, top: bounds.maxTop };
  }

  function savePosition(left, top) {
    try {
      window.localStorage.setItem(
        POSITION_STORAGE_KEY,
        JSON.stringify({ left: Math.round(left), top: Math.round(top) })
      );
    } catch (_error) {
      // best effort only
    }
  }

  function loadPosition() {
    try {
      var raw = window.localStorage.getItem(POSITION_STORAGE_KEY);
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return null;
      if (!Number.isFinite(parsed.left) || !Number.isFinite(parsed.top)) return null;
      return { left: Number(parsed.left), top: Number(parsed.top) };
    } catch (_error) {
      return null;
    }
  }

  function clampCurrentPosition() {
    var bounds = getBounds();
    var pos = currentLeftTop();
    applyPosition(clamp(pos.left, bounds.minLeft, bounds.maxLeft), clamp(pos.top, bounds.minTop, bounds.maxTop));
  }

  function placeInitialPosition() {
    var bounds = getBounds();
    var stored = loadPosition();
    if (stored) {
      applyPosition(clamp(stored.left, bounds.minLeft, bounds.maxLeft), clamp(stored.top, bounds.minTop, bounds.maxTop));
      return;
    }
    var fallback = defaultPosition();
    applyPosition(fallback.left, fallback.top);
  }

  function setBodyLocked(locked) {
    if (!document.body) return;
    var desktopLock = !isMobileViewport();
    if (locked) {
      if (!document.body.classList.contains("bm-assistant-open")) {
        bodyOverflowBeforeOpen = document.body.style.overflow || "";
      }
      document.body.classList.add("bm-assistant-open");
      if (desktopLock) {
        document.body.style.overflow = "hidden";
      }
      return;
    }
    document.body.classList.remove("bm-assistant-open");
    document.body.style.overflow = bodyOverflowBeforeOpen;
    bodyOverflowBeforeOpen = "";
  }

  function applyMobilePanelLayout() {
    if (!panel) return;
    var viewport = getViewportRect();
    var layoutHeight = window.innerHeight || document.documentElement.clientHeight || viewport.height;
    var keyboardInset = Math.max(0, Math.round(layoutHeight - (viewport.height + viewport.top)));
    var desiredHeight = Math.round(layoutHeight * 0.72);
    var maxDefault = Math.min(560, desiredHeight);
    var availableHeight = Math.max(0, Math.round(viewport.height) - 18);
    var panelHeight = Math.min(maxDefault, availableHeight);
    root.style.setProperty("--bm-assistant-vv-inset-bottom", keyboardInset + "px");
    root.style.setProperty("--bm-assistant-mobile-height", panelHeight + "px");
    root.classList.add("is-mobile-open");
  }

  function clearMobilePanelLayout() {
    root.classList.remove("is-mobile-open");
    root.style.removeProperty("--bm-assistant-vv-inset-bottom");
    root.style.removeProperty("--bm-assistant-mobile-height");
  }

  function syncViewportOffset() {
    if (!isPanelOpen()) return;
    if (isMobileViewport()) {
      applyMobilePanelLayout();
      return;
    }
    clearMobilePanelLayout();
    clampCurrentPosition();
  }

  function bindViewportEvents() {
    if (!window.visualViewport || viewportBound) return;
    window.visualViewport.addEventListener("resize", syncViewportOffset);
    window.visualViewport.addEventListener("scroll", syncViewportOffset);
    viewportBound = true;
  }

  function unbindViewportEvents() {
    if (!window.visualViewport || !viewportBound) return;
    window.visualViewport.removeEventListener("resize", syncViewportOffset);
    window.visualViewport.removeEventListener("scroll", syncViewportOffset);
    viewportBound = false;
  }

  function scrollToBottom() {
    var scroller = contentBox || messagesBox;
    if (!scroller) return;
    scroller.scrollTop = scroller.scrollHeight;
  }

  function setBusy(busy) {
    requestInFlight = busy;
    if (sendBtn) sendBtn.disabled = busy;
    if (pendingTimer !== null) {
      window.clearTimeout(pendingTimer);
      pendingTimer = null;
    }
    if (pending) {
      pending.hidden = true;
      if (busy) {
        pendingTimer = window.setTimeout(function () {
          pendingTimer = null;
          if (!requestInFlight) return;
          pending.hidden = false;
          scrollToBottom();
        }, 250);
      }
    }
    if (messagesBox) messagesBox.setAttribute("aria-busy", String(busy));
  }

  function createMessageBubble(text, role) {
    if (!messagesBox) return;
    var bubble = document.createElement("div");
    bubble.className = "bm-assistant-msg " + (role === "user" ? "user" : "bot");
    bubble.textContent = String(text || "");
    messagesBox.appendChild(bubble);
    scrollToBottom();
  }

  function clearQuickReplies() {
    if (!quickBox) return;
    quickBox.innerHTML = "";
    quickBox.classList.remove("is-menu");
  }

  function renderQuickReplies(replies, layout) {
    clearQuickReplies();
    if (!quickBox) return;
    var list = Array.isArray(replies) ? replies : [];
    lastQuickReplies = list;
    lastQuickLayout = layout || "";
    var isMenu = layout === "menu";
    quickBox.classList.toggle("is-menu", isMenu);
    if (isMenu) {
      var heading = document.createElement("p");
      heading.className = "bm-assistant-quick-heading";
      heading.textContent = "Que souhaitez-vous faire ?";
      quickBox.appendChild(heading);
    }
    list.slice(0, 8).forEach(function (reply) {
      if (!reply || typeof reply !== "object") return;
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "bm-assistant-quick-btn";
      var label = String(reply.label || "Option");
      btn.setAttribute("aria-label", label);
      if (isMenu && reply.action !== "handoff") {
        var iconName = /^bi-[a-z0-9-]+$/.test(String(reply.icon || "")) ? reply.icon : "bi-arrow-right";
        var icon = document.createElement("span");
        icon.className = "bm-assistant-option-icon";
        icon.setAttribute("aria-hidden", "true");
        var glyph = document.createElement("i");
        glyph.className = "bi " + iconName;
        icon.appendChild(glyph);
        btn.appendChild(icon);
        var text = document.createElement("span");
        text.className = "bm-assistant-option-text";
        text.textContent = String(reply.display_label || label);
        if (reply.detail) {
          var detail = document.createElement("small");
          detail.textContent = String(reply.detail);
          text.appendChild(detail);
        }
        btn.appendChild(text);
      } else {
        if (isMenu && reply.action === "handoff") {
          btn.classList.add("is-adviser");
          var adviserIcon = document.createElement("i");
          adviserIcon.className = "bi bi-headset";
          adviserIcon.setAttribute("aria-hidden", "true");
          btn.appendChild(adviserIcon);
        }
        btn.appendChild(document.createTextNode(label));
      }
      btn.dataset.action = String(reply.action || "");
      btn.dataset.value = String(reply.value || "");
      btn.addEventListener("click", function () {
        sendAssistantMessage({
          message: label,
          action: btn.dataset.action || "",
          value: btn.dataset.value || "",
          showAsUser: true,
        });
      });
      quickBox.appendChild(btn);
    });
  }

  function renderCards(items) {
    if (!messagesBox) return;
    var cards = Array.isArray(items) ? items : [];
    cards.forEach(function (item) {
      var card = document.createElement("article");
      card.className = "bm-assistant-card";

      var title = document.createElement("div");
      title.className = "bm-assistant-card-title";
      title.textContent = String(item.title || "");
      card.appendChild(title);

      if (item.subtitle) {
        var subtitle = document.createElement("div");
        subtitle.className = "bm-assistant-card-sub";
        subtitle.textContent = String(item.subtitle || "");
        card.appendChild(subtitle);
      }

      if (item.meta) {
        var meta = document.createElement("div");
        meta.className = "bm-assistant-card-meta";
        meta.textContent = String(item.meta || "");
        card.appendChild(meta);
      }

      if (item.url) {
        var link = document.createElement("a");
        link.href = String(item.url);
        link.textContent = String(item.cta || "Voir les détails");
        card.appendChild(link);
      }

      messagesBox.appendChild(card);
    });
    scrollToBottom();
  }

  function renderHandoff(handoff) {
    if (!messagesBox || !handoff || !handoff.url) return;
    var link = document.createElement("a");
    link.className = "bm-assistant-handoff";
    link.href = String(handoff.url);
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = String(handoff.label || "Contacter un conseiller");
    messagesBox.appendChild(link);
    scrollToBottom();
  }

  function renderMore(more) {
    if (!messagesBox || !more || !more.url) return;
    try {
      var target = new URL(String(more.url), window.location.origin);
      if (target.origin !== window.location.origin || !/^https?:$/.test(target.protocol)) return;
      var link = document.createElement("a");
      link.className = "bm-assistant-more";
      link.href = target.pathname + target.search + target.hash;
      link.textContent = String(more.label || "Voir toutes les offres");
      messagesBox.appendChild(link);
    } catch (_error) {
      // Ignore invalid catalog destinations.
    }
  }

  function redirectIfNeeded(url) {
    if (!url) return;
    try {
      var target = new URL(String(url), window.location.origin);
      window.location.assign(target.toString());
    } catch (_error) {
      window.location.assign(String(url));
    }
  }

  function renderAssistantResponse(payload) {
    var response = payload && payload.response ? payload.response : null;
    if (!response) return;
    var previousLast = messagesBox && messagesBox.lastElementChild;
    if (response.text) createMessageBubble(response.text, "bot");
    if (response.items) renderCards(response.items);
    if (response.more) renderMore(response.more);
    if (response.handoff) renderHandoff(response.handoff);
    renderQuickReplies(response.quick_replies || [], response.quick_layout);
    var responseStart = messagesBox && (previousLast ? previousLast.nextElementSibling : messagesBox.firstElementChild);
    var showResponseStart = response.quick_layout === "menu" || (Array.isArray(response.items) && response.items.length);
    if (showResponseStart && contentBox && responseStart) {
      // Show the welcome or first result without moving the surrounding page.
      var paddingTop = parseFloat(window.getComputedStyle(contentBox).paddingTop) || 0;
      contentBox.scrollTop += responseStart.getBoundingClientRect().top
        - contentBox.getBoundingClientRect().top - contentBox.clientTop - paddingTop;
    } else {
      scrollToBottom();
    }
    redirectIfNeeded(response.redirect_url);
  }

  function buildUrl(url, params) {
    var u = new URL(url, window.location.origin);
    Object.keys(params || {}).forEach(function (key) {
      var value = params[key];
      if (value === null || value === undefined || value === "") return;
      u.searchParams.set(key, String(value));
    });
    return u.toString();
  }

  async function fetchAssistant(url) {
    var controller = new AbortController();
    var timeout = window.setTimeout(function () { controller.abort(); }, 20000);
    try {
      var res = await fetch(url, {
        method: "GET",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });
      if (!res.ok) throw new Error("assistant_request_failed");
      var payload = await res.json();
      if (!payload || !payload.response || typeof payload.response !== "object") {
        throw new Error("assistant_invalid_response");
      }
      return payload;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  async function ensureBootstrap() {
    if (hydrated) return;
    if (initialPayload) {
      renderAssistantResponse(initialPayload);
      hydrated = true;
      setBusy(false);
      return;
    }
    if (!bootstrapPromise) {
      setBusy(true);
      bootstrapPromise = fetchAssistant(bootstrapUrl).then(function (payload) {
        initialPayload = payload;
        renderAssistantResponse(payload);
        hydrated = true;
      }).catch(function () {
        createMessageBubble("L'assistant est indisponible pour le moment. Réessayez plus tard.", "bot");
      }).finally(function () {
        setBusy(false);
        bootstrapPromise = null;
      });
    }
    return bootstrapPromise;
  }

  async function sendAssistantMessage(options) {
    if (requestInFlight) return;
    var opts = options || {};
    var message = String(opts.message || "").trim();
    var action = String(opts.action || "").trim();
    var value = String(opts.value || "").trim();
    var showAsUser = opts.showAsUser !== false;

    if ((action === "start" || action === "reset") && initialPayload) {
      messagesBox.textContent = "";
      renderAssistantResponse(initialPayload);
      hydrated = true;
      freshConversation = true;
      setBusy(false);
      return;
    }

    var previousReplies = lastQuickReplies;
    var previousLayout = lastQuickLayout;
    clearQuickReplies();
    if (showAsUser && message) {
      createMessageBubble(message, "user");
    }

    setBusy(true);
    scrollToBottom();
    var requestUrl = buildUrl(messageUrl, {
      message: message,
      action: action,
      value: value,
      fresh: freshConversation ? "1" : "",
    });
    try {
      var payload = await fetchAssistant(requestUrl);
      renderAssistantResponse(payload);
      freshConversation = false;
    } catch (_error) {
      createMessageBubble("Impossible de charger la réponse. Réessayez dans un instant.", "bot");
      renderQuickReplies(previousReplies, previousLayout);
    } finally {
      setBusy(false);
    }
  }

  function showHintIfNeeded() {
    if (!hintBtn || isPanelOpen()) return;
    var text = hintBtn.querySelector("span");
    if (text) text.textContent = HINT_TEXT;
    hintBtn.hidden = false;
    updatePanelPlacement();
    hintTimer = window.setTimeout(hideHint, 3000);
  }

  async function openPanel() {
    if (!panel || !toggleBtn) return;
    hideHint();
    panel.hidden = false;
    toggleBtn.setAttribute("aria-expanded", "true");
    setBodyLocked(true);
    bindViewportEvents();
    syncViewportOffset();
    updatePanelPlacement();
    // Keep the choices visible on mobile instead of opening the keyboard.
    panel.focus({ preventScroll: true });
    await ensureBootstrap();
    if (input && isPanelOpen() && !isMobileViewport()) {
      window.requestAnimationFrame(function () {
        if (!isPanelOpen() || isMobileViewport()) return;
        try {
          input.focus({ preventScroll: true });
        } catch (_error) {
          input.focus();
        }
        syncViewportOffset();
      });
    }
  }

  function closePanel() {
    if (!panel || !toggleBtn) return;
    if (input) input.blur();
    root.classList.remove("is-typing");
    panel.hidden = true;
    toggleBtn.setAttribute("aria-expanded", "false");
    clearMobilePanelLayout();
    unbindViewportEvents();
    setBodyLocked(false);
    updatePanelPlacement();
    toggleBtn.focus({ preventScroll: true });
  }

  function onDragStart(event) {
    if (!toggleBtn || isPanelOpen()) return;
    if (event.button !== undefined && event.button !== 0) return;
    var point = getPoint(event);
    var pos = currentLeftTop();
    dragState.active = true;
    dragState.moved = false;
    dragState.startX = point.x;
    dragState.startY = point.y;
    dragState.originLeft = pos.left;
    dragState.originTop = pos.top;
    root.classList.add("is-dragging");
    if (toggleBtn.setPointerCapture && event.pointerId !== undefined) {
      toggleBtn.setPointerCapture(event.pointerId);
    }
    event.preventDefault();
  }

  function onDragMove(event) {
    if (!dragState.active) return;
    var point = getPoint(event);
    var dx = point.x - dragState.startX;
    var dy = point.y - dragState.startY;
    if (!dragState.moved && Math.abs(dx) + Math.abs(dy) >= 6) {
      dragState.moved = true;
      hideHint();
    }
    var bounds = getBounds();
    var nextLeft = clamp(dragState.originLeft + dx, bounds.minLeft, bounds.maxLeft);
    var nextTop = clamp(dragState.originTop + dy, bounds.minTop, bounds.maxTop);
    applyPosition(nextLeft, nextTop);
  }

  function onDragEnd(event) {
    if (!dragState.active) return;
    dragState.active = false;
    root.classList.remove("is-dragging");
    if (toggleBtn && toggleBtn.releasePointerCapture && event.pointerId !== undefined) {
      try {
        toggleBtn.releasePointerCapture(event.pointerId);
      } catch (_error) {
        // no-op
      }
    }
    if (!dragState.moved) return;
    var pos = currentLeftTop();
    savePosition(pos.left, pos.top);
    suppressToggleClick = true;
    window.setTimeout(function () {
      suppressToggleClick = false;
    }, 0);
  }

  if (toggleBtn) {
    toggleBtn.addEventListener("click", function (event) {
      if (suppressToggleClick) {
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      if (!panel || panel.hidden) {
        openPanel();
      } else {
        closePanel();
      }
    });

    toggleBtn.addEventListener("pointerdown", onDragStart);
    toggleBtn.addEventListener("pointermove", onDragMove);
    toggleBtn.addEventListener("pointerup", onDragEnd);
    toggleBtn.addEventListener("pointercancel", onDragEnd);
    toggleBtn.addEventListener("lostpointercapture", onDragEnd);
  }

  if (hintBtn) {
    hintBtn.addEventListener("click", function () {
      openPanel();
    });
  }

  if (closeBtn) {
    closeBtn.addEventListener("click", closePanel);
  }

  if (panel) {
    panel.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      closePanel();
    });
  }

  if (form) {
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!input || requestInFlight || event.isComposing) return;
      var value = input.value.trim();
      if (!value) return;
      input.value = "";
      if (isMobileViewport()) input.blur();
      sendAssistantMessage({ message: value, showAsUser: true });
    });
  }

  if (input) {
    input.addEventListener("focus", function () {
      root.classList.add("is-typing");
      syncViewportOffset();
      window.setTimeout(syncViewportOffset, 80);
      window.setTimeout(syncViewportOffset, 220);
    });
    input.addEventListener("blur", function () {
      root.classList.remove("is-typing");
      syncViewportOffset();
    });
  }

  window.addEventListener("resize", function () {
    if (isPanelOpen()) {
      syncViewportOffset();
      updatePanelPlacement();
      return;
    }
    clampCurrentPosition();
  });

  placeInitialPosition();
  updatePanelPlacement();
  window.setTimeout(showHintIfNeeded, 900);
})();
