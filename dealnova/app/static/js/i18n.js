(() => {
  const body = document.body;
  if (!body) return;
  if ((window.location.pathname || "").startsWith("/admin")) return;

  /* observerRoot reste pour la compatibilité mais n'est plus utilisé
     comme cible de l'observer — on observe document.body à la place */
  const observerRoot =
    document.querySelector("main") ||
    document.getElementById("pageContent") ||
    body;

  /* Résout dynamiquement le nœud courant à chaque appel.
     Après navigation AJAX, <main> peut être remplacé dans le DOM. */
  const getLiveRoot = () =>
    document.querySelector("main") ||
    document.getElementById("pageContent") ||
    body;

  const getCookie = (name) => {
    const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
    return match ? decodeURIComponent(match[1]) : "";
  };

  let lang = (body.dataset.lang || "").toLowerCase();
  if (!lang || lang === "fr") {
    const cookieLang = (getCookie("lang") || "").toLowerCase();
    if (cookieLang) lang = cookieLang;
  }
  if (!lang) lang = "fr";
  if (lang === "fr") return;

  const rtlLangs = (body.dataset.rtlLangs || "")
    .split(",")
    .map((v) => v.trim().toLowerCase())
    .filter(Boolean);
  const isRtl = rtlLangs.includes(lang);

  const normalizeKey = (value) => String(value || "").replace(/\s+/g, " ").trim();

  const buildFrFallbackByEnValue = (enDict) => {
    const out = {};
    Object.entries(enDict || {}).forEach(([frKey, enValue]) => {
      const normalizedEn = normalizeKey(enValue);
      if (!normalizedEn) return;
      out[normalizedEn] = frKey;
    });
    return out;
  };

  /* ── Verrou anti-boucle ── */
  let _busy = false;

  const applyTranslations = (dict, frFallbackByValue = {}, scopeRoot) => {
    if (!dict) return;
    if (_busy) return;
    _busy = true;

    const root = scopeRoot && scopeRoot.nodeType === 1 ? scopeRoot : body;

    document.documentElement.lang = lang;
    if (isRtl) {
      document.documentElement.dir = "rtl";
      document.body.dir = "rtl";
    }

    const translateValue = (value) => {
      if (!value) return value;
      const key = normalizeKey(value);
      const translated = dict[key] || frFallbackByValue[key];
      if (!translated) return value;
      const leading = value.match(/^\s*/)?.[0] || "";
      const trailing = value.match(/\s*$/)?.[0] || "";
      return `${leading}${translated}${trailing}`;
    };

    const substringMap = { ...frFallbackByValue, ...dict };
    const keysSorted = Object.keys(substringMap)
      .filter((k) => k.length >= 4)
      .sort((a, b) => b.length - a.length);

    const translateBySubstring = (value) => {
      let out = value;
      let replaced = false;
      keysSorted.forEach((key) => {
        if (out.includes(key)) {
          out = out.split(key).join(substringMap[key]);
          replaced = true;
        }
      });
      return replaced ? out : value;
    };

    const attrTargets = ["placeholder", "title", "aria-label"];
    root.querySelectorAll("*").forEach((el) => {
      if (el.closest("[data-no-i18n]")) return;

      attrTargets.forEach((attr) => {
        if (!el.hasAttribute(attr)) return;
        const current = el.getAttribute(attr);
        const next = translateValue(current);
        if (next !== current) el.setAttribute(attr, next);
      });

      if (el.tagName === "INPUT") {
        const type = (el.getAttribute("type") || "").toLowerCase();
        if (["button", "submit", "reset"].includes(type)) {
          const currentValue = el.getAttribute("value");
          const nextValue = translateValue(currentValue);
          if (nextValue !== currentValue) el.setAttribute("value", nextValue);
        }
      }
    });

    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const text = node.nodeValue;
        if (!text || !text.trim()) return NodeFilter.FILTER_REJECT;
        const parent = node.parentElement;
        if (!parent) return NodeFilter.FILTER_REJECT;
        if (parent.closest("[data-no-i18n]")) return NodeFilter.FILTER_REJECT;
        const tag = parent.tagName;
        if (tag === "SCRIPT" || tag === "STYLE" || tag === "NOSCRIPT") return NodeFilter.FILTER_REJECT;
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

    _busy = false;
  };

  const cacheKey = `i18n_${lang}_v11`;
  const cached = localStorage.getItem(cacheKey);
  let observer = null;
  let debounceTimer = null;
  let observerBound = false;
  let observerDict = null;
  let observerFallback = {};

  const stopObserver = () => {
    if (observer) observer.disconnect();
    observer = null;
    if (debounceTimer) {
      clearTimeout(debounceTimer);
      debounceTimer = null;
    }
  };

  const startObserver = (dict, frFallbackByValue) => {
    observerDict = dict;
    observerFallback = frFallbackByValue || {};

    if (!observerBound) {
      observerBound = true;

      /* visibilitychange : identique à l'original */
      document.addEventListener("visibilitychange", () => {
        if (document.hidden) {
          stopObserver();
          return;
        }
        if (!observerDict) return;
        applyTranslations(observerDict, observerFallback, getLiveRoot());
        startObserver(observerDict, observerFallback);
      });

      /* ajax:page-replaced : déclenché par ajax_pagination.js
         après chaque swap de page — filet de sécurité */
      document.addEventListener("ajax:page-replaced", () => {
        if (_busy) return;
        /* Petit délai pour laisser le DOM se stabiliser */
        window.setTimeout(() => {
          applyTranslations(observerDict, observerFallback, getLiveRoot());
        }, 60);
      });
    }

    stopObserver();
    if (document.hidden) return;

    const debouncedApply = () => {
      if (_busy) return;
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = window.setTimeout(() => {
        debounceTimer = null;
        if (_busy) return;
        /* getLiveRoot() → toujours le <main> actuel dans le DOM,
           même si ajax_pagination.js l'a remplacé */
        applyTranslations(dict, frFallbackByValue, getLiveRoot());
      }, 180);
    };

    /* ── CHANGEMENT CLÉ ────────────────────────────────────────
       On observe document.body au lieu de observerRoot.
       
       Pourquoi :
       - Si ajax_pagination.js REMPLACE l'élément <main> lui-même
         (remove old <main>, insert new <main>), observerRoot
         pointe vers le nœud DÉTACHÉ → observer mort → 0 traduction.
       - document.body ne change JAMAIS → observer toujours actif.
       - Quand <main> est remplacé, c'est une mutation childList
         de document.body → observer fire → debouncedApply → traduit ✓
       
       On supprime characterData: true (cause du scintillement) :
       - node.nodeValue = x  →  characterData mutation
       - characterData: true →  re-fire le callback → boucle infinie
       - Sans characterData: seuls les nouveaux nœuds déclenchent ✓
    ── ─────────────────────────────────────────────────────── */
    observer = new MutationObserver(debouncedApply);
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      /* characterData: true → SUPPRIMÉ (causait la boucle) */
    });
  };

  const bootstrapTranslations = (dict, frFallbackByValue = {}) => {
    if (!dict) return;
    applyTranslations(dict, frFallbackByValue, body);
    startObserver(dict, frFallbackByValue);
  };

  if (cached) {
    try {
      const payload = JSON.parse(cached);
      if (payload && payload.dict) {
        bootstrapTranslations(payload.dict, payload.frFallbackByValue || {});
        return;
      }
    } catch (_) {
      localStorage.removeItem(cacheKey);
    }
  }

  Promise.all([
    fetch(`/static/i18n/${lang}.json`, { cache: "no-store" }).then((res) => (res.ok ? res.json() : null)),
    fetch("/static/i18n/en.json", { cache: "no-store" }).then((res) => (res.ok ? res.json() : null)),
  ])
    .then(([dict, enDict]) => {
      if (!dict) return;

      const frFallbackByValue = buildFrFallbackByEnValue(enDict || {});
      const payload = { dict, frFallbackByValue };

      try {
        localStorage.setItem(cacheKey, JSON.stringify(payload));
      } catch (_) {}

      bootstrapTranslations(dict, frFallbackByValue);
    })
    .catch(() => {});
})();