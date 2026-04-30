const SW_URL = new URL(self.location.href);
const SW_ASSET_VERSION = SW_URL.searchParams.get("v") || "dev";
const CACHE_VERSION = `dealnova-${SW_ASSET_VERSION}`;
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const PAGES_CACHE = `${CACHE_VERSION}-pages`;
const IMAGES_CACHE = `${CACHE_VERSION}-images`;
const OFFLINE_PATH = "/static/offline.html";
const OFFLINE_URL = `${OFFLINE_PATH}?v=${encodeURIComponent(SW_ASSET_VERSION)}`;
const PAGE_CACHE_MAX_ENTRIES = 24;
const IMAGE_CACHE_MAX_ENTRIES = 60;
const UPLOAD_IMAGE_EXT_RE = /\.(?:avif|gif|jpe?g|png|svg|webp)$/i;
const SW_DEBUG =
  SW_URL.searchParams.get("debug") === "1" ||
  SW_URL.hostname === "localhost" ||
  SW_URL.hostname === "127.0.0.1";

const PRECACHE_ASSETS = [
  OFFLINE_URL,
  "/static/manifest.json",
  "/static/logo.png",
  "/static/js/live.js",
  "/static/js/i18n.js",
  "/static/js/ajax_pagination.js",
  "/static/js/ui_drawer.js",
  "/static/js/ui_shell.js",
  "/static/js/home_shell.js",
  "/static/js/ui_home_tabs.js",
  "/static/js/core/core_ui.js",
  "/static/js/core/core_dom.js",
  "/static/js/ajax/core/bm_fetch.js",
  "/static/js/ajax/core/bm_guard.js",
  "/static/js/ajax/core/bm_csrf.js",
  "/static/js/support_issue_fab.js",
  "/static/css/ui_drawer_glass.css",
  "/static/css/ui_shell.css",
  "/static/css/home_shell.css",
  "/static/css/ui_home_tabs.css",
  "/static/css/support_issue_fab.css",
  "/static/css/ui_drawer.css",
  "/static/css/offline.css",
  "/static/js/offline_page.js",
];

const CRITICAL_STATIC_ASSETS = new Set([
  OFFLINE_PATH,
  "/static/js/ui_drawer.js",
  "/static/css/ui_drawer.css",
  "/static/css/ui_drawer_glass.css",
  "/static/js/ui_shell.js",
  "/static/css/ui_shell.css",
  "/static/js/home_shell.js",
  "/static/css/home_shell.css",
  "/static/js/ajax_pagination.js",
  "/static/js/i18n.js",
  "/static/js/offline_page.js",
  "/static/css/offline.css",
]);

const NETWORK_ONLY_PREFIXES = [
  "/admin",
  "/api",
  "/vendor",
  "/cart",
  "/delivery",
  "/login",
  "/logout",
  "/register",
  "/lang",
  "/booking",
];

const ROOT_PUBLIC_SHOP_RESERVED = new Set([
  "admin",
  "admin-access",
  "api",
  "booking",
  "cart",
  "delivery",
  "health",
  "lang",
  "location",
  "locations",
  "login",
  "logout",
  "maintenance",
  "register",
  "search",
  "shop",
  "shops",
  "signin",
  "signup",
  "sitemap.xml",
  "sw.js",
  "vendor",
]);

function debugLog() {
  if (!SW_DEBUG) return;
  console.info("[BM-SW]", ...arguments);
}

function debugWarn() {
  if (!SW_DEBUG) return;
  console.warn("[BM-SW]", ...arguments);
}

function buildPrecacheAssets() {
  const assets = new Set(PRECACHE_ASSETS);
  const version = encodeURIComponent(SW_ASSET_VERSION);
  for (const asset of PRECACHE_ASSETS) {
    if (asset.startsWith("/static/js/") || asset.startsWith("/static/css/")) {
      assets.add(`${asset}?v=${version}`);
    }
  }
  return Array.from(assets);
}

function isSameOrigin(url) {
  return url.origin === self.location.origin;
}

function isStaticAsset(pathname) {
  return pathname.startsWith("/static/") || pathname === "/favicon.ico" || pathname === "/manifest.json";
}

function isUploadImage(pathname) {
  return pathname.startsWith("/static/uploads/") && UPLOAD_IMAGE_EXT_RE.test(pathname);
}

