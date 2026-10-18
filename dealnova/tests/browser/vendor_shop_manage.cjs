/* Use only with vendor_shop_manage_server.py: disposable SQLite and uploads. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium, webkit } = require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');
const base = process.env.SHOP_MANAGE_PREVIEW_URL || 'http://127.0.0.1:5077';
const widths = (process.env.SHOP_MANAGE_WIDTHS || '280,320,390,768,1024,1440,1920').split(',').map(Number);
const local = url => new URL(url).origin === new URL(base).origin;
const formSelector = '#shopEditDialog #shopEditForm';
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=', 'base64');

async function fixture(context, variant = 'mixed', reset = true) {
  const response = await context.request.get(`${base}/__shop_manage_fixture__?variant=${variant}&reset=${reset ? '1' : '0'}`);
  assert(response.ok(), 'disposable fixture must be available');
  return response.json();
}

async function ready(page) {
  await page.locator('#shopManageContent').waitFor();
  await page.waitForFunction(() => {
    const loader = document.getElementById('bm-loader');
    return !loader || getComputedStyle(loader).display === 'none';
  });
}

async function geometry(page, label, modal = false) {
  const size = await page.evaluate(modal => {
    const dialog = modal ? document.querySelector('#shopEditDialog') : null;
    const shell = document.querySelector('.vd-workspace, .vd-shell');
    return { viewport: innerWidth, scroll: document.documentElement.scrollWidth,
      shell: shell?.getBoundingClientRect().toJSON(), dialog: dialog?.getBoundingClientRect().toJSON(),
      dialogWidth: dialog?.clientWidth, dialogScroll: dialog?.scrollWidth,
      dialogOpen: dialog?.open };
  }, modal);
  assert(size.scroll <= size.viewport + 1, `${label}: page does not overflow ${size.scroll}/${size.viewport}`);
  if (modal) {
    assert(size.dialogOpen, `${label}: native modal is open`);
    assert(size.dialog.left >= -1 && size.dialog.right <= size.viewport + 1, `${label}: modal fits viewport`);
    assert(size.dialogScroll <= size.dialogWidth + 1, `${label}: modal content fits`);
  } else if (size.viewport >= 1440) {
    assert(size.shell?.width > size.viewport * .85, `${label}: layout uses desktop width`);
  }
}

async function openEdit(page) {
  await page.locator('[data-shop-edit]:visible').click();
  await page.locator(formSelector).waitFor({ state: 'visible' });
  assert.equal(new URL(page.url()).pathname, '/vendor/shop/manage', 'editing stays on shop management');
  await geometry(page, 'shop edit modal', true);
}

async function closeEdit(page) {
  await page.locator('#shopEditDialog [data-shop-close]:visible').first().click();
  await page.waitForFunction(() => !document.querySelector('#shopEditDialog').open && !history.state?.bmShopEdit);
}

async function contentRules(page, width) {
  assert.equal(await page.locator('[data-shop-edit]:visible').count(), 1, 'one visible edit action');
  const forbidden = ['/vendor/product/new', '/owner/location/new', '/vendor/earnings', '/vendor/catalog', '/owner/locations'];
  for (const path of forbidden) {
    assert.equal(await page.locator(`#shopManageContent a[href="${path}"]`).count(), 0,
      'dashboard shortcut is absent from page content: ' + path);
  }
  assert.equal(await page.locator('#shopManageContent form[action$="/shop/set-open"]').count(), 0,
    'dashboard pause control is not duplicated');
  const navigation = width >= 1100 ? '.vd-sidebar-links' : '.vd-bottom-nav';
  assert.equal(await page.locator(`${navigation} a[href="/vendor/shop/manage"][aria-current="page"]`).count(), 1,
    'shared navigation identifies the current shop page');
  assert.equal(await page.locator('#shopChangeRequests').getAttribute('open'), null, 'requests start collapsed');
  assert.equal(await page.locator('#shopAdvancedOptions').getAttribute('open'), null, 'advanced options start collapsed');
}

async function deepChecks(page, context, original, mutations) {
  mutations.failGetNext = true;
  await page.locator('[data-shop-edit]:visible').click();
  await page.locator('[data-shop-retry]:visible').waitFor();
  await page.locator('[data-shop-retry]').click();
  await page.locator(formSelector).waitFor({ state: 'visible' });
  await closeEdit(page);
  for (let cycle = 0; cycle < 2; cycle++) { await openEdit(page); await closeEdit(page); }
  await openEdit(page);
  assert.equal(await page.locator(`${formSelector} [name="name"], ${formSelector} [name="contact_email"]`).count(), 0,
    'locked shop name and email are never writable fields in the edit form');
  const description = 'Description conservee pendant les erreurs et enregistree sans changer de page.';
  await page.evaluate(() => {
    window.__shopGeoDenied = true;
    Object.defineProperty(navigator, 'geolocation', { configurable: true, value: {
      getCurrentPosition(success, failure) {
        setTimeout(() => window.__shopGeoDenied ? failure({ code: 1 }) :
          success({ coords: { latitude: 34.0123, longitude: -6.8123 } }), 10);
      }
    } });
  });
  await page.locator('[data-shop-locate]').click();
  await page.waitForFunction(() => /Autorisez/.test(document.querySelector('#shopLocationStatus').textContent));
  await page.evaluate(() => { window.__shopGeoDenied = false; });
  await page.locator('[data-shop-locate]').click();
  await page.waitForFunction(() => document.querySelector('#shopEditForm [name="service_latitude"]').value === '34.0123');
  if (page.viewportSize().width === 390) {
    await page.setViewportSize({ width: 844, height: 390 });
    await geometry(page, 'mobile landscape edit', true);
    await page.setViewportSize({ width: 390, height: 844 });
    await geometry(page, 'mobile portrait edit', true);
  }
  await page.locator(`${formSelector} [name="description"]`).fill(description);
  await page.locator(`${formSelector} [name="logo"]`).setInputFiles({ name: 'shop-preview.png', mimeType: 'image/png', buffer: png });
  await page.locator(formSelector).evaluate(form => { window.__retainedShopForm = form; });
  mutations.failNext = 422;
  await page.locator('#shopEditDialog [data-shop-edit-submit]').click();
  await page.locator('#shopEditDialog [data-shop-form-error]:visible').waitFor();
  assert.equal(await page.locator(`${formSelector} [name="description"]`).inputValue(), description);
  assert.equal(await page.locator(`${formSelector} [name="logo"]`).evaluate(input => input.files.length), 1,
    'a validation response retains the selected logo');
  assert(await page.locator(formSelector).evaluate(form => form === window.__retainedShopForm),
    'validation does not replace the form DOM');
  mutations.failNext = 503;
  await page.locator('#shopEditDialog [data-shop-edit-submit]').click();
  await page.waitForFunction(() => !document.querySelector('#shopEditDialog [data-shop-edit-submit]').disabled);
  assert.equal(await page.locator(`${formSelector} [name="description"]`).inputValue(), description);
  assert.equal(await page.locator(`${formSelector} [name="logo"]`).evaluate(input => input.files.length), 1,
    'a transient server error retains the selected logo');
  const beforeCsrfPosts = mutations.edits;
  const beforeCsrfGets = mutations.gets;
  await page.locator(`${formSelector} [name="csrf_token"]`).evaluate(input => { input.value = 'expired-fixture-token'; });
  mutations.failNext = 400;
  await page.locator('#shopEditDialog [data-shop-edit-submit]').click();
  await page.waitForFunction(() => !document.querySelector('#shopEditDialog [data-shop-edit-submit]').disabled);
  assert.equal(mutations.edits, beforeCsrfPosts + 1, 'expired CSRF never triggers an automatic second POST');
  assert(mutations.gets > beforeCsrfGets, 'expired CSRF refreshes the token through a safe GET');
  assert.notEqual(await page.locator(`${formSelector} [name="csrf_token"]`).inputValue(), 'expired-fixture-token');
  assert.equal(await page.locator(`${formSelector} [name="logo"]`).evaluate(input => input.files.length), 1,
    'token refresh retains the chosen logo and form DOM');
  const beforeSave = mutations.edits;
  mutations.delayNext = true;
  await page.locator('#shopEditDialog [data-shop-edit-submit]').evaluate(button => { button.click(); button.click(); });
  await page.waitForFunction(() => !document.querySelector('#shopEditDialog').open);
  assert.equal(mutations.edits, beforeSave + 1, 'rapid repeated save submits once');
  const saved = await fixture(context, 'mixed', false);
  assert.equal(saved.description, description, 'a real CSRF-protected POST persists the edit');
  assert.notEqual(saved.logo, original.logo, 'uploaded logo is stored in the disposable fixture');
  assert.equal(saved.name, original.name, 'shop identity is preserved');
  assert.equal(saved.contact_email, original.contact_email, 'locked contact email is preserved');
  assert.equal(saved.latitude, 34.0123, 'GPS coordinates save in the unified edit form');
  assert.equal(saved.longitude, -6.8123);
  assert.match(await page.locator('#shopManageContent').innerText(), /Description conservee/,
    'successful edit refreshes shop information in place');

  await openEdit(page);
  await page.locator(`${formSelector} [name="description"]`).fill('Modification a abandonner');
  await page.locator('#shopEditDialog [data-shop-close]:visible').first().click();
  await page.locator('#shopDiscardConfirm:visible').waitFor();
  await page.locator('[data-shop-keep-editing]').click();
  assert.equal(await page.locator(`${formSelector} [name="description"]`).inputValue(), 'Modification a abandonner');
  await page.goBack();
  await page.locator('#shopDiscardConfirm:visible').waitFor();
  assert(await page.locator('#shopEditDialog').evaluate(dialog => dialog.open), 'Back keeps dirty form until explicit choice');
  await page.locator('[data-shop-discard]').click();
  await page.waitForFunction(() => !document.querySelector('#shopEditDialog').open && !history.state?.bmShopEdit);
  assert.equal((await fixture(context, 'mixed', false)).description, description, 'discard never persists unsaved changes');
  await openEdit(page);
  await page.locator('[data-shop-clear-location]').click();
  await page.locator('#shopEditDialog [data-shop-edit-submit]').click();
  await page.waitForFunction(() => !document.querySelector('#shopEditDialog').open && !history.state?.bmShopEdit);
  const cleared = await fixture(context, 'mixed', false);
  assert.equal(cleared.latitude, null, 'explicit GPS removal persists');
  assert.equal(cleared.longitude, null);
  assert.equal(cleared.address, original.address, 'GPS removal preserves the written address');

  const publicUrl = await page.locator('#shopPublicUrl').inputValue();
  await page.locator('#shopCopyLink').click();
  await page.waitForFunction(() => window.__shopClipboard.length > 0);
  assert.equal(await page.evaluate(() => window.__shopClipboard.at(-1)), publicUrl, 'copy uses the public shop URL');
  await page.evaluate(() => Object.defineProperty(navigator, 'share', { configurable: true, value: undefined }));
  await page.locator('#shopShareLink').click();
  await page.locator('#shopShareFallback:visible').waitFor();
  const whatsApp = page.locator('#shopShareFallback a[href*="wa.me"], #shopShareFallback a[href*="whatsapp"]');
  assert.equal(await whatsApp.count(), 1, 'unsupported native sharing has an explicit WhatsApp alternative');
  assert.match(await whatsApp.getAttribute('href'), /https%3A|http%3A/i, 'share fallback includes the public URL');

  await page.locator('#shopChangeRequests > summary').click();
  const changeForm = page.locator('[data-shop-request]');
  await changeForm.locator('[name="request_type"]').selectOption('shop_name');
  await changeForm.locator('[name="requested_value"]').fill('Nouveau nom a valider');
  await changeForm.locator('[name="reason"]').fill('Changement demande pour la nouvelle enseigne.');
  await changeForm.locator('button[type="submit"]').click();
  await page.waitForFunction(() => !document.querySelector('[data-shop-request] button[type="submit"]').disabled);
  await page.waitForFunction(() => /Nouveau nom a valider/.test(document.querySelector('#shopChangeRequests').textContent));
  const afterRequest = await fixture(context, 'mixed', false);
  assert.equal(afterRequest.requests, 1, 'administrative request is stored');
  assert.equal(afterRequest.name, original.name, 'request does not change locked shop identity immediately');

  await page.locator('#shopAdvancedOptions > summary').click();
  const visibilityForm = page.locator('#shopVisibilityForm');
  await visibilityForm.locator('button[type="submit"]').click();
  await page.locator('#shopVisibilityConfirm:visible').waitFor();
  assert.equal((await fixture(context, 'mixed', false)).is_active, true, 'deactivation waits for confirmation');
  await page.locator('[data-shop-visibility-confirm]').click();
  await page.waitForFunction(() => !document.querySelector('[data-shop-visibility-confirm]')?.disabled);
  await page.waitForTimeout(150);
  const inactive = await fixture(context, 'mixed', false);
  assert.equal(inactive.is_active, false, 'advanced visibility action deactivates shop');
  assert.equal(inactive.is_open, true, 'shop visibility action preserves dashboard pause state');
}

async function engineChecks(name, engine) {
  const browser = await engine.launch({ headless: true });
  try {
    for (const width of widths) {
      const context = await browser.newContext({ viewport: { width, height: width < 768 ? 844 : 960 },
        hasTouch: width < 768, isMobile: width < 768, serviceWorkers: 'block',
        reducedMotion: width >= 1440 ? 'reduce' : 'no-preference' });
      try {
        await context.addInitScript(() => {
          window.__shopClipboard = [];
          Object.defineProperty(navigator, 'clipboard', { configurable: true,
            value: { writeText: async text => { window.__shopClipboard.push(text); } } });
        });
        const original = await fixture(context);
        const page = await context.newPage();
        page.setDefaultTimeout(15000);
        const errors = [], documents = [];
        const mutations = { edits: 0, gets: 0, failNext: 0, failGetNext: false, delayNext: false };
        page.on('pageerror', error => errors.push(error.message));
        page.on('request', request => {
          if (request.isNavigationRequest() && request.frame() === page.mainFrame()) documents.push(request.url());
        });
        await page.route('**/*', route => local(route.request().url()) ? route.continue() : route.abort());
        await page.route('**/vendor/shop/edit*', async route => {
          if (route.request().method() !== 'POST') {
            mutations.gets++;
            if (mutations.failGetNext) {
              mutations.failGetNext = false;
              return route.fulfill({ status: 503, json: { success: false, message: 'Formulaire indisponible, reessayez.' } });
            }
            return route.continue();
          }
          mutations.edits++;
          if (mutations.failNext) {
            const status = mutations.failNext;
            mutations.failNext = 0;
            if (status === 400) return route.fulfill({ status, json: { error: 'csrf' } });
            return route.fulfill({ status, json: { success: false,
              message: status === 422 ? 'Verifiez le telephone.' : 'Serveur temporairement indisponible.',
              errors: status === 422 ? { contact_phone: 'Verifiez le telephone.' } : {} } });
          }
          if (mutations.delayNext) { mutations.delayNext = false; await new Promise(resolve => setTimeout(resolve, 650)); }
          return route.continue();
        });
        await page.goto(base + '/vendor/shop/manage', { waitUntil: 'domcontentloaded' });
        await ready(page);
        const initialDocuments = documents.length;
        await geometry(page, `${name}/${width}`);
        await contentRules(page, width);
        if (process.env.SHOP_MANAGE_SCREENSHOTS_DIR && (width === 390 || width === 1440)) {
          fs.mkdirSync(process.env.SHOP_MANAGE_SCREENSHOTS_DIR, { recursive: true });
          await page.screenshot({ path: path.join(process.env.SHOP_MANAGE_SCREENSHOTS_DIR,
            `shop-manage-${name.toLowerCase()}-${width}.png`), fullPage: true });
        }
        if (process.env.SHOP_MANAGE_GEOMETRY_ONLY === '1') { console.log(`${name} ${width}: geometry PASS`); continue; }
        await openEdit(page);
        const before = await page.locator('#shopEditDialog').boundingBox();
        await page.waitForTimeout(300);
        const after = await page.locator('#shopEditDialog').boundingBox();
        assert(Math.abs(before.x - after.x) <= 1 && Math.abs(before.y - after.y) <= 1,
          'modal remains stable after opening');
        await closeEdit(page);
        assert(await page.locator('[data-shop-edit]').evaluate(button => document.activeElement === button),
          'closing returns focus to the edit button');
        if (width === 390 || width === 1440) await deepChecks(page, context, original, mutations);
        assert.equal(documents.length, initialDocuments, 'shop actions never navigate away from the current page');
        assert.deepEqual(errors, [], `${name}/${width}: no uncaught JavaScript errors`);
        console.log(`${name} ${width}: PASS`);
      } finally { await context.close(); }
    }
    if (process.env.SHOP_MANAGE_GEOMETRY_ONLY !== '1') {
      for (const variant of ['products', 'services', 'location']) {
        const context = await browser.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
        try {
          await fixture(context, variant);
          const page = await context.newPage();
          await page.route('**/*', route => local(route.request().url()) ? route.continue() : route.abort());
          await page.goto(base + '/vendor/shop/manage');
          await ready(page);
          await geometry(page, `${name}/${variant}`);
          await contentRules(page, 390);
          await openEdit(page);
          assert.equal(await page.locator(`${formSelector} [name="description"]`).count(), 1);
          await closeEdit(page);
          console.log(`${name} ${variant}: PASS`);
        } finally { await context.close(); }
      }
      const context = await browser.newContext({ javaScriptEnabled: false, viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
      try {
        await fixture(context);
        const page = await context.newPage();
        await page.route('**/*', route => local(route.request().url()) ? route.continue() : route.abort());
        await page.goto(base + '/vendor/shop/manage?edit_shop=1');
        await page.locator('#shopEditForm').waitFor({ state: 'visible' });
        await page.locator('#shopEditForm [name="description"]').fill('Modification sans JavaScript');
        await page.locator('#shopEditForm button[type="submit"]').click();
        await page.waitForURL('**/vendor/shop/manage');
        assert.equal((await fixture(context, 'mixed', false)).description, 'Modification sans JavaScript');
        console.log(`${name} no-JavaScript: PASS`);
      } finally { await context.close(); }
    }
  } finally { await browser.close(); }
}

