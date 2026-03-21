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
    collectFormValues,
    applyFormValues,
    setupPaginationForTable,
    initFraudPage,
    __ready: true,
  };

  // Legacy global kept for compatibility with existing inline/admin scripts.
  window.initFraudPage = initFraudPage;
})();

