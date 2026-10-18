/* Use only owner_location_modal_server.py: synthetic users, database and media.
   PLAYWRIGHT_PACKAGE can point to an existing Playwright installation. */
const assert = require('node:assert/strict');
const { chromium, webkit } = require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');
const base = process.env.OWNER_MODAL_PREVIEW_URL || 'http://127.0.0.1:5073';
const image = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=', 'base64');
const cards = '.owner-rental-card';
const title = width => 'Appartement navigateur ' + width;

async function settled(page) {
  await page.waitForFunction(() => !document.querySelector('.owner-shell')?.classList.contains('is-loading'));
}
async function closed(page) {
  await page.waitForFunction(() => !document.getElementById('vendorProductDialog').open);
  // The animation and history.back() settle independently, especially in WebKit.
  // Reopen only after the owner list has regained its base history entry.
  await page.waitForFunction(() => !history.state?.bmVendorProductCreate);
}
async function loaded(page) {
  await page.locator('#vendorCreateForm').waitFor({ state: 'visible' });
  await page.waitForTimeout(260);
}
async function open(page) {
  await page.locator('[data-vendor-location-create]:visible').first().click();
  await loaded(page);
  assert.equal(new URL(page.url()).pathname, '/owner/locations');
  assert.match(await page.locator('[data-vpm-submit]').textContent(), /Publier/i);
}
async function choose(page, name, value) {
  const field = page.locator('#vendorCreateForm [name="' + name + '"]');
  const type = await field.first().evaluate(node => ({ tag: node.tagName, type: node.type }));
  if (type.tag === 'SELECT') return field.selectOption(value);
  if (type.type === 'checkbox') return field.setChecked(value === '1');
  if (type.type === 'radio') return page.locator('#vendorCreateForm label').filter({
    has: page.locator('input[name="' + name + '"][value="' + value + '"]'),
  }).first().click();
  return field.fill(value);
}
async function fill(page, ids, width) {
  const form = page.locator('#vendorCreateForm');
  await form.locator('[name="title"]').fill(title(width));
  await choose(page, 'listing_type', 'daily');
  await choose(page, 'property_type', 'apartment');
  await form.locator('[name="city"]').fill('Rabat');
  await form.locator('[name="area"]').fill('Centre');
  await form.locator('[name="rent"]').fill('350.50');
  const shop = form.locator('[name="shop_id"]');
  if (await shop.evaluate(node => node.tagName) === 'SELECT') await shop.selectOption(String(ids.shop));
  await choose(page, 'deposit_required', '1');
  await form.locator('[name="deposit"]').fill('700.25');
  await form.locator('details.vpm-rental-fees > summary').click();
  await form.locator('[name="owner_fee"]').fill('200.50');
  await form.locator('[name="owner_fee_text"]').fill('Frais de test');
  await form.locator('[name="description"]').fill('Description de demonstration pour une annonce de location.');
  assert.match(await form.locator('[data-vpm-rent-label]').textContent(), /jour/i);
  assert.match(await form.locator('[data-vpm-commission]').textContent(), /25[,.]06/);
}
async function geometry(page, width, modal) {
  const result = await page.evaluate(modal => {
    const grid = document.querySelector('.owner-listing-grid');
    const cardRects = Array.from(document.querySelectorAll('.owner-rental-card')).slice(0, 3)
      .map(node => node.getBoundingClientRect().toJSON());
    const dialog = document.getElementById('vendorProductDialog');
    const rect = dialog.getBoundingClientRect();
    const submit = dialog.querySelector('[data-vpm-submit]').getBoundingClientRect();
    return { width: innerWidth, height: innerHeight, scrollWidth: document.documentElement.scrollWidth,
      gridColumns: grid ? getComputedStyle(grid).gridTemplateColumns.split(' ').length : 0,
      cardRects, dialog: rect.toJSON(), dialogScroll: dialog.scrollWidth, dialogClient: dialog.clientWidth,
      submit: submit.toJSON() };
  }, modal);
  assert(result.scrollWidth <= result.width + 1, width + ': no page overflow');
  if (result.cardRects.length && width >= 1200) assert.equal(result.gridColumns, 3, 'desktop shows three rental cards per row');
  if (result.cardRects.length && width <= 390) assert.equal(result.gridColumns, 1, 'phone shows one rental card per row');
  if (modal) {
    assert(result.dialog.left >= -1 && result.dialog.right <= result.width + 1, 'modal stays in viewport');
    assert(result.dialogScroll <= result.dialogClient + 1, 'modal content has no horizontal overflow');
    assert(result.submit.top >= 0 && result.submit.bottom <= result.height + 1, 'publish action remains visible');
  }
}

