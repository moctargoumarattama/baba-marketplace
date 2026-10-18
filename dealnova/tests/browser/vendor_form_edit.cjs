/* Run only against owner_location_modal_server.py: disposable users/media/DB.
   Tests actual edits in Chromium and WebKit, plus submission with JS disabled. */
const assert = require('node:assert/strict');
const { chromium, webkit } = require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');
const base = process.argv[2] || process.env.OWNER_MODAL_PREVIEW_URL || 'http://127.0.0.1:5073';
const image = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=', 'base64');
const headers = (kind, mode) => ({ 'X-Vendor-Modal': kind + '-' + mode,
  'X-Requested-With': 'XMLHttpRequest', Accept: 'application/json' });

async function seed(context, kind, suffix) {
  const auth = await context.request.get(base + '/__owner_modal_fixture__');
  assert(auth.ok(), 'the isolated fixture provides its own synthetic login');
  const ids = await auth.json();
  const path = kind === 'product' ? '/vendor/product' : '/owner/location';
  const response = await context.request.get(base + path + '/new', { headers: headers(kind, 'create') });
  assert(response.ok());
  const { html } = await response.json();
  const csrf = html.match(/name="csrf_token"[^>]*value="([^"]+)"/)[1];
  const title = 'Edition ' + kind + ' ' + suffix;
  const values = kind === 'product'
    ? { name: title, kind: 'physical', category_id: String(ids.physical), price: '25.50', stock: '3' }
    : { title, listing_type: 'monthly', property_type: 'apartment', city: 'Rabat', area: 'Centre',
      rent: '2500.50', shop_id: String(ids.shop), deposit_required: '0', owner_fee: '500.25', owner_fee_text: 'Frais' };
  const creation = await context.request.post(base + path + '/new', { headers: headers(kind, 'create'),
    multipart: { ...values, csrf_token: csrf, description: 'Created only inside a disposable preview.',
      images: { name: 'original.png', mimeType: 'image/png', buffer: image } } });
  assert.equal(creation.status(), 201, await creation.text());
  const data = await creation.json();
  const item = data[kind === 'product' ? 'product' : 'listing'];
  return { id: item.id, ids, title, url: path + '/' + item.id + '/edit',
    page: kind === 'product' ? '/vendor/catalog' : '/owner/locations' };
}

async function loaded(page) {
  await page.locator('#vendorCreateForm').waitFor({ state: 'visible' });
  await page.waitForTimeout(250);
}
async function closed(page) {
  await page.waitForFunction(() => !document.getElementById('vendorProductDialog').open);
  await page.waitForFunction(() => !history.state?.bmVendorProductCreate);
}
async function open(page, kind, fixture) {
  await page.locator('[data-vendor-' + kind + '-edit][href^="' + fixture.url + '"]:visible').first().click();
  await loaded(page);
  assert.equal(new URL(page.url()).pathname, fixture.page, 'editing stays on the page that opened it');
  assert.equal(new URL(page.url()).searchParams.get('edit_' + kind), String(fixture.id));
  assert.match(await page.locator('[data-vpm-submit]').textContent(), /Enregistrer/i);
}
async function geometry(page) {
  const values = await page.evaluate(() => {
    const dialog = document.getElementById('vendorProductDialog');
    return { width: innerWidth, height: innerHeight, page: document.documentElement.scrollWidth,
      dialog: dialog.getBoundingClientRect().toJSON(), scroll: dialog.scrollWidth, client: dialog.clientWidth,
      save: dialog.querySelector('[data-vpm-submit]').getBoundingClientRect().toJSON() };
  });
  assert(values.page <= values.width + 1, 'no horizontal page overflow');
  assert(values.dialog.left >= -1 && values.dialog.right <= values.width + 1, 'modal stays within the viewport');
  assert(values.scroll <= values.client + 1, 'modal content fits its width');
  assert(values.save.top >= 0 && values.save.bottom <= values.height + 1, 'save remains visible');
}

