(function () {
  "use strict";

  if (typeof window === "undefined" || typeof document === "undefined") return;
  if (window.__BM_ADMIN_LOGS_INIT__) return;
  window.__BM_ADMIN_LOGS_INIT__ = true;
  var makeRequestSeq =
    window.BMCoreDom && typeof window.BMCoreDom.makeRequestSeq === "function"
      ? window.BMCoreDom.makeRequestSeq
      : window.BMAjaxGuard.makeRequestSeq.bind(window.BMAjaxGuard);
  var requestText =
    window.BMCoreDom && typeof window.BMCoreDom.requestText === "function"
      ? window.BMCoreDom.requestText
      : window.BMAjaxFetch.requestText.bind(window.BMAjaxFetch);

  function restoreY(y) {
    var target = Math.max(Number(y || 0), 0);
    if (window.AdminHelpers && typeof window.AdminHelpers.restoreInstantScroll === "function") {
      window.AdminHelpers.restoreInstantScroll(target);
      return;
    }
    requestAnimationFrame(function () {
      try {
        window.scrollTo({ top: target, left: 0, behavior: "instant" });
      } catch (_err) {
        window.scrollTo(0, target);
      }
    });
  }

  function initLogsPage() {
    var varsNode = document.getElementById("pageVars");
    if (!varsNode) return;

    if (document.body && document.body.dataset) {
      document.body.dataset.admLogsInit = "1";
    }

    var pv = {};
    try {
      pv = JSON.parse(varsNode.textContent || "{}");
    } catch (_err) {
      pv = {};
    }

    var baseUrl = window.location.pathname;
    var baseParams = {
      category: pv.category_filter,
      level: pv.level_filter,
      user: pv.user_filter,
      days: pv.days,
    };

    var auditTbody = document.getElementById("auditTbody");
    var auditPg = document.getElementById("auditPg");
    var auditMask = document.getElementById("auditMask");
    var auditCount = document.getElementById("auditCount");

    var auditState = {
      action: pv.audit_action_filter || "",
      entity: pv.audit_entity_filter || "",
      user: pv.audit_user_filter || "",
      page: Number.parseInt(String(pv.audit_page || "1"), 10) || 1,
    };

    var seq = makeRequestSeq();
    var activeController = null;
    var filterDebounce = null;

    function buildAuditURL(page) {
      var params = new URLSearchParams(baseParams);
      params.set("audit_action", String(auditState.action || ""));
      params.set("audit_entity", String(auditState.entity || ""));
      params.set("audit_user", String(auditState.user || ""));
      params.set("audit_page", String(page || auditState.page || 1));
      return baseUrl + "?" + params.toString();
    }

    function setMask(on) {
      if (!auditMask) return;
      auditMask.classList.toggle("show", !!on);
    }

    function bindAuditPager() {
      if (!auditPg) return;
      auditPg.querySelectorAll("[data-audit-page]").forEach(function (el) {
        if (el.dataset.bound === "1") return;
        el.dataset.bound = "1";
        el.addEventListener("click", function (event) {
          event.preventDefault();
          var nextPage = Number.parseInt(String(el.dataset.auditPage || "1"), 10);
          if (!Number.isFinite(nextPage)) return;
          loadAuditPage(nextPage);
        });
      });
    }

    async function loadAuditPage(page) {
      if (!auditTbody || !auditPg) return;

      var keepY = window.scrollY || 0;
      auditState.page = Number.parseInt(String(page || "1"), 10) || 1;
      setMask(true);

      if (activeController && typeof activeController.abort === "function") {
        try {
          activeController.abort();
        } catch (_err) {}
      }
      activeController = typeof AbortController !== "undefined" ? new AbortController() : null;

      var requestId = seq.next();
      try {
        var response = await requestText(buildAuditURL(auditState.page), {
          headers: { "X-Requested-With": "XMLHttpRequest" },
          signal: activeController ? activeController.signal : undefined,
        });

        if (!seq.isLatest(requestId)) return;
        if (!response.ok) {
          if (!response.aborted) window.location.href = buildAuditURL(auditState.page);
          return;
        }

        var doc = new DOMParser().parseFromString(String(response.data || ""), "text/html");
        var newTbody = doc.getElementById("auditTbody");
        var newPager = doc.getElementById("auditPg");
        var newCount = doc.getElementById("auditCount");

        if (!newTbody || !newPager) {
          window.location.href = buildAuditURL(auditState.page);
          return;
        }

        auditTbody.innerHTML = newTbody.innerHTML;
        auditTbody.classList.add("fade-in");
        window.setTimeout(function () {
          auditTbody.classList.remove("fade-in");
        }, 250);

        auditPg.innerHTML = newPager.innerHTML;
        bindAuditPager();

        if (auditCount && newCount) {
          auditCount.textContent = newCount.textContent;
        }

        try {
          window.history.replaceState(null, "", buildAuditURL(auditState.page));
        } catch (_err) {}

        restoreY(keepY);
      } catch (_err) {
        window.location.href = buildAuditURL(auditState.page);
      } finally {
        if (seq.isLatest(requestId)) {
          setMask(false);
          activeController = null;
        }
      }
    }

    bindAuditPager();

    ["f-audit-action", "f-audit-entity", "f-audit-user"].forEach(function (id) {
      var el = document.getElementById(id);
      if (!el) return;
      el.addEventListener("change", function () {
        var actionEl = document.getElementById("f-audit-action");
        var entityEl = document.getElementById("f-audit-entity");
        var userEl = document.getElementById("f-audit-user");
        auditState.action = actionEl ? actionEl.value : "";
        auditState.entity = entityEl ? entityEl.value : "";
        auditState.user = userEl ? userEl.value : "";

        if (filterDebounce) window.clearTimeout(filterDebounce);
        filterDebounce = window.setTimeout(function () {
          loadAuditPage(1);
        }, 120);
      });
    });

    var resetBtn = document.getElementById("auditReset");
    if (resetBtn) {
      resetBtn.addEventListener("click", function (event) {
        event.preventDefault();
        var actionEl = document.getElementById("f-audit-action");
        var entityEl = document.getElementById("f-audit-entity");
        var userEl = document.getElementById("f-audit-user");
        if (actionEl) actionEl.value = "";
        if (entityEl) entityEl.value = "";
        if (userEl) userEl.value = "";
        auditState = { action: "", entity: "", user: "", page: 1 };
        loadAuditPage(1);
      });
    }

    var PER_PAGE = 50;

    function renderTerminalPage(data, bodyEl, pgEl, pageNumEl, page) {
      if (!bodyEl) return;

      var safeData = Array.isArray(data) ? data : [];
      var total = safeData.length;
      var pages = Math.ceil(total / PER_PAGE);
      var currentPage = Math.min(Math.max(Number(page || 1), 1), Math.max(pages, 1));
      var start = (currentPage - 1) * PER_PAGE;
      var slice = safeData.slice(start, start + PER_PAGE);

      bodyEl.innerHTML = slice.length
        ? slice
            .map(function (item) {
              var catClass =
                item.cat === "auth" ? "le-auth" : item.cat === "admin" ? "le-admin" : "le-sys-cat";
              var userText = item.usr
                ? '<span class="le-user"> ' + item.usr + "</span>"
                : '<span class="le-sys"> SYSTEM</span>';
              var ipText = item.ip
                ? '<span class="le-ip"><i class="bi bi-globe"></i> ' + item.ip + "</span>"
                : "";
              var extraText =
                item.rt && item.ri
                  ? '<span style="color:#cbd5e1;font-size:.69rem"> [' + item.rt + " #" + item.ri + "]</span>"
                  : "";
              return (
                '<div class="le">' +
                '<span class="le-ts">[' +
                item.ts +
                "]</span>" +
                '<span class="le-' +
                item.lvl +
                '"> ' +
                item.lvl +
                "</span>" +
                '<span class="' +
                catClass +
                '"> ' +
                String(item.cat || "").toUpperCase() +
                "</span>" +
                userText +
                '<span class="le-msg">' +
                String(item.msg || "") +
                "</span>" +
                extraText +
                ipText +
                "</div>"
              );
            })
            .join("")
        : '<div style="text-align:center;padding:2rem;color:#475569">Aucune entree.</div>';

      if (pageNumEl) pageNumEl.textContent = String(currentPage);
      if (!pgEl) return;
      if (pages <= 1) {
        pgEl.innerHTML = "";
        return;
      }

      var html = "";
      if (currentPage > 1) {
        html += '<a data-p="' + (currentPage - 1) + '"><i class="bi bi-chevron-left"></i></a>';
      } else {
        html += '<span class="dis"><i class="bi bi-chevron-left"></i></span>';
      }

      for (var p = 1; p <= pages; p += 1) {
        if (p === 1 || p === pages || Math.abs(p - currentPage) <= 1) {
          html += '<a class="' + (p === currentPage ? "cur" : "") + '" data-p="' + p + '">' + p + "</a>";
        } else if (Math.abs(p - currentPage) === 2) {
          html += '<span class="dis">...</span>';
        }
      }

      if (currentPage < pages) {
        html += '<a data-p="' + (currentPage + 1) + '"><i class="bi bi-chevron-right"></i></a>';
      } else {
        html += '<span class="dis"><i class="bi bi-chevron-right"></i></span>';
      }

      pgEl.innerHTML = html;
      pgEl.querySelectorAll("[data-p]").forEach(function (el) {
        if (el.dataset.bound === "1") return;
        el.dataset.bound = "1";
        el.addEventListener("click", function () {
          var keepY = window.scrollY || 0;
          var next = Number.parseInt(String(el.dataset.p || "1"), 10) || 1;
          renderTerminalPage(safeData, bodyEl, pgEl, pageNumEl, next);
          restoreY(keepY);
        });
      });
    }

    var critData = [];
    var sysData = [];
    try {
      critData = JSON.parse((document.getElementById("critData") || {}).textContent || "[]");
    } catch (_err) {
      critData = [];
    }
    try {
      sysData = JSON.parse((document.getElementById("sysData") || {}).textContent || "[]");
    } catch (_err) {
      sysData = [];
    }

    var critBody = document.getElementById("critBody");
    var critPg = document.getElementById("critPg");
    var critPgNum = document.getElementById("critPageNum");
    var sysBody = document.getElementById("sysBody");
    var sysPg = document.getElementById("sysPg");
    var sysPgNum = document.getElementById("sysPageNum");

    if (Array.isArray(critData) && critData.length > PER_PAGE) {
      renderTerminalPage(critData, critBody, critPg, critPgNum, 1);
    }
    if (Array.isArray(sysData) && sysData.length > PER_PAGE) {
      renderTerminalPage(sysData, sysBody, sysPg, sysPgNum, 1);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initLogsPage, { once: true });
    return;
  }

  initLogsPage();
})();