async function run(name, engine) {
  const browser = await engine.launch({ headless: true });
  try {
    for (const width of [320, 390, 768, 1440]) {
      const touch = width < 768;
      const context = await browser.newContext({ viewport: { width, height: touch ? 844 : 940 },
        isMobile: touch, hasTouch: touch, reducedMotion: width === 1440 ? 'reduce' : 'no-preference',
        serviceWorkers: 'block' });
      try {
        const auth = await context.request.get(base + '/__owner_modal_fixture__');
        assert(auth.ok());
        const ids = await auth.json();
        const page = await context.newPage();
        page.setDefaultTimeout(12000);
        page.setDefaultNavigationTimeout(20000);
        const exceptions = [];
        const documents = [];
        page.on('pageerror', error => exceptions.push(error.message));
        page.on('request', request => {
          if (request.isNavigationRequest() && request.frame() === page.mainFrame()) documents.push(request.url());
        });
        await page.route('**/*', route => new URL(route.request().url()).origin === new URL(base).origin
          ? route.continue() : route.abort());
        const network = { getFailure: false, invalid: false, csrf: false, offline: false,
          gate: null, createPosts: 0, actionPosts: 0, actionFailure: false, listGets: 0 };
        await page.route('**/owner/locations*', route => { network.listGets++; return route.continue(); });
        await page.route('**/owner/location/**', async route => {
          const request = route.request();
          const path = new URL(request.url()).pathname;
          if (path === '/owner/location/new' && request.method() === 'GET' && network.getFailure) {
            network.getFailure = false;
            return route.fulfill({ status: 503, json: { success: false, message: 'Chargement indisponible.' } });
          }
          if (path === '/owner/location/new' && request.method() === 'POST') {
            network.createPosts++;
            if (network.invalid) {
              network.invalid = false;
              return route.fulfill({ status: 422, json: { success: false, message: 'Verifiez le titre.',
                errors: { title: 'Corrigez le titre de cette annonce.' } } });
            }
            if (network.csrf) {
              network.csrf = false;
              return route.fulfill({ status: 400, contentType: 'text/html', body: '<p>Session expiree.</p>' });
            }
            if (network.offline) { network.offline = false; return route.abort('connectionfailed'); }
            if (network.gate) await network.gate;
          }
          if (/\/owner\/location\/\d+\/(close|delete)$/.test(path) && request.method() === 'POST') {
            network.actionPosts++;
            if (network.actionFailure) return route.fulfill({ status: 503, contentType: 'text/html', body: '<p>Action indisponible.</p>' });
          }
          return route.continue();
        });
        await page.goto(base + '/owner/locations', { waitUntil: 'domcontentloaded' });
        await page.locator(cards).first().waitFor();
        const initialDocuments = documents.length;
        await geometry(page, width, false);

        // The list keeps AJAX search, status filters, pagination and Back working.
        await page.locator('.owner-refresh-pagination a[href*="page=2"]').first().click();
        await page.waitForFunction(() => new URL(location.href).searchParams.get('page') === '2');
        await settled(page);
        await page.goBack();
        await page.waitForFunction(() => new URL(location.href).searchParams.get('page') !== '2');
        await settled(page);
        const search = page.locator('.owner-filter-form [name="q"]');
        await search.fill('demonstration 07');
        await search.press('Enter');
        await page.waitForFunction(() => new URL(location.href).searchParams.get('q') === 'demonstration 07');
        await settled(page);
        assert.equal(await page.locator(cards).count(), 1, 'search shows the matching seeded announcement');
        assert.match(await page.locator(cards).first().textContent(), /demonstration 07/);
        await page.locator('.owner-filter-form [name="q"]').fill('');
        await page.locator('.owner-filter-form [name="q"]').press('Enter');
        await page.waitForFunction(() => !new URL(location.href).searchParams.get('q'));
        await settled(page);
        await page.locator('.owner-status-filters a[href*="status=reserved"]').click();
        await page.waitForFunction(() => new URL(location.href).searchParams.get('status') === 'reserved');
        await settled(page);
        assert(await page.locator(cards).count() >= 1, 'reserved filter has seeded matches');
        assert.equal(await page.locator('.owner-status-filter[aria-current="page"]').count(), 1);
        const all = page.locator('.owner-status-filter').filter({ hasText: /Tout|Tous/i }).first();
        await all.click();
        await page.waitForFunction(() => !new URL(location.href).searchParams.get('status'));
        await settled(page);

        // A failed list action stays on the list and is never retried automatically.
        network.actionFailure = true;
        const action = page.locator(cards).filter({ has: page.locator('form[action$="/close"] input[name="status"][value="reserved"]') }).first();
        await action.locator('details.owner-rental-more').evaluate(node => { node.open = true; });
        const reserve = action.locator('form[action$="/close"]').filter({
          has: page.locator('input[name="status"][value="reserved"]'),
        }).locator('button');
        const beforeActions = network.actionPosts;
        await Promise.all([
          page.waitForResponse(response => /\/owner\/location\/\d+\/close$/.test(new URL(response.url()).pathname) &&
            response.request().method() === 'POST' && response.status() === 503), reserve.click(),
        ]);
        await page.waitForTimeout(400);
        assert.equal(network.actionPosts - beforeActions, 1, 'failed action sends one POST');
        assert.equal(documents.length, initialDocuments, 'failed action keeps the current document');
        network.actionFailure = false;

        const opener = page.locator('[data-vendor-location-create]:visible').first();
        await opener.scrollIntoViewIfNeeded();
        const oldScroll = await page.evaluate(() => scrollY);
        await open(page);
        await geometry(page, width, true);
        await page.keyboard.press('Tab');
        assert(await page.evaluate(() => document.getElementById('vendorProductDialog').contains(document.activeElement)));
        await page.keyboard.press('Escape');
        await closed(page);
        assert(await opener.evaluate(node => document.activeElement === node), 'modal returns focus');
        assert(Math.abs(await page.evaluate(() => scrollY) - oldScroll) <= 3, 'modal restores page scroll');
        await open(page);
        await page.goBack();
        await closed(page);
        await settled(page);

        // A search response arriving after opening must never erase the modal's history entry.
        let delaySearch = true;
        const delayedSearch = async route => {
          if (delaySearch && route.request().headers()['x-requested-with']) {
            delaySearch = false;
            await new Promise(resolve => setTimeout(resolve, 700));
          }
          await route.continue();
        };
        await page.route('**/owner/locations?*', delayedSearch);
        const searching = page.waitForRequest(request => new URL(request.url()).pathname === '/owner/locations' &&
          new URL(request.url()).searchParams.get('q') === 'demonstration' && !!request.headers()['x-requested-with']);
        await page.locator('.owner-filter-form [name="q"]').fill('demonstration');
        await searching;
        await open(page);
        await page.waitForTimeout(800);
        assert.equal(await page.evaluate(() => history.state.bmVendorProductCreate), 'location',
          'pending search never replaces the open modal history entry');
        assert.equal(new URL(page.url()).searchParams.get('new'), 'location');
        await page.locator('[data-vpm-close]:visible').first().click();
        await closed(page);
        await page.waitForFunction(() => !document.querySelector('.owner-shell').classList.contains('is-loading') &&
          new URL(location.href).searchParams.get('q') === 'demonstration');
        await page.unroute('**/owner/locations?*', delayedSearch);

        // Publication refreshes the current filtered list, keeping its query intact.
        await page.locator('.owner-filter-form [name="q"]').fill(title(width));
        await page.locator('.owner-filter-form [name="q"]').press('Enter');
        await page.waitForFunction(query => new URL(location.href).searchParams.get('q') === query, title(width));
        await settled(page);

        network.getFailure = true;
        await page.locator('[data-vendor-location-create]:visible').first().click();
        await page.locator('[data-vpm-retry]').waitFor();
        await page.locator('[data-vpm-retry]').click();
        await loaded(page);
        await fill(page, ids, width);
        if (width === 390) {
          await page.locator('#vpmName').focus();
          await page.setViewportSize({ width, height: 520 });
          await page.waitForTimeout(250);
          await geometry(page, width, true);
          await page.setViewportSize({ width, height: 844 });
          await page.waitForTimeout(250);
        }
        await page.locator('#vpmImages').setInputFiles({ name: 'rental-fixture.png', mimeType: 'image/png', buffer: image });
        assert.equal(await page.locator('#vpmImagePreviews .vpm-image-preview').count(), 1);
        await page.locator('#vendorCreateForm').evaluate(node => { window.__rentalDraft = node; });
        network.invalid = true;
        await Promise.all([
          page.waitForResponse(response => response.url().includes('/owner/location/new') &&
            response.request().method() === 'POST' && response.status() === 422),
          page.locator('[data-vpm-submit]').click(),
        ]);
        await page.waitForFunction(() => !document.querySelector('[data-vpm-submit]').disabled);
        assert(await page.evaluate(() => document.getElementById('vendorCreateForm') === window.__rentalDraft));
        assert.equal(await page.locator('#vpmImagePreviews img[alt="rental-fixture.png"]').count(), 1);
        assert.equal(await page.locator('#vpmName').inputValue(), title(width));

        await page.locator('[data-vpm-close]:visible').first().click();
        await page.locator('#vpmDiscardConfirm').waitFor({ state: 'visible' });
        await page.locator('[data-vpm-keep]').click();
        network.offline = true;
        await Promise.all([
          page.waitForEvent('requestfailed', { predicate: request => request.url().includes('/owner/location/new') && request.method() === 'POST' }),
          page.locator('[data-vpm-submit]').click(),
        ]);
        await page.waitForFunction(() => !document.querySelector('[data-vpm-submit]').disabled);
        assert.equal(await page.locator('#vpmImagePreviews img[alt="rental-fixture.png"]').count(), 1);
        network.csrf = true;
        await page.locator('#vendorCreateForm [name="csrf_token"]').evaluate(node => { node.value = 'expired-rental-fixture'; });
        await Promise.all([
          page.waitForResponse(response => response.url().includes('/owner/location/new') &&
            response.request().method() === 'POST' && response.status() === 400),
          page.locator('[data-vpm-submit]').click(),
        ]);
        const beforeRefresh = network.createPosts;
        await page.locator('[data-vpm-refresh-session]').click();
        await page.waitForFunction(() => document.querySelector('#vendorCreateForm [name="csrf_token"]').value !== 'expired-rental-fixture');
        assert(await page.evaluate(() => document.getElementById('vendorCreateForm') === window.__rentalDraft));
        assert.equal(network.createPosts, beforeRefresh, 'session refresh does not republish automatically');

        let release;
        network.gate = new Promise(resolve => { release = resolve; });
        const beforeSave = network.createPosts;
        const created = page.waitForResponse(response => response.url().includes('/owner/location/new') &&
          response.request().method() === 'POST' && response.status() === 201);
        await page.locator('[data-vpm-submit]').click();
        await page.waitForFunction(() => document.querySelector('[data-vpm-submit]').disabled);
        await page.locator('#vendorCreateForm').evaluate(node => node.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
        await page.waitForTimeout(100);
        assert.equal(network.createPosts - beforeSave, 1, 'publication has one active POST');
        release();
        const createdResponse = await created;
        const payload = await createdResponse.json();
        assert.equal(payload.success, true);
        assert(createdResponse.request().postDataBuffer().includes(Buffer.from('filename="rental-fixture.png"')));
        await closed(page);
        await settled(page);
        await page.locator(cards).filter({ has: page.locator('a[href^="/owner/location/' + payload.listing.id + '/edit"]') }).waitFor();
        assert.equal(new URL(page.url()).pathname, '/owner/locations');
        assert.equal(new URL(page.url()).searchParams.get('q'), title(width), 'publication preserves the active search');

        await open(page);
        await page.locator('#vpmName').fill('Brouillon location a abandonner');
        await page.evaluate(() => {
          window.__ownerHistoryForward = history.forward;
          history.forward = function () { setTimeout(() => window.__ownerHistoryForward.call(history), 200); };
        });
        await page.goBack();
        await page.locator('#vpmDiscardConfirm').waitFor({ state: 'visible' });
        await page.locator('[data-vpm-discard]').click();
        await closed(page);
        await page.waitForTimeout(650);
        assert.equal(await page.locator('#vendorProductDialog').evaluate(node => node.open), false,
          'discard while history restores never reopens the location modal');
        await page.evaluate(() => { history.forward = window.__ownerHistoryForward; });
        assert.equal(documents.length, initialDocuments, 'filters and publication preserve the owner list document');
        assert.deepEqual(exceptions, [], 'no browser exceptions');
        console.log(name + ' owner ' + width + ': PASS');
      } finally { await context.close(); }
    }
  } finally { await browser.close(); }
}

(async () => { await run('chromium', chromium); await run('webkit', webkit); })()
  .catch(error => { console.error(error); process.exitCode = 1; });
