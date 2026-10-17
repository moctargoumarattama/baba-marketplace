/* Run only against a disposable public preview. No write or external sharing occurs.
   PLAYWRIGHT_PACKAGE may point to an existing Playwright installation.
   PUBLIC_SHARE_LOCATION_URL may name an existing preview rental detail page. */
const assert = require('node:assert/strict');
const { chromium, webkit } = require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');
const base = process.env.PUBLIC_PREVIEW_URL || 'http://127.0.0.1:5059';
const origin = new URL(base).origin;
const productId = 900101;
const serviceId = 900202;

function product(id, kind, name) {
  return { id, kind, name, description: name + ' description', price: 25, final_price: 25,
    stock: 4, has_promo: false, images: [], category: 'Test', shop: null,
    share_url: origin + '/shop/product/' + id, whatsapp_order_url: 'https://wa.me/000',
    booking_url: kind === 'service' ? '/booking/' + id : null };
}
const products = {
  [productId]: product(productId, 'physical', 'Produit A'),
  [serviceId]: product(serviceId, 'service', 'Service B'),
};
const shops = {
  'share-shop-a': { id: 900301, slug: 'share-shop-a', name: 'Boutique A' },
  'share-shop-b': { id: 900302, slug: 'share-shop-b', name: 'Boutique B' },
};

async function installFixtureRoutes(page) {
  await page.route('**/api/product/*', route => {
    const id = new URL(route.request().url()).pathname.split('/').pop();
    return products[id] ? route.fulfill({ json: { success: true, product: products[id] } }) : route.continue();
  });
  await page.route('**/api/shop/*', route => {
    const slug = new URL(route.request().url()).pathname.split('/').pop();
    const shop = shops[slug];
    if (!shop) return route.continue();
    return route.fulfill({ json: { success: true, shop: { ...shop, is_open: true,
      description: shop.name + ' description', address: 'Rabat', logo: '', banner: '',
      is_verified: false, review_count: 0, whatsapp_url: 'https://wa.me/000', call_url: null,
      share_url: origin + '/shops/' + shop.slug }, products: [], product_count: 0 } });
  });
  await page.route('**/api/catalog?**', route => {
    const universe = new URL(route.request().url()).searchParams.get('universe');
    if (universe === 'locations') return route.continue();
    const items = universe === 'shops' ? Object.values(shops).map(shop => ({ ...shop,
      item_type: 'shop', kind: 'shop', description: '', shop_name: shop.name, image_url: '',
      url: '/shops/' + shop.slug })) : Object.values(products).map(p => ({ ...p,
      item_type: p.kind === 'service' ? 'service' : 'product', image_url: '',
      available: true, url: '/shop/product/' + p.id }));
    return route.fulfill({ json: { success: true, items, facets: {}, filters: {},
      pagination: { page: 1, pages: 1, total: items.length, per_page: 12, has_next: false, has_prev: false } } });
  });
}

async function configureStubs(page) {
  await page.addInitScript(() => {
    const state = window.__shareTest = { mode: 'none', clipMode: 'success', execResult: false,
      native: [], copied: [], exec: [], messages: [] };
    Object.defineProperty(navigator, 'share', { configurable: true, get() {
      if (state.mode === 'none') return undefined;
      return async payload => {
        state.native.push({ ...payload });
        if (state.mode === 'abort') throw new DOMException('Canceled', 'AbortError');
        if (state.mode === 'denied') throw new DOMException('Denied', 'NotAllowedError');
        if (state.mode === 'deferredDenied') {
          await new Promise((_resolve, reject) => {
            window.__rejectNativeShare = () => reject(new DOMException('Denied later', 'NotAllowedError'));
          });
        }
        if (state.mode === 'pending') await new Promise(resolve => setTimeout(resolve, 400));
      };
    } });
    Object.defineProperty(navigator, 'clipboard', { configurable: true, get() {
      if (state.clipMode === 'absent') return undefined;
      return { async writeText(value) {
        if (state.clipMode === 'reject') throw new DOMException('Denied', 'NotAllowedError');
        if (state.clipMode === 'deferredReject') {
          await new Promise((_resolve, reject) => {
            window.__rejectClipboardCopy = () => reject(new DOMException('Denied later', 'NotAllowedError'));
          });
        }
        state.copied.push(value);
      } };
    } });
    document.execCommand = command => {
      const active = document.activeElement;
      state.exec.push({ command, value: active && active.value,
        dialog: active && active.closest('[role="dialog"]')?.id });
      return state.execResult;
    };
  });
}