function isCriticalStaticAsset(pathname) {
  return CRITICAL_STATIC_ASSETS.has(pathname);
}

function isNetworkOnlyPath(pathname) {
  return NETWORK_ONLY_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(prefix + "/"));
}

function getPathSegments(pathname) {
  return String(pathname || "")
    .split("/")
    .filter(Boolean);
}

function isRootPublicShopPath(pathname) {
  const segments = getPathSegments(pathname);
  if (segments.length !== 1) return false;
  const slug = String(segments[0] || "").trim().toLowerCase();
  if (!slug || slug.includes(".")) return false;
  return !ROOT_PUBLIC_SHOP_RESERVED.has(slug);
}

function canonicalReadonlyPath(pathname) {
  const rawPath = String(pathname || "");
  if (rawPath === "/shop") {
    return rawPath;
  }
  if (rawPath.startsWith("/shop/")) {
    const tail = rawPath.slice("/shop/".length).replace(/^\/+|\/+$/g, "");
    if (tail && !tail.includes("/") && !tail.includes(".")) {
      return `/${tail}`;
    }
  }
  return rawPath;
}

function isReadonlyPath(pathname) {
  const canonicalPath = canonicalReadonlyPath(pathname);
  if (canonicalPath === "/") return true;
  if (canonicalPath === "/shop") return true;
  if (canonicalPath === "/shops" || canonicalPath.startsWith("/shops/")) return true;
  if (canonicalPath === "/locations" || canonicalPath.startsWith("/locations/")) return true;
  if (canonicalPath === "/location" || canonicalPath.startsWith("/location/")) return true;
  if (canonicalPath === "/search" || canonicalPath.startsWith("/search/")) return true;
  if (canonicalPath === "/product" || canonicalPath.startsWith("/product/")) return true;
  return isRootPublicShopPath(canonicalPath);
}

function isCacheableStaticResponse(response) {
  if (!response) return false;
  if (response.status !== 200) return false;
  if (response.redirected) return false;
  if (response.type !== "basic") return false;
  return true;
}

function isCacheablePageResponse(response) {
  if (!response) return false;
  if (response.status !== 200) return false;
  if (response.type !== "basic") return false;
  return true;
}

function isHtmlRequest(req) {
  if (req.mode === "navigate") return true;
  const accept = req.headers.get("Accept") || "";
  return accept.includes("text/html");
}

function resolvePageUrl(input) {
  if (input instanceof URL) return input;
  if (input && input.url) return new URL(input.url, self.location.origin);
  return new URL(String(input || "/"), self.location.origin);
}

function buildPageCacheKey(input) {
  const url = resolvePageUrl(input);
  const normalized = new URL(self.location.origin);
  normalized.pathname = canonicalReadonlyPath(url.pathname);
  normalized.search = "";
  normalized.hash = "";
  return normalized.toString();
}

function shouldCachePageUrl(input) {
  const url = resolvePageUrl(input);
  const pathname = canonicalReadonlyPath(url.pathname);
  const hasSearch = Array.from(url.searchParams.keys()).length > 0;

  if (pathname === "/") {
    return !hasSearch;
  }

  if (
    pathname === "/shop" ||
    pathname.startsWith("/shop/") ||
    pathname === "/shops" ||
    pathname.startsWith("/shops/") ||
    pathname === "/locations" ||
    pathname.startsWith("/locations/") ||
    pathname === "/search" ||
    pathname.startsWith("/search/")
  ) {
    return true;
  }

  if (pathname.startsWith("/product/")) {
    return !hasSearch;
  }

  if (pathname.startsWith("/location/")) {
    return !hasSearch;
  }

  if (isRootPublicShopPath(pathname)) {
    return !hasSearch;
  }

  return false;
}

function isPublicPageResponse(response) {
  if (!isCacheablePageResponse(response)) return false;
  const cacheScope = String(response.headers.get("X-BM-PWA-Session-Scope") || "").toLowerCase();
  const cacheMode = String(response.headers.get("X-BM-PWA-Cache") || "").toLowerCase();
  return cacheScope === "anon" && cacheMode === "public";
}

