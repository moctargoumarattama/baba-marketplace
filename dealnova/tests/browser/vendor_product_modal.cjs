/* Run only against vendor_product_modal_server.py (disposable synthetic data).
   PLAYWRIGHT_PACKAGE may point to an existing local installation. */
const assert = require('node:assert/strict');
const { chromium, webkit } = require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');
const base = process.env.VENDOR_MODAL_PREVIEW_URL || 'http://127.0.0.1:5071';
const fixtureImage = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=',
  'base64');

async function isOpen(page) {
  return page.locator('#vendorProductDialog').evaluate(node => node.open);
}
async function closed(page) {
  await page.waitForFunction(() => !document.getElementById('vendorProductDialog').open);
  await page.waitForFunction(() => !history.state?.bmVendorProductCreate);
}
async function loaded(page) {
  await page.locator('#vendorCreateForm').waitFor({ state: 'visible' });
  await page.waitForTimeout(280);
}
async function open(page) {
  if (!await page.locator('[data-vendor-product-create]:visible').count()) {
    await page.locator('[data-vd-dialog="vendorAddChoiceDialog"]').click();
  }
  await page.locator('[data-vendor-product-create]:visible').first().click();
  await loaded(page);
  assert.equal(new URL(page.url()).pathname, '/vendor/dashboard');
}
async function fill(page, category) {
  const form = page.locator('#vendorCreateForm');
  await form.locator('[name="name"]').fill('Article modal navigateur');
  await form.locator('[name="category_id"]').selectOption(String(category));
  await form.locator('[name="price"]').fill('25.50');
  await form.locator('[name="stock"]').fill('3');
  await form.locator('[name="description"]').fill('Description de test pour la creation en modale.');
}
async function sizeChecks(page, width) {
  const sizes = await page.evaluate(() => {
    const dialog = document.getElementById('vendorProductDialog');
    const rect = dialog.getBoundingClientRect();
    const submit = dialog.querySelector('[data-vpm-submit]').getBoundingClientRect();
    return { screen: innerWidth, viewportHeight: innerHeight,
      pageWidth: document.documentElement.scrollWidth,
      dialogWidth: rect.width, left: rect.left, right: rect.right,
      submitBottom: submit.bottom, submitTop: submit.top,
      dialogScroll: dialog.scrollWidth, dialogClient: dialog.clientWidth };
  });
  assert(sizes.pageWidth <= sizes.screen + 1, width + ': page has no horizontal overflow');
  assert(sizes.left >= -1 && sizes.right <= sizes.screen + 1, width + ': modal stays in viewport');
  assert(sizes.dialogScroll <= sizes.dialogClient + 1, width + ': modal has no horizontal overflow');
  assert(sizes.submitTop >= 0 && sizes.submitBottom <= sizes.viewportHeight + 1,
    width + ': save button stays visible');
}