async function sharedWorkspaceChecks(name, engine) {
  const browser = await engine.launch({ headless: true });
  try {
    for (const width of [390, 1440]) {
      const context = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block' });
      try {
        await fixture(context);
        for (const pathname of ['/vendor/dashboard', '/vendor/catalog']) {
          const page = await context.newPage();
          const errors = [];
          let activeDocument = true;
          page.on('pageerror', error => { if (activeDocument) errors.push(error.message); });
          await page.route('**/*', route => local(route.request().url()) ? route.continue() : route.abort());
          await page.goto(base + pathname);
          await page.locator('.vd-main').waitFor();
          const loader = page.locator('#bm-loader');
          if (await loader.count()) await loader.waitFor({ state: 'hidden' });
          const menuButton = page.locator(width >= 1100 ? '.vd-profile' : '.vd-bottom-nav [data-vd-dialog="vendorDashboardMenu"]');
          await menuButton.click();
          await page.locator('#vendorDashboardMenu[open]').waitFor();
          await page.locator('#vendorDashboardMenu [data-vd-close]').click();
          await page.waitForFunction(() => !document.querySelector('#vendorDashboardMenu').open);
          assert.equal(new URL(page.url()).pathname, pathname, 'shared menu preserves current page');
          if (pathname === '/vendor/dashboard') {
            await page.locator('[data-vd-dialog="vendorAddChoiceDialog"]').click();
            await page.locator('#vendorAddChoiceDialog[open]').waitFor();
            await page.locator('#vendorAddChoiceDialog [data-vendor-product-create]').first().click();
            await page.locator('#vendorProductDialog #vendorCreateForm').waitFor({ state: 'visible' });
            await page.locator('#vendorProductDialog [data-vpm-close]:visible').first().click();
            await page.waitForFunction(() => !document.querySelector('#vendorProductDialog').open && !history.state?.bmVendorProductCreate);
            assert.equal(new URL(page.url()).pathname, pathname, 'dashboard creation modal stays on dashboard');
          }
          assert.deepEqual(errors, [], 'shared workspace has no uncaught errors while the document is active');
          // Closing a WebKit document can report cancellation of its existing
          // dashboard polling requests as access-control errors. These are not
          // shared-dialog behavior, so assess errors before intentional unload.
          activeDocument = false;
          await page.close();
        }
        console.log(`${name} ${width}: shared workspace PASS`);
      } finally { await context.close(); }
    }
  } finally { await browser.close(); }
}

(async () => {
  for (const [name, engine] of [['Chromium', chromium], ['WebKit', webkit]]) {
    if (process.env.SHOP_MANAGE_SHARED_ONLY === '1') await sharedWorkspaceChecks(name, engine);
    else await engineChecks(name, engine);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
