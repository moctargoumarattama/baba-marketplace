/* Only run against vendor_dashboard_refresh_server.py (temporary DB/media). */
const assert = require('node:assert/strict');
const { chromium, webkit } = require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');
const base = process.env.DASHBOARD_REFRESH_PREVIEW_URL || 'http://127.0.0.1:5075';
const widths = (process.env.DASHBOARD_WIDTHS || '280,320,390,768,1024,1440,1920').split(',').map(Number);

async function geometry(page, label, modal = false) {
  assert.equal(await page.locator('#vdQuickTitle').count(), 0, label + ': quick access card is removed');
  const sizes = await page.evaluate(modal => {
    const active = modal ? document.querySelector('dialog[open]') : null;
    const rect = active?.getBoundingClientRect();
    const grid = document.querySelector('.vd-content-grid');
    return { width: innerWidth, height: innerHeight, scroll: document.documentElement.scrollWidth,
      gridColumns: grid ? getComputedStyle(grid).gridTemplateColumns.split(' ').length : 0,
      gridChildren: grid ? Array.from(grid.children).filter(node => getComputedStyle(node).display !== 'none').length : 0,
      rect: rect?.toJSON(), modalScroll: active?.scrollWidth, modalClient: active?.clientWidth };
  }, modal);
  assert(sizes.scroll <= sizes.width + 1, `${label}: page overflow ${sizes.scroll}/${sizes.width}`);
  if (!modal) assert(sizes.gridColumns <= sizes.gridChildren, label + ': no empty dashboard grid column');
  if (modal) {
    assert(sizes.rect, label + ': dialog is open');
    assert(sizes.rect.left >= -1 && sizes.rect.right <= sizes.width + 1, label + ': dialog fits screen');
    assert(sizes.modalScroll <= sizes.modalClient + 1, label + ': modal has no horizontal overflow');
  }
}

async function documentScroll(page, label) {
  const state = await page.evaluate(() => {
    const previous = { left: scrollX, top: scrollY };
    const height = document.documentElement.scrollHeight;
    window.scrollTo({ top: height, left: 0, behavior: 'instant' });
    const main = document.querySelector('.vd-main');
    const visibleChildren = Array.from(main.children).filter(node => node.getBoundingClientRect().height > 0);
    const last = visibleChildren.at(-1);
    const nav = document.querySelector('.vd-bottom-nav');
    const navVisible = nav && getComputedStyle(nav).display !== 'none';
    const result = { viewport: innerHeight, documentHeight: height, scroll: scrollY,
      mainBottom: main.getBoundingClientRect().bottom, lastBottom: last?.getBoundingClientRect().bottom,
      navTop: navVisible ? nav.getBoundingClientRect().top : innerHeight };
    window.scrollTo({ ...previous, behavior: 'instant' });
    return result;
  });
  if (state.documentHeight > state.viewport + 1) assert(state.scroll > 0, label + ': window scrolls the document');
  assert(state.mainBottom <= state.viewport + 2, label + ': the main content bottom is reachable');
  assert(state.lastBottom <= state.navTop + 2, label + ': the last content is not hidden by bottom navigation');
}

async function formLoaded(page) {
  await page.locator('#vendorCreateForm').waitFor({ state: 'visible' });
  await page.waitForTimeout(270);
}

async function closeForm(page) {
  await page.locator('#vendorProductDialog [data-vpm-close]:visible').first().click();
  if (await page.locator('#vpmDiscardConfirm').isVisible()) await page.locator('[data-vpm-discard]').click();
  await page.waitForFunction(() => !document.getElementById('vendorProductDialog').open && !history.state?.bmVendorProductCreate);
}

async function chooseAdd(page, selector) {
  await page.locator('.vd-add-button:visible').first().click();
  await page.locator('#vendorAddChoiceDialog').waitFor({ state: 'visible' });
  await geometry(page, 'add choice', true);
  await page.locator('#vendorAddChoiceDialog ' + selector).click();
  await formLoaded(page);
  assert.equal(new URL(page.url()).pathname, '/vendor/dashboard', 'creation remains on dashboard');
  assert.equal(await page.locator('#vendorAddChoiceDialog').evaluate(node => node.open), false,
    'only one active native dialog');
}

