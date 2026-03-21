document.addEventListener("DOMContentLoaded", () => {

  /* =======================
     TOAST
  ======================= */
  function showToast(message, type = "success") {
    const toast = document.getElementById("toast");
    const msg = document.getElementById("toast-message");
    const icon = document.getElementById("toast-icon");

    if (!toast || !msg) return;

    toast.className = `toast ${type}`;
    if (icon) {
      icon.className = type === "error" ? "bi bi-x-circle" : "bi bi-check-circle";
    }
    msg.textContent = message;
    toast.style.display = "flex";

    window.setTimeout(() => {
      toast.style.display = "none";
    }, 3000);
  }

  /* =======================
     ADD TO CART
  ======================= */
  async function handleAddToCart(btn, e) {
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    if (btn.disabled) return;

    const productId = btn.dataset.pid;
    const productName = btn.dataset.name || "Produit";

    const originalHTML = btn.innerHTML;
    const originalBg = btn.style.background;

    btn.innerHTML = '<i class="bi bi-hourglass-split"></i>';
    btn.style.background = "#6B7280";
    btn.disabled = true;

    try {
      const response = await fetch(`/cart/api/add/${productId}`, {
        method: "POST",
        headers: {
          "X-CSRFToken": window.csrfToken,
        },
        credentials: "same-origin",
      });

      const data = await response.json();
      if (!data.success) {
        throw new Error(data.message || "Reponse invalide");
      }

      showToast(`${productName} ajout au panier`);

      btn.innerHTML = '<i class="bi bi-check2"></i> Ajout';
      btn.style.background = "#10B981";

      const badge = document.querySelector(".cart-badge");
      if (badge) {
        badge.textContent = data.cart_count ?? (parseInt(badge.textContent, 10) || 0) + 1;
        badge.style.display = "flex";
      }
      document.dispatchEvent(new CustomEvent("cart:changed", {
        detail: { source: "home_shell", cartCount: data.cart_count ?? null }
      }));

      window.setTimeout(() => {
        btn.innerHTML = originalHTML;
        btn.style.background = originalBg;
        btn.disabled = false;
      }, 1500);
    } catch (err) {
      console.error(err);
      showToast("Impossible de contacter le serveur", "error");
      btn.innerHTML = originalHTML;
      btn.style.background = originalBg;
      btn.disabled = false;
    }
  }

  /* =======================
     CARD/CTA CLICK (delegated)
  ======================= */
  document.addEventListener("click", (e) => {
    const addToCartBtn = e.target.closest(".add-to-cart");
    if (addToCartBtn) {
      handleAddToCart(addToCartBtn, e);
      return;
    }

    const card = e.target.closest(".product-card");
    if (!card) return;
    if (e.target.closest("a, button, .add-to-cart, .badge")) return;

    const link = card.querySelector(".btn-detail");
    if (link) window.location.href = link.href;
  });

  /* =======================
     SCROLL TO TOP
  ======================= */
  const scrollTopBtn = document.querySelector(".scroll-top");
  if (scrollTopBtn) {
    let ticking = false;
    let isVisible = null;

    const applyScrollTopVisibility = () => {
      const nextVisible = window.scrollY > 400;
      if (nextVisible !== isVisible) {
        scrollTopBtn.classList.toggle("show", nextVisible);
        isVisible = nextVisible;
      }
    };

    const onScroll = () => {
      if (ticking) return;
      ticking = true;
      window.requestAnimationFrame(() => {
        applyScrollTopVisibility();
        ticking = false;
      });
    };

    window.addEventListener("scroll", onScroll, { passive: true });
    applyScrollTopVisibility();

    scrollTopBtn.addEventListener("click", () => {
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  }
});