async function trimPageCache(cache, maxEntries) {
  const keys = await cache.keys();
  if (keys.length <= maxEntries) return;
  const overflow = keys.length - maxEntries;
  await Promise.all(keys.slice(0, overflow).map((key) => cache.delete(key)));
}

async function trimImageCache(cache, maxEntries) {
  const keys = await cache.keys();
  if (keys.length <= maxEntries) return;
  const overflow = keys.length - maxEntries;
  await Promise.all(keys.slice(0, overflow).map((key) => cache.delete(key)));
}

async function putInCache(cacheName, req, response) {
  if (!isCacheableStaticResponse(response)) return;
  const cache = await caches.open(cacheName);
  await cache.put(req, response);
}

async function putPublicPageInCache(req, response) {
  const responseUrl = resolvePageUrl(response && response.url ? response.url : req);
  if (!isSameOrigin(responseUrl)) return;
  if (!shouldCachePageUrl(responseUrl)) {
    return;
  }
  if (!isPublicPageResponse(response)) {
    await deletePublicPageCacheEntry(responseUrl);
    return;
  }

  const cache = await caches.open(PAGES_CACHE);
  await cache.put(buildPageCacheKey(responseUrl), response);
  await trimPageCache(cache, PAGE_CACHE_MAX_ENTRIES);
}

async function matchPublicPageCache(input) {
  const cache = await caches.open(PAGES_CACHE);
  return cache.match(buildPageCacheKey(input));
}

async function deletePublicPageCacheEntry(input) {
  const cache = await caches.open(PAGES_CACHE);
  await cache.delete(buildPageCacheKey(input));
}

async function clearPublicPageCaches() {
  const keys = await caches.keys();
  await Promise.all(
    keys
      .filter((key) => key.startsWith("dealnova-") && key.endsWith("-pages"))
      .map((key) => caches.delete(key))
  );
}