async function journey(browser, engineName, width, kind) {
  const context = await browser.newContext({ viewport: { width, height: width < 768 ? 844 : 940 },
    isMobile: width < 768, hasTouch: width < 768, serviceWorkers: 'block',
    reducedMotion: width === 1440 ? 'reduce' : 'no-preference' });
  try {
    const fixture = await seed(context, kind, engineName + '-' + width + '-' + Date.now());
    const page = await context.newPage();
    page.setDefaultTimeout(12000);
    const documents = [], exceptions = [];
    page.on('pageerror', error => exceptions.push(error.message));
    page.on('request', request => {
      if (request.isNavigationRequest() && request.frame() === page.mainFrame()) documents.push(request.url());
    });
    await page.route('**/*', route => new URL(route.request().url()).origin === new URL(base).origin
      ? route.continue() : route.abort());
    const network = { invalid: false, csrf: false, posts: 0, gate: null };
    await page.route('**' + fixture.url + '*', async route => {
      if (route.request().method() === 'POST') {
        network.posts++;
        if (network.invalid) {
          network.invalid = false;
          return route.fulfill({ status: 422, json: { success: false, message: 'Corrigez le champ.',
            errors: { [kind === 'product' ? 'name' : 'title']: 'Texte de test invalide.' } } });
        }
        if (network.csrf) {
          network.csrf = false;
          return route.fulfill({ status: 400, json: { success: false, error: 'csrf' } });
        }
        if (network.gate) await network.gate;
      }
      await route.continue();
    });
    await page.goto(base + fixture.page, { waitUntil: 'domcontentloaded' });
    const initialDocuments = documents.length;
    await open(page, kind, fixture);
    await geometry(page);
    const title = page.locator('#vendorCreateForm [name="' + (kind === 'product' ? 'name' : 'title') + '"]');
    assert.equal(await title.inputValue(), fixture.title);
    assert.equal(await page.locator('[name="delete_images"]').count(), 1);
    assert.equal(await page.locator('[name="delete_images"]:checked').count(), 0);
    await page.keyboard.press('Escape');
    await closed(page);
    await open(page, kind, fixture);

    const changedTitle = fixture.title + ' updated';
    await title.fill(changedTitle);
    await page.locator('[name="delete_images"]').check();
    await page.locator('#vpmImages').setInputFiles({ name: 'replacement.png', mimeType: 'image/png', buffer: image });
    await page.locator('#vendorCreateForm').evaluate(form => { window.__editDraft = form; });
    network.invalid = true;
    await Promise.all([
      page.waitForResponse(response => response.url().includes(fixture.url) && response.status() === 422),
      page.locator('[data-vpm-submit]').click(),
    ]);
    await page.waitForFunction(() => !document.querySelector('[data-vpm-submit]').disabled);
    assert(await page.evaluate(() => window.__editDraft === document.getElementById('vendorCreateForm')));
    assert.equal(await title.inputValue(), changedTitle);
    assert.equal(await page.locator('[name="delete_images"]:checked').count(), 1);
    assert.equal(await page.locator('#vpmImagePreviews img[alt="replacement.png"]').count(), 1);
    await page.locator('[data-vpm-close]:visible').first().click();
    await page.locator('#vpmDiscardConfirm').waitFor({ state: 'visible' });
    await page.locator('[data-vpm-keep]').click();

    network.csrf = true;
    const beforeCsrf = network.posts;
    await Promise.all([
      page.waitForResponse(response => response.url().includes(fixture.url) && response.status() === 400),
      page.locator('[data-vpm-submit]').click(),
    ]);
    await page.waitForFunction(() => !document.querySelector('[data-vpm-submit]').disabled);
    assert.equal(network.posts - beforeCsrf, 1, 'CSRF failure is never retried as an automatic POST');
    assert.equal(await title.inputValue(), changedTitle);
    assert.equal(await page.locator('[name="delete_images"]:checked').count(), 1);

    let release;
    network.gate = new Promise(resolve => { release = resolve; });
    const beforeSave = network.posts;
    const saving = page.waitForRequest(request => request.url().includes(fixture.url) && request.method() === 'POST');
    await page.locator('[data-vpm-submit]').click();
    await saving;
    await page.locator('[data-vpm-submit]').evaluate(button => { button.click(); button.click(); });
    await page.waitForTimeout(150);
    assert.equal(network.posts - beforeSave, 1, 'double activation sends a single edit');
    const saved = page.waitForResponse(response => response.url().includes(fixture.url) && response.request().method() === 'POST');
    release();
    const savedResponse = await saved;
    assert.equal(savedResponse.status(), 200, await savedResponse.text());
    const data = await savedResponse.json();
    assert.equal(data[kind === 'product' ? 'product' : 'listing'].id, fixture.id);
    await closed(page);
    assert.equal(new URL(page.url()).pathname, fixture.page);
    assert.equal(documents.length, initialDocuments, 'saving an edit never loads another document');
    await page.getByText(changedTitle, { exact: true }).first().waitFor();

    await open(page, kind, fixture);
    assert.equal(await title.inputValue(), changedTitle, 'reopening reads the saved record');
    assert.equal(await page.locator('[name="delete_images"]').count(), 1, 'replacement leaves one existing photo');
    assert.equal(await page.locator('[name="delete_images"]:checked').count(), 0);
    await page.goBack();
    await closed(page);
    assert.equal(documents.length, initialDocuments);
    assert.deepEqual(exceptions, [], 'no uncaught browser errors');
    console.log(engineName + ' ' + width + ' ' + kind + ': edit passed');
  } finally { await context.close(); }
}

async function withoutJavaScript(browser, engineName, kind) {
  const context = await browser.newContext({ javaScriptEnabled: false, serviceWorkers: 'block' });
  try {
    const fixture = await seed(context, kind, engineName + '-native-' + Date.now());
    const page = await context.newPage();
    await page.route('**/*', route => new URL(route.request().url()).origin === new URL(base).origin
      ? route.continue() : route.abort());
    await page.goto(base + fixture.url + '?standalone=1', { waitUntil: 'domcontentloaded' });
    await page.locator('#vendorCreateForm').waitFor({ state: 'visible' });
    const title = page.locator('#vendorCreateForm [name="' + (kind === 'product' ? 'name' : 'title') + '"]');
    assert.equal(await title.inputValue(), fixture.title);
    await title.fill(fixture.title + ' native');
    const response = page.waitForResponse(item => item.url().includes(fixture.url) && item.request().method() === 'POST');
    await page.locator('[data-vpm-submit]').click();
    assert([302, 303].includes((await response).status()), 'the same form submits natively without JS');
    const updated = await context.request.get(base + fixture.url, { headers: headers(kind, 'edit') });
    assert((await updated.json()).html.includes(fixture.title + ' native'));
    console.log(engineName + ' ' + kind + ': native form passed');
  } finally { await context.close(); }
}

(async () => {
  for (const [name, engine] of [['chromium', chromium], ['webkit', webkit]]) {
    const browser = await engine.launch({ headless: true });
    try {
      for (const width of [390, 1440]) for (const kind of ['product', 'location']) await journey(browser, name, width, kind);
      for (const kind of ['product', 'location']) await withoutJavaScript(browser, name, kind);
    } finally { await browser.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