async function run(name, engine) {
  const browser = await engine.launch({ headless: true });
  try {
    for (const width of [320, 390, 768, 1440]) {
      const touch = width < 768;
      const context = await browser.newContext({
        viewport: { width, height: touch ? 844 : 940 }, isMobile: touch, hasTouch: touch,
        serviceWorkers: 'block', reducedMotion: width === 1440 ? 'reduce' : 'no-preference',
      });
      try {
        const response = await context.request.get(base + '/__vendor_modal_fixture__');
        assert(response.ok(), 'preview fixture authenticates only its synthetic vendor');
        const ids = await response.json();
        const page = await context.newPage();
        page.setDefaultTimeout(12000);
        page.setDefaultNavigationTimeout(20000);
        const errors = [];
        const navigations = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('request', request => {
          if (request.isNavigationRequest() && request.frame() === page.mainFrame()) navigations.push(request.url());
        });
        await page.route('**/*', route => {
          const url = new URL(route.request().url());
          return url.origin === new URL(base).origin ? route.continue() : route.abort();
        });
        const network = { failGet: false, invalidPost: false, csrfPost: false, failPost: false, postGate: null, postCount: 0 };
        await page.route('**/vendor/product/new*', async route => {
          const request = route.request();
          if (request.method() === 'GET' && request.headers()['x-vendor-modal'] === 'product-create') {
            if (network.failGet) {
              network.failGet = false;
              return route.fulfill({ status: 503, json: { success: false, message: 'Chargement indisponible.' } });
            }
          }
          if (request.method() === 'POST') {
            network.postCount++;
            if (network.invalidPost) {
              network.invalidPost = false;
              return route.fulfill({ status: 422, json: { success: false,
                message: 'Verifiez le formulaire.', errors: { name: 'Corrigez le nom de cette offre.' } } });
            }
            if (network.csrfPost) {
              network.csrfPost = false;
              return route.fulfill({ status: 400, contentType: 'text/html', body: '<p>Session expiree.</p>' });
            }
            if (network.failPost) {
              network.failPost = false;
              return route.abort('connectionfailed');
            }
            if (network.postGate) await network.postGate;
          }
          return route.continue();
        });
        await page.goto(base + '/vendor/dashboard', { waitUntil: 'domcontentloaded' });
        await page.waitForFunction(() => window.__BM_VENDOR_PRODUCT_MODAL_INIT__ ||
          document.getElementById('vendorProductDialog'));
        const initialNavigations = navigations.length;
        const opener = page.locator('[data-vendor-product-create]:visible').first();
        await opener.scrollIntoViewIfNeeded();
        const oldScroll = await page.evaluate(() => scrollY);
        await open(page);
        await sizeChecks(page, width);

        // The native dialog keeps keyboard focus inside the active form.
        await page.keyboard.press('Tab');
        assert(await page.evaluate(() => document.getElementById('vendorProductDialog').contains(document.activeElement)),
          'keyboard focus stays inside the modal');
        const form = page.locator('#vendorCreateForm');
        await form.locator('[name="kind"][value="service"]').check();
        assert.equal(await form.locator('[name="stock"]').isVisible(), false, 'service hides physical stock');
        const serviceCategories = await form.locator('[name="category_id"] option').evaluateAll(nodes => nodes.map(n => n.value));
        assert(serviceCategories.includes(String(ids.service)), 'service category available');
        assert(!serviceCategories.includes(String(ids.physical)), 'physical category removed for service');
        await form.locator('[name="kind"][value="physical"]').check();
        assert.equal(await form.locator('[name="stock"]').isVisible(), true, 'physical stock restored');
        if (width === 390) {
          await form.locator('[name="name"]').focus();
          await page.setViewportSize({ width, height: 520 });
          await page.waitForTimeout(300);
          await sizeChecks(page, width);
          await page.setViewportSize({ width, height: 844 });
          await page.waitForTimeout(300);
          await page.locator('#vpmVideo').setInputFiles({ name: 'fixture.webm', mimeType: 'video/webm', buffer: Buffer.from('preview-only') });
          await page.locator('#vpmVideoPreview video').evaluate(node => { window.__oldVideoPlayer = node; });
        }

        // Type changes are a real form edit: discard explicitly before clean/history checks.
        await page.locator('[data-vpm-close]:visible').first().click();
        const discard = page.locator('#vpmDiscardConfirm');
        if (await discard.isVisible()) await page.locator('[data-vpm-discard]').click();
        await closed(page);
        if (width === 390) {
          assert(await page.evaluate(() => window.__oldVideoPlayer.paused && !window.__oldVideoPlayer.hasAttribute('src')),
            'closing pauses the video and removes its blob source');
        }
        assert(await opener.evaluate(node => node === document.activeElement), 'focus returns to original action');
        assert(Math.abs(await page.evaluate(() => scrollY) - oldScroll) <= 3, 'background scroll is restored');
        await open(page);
        await page.goBack();
        await closed(page);
        assert.equal(new URL(page.url()).pathname, '/vendor/dashboard', 'Back closes modal on dashboard');

        // Recover from fragment failure without navigating away.
        network.failGet = true;
        await opener.click();
        await page.locator('#vendorProductDialog').waitFor({ state: 'visible' });
        await page.waitForFunction(() => !document.getElementById('vendorCreateForm') &&
          document.getElementById('vendorProductContent').querySelector('button'));
        await page.locator('[data-vpm-retry]').click();
        await loaded(page);
        await fill(page, ids.physical);
        await page.locator('#vpmImages').setInputFiles({ name: 'fixture.png', mimeType: 'image/png', buffer: fixtureImage });
        assert.equal(await page.locator('#vpmImagePreviews .vpm-image-preview').count(), 1, 'photo preview displayed');

        // A failed POST must leave the actual file input mounted and the draft intact.
        await page.locator('#vendorCreateForm').evaluate(node => { window.__draftFormNode = node; });
        network.invalidPost = true;
        await Promise.all([
          page.waitForResponse(response => response.url().includes('/vendor/product/new') &&
            response.request().method() === 'POST' && response.status() === 422),
          page.locator('[data-vpm-submit]').click(),
        ]);
        await page.waitForFunction(() => document.getElementById('vpmFormError').textContent.trim() ||
          document.querySelector('#vendorCreateForm [aria-invalid="true"]'));
        assert(await isOpen(page), 'validation keeps modal open');
        assert(await page.evaluate(() => document.getElementById('vendorCreateForm') === window.__draftFormNode),
          'validation preserves the mounted form');
        assert.equal(await page.locator('#vpmImagePreviews img[alt="fixture.png"]').count(), 1,
          'selected photo survives validation');
        assert.equal(await form.locator('[name="name"]').inputValue(), 'Article modal navigateur');

        // Keep editing in the confirmation, then verify that a network failure also retains files.
        await page.locator('[data-vpm-close]:visible').first().click();
        await discard.waitFor({ state: 'visible' });
        await page.locator('[data-vpm-keep]').click();
        assert(await isOpen(page), 'keep preserves editing');
        network.failPost = true;
        await Promise.all([
          page.waitForEvent('requestfailed', { predicate: request =>
            request.url().includes('/vendor/product/new') && request.method() === 'POST' }),
          page.locator('[data-vpm-submit]').click(),
        ]);
        await page.waitForFunction(() => !document.querySelector('[data-vpm-submit]').disabled);
        await page.waitForFunction(() => document.getElementById('vpmFormError').textContent.trim());
        assert.equal(await page.locator('#vpmImagePreviews img[alt="fixture.png"]').count(), 1,
          'network failure preserves selected photo');

        // Refresh an expired CSRF token in place, without silently reposting the draft.
        await form.locator('[name="csrf_token"]').evaluate(node => { node.value = 'expired-fixture'; });
        network.csrfPost = true;
        await Promise.all([
          page.waitForResponse(response => response.url().includes('/vendor/product/new') &&
            response.request().method() === 'POST' && response.status() === 400),
          page.locator('[data-vpm-submit]').click(),
        ]);
        const postsBeforeRefresh = network.postCount;
        await page.locator('[data-vpm-refresh-session]').click();
        await page.waitForFunction(() => document.querySelector('#vendorCreateForm [name="csrf_token"]').value !== 'expired-fixture');
        assert(await page.evaluate(() => document.getElementById('vendorCreateForm') === window.__draftFormNode),
          'session refresh keeps the original form');
        assert.equal(await page.locator('#vpmImagePreviews img[alt="fixture.png"]').count(), 1,
          'session refresh preserves selected photo');
        assert.equal(network.postCount, postsBeforeRefresh, 'session refresh does not automatically repeat the POST');

        // A delayed real POST makes duplicate-submit protection observable.
        let release;
        network.postGate = new Promise(resolve => { release = resolve; });
        const beforePosts = network.postCount;
        const saved = page.waitForResponse(response => response.url().includes('/vendor/product/new') &&
          response.request().method() === 'POST' && response.status() === 201);
        await page.locator('[data-vpm-submit]').click();
        await page.waitForFunction(() => document.querySelector('[data-vpm-submit]').disabled);
        await page.locator('#vendorCreateForm').evaluate(node => {
          node.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
        });
        await page.waitForTimeout(120);
        assert.equal(network.postCount - beforePosts, 1, 'one network request while saving');
        release();
        const savedResponse = await saved;
        assert(savedResponse.request().postDataBuffer().includes(Buffer.from('filename="fixture.png"')),
          'real multipart request retains the selected photo after both failures');
        assert.equal((await savedResponse.json()).success, true, 'real backend creates offer');
        await closed(page);
        assert.equal(new URL(page.url()).pathname, '/vendor/dashboard');

        // Back first restores the draft's history entry. Discard before that asynchronous
        // restoration finishes must close once, without opening a fresh empty form.
        await open(page);
        await page.locator('#vendorCreateForm [name="name"]').fill('Brouillon a abandonner');
        await page.evaluate(() => {
          window.__originalHistoryForward = history.forward;
          history.forward = function () {
            setTimeout(() => window.__originalHistoryForward.call(history), 200);
          };
        });
        await page.goBack();
        await page.locator('#vpmDiscardConfirm').waitFor({ state: 'visible' });
        await page.locator('[data-vpm-discard]').click();
        await closed(page);
        await page.waitForTimeout(650);
        assert.equal(await isOpen(page), false, 'fast discard during history restoration never reopens modal');
        await page.evaluate(() => { history.forward = window.__originalHistoryForward; });
        assert.equal(navigations.length, initialNavigations, 'all actions preserve the dashboard document');
        assert.deepEqual(errors, [], 'no browser exceptions');
        console.log(name + ' ' + width + ': PASS');
      } finally {
        await context.close();
      }
    }
  } finally {
    await browser.close();
  }
}

(async () => {
  await run('chromium', chromium);
  await run('webkit', webkit);
})().catch(error => { console.error(error); process.exitCode = 1; });