async function captureFeedback(page) {
  await page.waitForFunction(() => !!window.BMCoreShare && !!window.BMCoreUI);
  await page.evaluate(() => {
    const original = window.BMCoreUI.showToast;
    window.BMCoreUI.showToast = (message, type) => {
      window.__shareTest.messages.push({ message: String(message), type });
      if (original) original.call(window.BMCoreUI, message, type);
    };
  });
}

async function readyCatalog(page) {
  await page.waitForFunction(() => document.querySelector('#catalogResults')?.getAttribute('aria-busy') === 'false');
}

async function openDetail(page, type, value) {
  await readyCatalog(page);
  const attr = type === 'product' ? 'data-open-product-detail' : 'data-open-shop-detail';
  await page.locator('#catalogResults [' + attr + '="' + value + '"]').first().tap();
  const panel = page.locator(type === 'product' ? '#productDetailPanel' : '#shopDetailPanel');
  const button = panel.locator('[data-share-button]');
  await button.waitFor({ state: 'visible' });
  await page.waitForFunction(el => !el.disabled && !!el.getAttribute('data-share-url'), await button.elementHandle());
  return button;
}

async function backToCatalog(page, type) {
  await page.keyboard.press('Escape');
  await page.waitForFunction(selector => document.querySelector(selector)?.getAttribute('aria-hidden') === 'true',
    type === 'product' ? '#productDetailPanel' : '#shopDetailPanel');
  await page.waitForFunction(selector => {
    const panel = document.querySelector(selector);
    return panel.hidden || (panel.classList.contains('is-covered') &&
      !panel.classList.contains('is-closing') && !panel.classList.contains('is-opening'));
  }, type === 'product' ? '#productDetailPanel' : '#shopDetailPanel');
  await readyCatalog(page);
}

async function snapshot(page) { return page.evaluate(() => structuredClone(window.__shareTest)); }

