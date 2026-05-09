(function () {
  "use strict";

  if (typeof window === "undefined" || typeof document === "undefined") return;
  if (window.__BM_CLIENT_WELCOME_NOTIFICATION__) return;
  window.__BM_CLIENT_WELCOME_NOTIFICATION__ = true;

  const body = document.body;
  const role = String((body && body.dataset && body.dataset.userRole) || "guest").toLowerCase();
  if (["vendor", "admin", "manager"].indexOf(role) !== -1) return;

  const title = "Bienvenue sur Baba Market";
  const message = "Produits, services et locations pres de vous.";
  let shown = false;
  let permissionRequested = false;

  function vibrateWelcome() {
    if (!navigator.vibrate) return;
    try {
      navigator.vibrate([120, 60, 120]);
    } catch (_error) {}
  }

  function showNativeWelcomeNotification() {
    if (shown || !("Notification" in window) || Notification.permission !== "granted") return;
    shown = true;
    vibrateWelcome();
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.ready
        .then(function (registration) {
          if (!registration || !registration.showNotification) return;
          return registration.showNotification(title, {
            body: message,
            icon: "/static/android-chrome-192x192.png",
            badge: "/static/favicon-32x32.png",
            tag: "client-welcome-baba-market",
            renotify: true,
            requireInteraction: false,
            vibrate: [120, 60, 120],
            data: {
              url: "/",
              type: "client_welcome",
            },
          });
        })
        .catch(function () {});
      return;
    }
    try {
      new Notification(title, {
        body: message,
        icon: "/static/android-chrome-192x192.png",
        tag: "client-welcome-baba-market",
      });
    } catch (_error) {}
  }

  function requestWelcomePermission() {
    if (permissionRequested || !("Notification" in window)) return;
    permissionRequested = true;
    if (Notification.permission === "granted") {
      showNativeWelcomeNotification();
      return;
    }
    if (Notification.permission === "denied") return;
    try {
      Notification.requestPermission().then(function (permission) {
        if (permission === "granted") showNativeWelcomeNotification();
      }).catch(function () {});
    } catch (_error) {}
  }

  function scheduleWelcome() {
    if (!("Notification" in window)) return;
    if (Notification.permission === "granted") {
      window.setTimeout(showNativeWelcomeNotification, 700);
      return;
    }
    ["pointerdown", "touchstart", "keydown"].forEach(function (eventName) {
      window.addEventListener(eventName, requestWelcomePermission, { once: true, passive: true });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", scheduleWelcome, { once: true });
  } else {
    scheduleWelcome();
  }
})();
