(() => {
  const existing = window.BMCoreDom || {};
  if (existing.__ready) return;

  function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
  }

  function safeUrl(url) {
    const u = String(url || "");
    if (
      u.startsWith("/") ||
      u.startsWith("http://") ||
      u.startsWith("https://") ||
      u.startsWith("tel:") ||
      u.startsWith("mailto:")
    ) {
      return u;
    }
    return "#";
  }

  function makeRequestSeq() {
    const ajaxGuard = window.BMAjaxGuard || {};
    if (typeof ajaxGuard.makeRequestSeq === "function") {
      return ajaxGuard.makeRequestSeq();
    }

    let latest = 0;
    return {
      next() {
        latest += 1;
        return latest;
      },
      isLatest(id) {
        return Number(id) === latest;
      },
    };
  }

  function toPlainHeaders(headers) {
    if (!headers) return {};
    if (headers instanceof Headers) {
      const plain = {};
      headers.forEach((value, key) => {
        plain[key] = value;
      });
      return plain;
    }
    return Object.assign({}, headers);
  }

  function shouldAttachCsrf(method) {
    const normalized = String(method || "GET").toUpperCase();
    return normalized !== "GET" && normalized !== "HEAD" && normalized !== "OPTIONS";
  }

  async function parseRequestData(response, expect) {
    if (expect === "json") {
      try {
        return await response.json();
      } catch (_error) {
        return null;
      }
    }

    try {
      return await response.text();
    } catch (_error) {
      return "";
    }
  }

  async function request(url, options) {
    const ajaxFetch = window.BMAjaxFetch || {};
    if (typeof ajaxFetch.request === "function") {
      return ajaxFetch.request(url, options || {});
    }

    const opts = options || {};
    const method = String(opts.method || "GET").toUpperCase();
    const expect = opts.expect === "json" ? "json" : "text";
    const headers = toPlainHeaders(opts.headers);
    const csrfApi = window.BMAjaxCSRF || {};
    const finalHeaders =
      shouldAttachCsrf(method) && typeof csrfApi.addToHeaders === "function"
        ? csrfApi.addToHeaders(headers, opts.form || null)
        : headers;

    const fetchOptions = Object.assign({}, opts, {
      method,
      headers: finalHeaders,
    });
    delete fetchOptions.expect;
    delete fetchOptions.timeoutMs;
    delete fetchOptions.onError;
    delete fetchOptions.form;

    if (!Object.prototype.hasOwnProperty.call(fetchOptions, "credentials")) {
      fetchOptions.credentials = "same-origin";
    }

    try {
      const response = await fetch(url, fetchOptions);
      const data = await parseRequestData(response, expect);
      const error =
        response.ok
          ? null
          : (data && typeof data === "object" && (data.error || data.message)) ||
            response.statusText ||
            ("HTTP " + response.status);

      return {
        ok: response.ok,
        status: response.status,
        data,
        error: error ? String(error) : null,
        aborted: false,
        timedOut: false,
      };
    } catch (error) {
      return {
        ok: false,
        status: 0,
        data: expect === "json" ? null : "",
        error: String((error && error.message) || "network_error"),
        aborted: !!(error && error.name === "AbortError"),
        timedOut: false,
      };
    }
  }

  function requestText(url, options) {
    return request(url, Object.assign({}, options || {}, { expect: "text" }));
  }

  function requestJSON(url, options) {
    return request(url, Object.assign({}, options || {}, { expect: "json" }));
  }

  function collectFormValues(root) {
    const values = {};
    if (!root) return values;
    root.querySelectorAll("input, select, textarea").forEach((el) => {
      if (!el.name) return;
      if (el.type === "checkbox") {
        values[el.name] = el.checked;
        return;
      }
      if (el.type === "radio") {
        if (el.checked) values[el.name] = el.value;
        return;
      }
      values[el.name] = el.value;
    });
    return values;
  }

  function applyFormValues(root, values) {
    if (!root || !values) return;
    Object.keys(values).forEach((key) => {
      const fields = root.querySelectorAll(`[name="${key}"]`);
      fields.forEach((field) => {
        if (field.type === "checkbox") {
          field.checked = !!values[key];
          return;
        }
        if (field.type === "radio") {
          field.checked = field.value === values[key];
          return;
        }
        field.value = values[key];
      });
    });
  }

  function setupPaginationForTable(table) {
    const pageSize = parseInt(table.dataset.pageSize || "10", 10);
    if (!pageSize || pageSize <= 0) return;

    const tbody = table.tBodies[0];
    if (!tbody) return;

    const rows = Array.from(tbody.rows).filter((row) => !row.querySelector(".fraud-empty"));
    const tableWrap = table.closest(".table-responsive");
    if (!tableWrap) return;

    const existingPager = tableWrap.nextElementSibling;
    if (existingPager && existingPager.classList.contains("fraud-pager")) {
      existingPager.remove();
    }

    if (rows.length <= pageSize) {
      rows.forEach((row) => {
        row.style.display = "";
      });
      return;
    }

    let currentPage = 1;
    const totalPages = Math.ceil(rows.length / pageSize);

    const pager = document.createElement("div");
    pager.className = "fraud-pager";
    const prevBtn = document.createElement("button");
    prevBtn.type = "button";
    prevBtn.textContent = "Precedent";
    const nextBtn = document.createElement("button");
    nextBtn.type = "button";
    nextBtn.textContent = "Suivant";
    const info = document.createElement("div");
    info.className = "fraud-page-info";
    pager.appendChild(prevBtn);
    pager.appendChild(info);
    pager.appendChild(nextBtn);
    tableWrap.insertAdjacentElement("afterend", pager);

    function render() {
      const start = (currentPage - 1) * pageSize;
      const end = start + pageSize;
      rows.forEach((row, idx) => {
        row.style.display = idx >= start && idx < end ? "" : "none";
      });
      info.textContent = `Page ${currentPage} / ${totalPages} - ${rows.length} elements`;
      prevBtn.disabled = currentPage <= 1;
      nextBtn.disabled = currentPage >= totalPages;
    }

    prevBtn.addEventListener("click", () => {
      if (currentPage > 1) {
        currentPage -= 1;
        render();
      }
    });
    nextBtn.addEventListener("click", () => {
      if (currentPage < totalPages) {
        currentPage += 1;
        render();
      }
    });

    render();
  }

  function initFraudPage(root) {
    const scope = root || document;
    const cleanBtn = scope.querySelector("#fraudCleanTwoDays");
    if (cleanBtn && !cleanBtn.dataset.bound) {
      cleanBtn.dataset.bound = "true";
      cleanBtn.addEventListener("click", () => {
        const form = scope.querySelector("#fraudFiltersForm");
        if (!form) return;
        const days = form.querySelector('input[name="days"]');
        if (days) days.value = 2;
        form.submit();
      });
    }

    scope.querySelectorAll(".fraud-table").forEach(setupPaginationForTable);
  }

  window.BMCoreDom = {
    escapeHtml,
    safeUrl,
    makeRequestSeq,
    request,
    requestText,
    requestJSON,
    collectFormValues,
    applyFormValues,
    setupPaginationForTable,
    initFraudPage,
    __ready: true,
  };

  // Legacy global kept for compatibility with existing inline/admin scripts.
  window.initFraudPage = initFraudPage;
})();

