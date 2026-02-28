const SW_URL = new URL(self.location.href);
const SW_ASSET_VERSION = SW_URL.searchParams.get("v") || "dev";
const CACHE_VERSION = `dealnova-${SW_ASSET_VERSION}`;
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const PAGES_CACHE = `${CACHE_VERSION}-pages`;
const OFFLINE_URL = "/static/offline.html";

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
  "/static/css/ui_drawer_glass.css",
  "/static/css/ui_shell.css",
  "/static/css/home_shell.css",
  "/static/css/ui_home_tabs.css",
];

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

const NETWORK_ONLY_PREFIXES = [
  "/admin",
  "/api",
  "/courier",
  "/vendor",
  "/cart",
  "/delivery",
  "/login",
  "/logout",
  "/register",
  "/lang",
  "/booking",
  "/shop/track",
  "/shop/suivi",
];

function isSameOrigin(url) {
  return url.origin === self.location.origin;
}

function isStaticAsset(pathname) {
  return pathname.startsWith("/static/") || pathname === "/favicon.ico" || pathname === "/manifest.json";
}

function isNetworkOnlyPath(pathname) {
  return NETWORK_ONLY_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(prefix + "/"));
}

function isReadonlyPath(pathname) {
  if (pathname === "/") return true;
  if (pathname === "/shop" || pathname.startsWith("/shop/")) return true;
  if (pathname === "/shops" || pathname.startsWith("/shops/")) return true;
  if (pathname === "/locations" || pathname.startsWith("/locations/")) return true;
  if (pathname === "/location" || pathname.startsWith("/location/")) return true;
  if (pathname === "/search" || pathname.startsWith("/search/")) return true;
  if (pathname === "/product" || pathname.startsWith("/product/")) return true;
  return false;
}

function isCacheableResponse(response) {
  if (!response) return false;
  if (response.status !== 200) return false;
  if (response.redirected) return false;
  if (response.type !== "basic") return false;
  return true;
}

function isHtmlRequest(req) {
  if (req.mode === "navigate") return true;
  const accept = req.headers.get("Accept") || "";
  return accept.includes("text/html");
}

async function putInCache(cacheName, req, response) {
  if (!isCacheableResponse(response)) return;
  const cache = await caches.open(cacheName);
  await cache.put(req, response);
}

async function getOfflineFallback() {
  const cache = await caches.open(STATIC_CACHE);
  const cached = await cache.match(OFFLINE_URL, { ignoreSearch: true });
  if (cached) return cached;
  return fetch(OFFLINE_URL, { cache: "no-store" });
}

async function handleStaticAsset(req) {
  const cache = await caches.open(STATIC_CACHE);
  const cached = await cache.match(req);
  if (cached) {
    fetch(req, { cache: "no-store" })
      .then((response) => putInCache(STATIC_CACHE, req, response.clone()))
      .catch(() => {});
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
      return getOfflineFallback();
    }
    throw err;
  }
}

async function handleReadonlyPage(req) {
  try {
    const response = await fetch(req, { cache: "no-store" });
    await putInCache(PAGES_CACHE, req, response.clone());
    return response;
  } catch (err) {
    const cache = await caches.open(PAGES_CACHE);
    const cached = await cache.match(req);
    if (cached) return cached;
    return getOfflineFallback();
  }
}

async function handleNetworkOnly(req) {
  try {
    return await fetch(req, { cache: "no-store" });
  } catch (err) {
    if (isHtmlRequest(req)) {
      return getOfflineFallback();
    }
    return new Response(JSON.stringify({ ok: false, offline: true }), {
      status: 503,
      headers: { "Content-Type": "application/json" },
    });
  }
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(STATIC_CACHE);
      await Promise.all(
        buildPrecacheAssets().map(async (asset) => {
          try {
            const response = await fetch(asset, { cache: "reload" });
            if (isCacheableResponse(response)) {
              await cache.put(asset, response);
            }
          } catch (_) {
            // Keep install resilient if one asset fails.
          }
        })
      );
      await self.skipWaiting();
    })()
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter((key) => key !== STATIC_CACHE && key !== PAGES_CACHE)
          .map((key) => caches.delete(key))
      );
      await self.clients.claim();
    })()
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  if (!isSameOrigin(url)) return;

  // Never cache auth/admin/API/tracking/order actions.
  if (isNetworkOnlyPath(url.pathname) || url.pathname === "/sw.js") {
    event.respondWith(handleNetworkOnly(req));
    return;
  }

  // Cache static assets safely (cache-first with background refresh).
  if (isStaticAsset(url.pathname)) {
    event.respondWith(handleStaticAsset(req));
    return;
  }

  // Public browse-only pages: network-first + cache fallback offline.
  if (isReadonlyPath(url.pathname)) {
    event.respondWith(handleReadonlyPage(req));
    return;
  }

  // Default: network-first, offline fallback only for HTML navigation.
  event.respondWith(handleNetworkOnly(req));
});