function buildEmergencyOfflineHtml() {
  return `<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Service temporairement indisponible</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; }
    body {
      min-height: 100vh;
      min-height: 100dvh;
      display: grid;
      place-items: center;
      padding: 20px;
      font-family: "Segoe UI", Arial, sans-serif;
      background:
        radial-gradient(circle at top, rgba(16, 185, 129, 0.16), transparent 36%),
        linear-gradient(180deg, #f8fffc 0%, #eef6ff 100%);
      color: #0f172a;
    }
    .offline-fallback-shell {
      width: 100%;
      display: grid;
      place-items: center;
    }
    .offline-fallback-card {
      width: min(100%, 440px);
      background: rgba(255, 255, 255, 0.98);
      border: 1px solid rgba(15, 23, 42, 0.08);
      border-radius: 26px;
      box-shadow: 0 24px 54px rgba(15, 23, 42, 0.12);
      padding: 22px;
    }
    .offline-fallback-chip,
    .offline-fallback-support-chip {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 32px;
      padding: 0.35rem 0.78rem;
      border-radius: 999px;
      background: rgba(16, 185, 129, 0.12);
      color: #0b7f59;
      font-size: 0.76rem;
      font-weight: 900;
      letter-spacing: 0.03em;
      text-transform: uppercase;
    }
    h1,
    .offline-fallback-support-card h2 {
      margin: 0.85rem 0 0.35rem;
      font-size: clamp(1.6rem, 5vw, 2rem);
      line-height: 1.05;
    }
    .offline-fallback-copy,
    .offline-fallback-support-copy {
      margin: 0;
      color: #475569;
      font-size: 0.98rem;
      line-height: 1.6;
    }
    .offline-fallback-points {
      display: grid;
      gap: 0.68rem;
      margin: 1.15rem 0 1.05rem;
    }
    .offline-fallback-point {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      padding: 0.85rem 0.95rem;
      border-radius: 18px;
      background: #f8fafc;
      border: 1px solid rgba(148, 163, 184, 0.18);
      font-weight: 700;
      color: #0f172a;
    }
    .offline-fallback-point-icon {
      width: 28px;
      height: 28px;
      border-radius: 10px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 0.8rem;
      font-weight: 900;
      flex-shrink: 0;
    }
    .offline-fallback-point.ok .offline-fallback-point-icon {
      background: rgba(16, 185, 129, 0.14);
      color: #0b7f59;
    }
    .offline-fallback-point.no .offline-fallback-point-icon {
      background: rgba(239, 68, 68, 0.12);
      color: #b91c1c;
    }
    .offline-fallback-btn,
    .offline-fallback-btn-secondary {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 100%;
      min-height: 50px;
      border-radius: 18px;
      font: inherit;
      font-size: 1rem;
      font-weight: 900;
      cursor: pointer;
    }
    .offline-fallback-btn {
      margin-top: 1rem;
      border: none;
      background: linear-gradient(135deg, #25d366, #128c7e);
      color: #fff;
      box-shadow: 0 16px 28px rgba(18, 140, 126, 0.22);
    }
    .offline-fallback-btn-secondary {
      border: 1px solid rgba(15, 23, 42, 0.1);
      background: #fff;
      color: #0f172a;
    }
    .offline-fallback-note {
      margin: 0.95rem 0 0;
      color: #64748b;
      font-size: 0.88rem;
      line-height: 1.5;
    }
    .offline-fallback-support {
      position: fixed;
      right: 1rem;
      bottom: 1rem;
      z-index: 12;
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
      min-height: 46px;
      padding: 0.75rem 0.92rem;
      border: 1px solid rgba(15, 23, 42, 0.08);
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.97);
      color: #0f172a;
      box-shadow: 0 18px 34px rgba(15, 23, 42, 0.16);
      font: inherit;
      font-size: 0.88rem;
      font-weight: 900;
      cursor: pointer;
    }
    .offline-fallback-support-icon {
      width: 24px;
      height: 24px;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: rgba(16, 185, 129, 0.12);
      color: #0b7f59;
      font-size: 0.82rem;
      font-weight: 900;
      flex-shrink: 0;
    }
    .offline-fallback-backdrop {
      position: fixed;
      inset: 0;
      z-index: 13;
      background: rgba(15, 23, 42, 0.42);
      backdrop-filter: blur(6px);
      -webkit-backdrop-filter: blur(6px);
    }
    .offline-fallback-dialog {
      position: fixed;
      inset: 0;
      z-index: 14;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 1rem;
    }
    .offline-fallback-backdrop[hidden],
    .offline-fallback-dialog[hidden] {
      display: none !important;
    }
    .offline-fallback-support-card {
      width: min(100%, 420px);
      max-height: calc(100dvh - 2rem);
      overflow-y: auto;
      border-radius: 24px;
      border: 1px solid rgba(15, 23, 42, 0.08);
      background: rgba(255, 255, 255, 0.99);
      box-shadow: 0 30px 60px rgba(15, 23, 42, 0.2);
      padding: 1rem;
    }
    .offline-fallback-support-top {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 0.75rem;
    }
    .offline-fallback-close {
      width: 38px;
      height: 38px;
      border: 1px solid rgba(15, 23, 42, 0.08);
      border-radius: 12px;
      background: #fff;
      color: #334155;
      font: inherit;
      font-weight: 900;
      cursor: pointer;
    }
    .offline-fallback-form {
      display: grid;
      gap: 0.8rem;
      margin-top: 1rem;
    }
    .offline-fallback-field {
      display: grid;
      gap: 0.36rem;
    }
    .offline-fallback-field label {
      font-size: 0.82rem;
      font-weight: 800;
    }
    .offline-fallback-field input,
    .offline-fallback-field textarea,
    .offline-fallback-field select {
      width: 100%;
      border: 1px solid rgba(148, 163, 184, 0.3);
      border-radius: 16px;
      background: #fff;
      color: #0f172a;
      font: inherit;
      font-size: 16px;
      padding: 0.88rem 0.95rem;
    }
    .offline-fallback-field textarea {
      min-height: 104px;
      resize: vertical;
    }
    .offline-fallback-actions {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0.75rem;
    }
    @media (max-width: 767.98px) {
      body {
        padding: 12px;
      }
      .offline-fallback-card {
        padding: 20px;
      }
      .offline-fallback-support {
        right: 0.82rem;
        bottom: calc(0.88rem + env(safe-area-inset-bottom, 0px));
        font-size: 0.82rem;
      }
      .offline-fallback-dialog {
        padding:
          max(0.9rem, env(safe-area-inset-top, 0px))
          0.9rem
          max(0.9rem, env(safe-area-inset-bottom, 0px));
      }
      .offline-fallback-support-card {
        max-height: calc(100dvh - 1.8rem - env(safe-area-inset-top, 0px) - env(safe-area-inset-bottom, 0px));
        border-radius: 22px;
        padding: 0.95rem;
      }
    }
  </style>
</head>
<body>
  <main class="offline-fallback-shell">
    <section class="offline-fallback-card" aria-labelledby="offlineFallbackTitle">
      <div class="offline-fallback-chip">Indisponible</div>
      <h1 id="offlineFallbackTitle">Service temporairement indisponible</h1>
      <p class="offline-fallback-copy">Votre connexion est peut-&ecirc;tre coup&eacute;e, ou le service est momentan&eacute;ment indisponible. Les pages d&eacute;j&agrave; ouvertes restent accessibles.</p>
      <div class="offline-fallback-points" role="list" aria-label="Ce qui reste disponible">
        <div class="offline-fallback-point ok" role="listitem">
          <span class="offline-fallback-point-icon">OK</span>
          <span>Pages d&eacute;j&agrave; ouvertes</span>
        </div>
        <div class="offline-fallback-point no" role="listitem">
          <span class="offline-fallback-point-icon">!</span>
          <span>Commande, paiement et mises &agrave; jour indisponibles</span>
        </div>
      </div>
      <button class="offline-fallback-btn" id="offlineFallbackRetry" type="button">R&eacute;essayer</button>
      <p class="offline-fallback-note">Si un souci persiste, vous pouvez pr&eacute;parer un message pour le support.</p>
    </section>
  </main>
  <button type="button" class="offline-fallback-support" id="offlineFallbackSupportOpen" aria-label="Signaler un probl&egrave;me">
    <span class="offline-fallback-support-icon">!</span>
    <span>Signaler</span>
  </button>
  <div class="offline-fallback-backdrop" id="offlineFallbackBackdrop" hidden></div>
  <div class="offline-fallback-dialog" id="offlineFallbackDialog" hidden>
    <div class="offline-fallback-support-card" role="dialog" aria-modal="true" aria-labelledby="offlineFallbackSupportTitle">
      <div class="offline-fallback-support-top">
        <div>
          <div class="offline-fallback-support-chip">Support</div>
          <h2 id="offlineFallbackSupportTitle">Signaler un probl&egrave;me</h2>
          <p class="offline-fallback-support-copy">Expliquez simplement le souci. Le message WhatsApp sera pr&eacute;par&eacute; juste apr&egrave;s.</p>
        </div>
        <button type="button" class="offline-fallback-close" id="offlineFallbackClose" aria-label="Fermer">x</button>
      </div>
      <form class="offline-fallback-form" id="offlineFallbackForm">
        <div class="offline-fallback-field">
          <label for="offlineFallbackType">Sujet</label>
          <select id="offlineFallbackType" name="issue_type">
            <option value="Connexion">Connexion</option>
            <option value="Page hors ligne">Page hors ligne</option>
            <option value="Commande">Commande</option>
            <option value="Paiement">Paiement</option>
            <option value="Autre">Autre</option>
          </select>
        </div>
        <div class="offline-fallback-field">
          <label for="offlineFallbackDetails">Ce qui ne va pas</label>
          <textarea id="offlineFallbackDetails" name="details" placeholder="Ex: la page reste bloqu&eacute;e hors ligne, un bouton ne r&eacute;pond pas."></textarea>
        </div>
        <div class="offline-fallback-field">
          <label for="offlineFallbackExpected">Ce que vous vouliez faire</label>
          <input id="offlineFallbackExpected" name="expected" type="text" placeholder="Ex: rouvrir l'accueil, finaliser ma commande.">
        </div>
        <div class="offline-fallback-actions">
          <button type="button" class="offline-fallback-btn-secondary" id="offlineFallbackCloseAlt">Fermer</button>
          <button type="submit" class="offline-fallback-btn">Continuer</button>
        </div>
      </form>
    </div>
  </div>
  <script>
    (function () {
      var retryBtn = document.getElementById("offlineFallbackRetry");
      var supportOpen = document.getElementById("offlineFallbackSupportOpen");
      var backdrop = document.getElementById("offlineFallbackBackdrop");
      var dialog = document.getElementById("offlineFallbackDialog");
      var closeBtn = document.getElementById("offlineFallbackClose");
      var closeAltBtn = document.getElementById("offlineFallbackCloseAlt");
      var form = document.getElementById("offlineFallbackForm");
      var supportNumber = "212770010264";
      function openDialog() {
        backdrop.hidden = false;
        dialog.hidden = false;
        document.body.style.overflow = "hidden";
      }
      function closeDialog() {
        backdrop.hidden = true;
        dialog.hidden = true;
        document.body.style.overflow = "";
      }
      function bullet(value) {
        var cleaned = String(value || "").replace(/\\s+/g, " ").trim();
        return cleaned ? "- " + cleaned : "- ";
      }
      function openWhatsAppMessage(message) {
        var encoded = encodeURIComponent(message);
        var appUrl = "whatsapp://send?phone=" + supportNumber + "&text=" + encoded;
        var webUrl = "https://wa.me/" + supportNumber + "?text=" + encoded;
        try {
          window.location.href = appUrl;
        } catch (error) {}
        window.setTimeout(function () {
          if (!document.hidden) {
            window.location.href = webUrl;
          }
        }, 700);
      }
      if (retryBtn) {
        retryBtn.addEventListener("click", function () {
          window.location.reload();
        });
      }
      if (supportOpen) {
        supportOpen.addEventListener("click", openDialog);
      }
      if (closeBtn) {
        closeBtn.addEventListener("click", closeDialog);
      }
      if (closeAltBtn) {
        closeAltBtn.addEventListener("click", closeDialog);
      }
      if (backdrop) {
        backdrop.addEventListener("click", closeDialog);
      }
      document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && dialog && !dialog.hidden) {
          closeDialog();
        }
      });
      if (form) {
        form.addEventListener("submit", function (event) {
          event.preventDefault();
          var data = new FormData(form);
          var issueType = String(data.get("issue_type") || "Autre").trim();
          var details = String(data.get("details") || "").trim();
          var expected = String(data.get("expected") || "").trim();
          var message = [
            "Bonjour, je signale un probleme sur l'ecran indisponible.",
            "Page: fallback service worker",
            "Type: " + issueType,
            "",
            "Probleme constate:",
            bullet(details),
            "",
            "Resultat attendu:",
            bullet(expected)
          ].join("\\n");
          closeDialog();
          openWhatsAppMessage(message);
        });
      }
    })();
  </script>
</body>
</html>`;
}

