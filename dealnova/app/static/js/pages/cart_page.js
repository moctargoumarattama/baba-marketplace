(function () {
  "use strict";

  if (window.__BM_CART_PAGE_INIT__) {
    return;
  }
  window.__BM_CART_PAGE_INIT__ = true;

  const bmFetchApi = window.BMAjaxFetch || null;
  const bmCsrfApi = window.BMAjaxCSRF || window.BMAjaxCsrf || null;

  function bmAddCsrfHeaders(headers, formEl) {
    const nextHeaders = Object.assign({}, headers || {});
    if (bmCsrfApi && typeof bmCsrfApi.addToHeaders === "function") {
      return bmCsrfApi.addToHeaders(nextHeaders, formEl || null);
    }
    if (!nextHeaders["X-CSRFToken"] && !nextHeaders["x-csrftoken"] && window.csrfToken) {
      nextHeaders["X-CSRFToken"] = window.csrfToken;
    }
    return nextHeaders;
  }

  async function bmFallbackFetch(url, options, expect) {
    const opts = Object.assign({}, options || {});
    const response = await fetch(url, opts);
    let data = null;
    if (expect === "json") {
      try {
        data = await response.json();
      } catch (_jsonError) {
        data = null;
      }
    } else {
      try {
        data = await response.text();
      } catch (_textError) {
        data = "";
      }
    }
    return {
      ok: response.ok,
      status: response.status,
      data: data,
      error: response.ok ? null : (response.statusText || ("HTTP " + response.status)),
      aborted: false,
      timedOut: false,
    };
  }

  async function bmFetchJSON(url, options) {
    if (bmFetchApi && typeof bmFetchApi.requestJSON === "function") {
      return bmFetchApi.requestJSON(url, options || {});
    }
    try {
      return await bmFallbackFetch(url, options, "json");
    } catch (error) {
      return {
        ok: false,
        status: 0,
        data: null,
        error: String((error && error.message) || "network_error"),
        aborted: !!(error && error.name === "AbortError"),
        timedOut: false,
      };
    }
  }

  function lockElement(el, ms) {
    if (!el) return;
    if (window.BMAjaxGuard && typeof window.BMAjaxGuard.lock === "function") {
      window.BMAjaxGuard.lock(el, ms || 900);
      return;
    }
    if ("disabled" in el) {
      el.disabled = true;
      window.setTimeout(function () {
        el.disabled = false;
      }, Math.max(0, Number(ms) || 900));
    }
  }

  function unlockElement(el) {
    if (!el) return;
    if (window.BMAjaxGuard && typeof window.BMAjaxGuard.unlock === "function") {
      window.BMAjaxGuard.unlock(el);
      return;
    }
    if ("disabled" in el) {
      el.disabled = false;
    }
  }

  function safeNumber(value, fallback) {
    const num = Number(value);
    return Number.isFinite(num) ? num : (Number(fallback) || 0);
  }

  function setItemBusy(item, busy) {
    if (!item) return;
    item.querySelectorAll(".qty-btn, .qty-input, .remove-item-btn").forEach(function (node) {
      if ("disabled" in node) {
        node.disabled = !!busy;
      }
    });
    item.classList.toggle("is-updating", !!busy);
  }

  document.addEventListener("DOMContentLoaded", function () {
    const coreUI = window.BMCoreUI || {};

    const qtyControllers = new Map();
    const qtySeq = new Map();
    const removeControllers = new Map();
    let clearController = null;

    function nextQtySeq(pid) {
      const key = String(pid || "");
      const next = (qtySeq.get(key) || 0) + 1;
      qtySeq.set(key, next);
      return next;
    }

    function isLatestQtySeq(pid, requestId) {
      return (qtySeq.get(String(pid || "")) || 0) === requestId;
    }

    function showToast(message, type) {
      if (typeof coreUI.showBootstrapToast === "function") {
        coreUI.showBootstrapToast({
          message: message || "",
          type: type || "success",
          toastId: "cartToast",
          messageId: "toastMessage",
          durationMs: 3000,
          classMap: {
            success: "bg-success",
            info: "bg-info",
            warning: "bg-warning",
            error: "bg-danger",
            danger: "bg-danger",
          },
        });
        return;
      }
      if (typeof coreUI.showToast === "function") {
        coreUI.showToast(message || "", type || "success");
      }
    }

    function updateCartTotals(data) {
      if (!data || typeof data !== "object") return;

      if (data.cart_count !== undefined) {
        const cartCountEl = document.getElementById("cartCount");
        if (cartCountEl) {
          cartCountEl.textContent = String(data.cart_count);
        }
      }

      if (data.total !== undefined) {
        const subtotalEl = document.getElementById("subtotalAmount");
        const totalEl = document.getElementById("totalAmount");
        if (subtotalEl && totalEl) {
          const baseTotal = safeNumber(data.total, 0);
          subtotalEl.textContent = baseTotal.toFixed(2) + " MAD";
          totalEl.textContent = baseTotal.toFixed(2) + " MAD";

          if (data.shipping !== undefined) {
            const shippingEl = document.getElementById("shippingAmount");
            const shipping = safeNumber(data.shipping, 0);
            if (shippingEl) {
              shippingEl.textContent = shipping.toFixed(2) + " MAD";
              shippingEl.className = "";

              if (shipping > 0) {
                shippingEl.classList.add("text-info");
              } else {
                shippingEl.classList.add("text-success");
                shippingEl.innerHTML = '<i class="bi bi-check-circle me-1"></i>Gratuite';
              }
            }
            totalEl.textContent = (baseTotal + shipping).toFixed(2) + " MAD";
          }
        }
      }

      const headerCartCount = document.querySelector(".cart-count-badge");
      if (headerCartCount && data.cart_count !== undefined) {
        headerCartCount.textContent = String(data.cart_count);
        headerCartCount.classList.remove("d-none");
      }
    }

    async function updateQuantity(pid, newQty, triggerEl) {
      const item = document.querySelector('.cart-item[data-pid="' + pid + '"]');
      if (!item) return;

      const requestId = nextQtySeq(pid);
      const currentPid = String(pid || "");
      const currentQty = safeNumber(newQty, 0);

      if (qtyControllers.has(currentPid)) {
        try {
          qtyControllers.get(currentPid).abort();
        } catch (_abortError) {}
      }

      const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
      if (controller) {
        qtyControllers.set(currentPid, controller);
      } else {
        qtyControllers.delete(currentPid);
      }

      lockElement(triggerEl, 700);
      setItemBusy(item, true);

      try {
        const result = await bmFetchJSON("/cart/api/update/" + encodeURIComponent(currentPid), {
          method: "POST",
          headers: bmAddCsrfHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ quantity: currentQty }),
          signal: controller ? controller.signal : undefined,
          credentials: "same-origin",
          cache: "no-store",
        });

        if (!isLatestQtySeq(currentPid, requestId)) {
          return;
        }

        if (result.aborted) {
          return;
        }

        const data = result.data || {};
        if (result.ok && data.success) {
          const freshItem = document.querySelector('.cart-item[data-pid="' + currentPid + '"]');
          if (freshItem) {
            const input = freshItem.querySelector(".qty-input");
            const subtotalEl = freshItem.querySelector(".product-subtotal");

            if (input && data.product_qty !== undefined) {
              input.value = String(data.product_qty);
            }
            if (subtotalEl && data.product_total !== undefined) {
              const productTotal = safeNumber(data.product_total, 0);
              subtotalEl.textContent = productTotal.toFixed(2) + " MAD";
            }
            if (safeNumber(data.product_qty, 0) === 0) {
              freshItem.remove();
            }
          }

          updateCartTotals(data);
          showToast(data.message || "Panier mis a jour");
        } else {
          showToast(data.message || result.error || "Erreur de connexion", "error");
        }
      } catch (_error) {
        showToast("Erreur de connexion", "error");
      } finally {
        unlockElement(triggerEl);
        if (isLatestQtySeq(currentPid, requestId)) {
          const latestItem = document.querySelector('.cart-item[data-pid="' + currentPid + '"]');
          setItemBusy(latestItem, false);
        }
        if (controller && qtyControllers.get(currentPid) === controller) {
          qtyControllers.delete(currentPid);
        }
      }
    }

    async function removeFromCart(pid, triggerEl) {
      const currentPid = String(pid || "");
      const item = document.querySelector('.cart-item[data-pid="' + currentPid + '"]');
      if (item) {
        setItemBusy(item, true);
      }
      lockElement(triggerEl, 900);

      if (removeControllers.has(currentPid)) {
        try {
          removeControllers.get(currentPid).abort();
        } catch (_abortError) {}
      }
      const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
      if (controller) {
        removeControllers.set(currentPid, controller);
      }

      try {
        const result = await bmFetchJSON("/cart/api/remove/" + encodeURIComponent(currentPid), {
          method: "POST",
          headers: bmAddCsrfHeaders({}),
          signal: controller ? controller.signal : undefined,
          credentials: "same-origin",
          cache: "no-store",
        });

        if (result.aborted) return;
        const data = result.data || {};
        if (result.ok && data.success) {
          const freshItem = document.querySelector('.cart-item[data-pid="' + currentPid + '"]');
          if (freshItem) {
            freshItem.remove();
          }

          updateCartTotals(data);
          showToast(data.message || "Produit supprime");

          if (safeNumber(data.cart_count, 0) === 0) {
            window.setTimeout(function () {
              window.location.reload();
            }, 1000);
          }
        } else {
          showToast(data.message || result.error || "Erreur de connexion", "error");
        }
      } catch (_error) {
        showToast("Erreur de connexion", "error");
      } finally {
        unlockElement(triggerEl);
        const latestItem = document.querySelector('.cart-item[data-pid="' + currentPid + '"]');
        setItemBusy(latestItem, false);
        if (controller && removeControllers.get(currentPid) === controller) {
          removeControllers.delete(currentPid);
        }
      }
    }

    async function clearCart(triggerEl) {
      lockElement(triggerEl, 1200);
      if (clearController) {
        try {
          clearController.abort();
        } catch (_abortError) {}
      }
      clearController = typeof AbortController !== "undefined" ? new AbortController() : null;

      try {
        const result = await bmFetchJSON("/cart/api/clear", {
          method: "POST",
          headers: bmAddCsrfHeaders({}),
          signal: clearController ? clearController.signal : undefined,
          credentials: "same-origin",
          cache: "no-store",
        });
        if (result.aborted) return;

        const data = result.data || {};
        if (result.ok && data.success) {
          const cartItemsEl = document.getElementById("cartItems");
          if (cartItemsEl) {
            cartItemsEl.innerHTML = "";
          }
          updateCartTotals(data);
          showToast(data.message || "Panier vide");
          window.setTimeout(function () {
            window.location.reload();
          }, 1500);
        } else {
          showToast(data.message || result.error || "Erreur de connexion", "error");
        }
      } catch (_error) {
        showToast("Erreur de connexion", "error");
      } finally {
        unlockElement(triggerEl);
      }
    }

    document.querySelectorAll(".qty-increase").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const item = this.closest(".cart-item");
        if (!item) return;
        const pid = item.dataset.pid;
        const input = item.querySelector(".qty-input");
        if (!input) return;
        const currentValue = safeNumber(parseInt(input.value, 10), 0);
        const max = safeNumber(parseInt(input.max, 10), 99);

        if (currentValue < max) {
          updateQuantity(pid, currentValue + 1, this);
        } else {
          showToast("Quantite maximale: " + max, "error");
        }
      });
    });

    document.querySelectorAll(".qty-decrease").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const item = this.closest(".cart-item");
        if (!item) return;
        const pid = item.dataset.pid;
        const input = item.querySelector(".qty-input");
        if (!input) return;
        const currentValue = safeNumber(parseInt(input.value, 10), 1);

        if (currentValue > 1) {
          updateQuantity(pid, currentValue - 1, this);
        } else {
          removeFromCart(pid, this);
        }
      });
    });

    document.querySelectorAll(".qty-input").forEach(function (input) {
      input.addEventListener("change", function () {
        const item = this.closest(".cart-item");
        if (!item) return;
        const pid = item.dataset.pid;
        const newQty = safeNumber(parseInt(this.value, 10), 0);
        const max = safeNumber(parseInt(this.max, 10), 99);

        if (newQty > 0 && newQty <= max) {
          updateQuantity(pid, newQty, this);
        } else if (newQty > max) {
          this.value = String(max);
          showToast("Quantite maximale: " + max, "error");
        }
      });
    });

    document.querySelectorAll(".remove-item-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const item = this.closest(".cart-item");
        if (!item) return;
        const pid = item.dataset.pid;
        removeFromCart(pid, this);
      });
    });

    const clearCartBtn = document.getElementById("clearCartBtn");
    if (clearCartBtn) {
      clearCartBtn.addEventListener("click", function () {
        if (window.confirm("Voulez-vous vraiment vider tout votre panier ?")) {
          clearCart(this);
        }
      });
    }

    document.querySelectorAll(".cart-item").forEach(function (item, index) {
      item.style.opacity = "0";
      item.style.transform = "translateY(10px)";

      window.setTimeout(function () {
        item.style.transition = "opacity 0.3s ease, transform 0.3s ease";
        item.style.opacity = "1";
        item.style.transform = "translateY(0)";
      }, index * 50);
    });
  });
})();

