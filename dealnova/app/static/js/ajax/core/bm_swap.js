(function () {
  "use strict";

  function resolveTarget(targetEl) {
    if (!targetEl) return null;
    if (typeof targetEl === "string") {
      return document.querySelector(targetEl);
    }
    return targetEl;
  }

  function dispatchSwapEvent(target, mode) {
    try {
      document.dispatchEvent(
        new CustomEvent("ajax:page-replaced", {
          detail: {
            target: target || null,
            mode: mode || "replace",
          },
        })
      );
    } catch (_err) {}
  }

  function swapHTML(options) {
    const opts = options || {};
    const mode = opts.mode === "inner" ? "inner" : "replace";
    const target = resolveTarget(opts.targetEl);
    const html = String(opts.html || "");

    if (!target) {
      return { ok: false, error: "missing_target", target: null };
    }

    if (mode === "inner") {
      target.innerHTML = html;
      dispatchSwapEvent(target, mode);
      return { ok: true, error: null, target: target };
    }

    const template = document.createElement("template");
    template.innerHTML = html.trim();

    let replacementTarget = target;
    if (template.content.childElementCount === 1) {
      const nextNode = template.content.firstElementChild;
      target.replaceWith(nextNode);
      replacementTarget = nextNode;
    } else {
      target.innerHTML = "";
      target.appendChild(template.content);
    }

    dispatchSwapEvent(replacementTarget, mode);
    return { ok: true, error: null, target: replacementTarget };
  }

  const api = window.BMAjaxSwap || {};
  api.swapHTML = swapHTML;
  window.BMAjaxSwap = api;
})();


