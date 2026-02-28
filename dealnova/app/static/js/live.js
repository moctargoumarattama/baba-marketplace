(() => {
  const body = document.body;
  if (!body) return;
  let ordersLiveStarted = false;
  const pollers = new Map();

  const csrfToken = (() => {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    if (window.csrfToken) return window.csrfToken;
    return '';
  })();

  function showToast(message, type) {
    if (!message) return;
    const toast = document.createElement('div');
    const isError = type === 'error' || type === 'danger';
    const isInfo = type === 'info';
    toast.textContent = message;
    toast.style.cssText = [
      'position:fixed',
      'right:20px',
      'bottom:20px',
      'z-index:9999',
      'max-width:320px',
      'background:' + (isError ? '#DC2626' : isInfo ? '#2563EB' : '#16A34A'),
      'color:#fff',
      'padding:12px 16px',
      'border-radius:12px',
      'box-shadow:0 18px 36px rgba(15,23,42,0.25)',
      'font-size:0.95rem',
      'opacity:0',
      'transform:translateY(10px)',
      'transition:all .18s ease'
    ].join(';');
    document.body.appendChild(toast);
    requestAnimationFrame(() => {
      toast.style.opacity = '1';
      toast.style.transform = 'translateY(0)';
    });
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(8px)';
      setTimeout(() => toast.remove(), 200);
    }, 3000);
  }

  function showAlert(message, type) {
    if (!message) return;
    if (document.body) {
      showToast(message, type || 'error');
      return;
    }
    alert(message);
  }

  function setButtonLoading(btn, loading) {
    if (!btn) return;
    if (loading) {
      btn.dataset.originalText = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = btn.dataset.loadingText || '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>Chargement';
    } else {
      if (btn.dataset.originalText) btn.innerHTML = btn.dataset.originalText;
      btn.disabled = false;
    }
  }

  function buildIconHtml(iconClass) {
    if (!iconClass) return '';
    return `<i class="${iconClass}"></i>`;
  }

  function applyToggleState(btn, isActive) {
    if (!btn) return;
    const activeText = btn.dataset.activeText;
    const inactiveText = btn.dataset.inactiveText;
    const activeIcon = btn.dataset.activeIcon;
    const inactiveIcon = btn.dataset.inactiveIcon;
    const activeClass = btn.dataset.activeClass;
    const inactiveClass = btn.dataset.inactiveClass;

    if (activeClass || inactiveClass) {
      if (activeClass) btn.classList.remove(activeClass);
      if (inactiveClass) btn.classList.remove(inactiveClass);
      const cls = isActive ? activeClass : inactiveClass;
      if (cls) btn.classList.add(cls);
    }

    const text = isActive ? activeText : inactiveText;
    const icon = isActive ? activeIcon : inactiveIcon;
    if (text || icon) {
      const html = `${buildIconHtml(icon)}${text ? ' ' + text : ''}`.trim();
      if (html) btn.innerHTML = html;
    }
  }

  function updateBadge(badge, isActive) {
    if (!badge) return;
    const activeText = badge.dataset.activeText || 'Actif';
    const inactiveText = badge.dataset.inactiveText || 'Inactif';
    const activeClass = badge.dataset.activeClass || 'bg-success';
    const inactiveClass = badge.dataset.inactiveClass || 'bg-secondary';

    badge.textContent = isActive ? activeText : inactiveText;
    badge.classList.remove(activeClass, inactiveClass);
    badge.classList.add(isActive ? activeClass : inactiveClass);
  }

  function removeClosest(el, selector) {
    if (!el) return;
    const target = el.closest(selector || 'tr');
    if (target) target.remove();
  }

  function cleanupStuckModalState() {
    const hasModal = !!document.querySelector('.modal.show');
    if (hasModal) return;
    document.querySelectorAll('.modal-backdrop').forEach((el) => el.remove());

    const sidebar = document.getElementById('sidebar');
    const sidebarBackdrop = document.getElementById('sidebarBackdrop');
    const sidebarIsOpen = !!(sidebar && sidebar.classList.contains('show'));
    if (sidebarBackdrop && !sidebarIsOpen) {
      sidebarBackdrop.classList.remove('show');
    }

    document.body.classList.remove('modal-open');

    if (!sidebarIsOpen) {
      document.body.style.overflow = '';
      document.body.style.paddingRight = '';
    }
  }

  document.addEventListener('hidden.bs.modal', () => {
    setTimeout(cleanupStuckModalState, 50);
  });

  document.addEventListener('show.bs.modal', (e) => {
    const modalEl = e && e.target;
    if (!modalEl || !document.body) return;
    if (modalEl.parentElement !== document.body) {
      document.body.appendChild(modalEl);
    }
  });

  function renderStatus(status) {
    if (status === 'pending') {
      return '<span class="status-pill status-pending"><i class="bi bi-clock"></i> En attente</span>';
    }
    if (status === 'delivered') {
      return '<span class="status-pill status-delivered"><i class="bi bi-check-circle"></i> Livree</span>';
    }
    if (status === 'cancelled') {
      return '<span class="status-pill status-cancelled"><i class="bi bi-x-circle"></i> Annulee</span>';
    }
    return `<span class="status-pill status-pending">${status || ''}</span>`;
  }

  function updateOrderRow(orderId, status) {
    if (!orderId) return;
    const row = document.querySelector(`[data-order-id="${orderId}"]`);
    if (!row) return;
    const statusEl = row.querySelector('[data-order-status]');
    if (statusEl) statusEl.innerHTML = renderStatus(status);
    row.classList.toggle('order-row-pending', status === 'pending');
    if (row.dataset.orderSection === 'pending' && status !== 'pending') {
      row.remove();
    }
  }

  async function handleAjaxForm(form) {
    const confirmMessage = form.dataset.confirm;
    if (confirmMessage && !confirm(confirmMessage)) return;

    const submitBtn = form.querySelector('button[type="submit"]');
    setButtonLoading(submitBtn, true);

    const formData = new FormData(form);

    try {
      const res = await fetch(form.action, {
        method: form.method || 'POST',
        body: formData,
        headers: {
          'X-Requested-With': 'fetch',
          'X-CSRFToken': csrfToken,
          'Accept': 'application/json'
        }
      });

      let data = {};
      try {
        data = await res.json();
      } catch (e) {
        data = {};
      }

      if (!res.ok || data.success === false) {
        const msg = data.message || 'Erreur lors de la modification.';
        showAlert(msg, 'error');
        setButtonLoading(submitBtn, false);
        return;
      }

      const action = form.dataset.action;
      const successMsg = data.message || form.dataset.successMessage;
      if (successMsg) {
        showToast(successMsg, 'success');
      } else if (action) {
        showToast('Action effectuee', 'success');
      }
      if (action === 'toggle-user') {
        const isActive = !!data.is_active;
        applyToggleState(submitBtn, isActive);
        if (data.user_id) {
          document.querySelectorAll(`[data-user-status="${data.user_id}"]`).forEach((el) => updateBadge(el, isActive));
        }
      } else if (action === 'delete-user' || action === 'delete-shop' || action === 'delete-product') {
        const shouldRedirect = form.dataset.redirect === 'true';
        if (shouldRedirect && data.redirect_url) {
          window.location.href = data.redirect_url;
        } else {
          removeClosest(form, form.dataset.removeTarget || 'tr');
        }
      } else if (action === 'toggle-shop' || action === 'toggle-vendor-shop') {
        const isActive = !!data.is_active;
        applyToggleState(submitBtn, isActive);
        if (data.shop_id) {
          document.querySelectorAll(`[data-shop-status="${data.shop_id}"]`).forEach((el) => updateBadge(el, isActive));
        }
      } else if (action === 'order-status') {
        updateOrderRow(data.order_id, data.status);
      }

      setButtonLoading(submitBtn, false);
    } catch (e) {
      showAlert('Erreur lors de la requete.', 'error');
      setButtonLoading(submitBtn, false);
    }
  }

  document.addEventListener('submit', (e) => {
    const form = e.target;
    if (!form || form.dataset.ajax !== 'true') return;
    e.preventDefault();
    handleAjaxForm(form);
  });

  function collectFormValues(root) {
    const values = {};
    if (!root) return values;
    root.querySelectorAll('input, select, textarea').forEach((el) => {
      if (!el.name) return;
      if (el.type === 'checkbox') {
        values[el.name] = el.checked;
      } else if (el.type === 'radio') {
        if (el.checked) values[el.name] = el.value;
      } else {
        values[el.name] = el.value;
      }
    });
    return values;
  }

  function applyFormValues(root, values) {
    if (!root) return;
    Object.keys(values).forEach((key) => {
      const fields = root.querySelectorAll(`[name="${key}"]`);
      fields.forEach((field) => {
        if (field.type === 'checkbox') {
          field.checked = !!values[key];
        } else if (field.type === 'radio') {
          field.checked = field.value === values[key];
        } else {
          field.value = values[key];
        }
      });
    });
  }

  function setupPaginationForTable(table) {
    const pageSize = parseInt(table.dataset.pageSize || '10', 10);
    if (!pageSize || pageSize <= 0) return;

    const tbody = table.tBodies[0];
    if (!tbody) return;

    const rows = Array.from(tbody.rows).filter((row) => !row.querySelector('.fraud-empty'));
    const tableWrap = table.closest('.table-responsive');
    if (!tableWrap) return;

    const existingPager = tableWrap.nextElementSibling;
    if (existingPager && existingPager.classList.contains('fraud-pager')) {
      existingPager.remove();
    }

    if (rows.length <= pageSize) {
      rows.forEach((row) => (row.style.display = ''));
      return;
    }

    let currentPage = 1;
    const totalPages = Math.ceil(rows.length / pageSize);

    const pager = document.createElement('div');
    pager.className = 'fraud-pager';
    const prevBtn = document.createElement('button');
    prevBtn.type = 'button';
    prevBtn.textContent = 'Precedent';
    const nextBtn = document.createElement('button');
    nextBtn.type = 'button';
    nextBtn.textContent = 'Suivant';
    const info = document.createElement('div');
    info.className = 'fraud-page-info';
    pager.appendChild(prevBtn);
    pager.appendChild(info);
    pager.appendChild(nextBtn);
    tableWrap.insertAdjacentElement('afterend', pager);

    function render() {
      const start = (currentPage - 1) * pageSize;
      const end = start + pageSize;
      rows.forEach((row, idx) => {
        row.style.display = idx >= start && idx < end ? '' : 'none';
      });
      info.textContent = `Page ${currentPage} / ${totalPages} - ${rows.length} elements`;
      prevBtn.disabled = currentPage <= 1;
      nextBtn.disabled = currentPage >= totalPages;
    }

    prevBtn.addEventListener('click', () => {
      if (currentPage > 1) {
        currentPage -= 1;
        render();
      }
    });
    nextBtn.addEventListener('click', () => {
      if (currentPage < totalPages) {
        currentPage += 1;
        render();
      }
    });

    render();
  }

  function initFraudPage(root) {
    const scope = root || document;
    const cleanBtn = scope.querySelector('#fraudCleanTwoDays');
    if (cleanBtn && !cleanBtn.dataset.bound) {
      cleanBtn.dataset.bound = 'true';
      cleanBtn.addEventListener('click', () => {
        const form = scope.querySelector('#fraudFiltersForm');
        if (!form) return;
        const days = form.querySelector('input[name="days"]');
        if (days) days.value = 2;
        form.submit();
      });
    }

    scope.querySelectorAll('.fraud-table').forEach(setupPaginationForTable);
  }

  window.initFraudPage = initFraudPage;

  function stopPoller(key) {
    const poller = pollers.get(key);
    if (poller && typeof poller.stop === 'function') poller.stop();
    pollers.delete(key);
  }

  function startAdaptivePoll(key, fn, options) {
    stopPoller(key);
    const config = options || {};
    const activeInterval = Number(config.activeInterval || 5000);
    const inactiveInterval = Number(config.inactiveInterval || Math.max(activeInterval * 3, 30000));
    const runWhenHidden = !!config.runWhenHidden;
    let timer = null;
    let stopped = false;

    async function tick(force) {
      if (stopped) return;
      const hidden = document.hidden;
      if (force || !hidden || runWhenHidden) {
        try {
          await fn();
        } catch (e) {}
      }
      const interval = document.hidden ? inactiveInterval : activeInterval;
      timer = setTimeout(() => tick(false), interval);
    }

    tick(true);
    const poller = {
      stop() {
        stopped = true;
        if (timer) clearTimeout(timer);
      },
      refresh() {
        if (!stopped) tick(true);
      }
    };
    pollers.set(key, poller);
    return poller;
  }

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
      pollers.forEach((poller) => {
        if (poller && typeof poller.refresh === 'function') poller.refresh();
      });
    }
  });


  function initOrdersLive() {
    const liveUrl = body.dataset.liveUrl;
    if (!liveUrl) return;
    const ordersTableBody = document.querySelector('.orders-table-list tbody');
    const totalOrdersStat = document.getElementById('totalOrdersStat');
    const totalCommissionStat = document.getElementById('totalCommissionStat');
    const ordersPageCount = document.getElementById('ordersPageCount');
    const updatePending = typeof window.updatePending === 'function' ? window.updatePending : () => {};

    function escapeHtml(value) {
      const div = document.createElement('div');
      div.textContent = value == null ? '' : String(value);
      return div.innerHTML;
    }

    function safeUrl(url) {
      const u = String(url || '');
      if (u.startsWith('/') || u.startsWith('http://') || u.startsWith('https://') || u.startsWith('tel:') || u.startsWith('mailto:')) {
        return u;
      }
      return '#';
    }

    function renderOrderRow(order) {
      const pending = order.status === 'pending';
      const rowClass = pending ? 'order-row-pending' : '';
      const total = Number(order.total || 0).toFixed(2);
      const deliveryPrice = Number(order.delivery_price || 0).toFixed(2);
      const babaFee = Number(order.delivery_platform_fee || 0).toFixed(2);
      const courierNet = Number(order.delivery_courier_net || 0).toFixed(2);
      const productLines = (order.items || []).map((item) => {
        const name = escapeHtml(item.name || '');
        const price = Number(item.price || 0).toFixed(2);
        const qty = Number(item.qty || 0);
        return `<div class="product-line"><span>${name}</span><span class="text-muted">${price} MAD x${qty}</span></div>`;
      }).join('');
      const productsCell = `<div class="product-lines">${productLines || '<span class="text-muted">-</span>'}</div>`;
      const detailUrl = safeUrl(order.detail_url);
      const callUrl = safeUrl(order.call_url);
      const actionButtons = `<div class="d-flex gap-2 flex-wrap"><a href="${detailUrl}" class="btn btn-sm btn-primary"><i class="bi bi-eye"></i></a><a href="${callUrl}" class="btn btn-sm btn-outline-primary"><i class="bi bi-telephone"></i></a></div>`;
      const fullName = escapeHtml(order.full_name || '');
      const phone = escapeHtml(order.phone || '');
      const city = escapeHtml(order.city || '');
      const createdAt = escapeHtml(order.created_at || '');
      const courierName = escapeHtml(order.courier_name || '');
      const courierCell = courierName ? `<div class="small fw-semibold">Assigne a: ${courierName}</div>` : '<div class="small text-muted">Non assignee</div>';
      return `<tr class="${rowClass}"><td>${order.id}</td><td><div class="fw-semibold">${fullName}</div><small class="text-muted">${phone}</small></td><td>${city}</td><td>${productsCell}</td><td>${total} MAD</td><td>${deliveryPrice} MAD</td><td><span class="badge bg-warning text-dark">${babaFee} MAD</span></td><td>${courierNet} MAD</td><td>${courierCell}</td><td>${renderStatus(order.status)}</td><td><small>${createdAt}</small></td><td class="order-actions">${actionButtons}</td></tr>`;
    }

  async function refreshOrdersPage() {
      if (!ordersTableBody) return;
      try {
        const res = await fetch(liveUrl, { cache: 'no-store' });
        if (!res.ok) return;
        const data = await res.json();
        if (!data) return;
        updatePending(data.pending_count || 0);
        if (totalOrdersStat) totalOrdersStat.textContent = data.total_orders ?? totalOrdersStat.textContent;
        if (totalCommissionStat) totalCommissionStat.textContent = `${Number(data.total_baba_fee || data.total_commission || 0).toFixed(2)} MAD`;
        if (ordersPageCount) ordersPageCount.textContent = `${(data.orders || []).length} commandes sur cette page`;
        if (Array.isArray(data.orders)) ordersTableBody.innerHTML = data.orders.map(renderOrderRow).join('');
      } catch (e) {}
  }

    const interval = parseInt(body.dataset.interval || '15000', 10);
    if (!ordersLiveStarted) {
      ordersLiveStarted = true;
      startAdaptivePoll('orders', refreshOrdersPage, {
        activeInterval: interval,
        inactiveInterval: Math.max(interval * 3, 30000)
      });
    } else {
      startAdaptivePoll('orders', refreshOrdersPage, {
        activeInterval: interval,
        inactiveInterval: Math.max(interval * 3, 30000)
      });
    }
  }

  function initOrderNotifications() {
    const notifyUrl = body.dataset.notifyUrl;
    if (!notifyUrl) return;
    const interval = parseInt(body.dataset.notifyInterval || '20000', 10);
    const notifyKey = body.dataset.notifyKey || 'adminLastOrderId';

    const orderToast = document.getElementById('admin-order-toast');
    const orderToastText = document.getElementById('admin-order-toast-text');
    const sidebarBadge = document.getElementById('sidebarPendingBadge');
    const sidebarToConfirmBadge = document.getElementById('sidebarToConfirmBadge');
    const navPendingBadge = document.getElementById('navPendingBadge');
    const navToConfirmBadge = document.getElementById('navToConfirmBadge');
    const pendingCountEl = document.getElementById('pendingCount');
    const pendingStatEl = document.getElementById('pendingStat');
    const pendingPill = document.getElementById('pendingPill');
    const toConfirmCountEl = document.getElementById('toConfirmCount');
    const toConfirmStatEl = document.getElementById('toConfirmStat');
    const toConfirmPill = document.getElementById('toConfirmPill');
    const soundToggle = document.getElementById('soundToggle');

    let soundEnabled = localStorage.getItem('adminOrderSound') !== '0';
    function updateSoundToggle() {
      if (!soundToggle) return;
      soundToggle.innerHTML = soundEnabled ? '<i class="bi bi-volume-up"></i> Son On' : '<i class="bi bi-volume-mute"></i> Son Off';
    }
    updateSoundToggle();

    if (soundToggle) {
      soundToggle.addEventListener('click', () => {
        soundEnabled = !soundEnabled;
        localStorage.setItem('adminOrderSound', soundEnabled ? '1' : '0');
        updateSoundToggle();
      });
    }

    function playPing() {
      if (!soundEnabled) return;
      try {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        const ctx = new AudioCtx();
        const notes = [880, 1174, 988];
        let t = ctx.currentTime;
        notes.forEach((freq) => {
          const osc = ctx.createOscillator();
          const gain = ctx.createGain();
          osc.type = 'sine';
          osc.frequency.value = freq;
          gain.gain.value = 0.0001;
          osc.connect(gain);
          gain.connect(ctx.destination);
          osc.start(t);
          gain.gain.exponentialRampToValueAtTime(0.16, t + 0.05);
          gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.3);
          osc.stop(t + 0.32);
          t += 0.12;
        });
      } catch (e) {}
    }

    function escapeHtml(value) {
      const div = document.createElement('div');
      div.textContent = value == null ? '' : String(value);
      return div.innerHTML;
    }

    function buildItemsText(items) {
      if (!Array.isArray(items) || !items.length) return '';
      const parts = items.slice(0, 3).map((item) => {
        const name = escapeHtml(item.name || 'Produit');
        const qty = Number(item.qty || item.quantity || 0);
        return `${name} x${qty}`;
      });
      if (items.length > 3) parts.push(`+${items.length - 3} autres`);
      return parts.join(', ');
    }

    function showToast(pendingCount, message, items) {
      if (!orderToast || !orderToastText) return;
      const itemsText = buildItemsText(items);
      const text = message || itemsText || (pendingCount > 0 ? `${pendingCount} commande(s) en attente` : 'Nouvelle commande');
      orderToastText.textContent = text;
      orderToast.classList.add('show');
      setTimeout(() => orderToast.classList.remove('show'), 3200);
    }

    function updatePending(count) {
      if (pendingCountEl) pendingCountEl.textContent = count;
      if (pendingStatEl) pendingStatEl.textContent = count;
      if (pendingPill) pendingPill.style.opacity = count > 0 ? '1' : '0.6';
      if (sidebarBadge) {
        sidebarBadge.textContent = count;
        sidebarBadge.classList.toggle('is-hidden', !count);
      }
      if (navPendingBadge) {
        navPendingBadge.textContent = count;
        navPendingBadge.classList.toggle('is-hidden', !count);
      }
    }
    window.updatePending = updatePending;

    function updateToConfirm(count) {
      const val = Number(count || 0);
      if (toConfirmCountEl) toConfirmCountEl.textContent = val;
      if (toConfirmStatEl) toConfirmStatEl.textContent = val;
      if (toConfirmPill) toConfirmPill.classList.toggle('is-hidden', !val);
      if (sidebarToConfirmBadge) {
        sidebarToConfirmBadge.textContent = val;
        sidebarToConfirmBadge.classList.toggle('is-hidden', !val);
      }
      if (navToConfirmBadge) {
        navToConfirmBadge.textContent = val;
        navToConfirmBadge.classList.toggle('is-hidden', !val);
      }
    }
    window.updateToConfirm = updateToConfirm;

    let lastNotified = Number(localStorage.getItem(notifyKey) || 0);
    let notifInitialized = false;

    async function pollOrders() {
      try {
        const res = await fetch(notifyUrl, { cache: 'no-store' });
        if (!res.ok) return;
        const data = await res.json();
        if (!data) return;
        updatePending(data.pending_count || 0);
        updateToConfirm(data.to_confirm_count || 0);
        if (!notifInitialized && !lastNotified) {
          lastNotified = data.latest_id || 0;
          localStorage.setItem(notifyKey, String(lastNotified));
          notifInitialized = true;
          return;
        }
        if (data.latest_id && data.latest_id > lastNotified) {
          lastNotified = data.latest_id;
          localStorage.setItem(notifyKey, String(lastNotified));
          showToast(data.pending_count || 0, data.message || '', data.items || []);
          playPing();
        }
        notifInitialized = true;
        if (body.dataset.live === 'orders') {
          initOrdersLive();
        }
      } catch (e) {}
    }

    startAdaptivePoll('notify', pollOrders, {
      activeInterval: interval,
      inactiveInterval: Math.max(interval * 3, 30000),
      runWhenHidden: false
    });
  }

  function initDeliveriesLive() {
    const liveUrl = body.dataset.liveUrl;
    if (!liveUrl) return;

    const deliveriesPage = document.querySelector('[data-deliveries-page="true"]');
    if (!deliveriesPage) return;
    let readOnly = deliveriesPage.dataset.readOnly === '1';

    const pendingTableBody = document.getElementById('pendingTableBody');
    const historyTableBody = document.getElementById('historyTableBody');
    const pendingCountLabel = document.getElementById('pendingCountLabel');
    const historyTotalLabel = document.getElementById('historyTotalLabel');
    const pendingStat = document.getElementById('pendingStat');
    const deliveredStat = document.getElementById('deliveredStat');
    const commissionStat = document.getElementById('commissionStat');
    const availableCouriersStat = document.getElementById('availableCouriersStat');

    function escapeHtml(value) {
      const div = document.createElement('div');
      div.textContent = value == null ? '' : String(value);
      return div.innerHTML;
    }

    function safeUrl(url) {
      const u = String(url || '');
      if (u.startsWith('/') || u.startsWith('http://') || u.startsWith('https://') || u.startsWith('tel:') || u.startsWith('mailto:')) {
        return u;
      }
      return '#';
    }

    function getValue(name) {
      const el = document.querySelector(`[name="${name}"]`);
      return el ? el.value : '';
    }

    function buildQuery() {
      const params = new URLSearchParams();
      const page = deliveriesPage.dataset.page || new URLSearchParams(window.location.search).get('page') || '1';
      params.set('page', page);

      const fields = ['period_id', 'status', 'from', 'to', 'product', 'shop', 'city', 'client', 'phone'];
      fields.forEach((field) => {
        params.set(field, getValue(field) || '');
      });
      const includeLegacy = document.querySelector('[name="include_legacy"]');
      params.set('include_legacy', includeLegacy && includeLegacy.checked ? '1' : '');
      return params.toString();
    }

    function buildLiveUrl(query) {
      const url = new URL(liveUrl, window.location.origin);
      const params = new URLSearchParams(query);
      params.forEach((value, key) => {
        if (!value) {
          url.searchParams.delete(key);
        } else {
          url.searchParams.set(key, value);
        }
      });
      return `${url.pathname}?${url.searchParams.toString()}`;
    }

    function renderStatus(status) {
      if (status === 'pending') {
        return '<span class="status-pill status-pending"><i class="bi bi-clock"></i> En attente</span>';
      }
      if (status === 'delivered') {
        return '<span class="status-pill status-delivered"><i class="bi bi-check-circle"></i> Livree</span>';
      }
      if (status === 'cancelled') {
        return '<span class="status-pill status-cancelled"><i class="bi bi-x-circle"></i> Annulee</span>';
      }
      return `<span class="status-pill status-pending">${escapeHtml(status)}</span>`;
    }

    function renderPendingRow(order) {
      const canMutate = !readOnly && !!order.can_mutate;
      const products = (order.product_names || []).map(escapeHtml).join(', ');
      const shops = (order.shop_names || []).map(escapeHtml).join(', ');
      const fullName = escapeHtml(order.full_name || '');
      const phone = escapeHtml(order.phone || '');
      const city = escapeHtml(order.city || '');
      const detailUrl = safeUrl(order.detail_url);
      const callUrl = safeUrl(order.call_url);
      const deliverUrl = safeUrl(order.deliver_url);
      const cancelUrl = safeUrl(order.cancel_url);
      const courierName = escapeHtml(order.courier_name || '');
      const courierCell = courierName ? `<div class="small fw-semibold">Assigne a: ${courierName}</div>` : '<div class="small text-muted">Non assignee</div>';
      const deliveryPrice = Number(order.delivery_price || 0).toFixed(2);
      const babaFee = Number(order.delivery_platform_fee || 0).toFixed(2);
      const courierNet = Number(order.delivery_courier_net || 0).toFixed(2);
      const babaSettled = !!order.baba_fee_settled;
      const babaCell = `<span class="badge bg-warning text-dark">${babaFee} MAD</span>${babaSettled ? '<div class="small text-success">Remis</div>' : ''}`;
      const mutateActions = canMutate
        ? `
              <form method="POST" action="${deliverUrl}" class="d-inline" data-ajax="true" data-action="order-status" data-order-id="${order.id}">
                <input type="hidden" name="csrf_token" value="${csrfToken}">
                <button class="btn btn-success btn-sm" type="submit">
                  <i class="bi bi-check-circle me-1"></i>Livree
                </button>
              </form>
              <form method="POST" action="${cancelUrl}" class="d-inline" data-ajax="true" data-action="order-status" data-order-id="${order.id}" data-confirm="Annuler cette commande ?">
                <input type="hidden" name="csrf_token" value="${csrfToken}">
                <button class="btn btn-outline-danger btn-sm" type="submit">
                  <i class="bi bi-x-circle me-1"></i>Annuler
                </button>
              </form>
            `
        : '<span class="badge text-bg-secondary align-self-center">Lecture seule</span>';
      return `
        <tr class="order-row-pending" data-order-id="${order.id}" data-order-section="pending">
          <td>${order.id}</td>
          <td>
            <div class="fw-semibold">${fullName}</div>
            <small class="text-muted">${phone}</small>
          </td>
          <td>${city}</td>
          <td><div class="list-text">${products}</div></td>
          <td><div class="list-text">${shops}</div></td>
          <td>${Number(order.total || 0).toFixed(2)} MAD</td>
          <td>${deliveryPrice} MAD</td>
          <td>${babaCell}</td>
          <td>${courierNet} MAD</td>
          <td>${courierCell}</td>
          <td class="order-actions">
            <div class="d-flex gap-2 flex-wrap">
              <a href="${detailUrl}" class="btn btn-sm btn-primary">
                <i class="bi bi-eye"></i>
              </a>
              <a href="${callUrl}" class="btn btn-sm btn-outline-primary">
                <i class="bi bi-telephone"></i>
              </a>
              ${mutateActions}
            </div>
          </td>
        </tr>
      `;
    }

    function renderHistoryRow(order) {
      const canMutate = !readOnly && !!order.can_mutate;
      const products = (order.product_names || []).map(escapeHtml).join(', ');
      const shops = (order.shop_names || []).map(escapeHtml).join(', ');
      const statusCell = renderStatus(order.status);
      const fullName = escapeHtml(order.full_name || '');
      const phone = escapeHtml(order.phone || '');
      const city = escapeHtml(order.city || '');
      const createdAt = escapeHtml(order.created_at || '');
      const detailUrl = safeUrl(order.detail_url);
      const callUrl = safeUrl(order.call_url);
      const deliverUrl = safeUrl(order.deliver_url);
      const cancelUrl = safeUrl(order.cancel_url);
      const courierName = escapeHtml(order.courier_name || '');
      const courierCell = courierName ? `<div class="small fw-semibold">Assigne a: ${courierName}</div>` : '<div class="small text-muted">Non assignee</div>';
      const deliveryPrice = Number(order.delivery_price || 0).toFixed(2);
      const babaFee = Number(order.delivery_platform_fee || 0).toFixed(2);
      const courierNet = Number(order.delivery_courier_net || 0).toFixed(2);
      const babaSettled = !!order.baba_fee_settled;
      const babaCell = `<span class="badge bg-warning text-dark">${babaFee} MAD</span>${babaSettled ? '<div class="small text-success">Remis</div>' : ''}`;
      const mutateActions = (order.status === 'pending' && canMutate)
        ? `
            <form method="POST" action="${deliverUrl}" class="d-inline" data-ajax="true" data-action="order-status" data-order-id="${order.id}">
              <input type="hidden" name="csrf_token" value="${csrfToken}">
              <button class="btn btn-success btn-sm" type="submit">
                <i class="bi bi-check-circle me-1"></i>Livree
              </button>
            </form>
            <form method="POST" action="${cancelUrl}" class="d-inline" data-ajax="true" data-action="order-status" data-order-id="${order.id}" data-confirm="Annuler cette commande ?">
              <input type="hidden" name="csrf_token" value="${csrfToken}">
              <button class="btn btn-outline-danger btn-sm" type="submit">
                <i class="bi bi-x-circle me-1"></i>Annuler
              </button>
            </form>
          `
        : (readOnly ? '<span class="badge text-bg-secondary align-self-center">Lecture seule</span>' : '');
      const actions = `
        <div class="d-flex gap-2 flex-wrap">
          <a href="${detailUrl}" class="btn btn-sm btn-primary">
            <i class="bi bi-eye"></i>
          </a>
          <a href="${callUrl}" class="btn btn-sm btn-outline-primary">
            <i class="bi bi-telephone"></i>
          </a>
          ${mutateActions}
        </div>
      `;

      return `
        <tr class="${order.status === 'pending' ? 'order-row-pending' : ''}" data-order-id="${order.id}" data-order-section="history">
          <td>${order.id}</td>
          <td>
            <div class="fw-semibold">${fullName}</div>
            <small class="text-muted">${phone}</small>
          </td>
          <td>${city}</td>
          <td><div class="list-text">${products}</div></td>
          <td><div class="list-text">${shops}</div></td>
          <td>${Number(order.total || 0).toFixed(2)} MAD</td>
          <td>${deliveryPrice} MAD</td>
          <td>${babaCell}</td>
          <td>${courierNet} MAD</td>
          <td>${courierCell}</td>
          <td data-order-status>${statusCell}</td>
          <td><small>${createdAt}</small></td>
          <td class="order-actions">${actions}</td>
        </tr>
      `;
    }

    async function refreshDeliveries() {
      try {
        const query = buildQuery();
        const res = await fetch(buildLiveUrl(query), { cache: 'no-store' });
        if (!res.ok) return;
        const data = await res.json();
        if (!data) return;
        readOnly = !!data.read_only;
        deliveriesPage.dataset.readOnly = readOnly ? '1' : '0';
        if (data.page) deliveriesPage.dataset.page = String(data.page);

        if (pendingCountLabel) pendingCountLabel.textContent = data.pending_count || 0;
        if (historyTotalLabel) historyTotalLabel.textContent = data.history_total || 0;
        if (pendingStat) pendingStat.textContent = data.pending_count || 0;
        if (deliveredStat) deliveredStat.textContent = data.delivered_recent_count || 0;
        if (commissionStat) commissionStat.textContent = `${Number(data.total_baba_fee || data.total_commission || 0).toFixed(2)} MAD`;
        if (availableCouriersStat) availableCouriersStat.textContent = Number(data.available_couriers_count || 0);

        const pendingRows = data.pending || data.pending_orders || [];
        const historyRows = data.history || data.history_orders || [];
        if (pendingTableBody) {
          pendingTableBody.innerHTML = pendingRows.map(renderPendingRow).join('') || '';
        }
        if (historyTableBody) {
          historyTableBody.innerHTML = historyRows.map(renderHistoryRow).join('') || '';
        }
      } catch (e) {}
    }

    const interval = parseInt(body.dataset.interval || '15000', 10);
    startAdaptivePoll('deliveries', refreshDeliveries, {
      activeInterval: interval,
      inactiveInterval: Math.max(interval * 3, 30000)
    });
  }

  function initLiveFeatures() {
    const liveType = body.dataset.live;
    stopPoller('orders');
    stopPoller('deliveries');
    if (liveType === 'orders') initOrdersLive();
    if (liveType === 'deliveries') initDeliveriesLive();
  }

  window.initLiveFeatures = initLiveFeatures;
  initLiveFeatures();
  initOrderNotifications();

})();
