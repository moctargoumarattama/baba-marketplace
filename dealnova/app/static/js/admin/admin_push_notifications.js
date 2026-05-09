(function () {
  "use strict";

  const button = document.getElementById("adminPushStatus");
  if (!button) return;

  const cfg = {
    configUrl: button.dataset.pushConfigUrl || "",
    statusUrl: button.dataset.pushStatusUrl || "",
    subscribeUrl: button.dataset.pushSubscribeUrl || "",
  };

  function setStatus(label, state) {
    button.classList.toggle("is-active", state === "active");
    button.classList.toggle("is-error", state === "error");
    button.innerHTML = '<i class="bi bi-bell"></i><span>' + String(label || "Alertes").replace(/[<>&]/g, "") + "</span>";
  }

  function headers() {
    const next = { Accept: "application/json", "Content-Type": "application/json" };
    if (window.BMAjaxCSRF && typeof window.BMAjaxCSRF.addToHeaders === "function") {
      return window.BMAjaxCSRF.addToHeaders(next);
    }
    const token = document.querySelector('meta[name="csrf-token"]');
    if (token && token.content) next["X-CSRFToken"] = token.content;
    return next;
  }

  function decodeKey(key) {
    const value = String(key || "").trim();
    const padding = "=".repeat((4 - (value.length % 4)) % 4);
    const raw = window.atob((value + padding).replace(/-/g, "+").replace(/_/g, "/"));
    const output = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i += 1) output[i] = raw.charCodeAt(i);
    return output;
  }

  function validKey(key) {
    try {
      const decoded = decodeKey(key);
      return decoded.length === 65 && decoded[0] === 4;
    } catch (_error) {
      return false;
    }
  }

  function post(url, payload) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: headers(),
      body: JSON.stringify(payload || {}),
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (!response.ok || data.success === false) throw new Error(data.message || "push_failed");
        return data;
      });
    });
  }

  function subscribe() {
    if (!("Notification" in window) || !("serviceWorker" in navigator) || !("PushManager" in window)) {
      setStatus("Non supporte", "error");
      return;
    }
    setStatus("Activation...", "");
    fetch(cfg.configUrl, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (response) { return response.json(); })
      .then(function (config) {
        if (!config || !config.publicKey) throw new Error("server_not_configured");
        if (config.validPublicKey === false || !validKey(config.publicKey)) throw new Error("invalid_key");
        return Notification.requestPermission().then(function (permission) {
          if (permission !== "granted") throw new Error("blocked");
          return navigator.serviceWorker.ready.then(function (registration) {
            return registration.pushManager.getSubscription().then(function (existing) {
              if (existing) return existing;
              return registration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: decodeKey(config.publicKey),
              });
            });
          });
        });
      })
      .then(function (subscription) {
        return post(cfg.subscribeUrl, {
          subscription: subscription.toJSON ? subscription.toJSON() : subscription,
          send_test: true,
        });
      })
      .then(function (result) {
        if (result.configured === false) {
          setStatus("Serveur a configurer", "error");
          return;
        }
        setStatus("Alertes actives", "active");
      })
      .catch(function (error) {
        const code = String(error && error.message || "");
        if (code === "invalid_key") setStatus("Cle push invalide", "error");
        else if (code === "blocked") setStatus("Bloquees", "error");
        else setStatus("A verifier", "error");
      });
  }

  function refreshStatus() {
    if (!cfg.statusUrl) return;
    fetch(cfg.statusUrl, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (response) { return response.json(); })
      .then(function (data) {
        if (!data || data.configured === false) {
          setStatus("Alertes", "");
          return;
        }
        if (Number(data.activeSubscriptions || 0) > 0) setStatus("Alertes actives", "active");
      })
      .catch(function () {});
  }

  button.addEventListener("click", subscribe);
  refreshStatus();
})();