async function run(name, engine) {
  const browser = await engine.launch({ headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true,
      hasTouch: true, serviceWorkers: 'block' });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await configureStubs(page);
    await installFixtureRoutes(page);
    await page.goto(base + '/?open=search', { waitUntil: 'networkidle' });
    await captureFeedback(page);
    assert.equal(await page.locator('script[src*="core_share.js"]').count(), 1, 'one shared implementation');

    let share = await openDetail(page, 'product', productId);
    await share.tap();
    await page.waitForFunction(() => window.__shareTest.copied.length === 1);
    assert.equal((await snapshot(page)).copied[0], products[productId].share_url);
    await backToCatalog(page, 'product');
    let releaseResponse;
    let markStarted;
    const heldResponse = new Promise(resolve => { releaseResponse = resolve; });
    const responseStarted = new Promise(resolve => { markStarted = resolve; });
    await page.route('**/api/product/' + serviceId, async route => {
      markStarted();
      await heldResponse;
      await route.fallback();
    }, { times: 1 });
    await page.locator('#catalogResults [data-open-product-detail="' + serviceId + '"]').first().tap();
    await responseStarted;
    share = page.locator('#productDetailPanel [data-share-button]');
    assert.equal(await share.isDisabled(), true, 'cannot share previous item while B loads');
    assert(!await share.getAttribute('data-share-url'), 'old URL cleared before new response');
    releaseResponse();
    await page.waitForFunction(el => !el.disabled && !!el.getAttribute('data-share-url'), await share.elementHandle());
    await share.tap();
    await page.waitForFunction(() => window.__shareTest.copied.length === 2);
    assert.equal((await snapshot(page)).copied[1], products[serviceId].share_url, 'reopened modal shares B rather than A');

    await page.evaluate(() => { window.__shareTest.mode = 'success'; });
    await share.tap();
    await page.waitForFunction(() => window.__shareTest.native.length === 1);
    let state = await snapshot(page);
    assert.equal(state.native[0].url, products[serviceId].share_url);
    assert.match(state.native[0].title, /Service B/);
    assert.equal(state.copied.length, 2, 'native success does not copy');

    await page.evaluate(() => { window.__shareTest.mode = 'abort'; });
    const beforeCancel = await snapshot(page);
    await share.tap();
    await page.waitForFunction(() => window.__shareTest.native.length === 2);
    await page.waitForFunction(el => !el.disabled && el.getAttribute('aria-busy') !== 'true', await share.elementHandle());
    state = await snapshot(page);
    assert.equal(state.copied.length, beforeCancel.copied.length, 'cancel does not copy');
    assert.equal(state.messages.length, beforeCancel.messages.length, 'cancel is silent');

    await page.evaluate(() => { window.__shareTest.mode = 'denied'; });
    await share.tap();
    await page.waitForFunction(() => window.__shareTest.copied.length === 3);
    assert.equal((await snapshot(page)).copied[2], products[serviceId].share_url, 'native permission error falls back to copying');

    await page.evaluate(() => { window.__shareTest.mode = 'none'; window.__shareTest.clipMode = 'absent'; window.__shareTest.execResult = true; });
    await share.focus();
    // Keyboard activation preserves the known focus target across Safari's touch blur.
    await share.press('Enter');
    await page.waitForFunction(() => window.__shareTest.exec.length === 1);
    await page.waitForFunction(el => !el.disabled && el.getAttribute('aria-busy') !== 'true', await share.elementHandle());
    state = await snapshot(page);
    assert.equal(state.exec[0].command, 'copy');
    assert.equal(state.exec[0].value, products[serviceId].share_url);
    assert.equal(state.exec[0].dialog, 'productDetailPanel', 'copy input remains inside modal focus trap');
    assert.equal(await share.evaluate(el => document.activeElement === el), true, 'copy restores button focus');

    await page.evaluate(() => { window.__shareTest.clipMode = 'reject'; window.__shareTest.execResult = false; });
    const messageCount = (await snapshot(page)).messages.length;
    await share.tap();
    await page.waitForFunction(count => window.__shareTest.messages.length > count, messageCount);
    state = await snapshot(page);
    assert.match(state.messages.at(-1).message, /Impossible de copier/i);
    assert.equal(await page.locator('#productDetailPanel [data-share-status]').getAttribute('role'), 'status');
    assert.match(await page.locator('#productDetailPanel [data-share-status]').textContent(), /Impossible de copier/i);

    await page.evaluate(() => { window.__shareTest.mode = 'pending'; window.__shareTest.clipMode = 'success'; });
    const nativeCount = (await snapshot(page)).native.length;
    await share.dblclick();
    await page.waitForFunction(el => !el.disabled && el.getAttribute('aria-busy') !== 'true', await share.elementHandle());
    assert.equal((await snapshot(page)).native.length, nativeCount + 1, 'double click opens one share request');

    await backToCatalog(page, 'product');
    share = await openDetail(page, 'product', productId);
    await page.evaluate(() => { window.__shareTest.mode = 'deferredDenied'; });
    const beforeClosedShare = await snapshot(page);
    await share.tap();
    await page.waitForFunction(() => typeof window.__rejectNativeShare === 'function');
    await backToCatalog(page, 'product');
    await page.evaluate(() => { window.__rejectNativeShare(); delete window.__rejectNativeShare; });
    await page.waitForFunction(el => el.getAttribute('aria-busy') !== 'true', await share.elementHandle());
    state = await snapshot(page);
    assert.equal(state.copied.length, beforeClosedShare.copied.length, 'closed modal never copies after delayed native failure');
    assert.equal(state.exec.length, beforeClosedShare.exec.length, 'closed modal never falls back to old text');
    assert.equal(state.messages.length, beforeClosedShare.messages.length, 'closed modal never displays stale feedback');

    share = await openDetail(page, 'product', serviceId);
    await page.evaluate(() => { window.__shareTest.mode = 'none'; });
    await share.tap();
    await page.waitForFunction(count => window.__shareTest.copied.length === count, beforeClosedShare.copied.length + 1);
    assert.equal((await snapshot(page)).copied.at(-1), products[serviceId].share_url, 'new offer shares normally after earlier share was canceled');

    await page.evaluate(() => { window.__shareTest.clipMode = 'deferredReject'; window.__shareTest.execResult = true; });
    const beforeClosedCopy = await snapshot(page);
    await share.tap();
    await page.waitForFunction(() => typeof window.__rejectClipboardCopy === 'function');
    await backToCatalog(page, 'product');
    await page.evaluate(() => { window.__rejectClipboardCopy(); delete window.__rejectClipboardCopy; });
    await page.waitForFunction(el => el.getAttribute('aria-busy') !== 'true', await share.elementHandle());
    state = await snapshot(page);
    assert.equal(state.copied.length, beforeClosedCopy.copied.length, 'closed modal never copies after delayed clipboard denial');
    assert.equal(state.exec.length, beforeClosedCopy.exec.length, 'late clipboard denial never moves focus into closed modal');
    assert.equal(state.messages.length, beforeClosedCopy.messages.length, 'late clipboard denial never displays stale feedback');

    share = await openDetail(page, 'product', serviceId);
    await page.evaluate(() => { window.__shareTest.clipMode = 'success'; });
    await share.tap();
    await page.waitForFunction(count => window.__shareTest.copied.length === count, beforeClosedCopy.copied.length + 1);
    assert.equal((await snapshot(page)).copied.at(-1), products[serviceId].share_url);

    await backToCatalog(page, 'product');
    await page.route('**/api/product/' + productId, route => route.fulfill({ status: 503,
      json: { success: false, error: 'Unavailable' } }), { times: 1 });
    await page.locator('#catalogResults [data-open-product-detail="' + productId + '"]').first().tap();
    await page.locator('#pDetailLoading').getByText(/Impossible de charger/i).waitFor();
    share = page.locator('#productDetailPanel [data-share-button]');
    assert.equal(await share.isDisabled(), true, 'failed detail cannot share an old item');
    assert(!await share.getAttribute('data-share-url'), 'failed detail has no stale share URL');

    await page.goto(base + '/?open=shops', { waitUntil: 'networkidle' });
    await captureFeedback(page);
    for (const [index, slug] of Object.keys(shops).entries()) {
      share = await openDetail(page, 'shop', slug);
      await share.tap();
      await page.waitForFunction(count => window.__shareTest.copied.length === count, index + 1);
      assert.equal((await snapshot(page)).copied[index], origin + '/shops/' + slug);
      await backToCatalog(page, 'shop');
    }

    let rentalURL = process.env.PUBLIC_SHARE_LOCATION_URL;
    if (!rentalURL) {
      const response = await context.request.get(base + '/api/catalog?universe=locations&per_page=1');
      assert.equal(response.ok(), true);
      const listing = (await response.json()).items[0];
      assert(listing, 'preview needs one public rental or PUBLIC_SHARE_LOCATION_URL');
      rentalURL = new URL(listing.url, base).href;
    }
    const rentalResponse = await page.goto(rentalURL, { waitUntil: 'networkidle' });
    assert.equal(rentalResponse.status(), 200, 'public rental fixture must be accessible at ' + rentalURL);
    await captureFeedback(page);
    assert.equal(await page.locator('script[src*="core_share.js"]').count(), 1, 'rental uses the shared script once');
    share = page.locator('[data-share-button]');
    await share.tap();
    await page.waitForFunction(() => window.__shareTest.copied.length === 1);
    const canonical = await page.locator('link[rel="canonical"]').getAttribute('href');
    const copiedRental = (await snapshot(page)).copied[0];
    assert.equal(copiedRental, origin + new URL(canonical).pathname, 'rental shares runtime host and canonical path');
    assert.equal(new URL(copiedRental).origin, origin);
    assert(new URL(copiedRental).pathname.startsWith('/location/'));
    assert.deepEqual(errors, []);
    console.log(name + ': public product/service/shop A/B, native/cancel/copy/error/focus and rental sharing PASS');
    await context.close();
  } finally { await browser.close(); }
}

(async () => { for (const [name, engine] of Object.entries({ chromium, webkit })) await run(name, engine); })()
  .catch(error => { console.error(error); process.exitCode = 1; });
