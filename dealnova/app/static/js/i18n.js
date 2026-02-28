(() => {
  const body = document.body;
  if (!body) return;
  if ((window.location.pathname || "").startsWith("/admin")) return;

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

  const applyTranslations = (dict, frFallbackByValue = {}) => {
    if (!dict) return;

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
    document.querySelectorAll("*").forEach((el) => {
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

    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
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
  };

  const cacheKey = `i18n_${lang}_v9`;
  const cached = localStorage.getItem(cacheKey);
  if (cached) {
    try {
      const payload = JSON.parse(cached);
      if (payload && payload.dict) {
        applyTranslations(payload.dict, payload.frFallbackByValue || {});
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

      applyTranslations(dict, frFallbackByValue);

      let scheduled = false;
      const schedule = () => {
        if (scheduled) return;
        scheduled = true;
        window.requestAnimationFrame(() => {
          scheduled = false;
          applyTranslations(dict, frFallbackByValue);
        });
      };

      const observer = new MutationObserver(schedule);
      observer.observe(document.body, {
        childList: true,
        subtree: true,
        characterData: true,
      });
    })
    .catch(() => {});
})();