async function getOfflineFallback(reason, pathname) {
  debugWarn("Offline fallback", { reason, pathname: pathname || "" });

  const cache = await caches.open(STATIC_CACHE);
  const cachedVersioned = await cache.match(OFFLINE_URL);
  if (cachedVersioned) return cachedVersioned;

  const cachedLegacy = await cache.match(OFFLINE_PATH, { ignoreSearch: true });
  if (cachedLegacy) return cachedLegacy;

  try {
    return await fetch(OFFLINE_URL, { cache: "no-store" });
  } catch (_) {
    try {
      return await fetch(OFFLINE_PATH, { cache: "no-store" });
    } catch (_) {
      return new Response(buildEmergencyOfflineHtml(), {
        status: 503,
        headers: {
          "Content-Type": "text/html; charset=utf-8",
          "Cache-Control": "no-store",
        },
      });
      return new Response(
        `<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Service temporairement indisponible</title>
  <style>
    html, body { margin: 0; min-height: 100%; }
    body {
      display: grid;
      place-items: center;
      padding: 24px;
      font-family: "Segoe UI", Arial, sans-serif;
      background: linear-gradient(180deg, #f8fffc 0%, #eef6ff 100%);
      color: #0f172a;
    }
    .offline-fallback-card {
      width: min(100%, 440px);
      background: rgba(255, 255, 255, 0.98);
      border: 1px solid rgba(15, 23, 42, 0.08);
      border-radius: 24px;
      box-shadow: 0 24px 54px rgba(15, 23, 42, 0.12);
      padding: 24px;
    }
    .offline-fallback-chip {
      display: inline-flex;
      align-items: center;
      min-height: 32px;
      padding: 0.35rem 0.78rem;
      border-radius: 999px;
      background: rgba(16, 185, 129, 0.12);
      color: #0b7f59;
      font-size: 0.76rem;
      font-weight: 900;
      letter-spacing: 0.03em;
      text-transform: uppercase;
    }
    h1 {
      margin: 0.85rem 0 0.35rem;
      font-size: clamp(1.6rem, 5vw, 2rem);
      line-height: 1.05;
    }
    p {
      margin: 0;
      color: #475569;
      font-size: 0.98rem;
      line-height: 1.6;
    }
    .offline-fallback-btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 100%;
      min-height: 50px;
      margin-top: 1rem;
      border: none;
      border-radius: 18px;
      background: linear-gradient(135deg, #25d366, #128c7e);
      color: #fff;
      font: inherit;
      font-size: 1rem;
      font-weight: 900;
      cursor: pointer;
    }
  </style>
</head>
<body>
  <main class="offline-fallback-card">
    <div class="offline-fallback-chip">Indisponible</div>
    <h1>Service temporairement indisponible</h1>
    <p>Votre connexion est peut-être coupée, ou le service est momentanément indisponible. Les pages déjà ouvertes restent accessibles.</p>
    <button class="offline-fallback-btn" type="button" onclick="window.location.reload()">Réessayer</button>
  </main>
</body>
</html>`,
        {
          status: 503,
          headers: {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "no-store",
          },
        }
      );
    }
  }
}

