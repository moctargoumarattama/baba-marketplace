/* Run only against vendor_catalog_refresh_server.py: disposable SQLite/media. */
const assert = require('node:assert/strict');
const { chromium, webkit } = require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');
const base = process.env.CATALOG_REFRESH_PREVIEW_URL || 'http://127.0.0.1:5076';
const widths = (process.env.CATALOG_WIDTHS || '280,320,390,768,1024,1440,1920').split(',').map(Number);
const local = url => new URL(url).origin === new URL(base).origin;
const rowSelector = '.catalog-card[data-product-id]';
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=', 'base64');

async function ready(page) {
  await page.locator('#catalogFilterForm').waitFor();
  await page.waitForFunction(() => !document.querySelector('#catalogResultsRegion')?.classList.contains('is-loading'));
}

async function geometry(page, label, modal = false) {
  const sizes = await page.evaluate(modal => {
    const summary = document.querySelector('.catalog-summary');
    const shell = document.querySelector('.vd-workspace, .vd-shell, .catalog-shell');
    const active = modal ? document.querySelector('dialog[open]') : null;
    return { width: innerWidth, scroll: document.documentElement.scrollWidth,
      summary: summary?.getBoundingClientRect().toJSON(), shell: shell?.getBoundingClientRect().toJSON(),
      modal: active?.getBoundingClientRect().toJSON(), modalScroll: active?.scrollWidth, modalWidth: active?.clientWidth };
  }, modal);
  assert(sizes.scroll <= sizes.width + 1, `${label}: no horizontal overflow ${sizes.scroll}/${sizes.width}`);
  if (!modal) {
    assert(sizes.summary, label + ': compact summary exists');
    assert(sizes.summary.height <= (sizes.width < 768 ? 125 : 100), label + ': summary stays compact');
    if (sizes.width >= 1440) assert(sizes.shell.width > sizes.width * .85, label + ': seller layout uses screen width');
  } else {
    assert(sizes.modal, label + ': native dialog is open');
    assert(sizes.modal.left >= -1 && sizes.modal.right <= sizes.width + 1, label + ': dialog fits viewport');
    assert(sizes.modalScroll <= sizes.modalWidth + 1, label + ': dialog does not overflow horizontally');
  }
}

async function search(page, value, expectedCount = null) {
  const response = page.waitForResponse(response => {
    const url = new URL(response.url());
    return url.pathname === '/vendor/catalog' && (url.searchParams.get('q') || '') === value &&
      response.request().headers()['x-catalog-partial'] === '1';
  });
  await page.locator('#catalogSearchInput').fill(value);
  await response;
  await page.waitForFunction(value => (new URL(location.href).searchParams.get('q') || '') === value &&
    !document.querySelector('#catalogResultsRegion').classList.contains('is-loading'), value);
  if (expectedCount !== null) await page.waitForFunction(({ selector, count }) =>
    document.querySelectorAll(selector).length === count, { selector: rowSelector, count: expectedCount });
}

async function closeForm(page) {
  await page.locator('#vendorProductDialog [data-vpm-close]:visible').first().click();
  if (await page.locator('#vpmDiscardConfirm').isVisible()) await page.locator('[data-vpm-discard]').click();
  await page.waitForFunction(() => !document.getElementById('vendorProductDialog').open && !history.state?.bmVendorProductCreate);
}

async function openForm(page, locator) {
  await locator.click();
  await page.locator('#vendorCreateForm').waitFor({ state: 'visible' });
  await page.waitForTimeout(250);
  assert.equal(new URL(page.url()).pathname, '/vendor/catalog', 'form stays on catalogue');
  await geometry(page, 'catalogue form', true);
}