async function runEngine(name, engine) {
  const browser = await engine.launch({ headless: true });
  try {
    for (const width of widths) {
      const context = await browser.newContext({ viewport: { width, height: width < 768 ? 844 : 960 },
        isMobile: width < 768, hasTouch: width < 768, serviceWorkers: 'block',
        reducedMotion: width >= 1440 ? 'reduce' : 'no-preference' });
      try {
        const auth = await context.request.get(base + '/__dashboard_refresh_fixture__?variant=mixed&long=1');
        assert(auth.ok());
        const page = await context.newPage();
        const errors = [];
        const documents = [];
        const live = { count: 0, failures: false };
        const shopActions = { count: 0, failNext: false };
        page.setDefaultTimeout(10000);
        page.on('pageerror', error => errors.push(error.message));
        page.on('request', request => {
          if (request.isNavigationRequest() && request.frame() === page.mainFrame()) documents.push(request.url());
        });
        await page.route('**/*', route => new URL(route.request().url()).origin === new URL(base).origin
          ? route.continue() : route.abort());
        await page.route('**/vendor/dashboard/orders-live*', route => {
          live.count++;
          return live.failures ? route.fulfill({ status: 503, json: { success: false } }) : route.continue();
        });
        await page.route('**/vendor/shop/set-open', route => {
          if (route.request().method() !== 'POST') return route.continue();
          shopActions.count++;
          if (shopActions.failNext) {
            shopActions.failNext = false;
            return route.fulfill({ status: 503, json: { success: false, message: 'Action temporairement indisponible.' } });
          }
          return route.continue();
        });
        // Accelerate polling callbacks only; modal animations and request timeouts stay real.
        if (width === 390) await page.addInitScript(() => {
          const native = window.setTimeout.bind(window);
          window.setTimeout = (handler, delay, ...args) => native(handler,
            typeof handler === 'function' && /^(tick|runTick)$/.test(handler.name) && delay >= 1000 ? 350 : delay, ...args);
        });
        await page.goto(base + '/vendor/dashboard', { waitUntil: 'domcontentloaded' });
        await page.locator('.vd-shell').waitFor();
        await page.waitForFunction(() => document.querySelector('.vd-tab[aria-selected="true"]'));
        await page.waitForTimeout(300);
        const initialDocuments = documents.length;
        await geometry(page, `${name}/${width}`);
        await documentScroll(page, `${name}/${width}`);
        if (process.env.DASHBOARD_GEOMETRY_ONLY === '1') {
          console.log(`${name} ${width} document scroll: PASS`);
          continue;
        }
        if (width < 1100) {
          assert(await page.locator('.vd-bottom-nav').isVisible(), 'phone/tablet bottom navigation');
          assert(await page.locator('.vd-mobile-header').isVisible(), 'phone/tablet header');
        } else assert(await page.locator('.vd-sidebar').isVisible(), 'desktop sidebar');

        const tabs = page.locator('.vd-tab[data-vd-tab]');
        assert.equal(await tabs.count(), 3);
        for (const id of ['recent', 'prepare', 'bookings']) {
          const tab = page.locator(`.vd-tab[data-vd-tab="${id}"]`);
          await tab.click();
          assert.equal(await tab.getAttribute('aria-selected'), 'true');
          assert(await page.locator('#vd-panel-' + id).isVisible());
          assert.equal(await page.locator('.vd-tab-panel:visible').count(), 1);
        }
        await tabs.first().focus();
        await page.keyboard.press('ArrowRight');
        assert.equal(await tabs.nth(1).getAttribute('aria-selected'), 'true');
        await page.keyboard.press('End');
        assert.equal(await tabs.last().getAttribute('aria-selected'), 'true');
        await page.keyboard.press('Home');
        assert.equal(await tabs.first().getAttribute('aria-selected'), 'true');

        for (const id of ['vendorDashboardNotifications', 'vendorDashboardMenu']) {
          await page.locator(`[data-vd-dialog="${id}"]:visible`).first().click();
          await page.locator('#' + id).waitFor({ state: 'visible' });
          await geometry(page, id, true);
          await page.keyboard.press('Escape');
          await page.waitForFunction(id => !document.getElementById(id).open, id);
        }

        await page.locator('.vd-add-button:visible').first().click();
        await page.locator('#vendorAddChoiceDialog').waitFor({ state: 'visible' });
        await page.keyboard.press('Escape');
        await page.waitForFunction(() => !document.getElementById('vendorAddChoiceDialog').open);
        await chooseAdd(page, '[data-vendor-product-create][data-vendor-default-kind="service"]');
        assert.equal(await page.locator('#vendorCreateForm [name="kind"]:checked').inputValue(), 'service');
        assert.equal(await page.locator('#vendorCreateForm [name="stock"]').isVisible(), false);
        await geometry(page, 'service form', true);
        if (width === 390) {
          assert(live.count >= 2, 'accelerated polling was active before opening the modal');
          await page.waitForTimeout(500);
          const frozen = live.count;
          await page.waitForTimeout(1000);
          assert.equal(live.count, frozen, 'polling pauses while create modal is open');
        }
        await closeForm(page);
        await chooseAdd(page, '[data-vendor-location-create]');
        assert.equal(await page.locator('#vendorCreateForm [name="title"]').count(), 1);
        await geometry(page, 'location form', true);
        await closeForm(page);
        await chooseAdd(page, '[data-vendor-product-create]:not([data-vendor-default-kind="service"])');
        assert.equal(await page.locator('#vendorCreateForm [name="kind"]:checked').inputValue(), 'physical');
        await closeForm(page);

        if (width === 390 || width === 1440) {
          const shopForm = page.locator('form[data-action="set-shop-open"]');
          assert.equal(await shopForm.locator('[name="state"]').inputValue(), 'closed');
          if (width === 390) {
            shopActions.failNext = true;
            const failure = page.waitForResponse(response => response.url().includes('/vendor/shop/set-open') && response.status() === 503);
            await shopForm.locator('button[type="submit"]').click();
            await failure;
            await page.waitForFunction(() => !document.querySelector('form[data-action="set-shop-open"] button[type="submit"]').disabled);
            await page.waitForTimeout(200);
            assert.equal(shopActions.count, 1, 'failed shop action is not automatically posted again');
            assert.equal(await shopForm.locator('[name="state"]').inputValue(), 'closed', 'failed pause restores the current shop state');
          }
          for (const expected of [false, true]) {
            const wait = page.waitForResponse(response => response.url().includes('/vendor/shop/set-open') &&
              response.request().method() === 'POST');
            await shopForm.locator('button[type="submit"]').click();
            const response = await wait;
            assert(response.ok(), 'shop action sends valid CSRF');
            assert.equal((await response.json()).is_open, expected);
            await page.waitForFunction(state => document.querySelector('form[data-action="set-shop-open"] [name="state"]')?.value === state,
              expected ? 'closed' : 'open');
          }
        }
        if (width === 390) {
          await page.locator('#recentOrdersList').evaluate(node => { window.__retainedDashboardList = node; });
          const beforeFailure = await page.locator('#recentOrdersList').textContent();
          live.failures = true;
          const failed = page.waitForResponse(response => response.url().includes('/dashboard/orders-live') && response.status() === 503);
          await page.evaluate(() => window.dispatchEvent(new Event('focus')));
          await failed;
          await page.waitForTimeout(250);
          assert(await page.evaluate(() => document.getElementById('recentOrdersList') === window.__retainedDashboardList));
          assert.equal(await page.locator('#recentOrdersList').textContent(), beforeFailure,
            'failed refresh keeps mounted tasks and content');
          live.failures = false;
        }
        assert.equal(documents.length, initialDocuments, 'dashboard interactions never navigate the main document');
        assert.deepEqual(errors, [], 'no uncaught JS errors');
        console.log(`${name} ${width}: PASS`);
      } finally { await context.close(); }
    }

    if (process.env.DASHBOARD_GEOMETRY_ONLY === '1') return;
    for (const variant of ['products', 'services']) for (const width of [390, 1440]) {
      const context = await browser.newContext({ viewport: { width, height: 960 }, serviceWorkers: 'block' });
      try {
        await context.request.get(base + '/__dashboard_refresh_fixture__?variant=' + variant);
        const page = await context.newPage();
        await page.route('**/*', route => new URL(route.request().url()).origin === new URL(base).origin ? route.continue() : route.abort());
        await page.goto(base + '/vendor/dashboard', { waitUntil: 'domcontentloaded' });
        await geometry(page, `${name}/${variant}/${width}`);
        await documentScroll(page, `${name}/${variant}/${width}`);
        await page.locator('.vd-add-button:visible').first().click();
        await formLoaded(page);
        assert.equal(await page.locator('#vendorCreateForm [name="kind"]').inputValue(), variant === 'services' ? 'service' : 'physical');
        await geometry(page, name + '/' + variant, true);
        await closeForm(page);
        console.log(`${name} ${variant}-only ${width}: PASS`);
      } finally { await context.close(); }
    }

    const context = await browser.newContext({ javaScriptEnabled: false, viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
    try {
      await context.request.get(base + '/__dashboard_refresh_fixture__?variant=mixed');
      const page = await context.newPage();
      await page.route('**/*', route => new URL(route.request().url()).origin === new URL(base).origin ? route.continue() : route.abort());
      await page.goto(base + '/vendor/dashboard', { waitUntil: 'domcontentloaded' });
      assert.equal(await page.locator('.vd-tab-panel:visible').count(), 3, 'no-JS exposes every task panel');
      assert(await page.locator('a[href*="/vendor/product/new?standalone=1"]:visible').count() > 0,
        'no-JS provides native shared form link');
      await geometry(page, name + '/no-JS');
      await documentScroll(page, name + '/no-JS');
      console.log(`${name} no-JS: PASS`);
    } finally { await context.close(); }
  } finally { await browser.close(); }
}

(async () => {
  const engines = process.env.DASHBOARD_ENGINE ? [[process.env.DASHBOARD_ENGINE,
    process.env.DASHBOARD_ENGINE === 'webkit' ? webkit : chromium]] : [['chromium', chromium], ['webkit', webkit]];
  for (const [name, engine] of engines) await runEngine(name, engine);
})().catch(error => { console.error(error); process.exitCode = 1; });