async function handleStaticAsset(req) {
  const cache = await caches.open(STATIC_CACHE);
  const cached = await cache.match(req);
  if (cached) {
    fetch(req, { cache: "no-store" })
      .then((response) => putInCache(STATIC_CACHE, req, response.clone()))
      .catch((error) => {
        debugWarn("Static refresh failed", { url: req.url, error: String(error && error.message || error) });
      });
    return cached;
  }

  try {
    const response = await fetch(req, { cache: "no-store" });
    await putInCache(STATIC_CACHE, req, response.clone());
    return response;
  } catch (err) {
    const fallbackCached = await cache.match(req, { ignoreSearch: true });
    if (fallbackCached) return fallbackCached;
    if (isHtmlRequest(req)) {
      return getOfflineFallback("static", new URL(req.url).pathname);
    }
    throw err;
  }
}

async function handleCriticalStaticAsset(req) {
  const cache = await caches.open(STATIC_CACHE);
  try {
    const response = await fetch(req, { cache: "no-store" });
    await putInCache(STATIC_CACHE, req, response.clone());
    return response;
  } catch (err) {
    const cached = await cache.match(req);
    if (cached) return cached;
    const fallbackCached = await cache.match(req, { ignoreSearch: true });
    if (fallbackCached) return fallbackCached;
    if (isHtmlRequest(req)) {
      return getOfflineFallback("critical-static", new URL(req.url).pathname);
    }
    throw err;
  }
}