async function runEngine(name, engine) {
  const browser = await engine.launch({ headless: true });
  try {
    for (const width of widths) {
      const context = await browser.newContext({ viewport: { width, height: width < 768 ? 844 : 960 },
        isMobile: width < 768, hasTouch: width < 768, serviceWorkers: 'block',
        reducedMotion: width >= 1440 ? 'reduce' : 'no-preference' });
      try {
        const response = await context.request.get(base + '/__catalog_refresh_fixture__');
        assert(response.ok());
        const fixture = await response.json();
        assert.equal(fixture.total, 60);
        const page = await context.newPage();
        page.setDefaultTimeout(15000);
        const errors = [], documents = [];
        const deletes = { count: 0, failNext: false };
        page.on('pageerror', error => errors.push(error.message));
        page.on('request', request => {
          if (request.isNavigationRequest() && request.frame() === page.mainFrame()) documents.push(request.url());
        });
        await page.route('**/*', route => local(route.request().url()) ? route.continue() : route.abort());
        await page.route('**/vendor/product/*/delete', route => {
          if (route.request().method() !== 'POST') return route.continue();
          deletes.count++;
          if (deletes.failNext) {
            deletes.failNext = false;
            return route.fulfill({ status: 503, json: { success: false, message: 'Réessayez dans un instant.' } });
          }
          return route.continue();
        });
        await page.goto(base + '/vendor/catalog', { waitUntil: 'domcontentloaded' });
        await ready(page);
        const initialDocuments = documents.length;
        await geometry(page, `${name}/${width}`);
        assert.equal(await page.locator('#catalogFilterForm select:visible').count(), 1, 'only category selector remains');
        assert.equal(await page.locator('#catalogStatusSelect, #catalogKindSelect, #catalogStockSelect, #catalogSortSelect, #catalogPerPageSelect').count(), 0);
        if (process.env.CATALOG_GEOMETRY_ONLY === '1') { console.log(`${name} ${width}: geometry PASS`); continue; }
        assert.equal(await page.locator(rowSelector).count(), 24, 'catalogue is paginated');
        assert.equal(await page.locator(`[data-product-id="${fixture.target}"]`).count(), 0, 'search target starts beyond the first page');
        await page.locator('#catalogSearchInput').evaluate(node => { window.__retainedSearch = node; });
        await search(page, 'epices etoilees', 1);
        assert.equal(await page.locator(rowSelector).getAttribute('data-product-id'), String(fixture.target),
          'accent and multiword search finds an older item beyond the current page');
        assert(await page.evaluate(() => document.querySelector('#catalogSearchInput') === window.__retainedSearch &&
          document.activeElement === window.__retainedSearch), 'search remains mounted and focused');
        await search(page, '#' + fixture.target, 1);
        await search(page, 'confidentielles', 0);
        assert.match(await page.locator('#catalogResultsRegion').innerText(), /Aucun résultat|Aucune offre trouvée/i);
        await search(page, 'produits de test', 20);
        await search(page, '');

        const categoryResponse = page.waitForResponse(response => {
          const url = new URL(response.url());
          return url.pathname === '/vendor/catalog' && url.searchParams.get('category_id') === String(fixture.service) &&
            response.request().headers()['x-catalog-partial'] === '1';
        });
        await page.locator('#catalogCategorySelect').selectOption(String(fixture.service));
        await categoryResponse;
        await page.waitForFunction(() => !document.querySelector('#catalogResultsRegion').classList.contains('is-loading'));
        assert.equal(await page.locator(rowSelector).count(), 20);
        const allCategories = page.waitForResponse(response => {
          const url = new URL(response.url());
          return url.pathname === '/vendor/catalog' && !url.searchParams.get('category_id') &&
            response.request().headers()['x-catalog-partial'] === '1';
        });
        await page.locator('#catalogCategorySelect').selectOption('');
        await allCategories;
        await ready(page);
        await page.locator('[data-catalog-page-link="next"]').click();
        await page.waitForFunction(() => new URL(location.href).searchParams.get('page') === '2' &&
          !document.querySelector('#catalogResultsRegion').classList.contains('is-loading'));
        await page.goBack();
        await page.waitForFunction(() => !new URL(location.href).searchParams.get('page') &&
          !document.querySelector('#catalogResultsRegion').classList.contains('is-loading'));

        await openForm(page, page.locator('[data-vendor-product-create]:visible').first());
        await closeForm(page);
        await openForm(page, page.locator(`${rowSelector} [data-vendor-product-edit]`).first());
        assert(await page.locator('#vpmName').inputValue(), 'edit modal is prefilled');
        await closeForm(page);

        if (width === 390 || width === 1440) {
          await page.route('**/vendor/catalog*', async route => {
            const request = route.request();
            const query = new URL(request.url()).searchParams.get('q');
            if (request.headers()['x-catalog-partial'] === '1' && query === 'connexion-test') {
              return route.fulfill({ status: 503, json: { success: false } });
            }
            if (request.headers()['x-catalog-partial'] === '1' && query === 'entretien') {
              await new Promise(resolve => setTimeout(resolve, 800));
            }
            try { await route.continue(); } catch (_error) { /* older aborted query */ }
          });
          const slowRead = page.waitForRequest(request => new URL(request.url()).pathname === '/vendor/catalog' &&
            new URL(request.url()).searchParams.get('q') === 'entretien');
          await page.locator('#catalogSearchInput').fill('entretien');
          await slowRead;
          await search(page, 'confidentielles', 0);
          await page.waitForTimeout(900);
          assert.equal(await page.locator(rowSelector).count(), 0, 'obsolete response never replaces the latest search');
          await search(page, '');
          const beforeFailure = await page.locator('#catalogResultsRegion').innerHTML();
          const beforeFailureUrl = page.url();
          const failedRead = page.waitForResponse(response => response.status() === 503 &&
            new URL(response.url()).searchParams.get('q') === 'connexion-test');
          await page.locator('#catalogSearchInput').fill('connexion-test');
          await failedRead;
          await page.locator('[data-catalog-feedback].is-error').waitFor({ state: 'visible' });
          assert.equal(await page.locator('#catalogResultsRegion').innerHTML(), beforeFailure,
            'a failed search preserves existing offers');
          assert.equal(page.url(), beforeFailureUrl, 'failed read preserves committed history');
          await search(page, '');
          let delayed = false;
          await page.route('**/vendor/catalog*', async route => {
            const query = new URL(route.request().url()).searchParams.get('q');
            if (route.request().headers()['x-catalog-partial'] === '1' && query === 'epices' && !delayed) {
              delayed = true;
              await new Promise(resolve => setTimeout(resolve, 700));
            }
            try { await route.continue(); } catch (_error) { /* cancelled obsolete read */ }
          });
          const delayedRead = page.waitForRequest(request => new URL(request.url()).pathname === '/vendor/catalog' &&
            new URL(request.url()).searchParams.get('q') === 'epices');
          await page.locator('#catalogSearchInput').fill('epices');
          await delayedRead;
          await openForm(page, page.locator('[data-vendor-product-create]:visible').first());
          await page.waitForTimeout(900);
          assert(await page.evaluate(() => !!history.state?.bmVendorProductCreate),
            'pending search does not overwrite modal history');
          await closeForm(page);
          await page.waitForFunction(() => new URL(location.href).searchParams.get('q') === 'epices' &&
            !document.querySelector('#catalogResultsRegion').classList.contains('is-loading'));
          await search(page, 'catalogue');

          const creates = { count: 0 };
          await page.route('**/vendor/product/new*', async route => {
            if (route.request().method() === 'POST') creates.count++;
            await route.continue();
          });
          await openForm(page, page.locator('[data-vendor-product-create]:visible').first());
          await page.locator('#vpmName').fill('Offre catalogue créée en test');
          await page.locator('#vpmCategory').selectOption(String(fixture.physical));
          await page.locator('#vpmPrice').fill('42.50');
          await page.locator('#vpmStock').fill('7');
          await page.locator('#vpmImages').setInputFiles({ name: 'catalogue.png', mimeType: 'image/png', buffer: png });
          const created = page.waitForResponse(response => response.url().includes('/vendor/product/new') &&
            response.request().method() === 'POST');
          await page.locator('[data-vpm-submit]').click();
          const createdResponse = await created;
          assert.equal(createdResponse.status(), 201, 'create uses valid real CSRF');
          const createdData = await createdResponse.json();
          await page.waitForFunction(() => !document.getElementById('vendorProductDialog').open &&
            !history.state?.bmVendorProductCreate && !document.querySelector('#catalogResultsRegion').classList.contains('is-loading'));
          await page.locator(`[data-product-id="${createdData.product.id}"]`).waitFor();
          assert.equal(creates.count, 1, 'one create submission');
          assert.equal(new URL(page.url()).searchParams.get('q'), 'catalogue', 'create preserves catalogue search');

          const editedRow = page.locator(`[data-product-id="${createdData.product.id}"]`);
          await openForm(page, editedRow.locator('[data-vendor-product-edit]').first());
          await page.locator('#vpmPrice').fill('43.75');
          const edited = page.waitForResponse(response => /\/vendor\/product\/\d+\/edit$/.test(new URL(response.url()).pathname) &&
            response.request().method() === 'POST');
          await page.locator('[data-vpm-submit]').click();
          assert.equal((await edited).status(), 200, 'edit submits with real CSRF');
          await page.waitForFunction(() => !document.getElementById('vendorProductDialog').open &&
            !history.state?.bmVendorProductCreate && !document.querySelector('#catalogResultsRegion').classList.contains('is-loading'));
          await page.waitForFunction(id => document.querySelector(`[data-product-id="${id}"]`)?.textContent.includes('43.75'), createdData.product.id);

          const row = page.locator(`[data-product-id="${createdData.product.id}"]`);
          await row.locator('summary').click();
          assert(await row.locator('details').evaluate(node => node.open), 'ellipsis menu opens');
          await page.locator('h1').click();
          assert.equal(await row.locator('details').evaluate(node => node.open), false, 'outside click closes menu');
          await row.locator('summary').click();
          await row.locator('[data-catalog-delete] button[type="submit"]').click();
          await page.locator('#catalogDeleteDialog').waitFor({ state: 'visible' });
          await geometry(page, 'delete confirmation', true);
          await page.locator('[data-catalog-delete-cancel]:visible').first().click();
          assert.equal(deletes.count, 0, 'cancel never posts deletion');
          if (!(await row.locator('details').evaluate(node => node.open))) await row.locator('summary').click();
          await row.locator('[data-catalog-delete] button[type="submit"]').click();
          deletes.failNext = true;
          const rejected = page.waitForResponse(response => /\/delete$/.test(new URL(response.url()).pathname) && response.status() === 503);
          await page.locator('[data-catalog-delete-confirm]').click();
          await rejected;
          await page.waitForFunction(() => !document.querySelector('[data-catalog-delete-confirm]').disabled);
          await page.waitForTimeout(350);
          assert.equal(deletes.count, 1, 'failed deletion is never reposted automatically');
          assert.equal(await row.count(), 1, 'failed deletion keeps existing row');
          assert.match(await page.locator('[data-catalog-delete-confirm]').textContent(), /Vérifier la liste/);
          await page.locator('[data-catalog-delete-confirm]').click();
          await page.waitForFunction(() => !document.getElementById('catalogDeleteDialog').open &&
            !document.querySelector('#catalogResultsRegion').classList.contains('is-loading'));
          assert.equal(deletes.count, 1, 'checking an uncertain mutation only sends GET');
          await row.locator('summary').click();
          await row.locator('[data-catalog-delete] button[type="submit"]').click();
          const deleted = page.waitForResponse(response => /\/delete$/.test(new URL(response.url()).pathname) && response.status() === 200);
          await page.locator('[data-catalog-delete-confirm]').click();
          await deleted;
          await page.waitForFunction(id => !document.querySelector(`[data-product-id="${id}"]`) &&
            !document.getElementById('catalogDeleteDialog').open, createdData.product.id);
          assert.equal(deletes.count, 2, 'successful retry is an explicit click');

          await search(page, '<img src=x onerror="window.__catalogXss=1">', 0);
          assert.equal(await page.evaluate(() => window.__catalogXss), undefined);
          assert.equal(await page.locator('#catalogFilterForm img[src="x"]').count(), 0,
            'query text is never parsed as markup');
        }
        assert.equal(documents.length, initialDocuments, 'catalogue interactions do not navigate the main document');
        assert.deepEqual(errors, [], 'no uncaught JavaScript errors');
        console.log(`${name} ${width}: PASS`);
      } finally { await context.close(); }
    }
    if (process.env.CATALOG_GEOMETRY_ONLY === '1') return;
    for (const variant of ['empty', 'products', 'services']) {
      const context = await browser.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
      try {
        await context.request.get(base + '/__catalog_refresh_fixture__?variant=' + variant);
        const page = await context.newPage();
        await page.route('**/*', route => local(route.request().url()) ? route.continue() : route.abort());
        await page.goto(base + '/vendor/catalog', { waitUntil: 'domcontentloaded' });
        await ready(page);
        await geometry(page, name + '/' + variant);
        if (variant === 'empty') {
          assert.equal(await page.locator(rowSelector).count(), 0);
          assert.match(await page.locator('#catalogResultsRegion').innerText(), /premi[eè]re? offre|catalogue est vide|aucune offre/i);
          assert.equal(await page.locator('[data-vendor-product-create]:visible').count(), 1, 'empty catalogue keeps a single add action');
        }
        console.log(`${name} ${variant}: PASS`);
      } finally { await context.close(); }
    }
    const context = await browser.newContext({ javaScriptEnabled: false, viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
    try {
      const auth = await context.request.get(base + '/__catalog_refresh_fixture__');
      const fixture = await auth.json();
      const page = await context.newPage();
      await page.route('**/*', route => local(route.request().url()) ? route.continue() : route.abort());
      await page.goto(base + '/vendor/catalog', { waitUntil: 'domcontentloaded' });
      await page.locator('#catalogCategorySelect').selectOption(String(fixture.service));
      await page.locator('#catalogFilterForm button[type="submit"]').click();
      await page.waitForURL(url => url.searchParams.get('category_id') === String(fixture.service));
      assert.equal(await page.locator(rowSelector).count(), 20, 'no-JS native category filtering remains usable');
      await page.locator(`${rowSelector} [data-vendor-product-edit]`).first().click();
      await page.locator('#vendorCreateForm').waitFor();
      assert(await page.locator('#vpmName').inputValue(), 'same form renders natively without JavaScript');
      console.log(`${name} no-JS: PASS`);
    } finally { await context.close(); }
  } finally { await browser.close(); }
}

(async () => {
  const engines = process.env.CATALOG_ENGINE ? [[process.env.CATALOG_ENGINE,
    process.env.CATALOG_ENGINE === 'webkit' ? webkit : chromium]] : [['chromium', chromium], ['webkit', webkit]];
  for (const [name, engine] of engines) await runEngine(name, engine);
})().catch(error => { console.error(error); process.exitCode = 1; });
