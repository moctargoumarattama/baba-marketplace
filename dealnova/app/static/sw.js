const SW_URL = new URL(self.location.href);
const SW_ASSET_VERSION = SW_URL.searchParams.get("v") || "dev";
const CACHE_VERSION = `dealnova-${SW_ASSET_VERSION}`;
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const PAGES_CACHE = `${CACHE_VERSION}-pages`;
const OFFLINE_PATH = "/static/offline.html";
const OFFLINE_URL = `${OFFLINE_PATH}?v=${encodeURIComponent(SW_ASSET_VERSION)}`;
const PAGE_CACHE_MAX_ENTRIES = 24;
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
  "/static/css/ui_drawer_glass.css",
  "/static/css/ui_shell.css",
  "/static/css/home_shell.css",
  "/static/css/ui_home_tabs.css",
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

  if (pathname === "/" || pathname === "/shop" || pathname === "/shops" || pathname === "/locations" || pathname === "/search") {
    return !hasSearch;
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
    return fetch(OFFLINE_PATH, { cache: "no-store" });
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

async function handleReadonlyPage(req) {
  const requestUrl = new URL(req.url);
  const requestIsCacheable = shouldCachePageUrl(requestUrl);

  try {
    const response = await fetch(req, { cache: "no-store" });
    if (requestIsCacheable) {
      await putPublicPageInCache(req, response.clone());
    }
    return response;
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
            .filter((key) => key !== STATIC_CACHE && key !== PAGES_CACHE)
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