async function handleUploadImage(req) {
  const cache = await caches.open(IMAGES_CACHE);
  const cached = await cache.match(req);
  if (cached) {
    return cached;
  }

  try {
    const response = await fetch(req, { cache: "no-store" });
    if (isCacheableStaticResponse(response)) {
      await cache.put(req, response.clone());
      await trimImageCache(cache, IMAGE_CACHE_MAX_ENTRIES);
    }
    return response;
  } catch (err) {
    const fallbackCached = await cache.match(req, { ignoreSearch: true });
    if (fallbackCached) return fallbackCached;
    throw err;
  }
}

async function handleReadonlyPage(req) {
  const requestUrl = new URL(req.url);
  const requestIsCacheable = shouldCachePageUrl(requestUrl);

  const fetchPromise = fetch(req, { cache: "no-store" });
  const raceResult = await Promise.race([
    fetchPromise.then((response) => ({ response })),
    new Promise((resolve) => {
      setTimeout(() => resolve({ timeout: true }), 3000);
    }),
  ]).catch((error) => ({ error }));

  try {
    if (raceResult && raceResult.response) {
      const isMaintenanceResponse = raceResult.response.headers.get("X-BM-Maintenance") === "1";
      if ([502, 503, 504].includes(raceResult.response.status) && !isMaintenanceResponse) {
        return getOfflineFallback("public-page-upstream", requestUrl.pathname);
      }
      if (requestIsCacheable) {
        putPublicPageInCache(req, raceResult.response.clone()).catch((error) => {
          debugWarn("Failed to update public page cache", error);
        });
      }
      return raceResult.response;
    }

    if (raceResult && raceResult.timeout) {
      if (requestIsCacheable) {
        const cached = await matchPublicPageCache(requestUrl);
        if (cached) {
          fetchPromise
            .then((response) => putPublicPageInCache(req, response.clone()))
            .catch(() => {});
          debugWarn("Serving cached public page after timeout", {
            pathname: canonicalReadonlyPath(requestUrl.pathname),
          });
          return cached;
        }
      }

      const response = await fetchPromise;
      if (requestIsCacheable) {
        putPublicPageInCache(req, response.clone()).catch((error) => {
          debugWarn("Failed to update public page cache", error);
        });
      }
      return response;
    }

    throw raceResult && raceResult.error ? raceResult.error : new Error("public_page_fetch_failed");
  } catch (err) {
    if (requestIsCacheable) {
      const cached = await matchPublicPageCache(requestUrl);
      if (cached) {
        debugWarn("Serving cached public page", { pathname: canonicalReadonlyPath(requestUrl.pathname) });
        return cached;
      }
    }
    return getOfflineFallback("public-page", requestUrl.pathname);
  }
}

