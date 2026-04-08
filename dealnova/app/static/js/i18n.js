(() => {
  const body = document.body;
  if (!body) return;
  if ((window.location.pathname || "").startsWith("/admin")) return;

  const getCookie = (name) => {
    const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
    return match ? decodeURIComponent(match[1]) : "";
  };

  const state = Object.assign(
    {
      lang: "",
      pending: false,
      ready: true,
    },
    window.__BM_I18N_STATE__ || {}
  );
  window.__BM_I18N_STATE__ = state;

  let lang = String(body.dataset.lang || state.lang || "").trim().toLowerCase();
  if (!lang) lang = String(getCookie("lang") || "fr").trim().toLowerCase();
  if (!lang) lang = "fr";
  state.lang = lang;

  const rtlLangs = (body.dataset.rtlLangs || "")
    .split(",")
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean);
  const isRtl = rtlLangs.includes(lang);
  const normalizeKey = (value) => String(value || "").replace(/\s+/g, " ").trim();
  const getLiveRoot = () =>
    document.querySelector("main") ||
    document.getElementById("pageContent") ||
    body;

  const applyLangAttributes = () => {
    document.documentElement.lang = lang;
    document.body.dataset.lang = lang;
    if (isRtl) {
      document.documentElement.dir = "rtl";
      document.body.dir = "rtl";
      return;
    }
    document.documentElement.dir = "ltr";
    document.body.dir = "ltr";
  };

  let readyDispatched = false;
  const markReady = () => {
    if (readyDispatched) return;
    readyDispatched = true;
    state.ready = true;
    state.pending = false;
    document.documentElement.setAttribute("data-bm-i18n", "ready");
    document.dispatchEvent(new CustomEvent("bm:i18n-ready", { detail: { lang } }));
  };

  applyLangAttributes();
  if (lang === "fr") {
    markReady();
    return;
  }

  const bootPayload = window.__BM_I18N_PAYLOAD__;
  const hasServerPayload = !!(
    bootPayload &&
    bootPayload.lang === lang &&
    bootPayload.dict &&
    typeof bootPayload.dict === "object"
  );

  state.pending = false;
  state.ready = true;
  document.documentElement.setAttribute("data-bm-i18n", "ready");

  let dictionary = null;
  let substringKeys = [];
  let busy = false;

  const translateValue = (rawValue) => {
    if (!rawValue || !dictionary) return rawValue;
    const normalized = normalizeKey(rawValue);
    const translated = dictionary[normalized];
    if (!translated) return rawValue;
    const leading = rawValue.match(/^\s*/)?.[0] || "";
    const trailing = rawValue.match(/\s*$/)?.[0] || "";
    return `${leading}${translated}${trailing}`;
  };

  const translateBySubstring = (rawValue) => {
    if (!rawValue || !substringKeys.length || !dictionary) return rawValue;
    let output = rawValue;
    let changed = false;
    substringKeys.forEach((key) => {
      const translated = dictionary[key];
      if (!translated || !output.includes(key)) return;
      output = output.split(key).join(translated);
      changed = true;
    });
    return changed ? output : rawValue;
  };

  const translateAttributes = (scope) => {
    if (!scope || scope.nodeType !== 1) return;
    const attrTargets = ["placeholder", "title", "aria-label"];
    scope.querySelectorAll("*").forEach((element) => {
      if (element.closest("[data-no-i18n]")) return;

      attrTargets.forEach((attr) => {
        if (!element.hasAttribute(attr)) return;
        const current = element.getAttribute(attr);
        const next = translateValue(current);
        if (next !== current) element.setAttribute(attr, next);
      });

      if (element.tagName === "INPUT") {
        const type = (element.getAttribute("type") || "").toLowerCase();
        if (["button", "submit", "reset"].includes(type)) {
          const currentValue = element.getAttribute("value");
          const nextValue = translateValue(currentValue);
          if (nextValue !== currentValue) element.setAttribute("value", nextValue);
        }
      }
    });
  };

  const translateTextNodes = (scope) => {
    if (!scope || scope.nodeType !== 1) return;
    const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const text = node.nodeValue;
        if (!text || !text.trim()) return NodeFilter.FILTER_REJECT;
        const parent = node.parentElement;
        if (!parent) return NodeFilter.FILTER_REJECT;
        if (parent.closest("[data-no-i18n]")) return NodeFilter.FILTER_REJECT;
        const tagName = parent.tagName;
        if (tagName === "SCRIPT" || tagName === "STYLE" || tagName === "NOSCRIPT") {
          return NodeFilter.FILTER_REJECT;
        }
        return NodeFilter.FILTER_ACCEPT;
      },
    });

    let node;
    while ((node = walker.nextNode())) {
      const raw = node.nodeValue;
      let next = translateValue(raw);
      if (next === raw) next = translateBySubstring(raw);
      if (next !== raw) node.nodeValue = next;
    }
  };

  const translateScope = (scopeRoot) => {
    if (!dictionary || busy) return;
    const scope = scopeRoot && scopeRoot.nodeType === 1 ? scopeRoot : body;
    busy = true;
    applyLangAttributes();
    translateAttributes(scope);
    translateTextNodes(scope);
    busy = false;
  };

  const bootstrapTranslations = (dict) => {
    dictionary = dict && typeof dict === "object" ? dict : {};
    substringKeys = Object.keys(dictionary)
      .filter((key) => key.length >= 4)
      .sort((a, b) => b.length - a.length);

    if (!Object.keys(dictionary).length) {
      markReady();
      return;
    }

    translateScope(body);
    markReady();
  };

  document.addEventListener("visibilitychange", () => {
    if (!dictionary || document.hidden) return;
    translateScope(getLiveRoot());
  });

  document.addEventListener("ajax:page-replaced", () => {
    if (!dictionary) return;
    window.setTimeout(() => {
      translateScope(getLiveRoot());
    }, 30);
  });

  document.addEventListener("bm:i18n-refresh", (event) => {
    if (!dictionary) return;
    const detail = event && event.detail ? event.detail : {};
    translateScope(detail.root || getLiveRoot());
  });

  window.BM_I18N = Object.assign({}, window.BM_I18N || {}, {
    lang,
    translateScope,
    translateDocument: () => translateScope(body),
  });

  if (hasServerPayload) {
    bootstrapTranslations(bootPayload.dict);
    return;
  }

  markReady();
})();