async function handleNetworkOnly(req) {
  try {
    return await fetch(req, { cache: "no-store" });
  } catch (err) {
    if (isHtmlRequest(req)) {
      return getOfflineFallback("network-only", new URL(req.url).pathname);
    }
    return new Response(JSON.stringify({ ok: false, offline: true }), {
      status: 503,
      headers: { "Content-Type": "application/json" },
    });
  }
}

self.addEventListener("message", (event) => {
  const data = event && event.data ? event.data : null;
  if (!data || typeof data !== "object") return;

  if (data.type === "BM_CLEAR_PUBLIC_PAGE_CACHE") {
    event.waitUntil(
      clearPublicPageCaches().catch((error) => {
        debugWarn("Failed to clear public page caches", error);
      })
    );
    return;
  }

  if (data.type === "BM_SKIP_WAITING") {
    self.skipWaiting();
  }
});

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      try {
        const cache = await caches.open(STATIC_CACHE);
        await Promise.all(
          buildPrecacheAssets().map(async (asset) => {
            try {
              const response = await fetch(asset, { cache: "reload" });
              if (isCacheableStaticResponse(response)) {
                await cache.put(asset, response);
              }
            } catch (error) {
              debugWarn("Precache asset skipped", { asset, error: String(error && error.message || error) });
            }
          })
        );
        debugLog("Install complete", { version: SW_ASSET_VERSION });
        self.skipWaiting();
      } catch (error) {
        debugWarn("Install failed", error);
        throw error;
      }
    })()
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      try {
        const keys = await caches.keys();
        await Promise.all(
          keys
            .filter((key) => key !== STATIC_CACHE && key !== PAGES_CACHE && key !== IMAGES_CACHE)
            .map((key) => caches.delete(key))
        );
        await self.clients.claim();
        debugLog("Activate complete", { version: SW_ASSET_VERSION });
      } catch (error) {
        debugWarn("Activate failed", error);
        throw error;
      }
    })()
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  if (!isSameOrigin(url)) return;

  if (isNetworkOnlyPath(url.pathname) || url.pathname === "/sw.js") {
    event.respondWith(handleNetworkOnly(req));
    return;
  }

  if (isUploadImage(url.pathname)) {
    event.respondWith(handleUploadImage(req));
    return;
  }

  if (isStaticAsset(url.pathname)) {
    if (isCriticalStaticAsset(url.pathname)) {
      event.respondWith(handleCriticalStaticAsset(req));
      return;
    }
    event.respondWith(handleStaticAsset(req));
    return;
  }

  if (isReadonlyPath(url.pathname)) {
    event.respondWith(handleReadonlyPage(req));
    return;
  }

  event.respondWith(handleNetworkOnly(req));
});

self.addEventListener("error", (event) => {
  const error = event && event.error ? event.error : event;
  debugWarn("Unhandled service worker error", error);
});

self.addEventListener("unhandledrejection", (event) => {
  debugWarn("Unhandled service worker rejection", event && event.reason);
});
