/* Run only with vendor_records_server.py: synthetic orders, SQLite and media. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium, webkit } = require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');
const base = process.env.VENDOR_RECORDS_PREVIEW_URL || 'http://127.0.0.1:5078';
const widths = (process.env.VENDOR_RECORDS_WIDTHS || '280,320,390,768,1024,1440,1920').split(',').map(Number);
const local = url => new URL(url).origin === new URL(base).origin;
const configs = {
  earnings: { pathname: '/vendor/earnings', form: '#earningsFilterForm', search: '#earningsSearchInput',
    region: '#earningsResultsRegion', summary: '[data-earnings-summary]', rows: '.order-row[data-order-id]',
    id: 'data-order-id', target: 'targetOrder', query: 'safran dore', common: 'article', firstPage: 30,
    dialog: '#earningsReceiptDialog' },
  archives: { pathname: '/owner/locations/archives', form: '#archiveFilterForm', search: '#archiveSearchInput',
    region: '#archiveResultsRegion', summary: '#archiveSummary', rows: '[data-archive-row][data-archive-id]',
    id: 'data-archive-id', target: 'targetArchive', query: 'Studio lumineux', common: 'Appartement', firstPage: 20,
    dialog: '#archiveDetailDialog' },
};
const selectedConfigs = Object.entries(configs).filter(([kind]) =>
  !process.env.VENDOR_RECORDS_PAGES || process.env.VENDOR_RECORDS_PAGES.split(',').includes(kind));

async function fixture(context, reset = true) {
  const response = await context.request.get(`${base}/__vendor_records_fixture__?reset=${reset ? '1' : '0'}`);
  assert(response.ok(), 'disposable records fixture is available');
  return response.json();
}

async function ready(page, config) {
  await page.locator(config.form).waitFor();
  const loader = page.locator('#bm-loader');
  if (await loader.count()) await loader.waitFor({ state: 'hidden' });
}

async function geometry(page, config, label, modal = false) {
  const size = await page.evaluate(({ config, modal }) => {
    const shell = document.querySelector('.vd-shell');
    const summary = document.querySelector(config.summary);
    const dialog = modal ? document.querySelector(config.dialog) : null;
    return { viewport: innerWidth, scroll: document.documentElement.scrollWidth,
      shell: shell?.getBoundingClientRect().toJSON(), summary: summary?.getBoundingClientRect().toJSON(),
      dialog: dialog?.getBoundingClientRect().toJSON(), dialogOpen: dialog?.open,
      dialogWidth: dialog?.clientWidth, dialogScroll: dialog?.scrollWidth };
  }, { config, modal });
  assert(size.scroll <= size.viewport + 1, `${label}: no horizontal overflow ${size.scroll}/${size.viewport}`);
  if (modal) {
    assert(size.dialogOpen, label + ': native dialog is open');
    assert(size.dialog.left >= -1 && size.dialog.right <= size.viewport + 1, label + ': dialog fits viewport');
    assert(size.dialogScroll <= size.dialogWidth + 1, label + ': dialog content does not overflow');
  } else {
    assert(size.summary, label + ': compact summary exists');
    assert(size.summary.height <= (size.viewport < 768 ? 130 : 110), label + ': summary is compact');
    if (size.viewport >= 1440) assert(size.shell?.width > size.viewport * .85, label + ': seller layout uses desktop width');
  }
  const identifiers = await page.locator(config.rows).evaluateAll((rows, attribute) => rows.map(row => row.getAttribute(attribute)), config.id);
  assert.equal(new Set(identifiers).size, identifiers.length, label + ': records are not duplicated for desktop/mobile');
}

async function search(page, config, query, count = null) {
  const response = page.waitForResponse(response => new URL(response.url()).pathname === config.pathname &&
    (new URL(response.url()).searchParams.get('q') || '') === query && response.request().method() === 'GET');
  await page.locator(config.search).fill(query);
  const result = await response;
  assert(result.ok(), 'server search succeeds');
  await page.waitForFunction(({ pathname, query }) => location.pathname === pathname &&
    (new URL(location.href).searchParams.get('q') || '') === query, { pathname: config.pathname, query });
  if (count !== null) await page.waitForFunction(({ rows, count }) => document.querySelectorAll(rows).length === count,
    { rows: config.rows, count });
}

async function searchAndPagination(page, config, state) {
  assert.equal(await page.locator(`${config.rows}[${config.id}="${state[config.target]}"]`).count(), 0,
    'search target starts beyond the first page');
  await page.locator(config.search).evaluate(input => { window.__recordsSearch = input; });
  await search(page, config, config.query, 1);
  assert.equal(await page.locator(config.rows).getAttribute(config.id), String(state[config.target]),
    'server search finds an older record beyond the current page');
  assert(await page.evaluate(selector => document.querySelector(selector) === window.__recordsSearch &&
    document.activeElement === window.__recordsSearch, config.search), 'search input remains mounted and focused');
  await search(page, config, 'SECRET_', 0);
  await search(page, config, config.common, config.firstPage);
  const next = page.locator(`${config.region} a[href*="page=2"]`).first();
  assert.equal(await next.count(), 1, 'matching records have a second page');
  await next.click();
  await page.waitForFunction(query => new URL(location.href).searchParams.get('page') === '2' &&
    new URL(location.href).searchParams.get('q') === query, config.common);
  assert.equal(await page.locator(config.search).inputValue(), config.common, 'pagination preserves search');
  await page.goBack();
  await page.waitForFunction(query => new URL(location.href).searchParams.get('page') !== '2' &&
    new URL(location.href).searchParams.get('q') === query, config.common);
  await page.waitForFunction(({ rows, count }) => document.querySelectorAll(rows).length === count,
    { rows: config.rows, count: config.firstPage });
  assert.equal(await page.locator(config.search).inputValue(), config.common, 'Back preserves filter controls');
  await search(page, config, '');
}

async function getFailure(page, config, failures) {
  const previousHtml = await page.locator(config.region).innerHTML();
  const previousUrl = page.url();
  failures.query = 'connexion-indisponible';
  const failed = page.waitForResponse(response => response.status() === 503 &&
    new URL(response.url()).searchParams.get('q') === failures.query);
  await page.locator(config.search).fill(failures.query);
  await failed;
  await page.waitForTimeout(180);
  assert.equal(await page.locator(config.region).innerHTML(), previousHtml, 'failed GET keeps existing records');
  assert.equal(page.url(), previousUrl, 'failed GET keeps committed URL');
  failures.query = null;
  await page.locator(config.search).press('Enter');
  await page.waitForFunction(() => new URL(location.href).searchParams.get('q') === 'connexion-indisponible');
  assert.equal(await page.locator(config.rows).count(), 0, 'retry searches the server successfully');
  await search(page, config, '');
}

async function archiveDetails(page, config, width) {
  const row = page.locator(config.rows).first();
  const trigger = row.locator('[data-archive-details]');
  const id = await row.getAttribute(config.id);
  const scrollBefore = await page.evaluate(() => scrollY);
  await trigger.click();
  await page.locator(`${config.dialog}[open]`).waitFor();
  await geometry(page, config, 'archive details', true);
  const first = await page.locator(config.dialog).boundingBox();
  await page.waitForTimeout(180);
  const second = await page.locator(config.dialog).boundingBox();
  assert(Math.abs(first.x - second.x) <= 1 && Math.abs(first.y - second.y) <= 1, 'archive modal stays stable');
  assert.equal(new URL(page.url()).pathname, config.pathname, 'archive detail stays on the current page');
  await page.locator(`${config.dialog} [data-vd-close]:visible`).first().click();
  await page.waitForFunction(selector => !document.querySelector(selector).open, config.dialog);
  assert(await trigger.evaluate(node => node === document.activeElement), 'detail close restores focus');
  assert.equal(await row.locator('[data-archive-detail-content]').count(), 1, 'detail content returns to the original record');
  assert.equal(await row.getAttribute(config.id), id);
  assert(Math.abs((await page.evaluate(() => scrollY)) - scrollBefore) <= 2, 'modal close restores page position');
  if (width === 390 || width === 1440) {
    await page.locator('#archiveReasonSelect').selectOption('taken');
    await page.waitForFunction(() => new URL(location.href).searchParams.get('status') === 'taken');
    assert.equal(await page.locator(config.rows).count(), 10, 'closure reason filters on the server');
    await page.locator('#archiveReasonSelect').selectOption('');
    await page.waitForFunction(() => !new URL(location.href).searchParams.get('status'));
  }
}

async function receipt(page, config, context, state, posts) {
  const row = page.locator(`${config.rows}[data-order-id="${state.mixedOrder}"]`);
  assert.equal(await row.count(), 1, 'mixed order is visible to its physical-product vendor');
  const amount = state.amounts[String(state.mixedOrder)];
  const amountPattern = new RegExp(`${Math.floor(amount / 100)}[.,]${String(amount % 100).padStart(2, '0')}`);
  assert.match(await row.innerText(), amountPattern, 'ledger amount counts only owned physical lines');
  assert.doesNotMatch(await page.locator(config.region).innerText(), /SECRET_PRODUIT_AUTRE_VENDEUR|SERVICE_HORS_CAISSE/,
    'foreign products and services do not leak into the physical ledger');
  const trigger = row.locator('.pay-form[data-earnings-receipt] button[type="submit"]');
  await trigger.click();
  await page.locator(`${config.dialog}[open]`).waitFor();
  await geometry(page, config, 'receipt confirmation', true);
  assert.match(await page.locator(config.dialog).innerText(), amountPattern, 'confirmation shows owned physical amount');
  await page.locator('#earningsReceiptForm [name="note"]').fill('Note annulee');
  await page.locator(`${config.dialog} [data-vd-close]:visible`).first().click();
  await page.waitForFunction(selector => !document.querySelector(selector).open, config.dialog);
  assert.equal((await fixture(context, false)).confirmed.length, state.confirmed.length, 'cancel makes no financial change');
  await trigger.click();
  await page.locator(`${config.dialog}[open]`).waitFor();
  const note = 'Especes recues apres verification client';
  await page.locator('#earningsReceiptForm [name="note"]').fill(note);
  const beforeCsrf = posts.count;
  const beforeTokenRead = posts.gets;
  await page.locator('#earningsReceiptForm [name="csrf_token"]').evaluate(input => { input.value = 'expired-records-fixture'; });
  posts.failNext = 400;
  await page.locator('[data-earnings-confirm]').click();
  await page.waitForFunction(() => !document.querySelector('[data-earnings-confirm]').disabled &&
    document.querySelector('#earningsReceiptForm [name="csrf_token"]').value !== 'expired-records-fixture');
  assert.equal(posts.count, beforeCsrf + 1, 'expired CSRF never resubmits a financial POST automatically');
  assert(posts.gets > beforeTokenRead, 'expired CSRF refreshes the token through GET');
  assert.equal(await page.locator('#earningsReceiptForm [name="note"]').inputValue(), note,
    'expired CSRF retains the receipt note');
  posts.failNext = 503;
  const beforeFailure = posts.count;
  await page.locator('[data-earnings-confirm]').click();
  await page.locator('[data-earnings-receipt-error]:visible').waitFor();
  assert.equal(await page.locator('#earningsReceiptForm [name="note"]').inputValue(), note, 'failed POST preserves the note');
  assert.equal(posts.count, beforeFailure + 1, 'failed receipt is never retried automatically');
  assert.equal((await fixture(context, false)).confirmed.length, state.confirmed.length);
  const verification = page.waitForResponse(response => response.request().method() === 'GET' &&
    new URL(response.url()).pathname === config.pathname);
  await page.locator('[data-earnings-confirm]').click();
  await verification;
  await page.waitForFunction(selector => !document.querySelector(selector).open, config.dialog);
  assert.equal(posts.count, beforeFailure + 1, 'uncertain receipt is checked through GET, never a second POST');
  await trigger.click();
  await page.locator(`${config.dialog}[open]`).waitFor();
  assert.equal(await page.locator('#earningsReceiptForm [name="note"]').inputValue(), note,
    'explicit reopen preserves the failed receipt note');
  const beforeSave = posts.count;
  posts.delayNext = true;
  await page.locator('[data-earnings-confirm]').evaluate(button => { button.click(); button.click(); });
  await page.locator(`${config.dialog} [data-vd-close]:visible`).first().evaluate(button => button.click());
  assert(await page.locator(config.dialog).evaluate(dialog => dialog.open), 'busy confirmation cannot close during submission');
  await page.waitForFunction(selector => !document.querySelector(selector).open, config.dialog);
  await row.locator('.earnings-status-confirmed').waitFor();
  assert.equal(posts.count, beforeSave + 1, 'rapid double confirmation produces one POST');
  const saved = await fixture(context, false);
  assert.equal(saved.confirmed.filter(id => id === state.mixedOrder).length, 1, 'real CSRF-protected confirmation stores one receipt');
  assert.equal(saved.receiptNotes[String(state.mixedOrder)], note, 'receipt note is stored exactly');
  assert.equal(saved.confirmed.length, state.confirmed.length + 1);
}

async function earningsFilters(page, config, state) {
  await page.locator('#earningsShow').selectOption('confirmed');
  await page.waitForFunction(() => new URL(location.href).searchParams.get('show') === 'confirmed');
  assert.equal(await page.locator(config.rows).count(), state.confirmed.length, 'confirmed filter matches stored receipts');
  await page.locator('#earningsShow').selectOption('all');
  await page.waitForFunction(() => !new URL(location.href).searchParams.get('show'));
  await page.locator('#earningsRange').selectOption('custom');
  await page.waitForFunction(() => new URL(location.href).searchParams.get('range') === 'custom');
  assert(await page.locator('#earningsDateFrom').isVisible(), 'custom date fields are visible');
  assert(await page.locator('#earningsDateTo').isEnabled(), 'custom date fields are enabled');
  const day = new Date().toISOString().slice(0, 10);
  await page.locator('#earningsDateFrom').fill(day);
  await page.locator('#earningsDateTo').fill(day);
  await page.locator('#earningsDateTo').press('Tab');
  await page.waitForFunction(day => new URL(location.href).searchParams.get('from') === day &&
    new URL(location.href).searchParams.get('to') === day, day);
  assert((await page.locator(config.rows).count()) > 0, 'custom date range returns the synthetic current-day orders');
  await page.locator('#earningsRange').selectOption('month');
  await page.waitForFunction(() => new URL(location.href).searchParams.get('range') === 'month' &&
    !new URL(location.href).searchParams.has('from') && !new URL(location.href).searchParams.has('to'));
  assert(await page.locator('#earningsDateFrom').isDisabled(), 'preset range excludes custom date values');
}

async function receiptGeometry(page, config) {
  const trigger = page.locator(`${config.region} .pay-form button[type="submit"]`).first();
  await trigger.click();
  await page.locator(`${config.dialog}[open]`).waitFor();
  await geometry(page, config, 'receipt confirmation layout', true);
  const first = await page.locator(config.dialog).boundingBox();
  await page.waitForTimeout(180);
  const second = await page.locator(config.dialog).boundingBox();
  assert(Math.abs(first.x - second.x) <= 1 && Math.abs(first.y - second.y) <= 1, 'receipt modal stays stable');
  await page.locator(`${config.dialog} [data-vd-close]:visible`).first().click();
  await page.waitForFunction(selector => !document.querySelector(selector).open, config.dialog);
  assert(await trigger.evaluate(node => document.activeElement === node), 'receipt close restores focus');
}

async function runEngine(name, engine) {
  const browser = await engine.launch({ headless: true });
  try {
    for (const width of widths) {
      for (const [kind, config] of selectedConfigs) {
        const context = await browser.newContext({ viewport: { width, height: width < 768 ? 844 : 960 },
          hasTouch: width < 768, isMobile: width < 768, serviceWorkers: 'block',
          reducedMotion: width >= 1440 ? 'reduce' : 'no-preference' });
        try {
          const state = await fixture(context);
          const page = await context.newPage();
          const errors = [], documents = [];
          const failures = { query: null }, posts = { count: 0, gets: 0, failNext: 0, delayNext: false };
          page.setDefaultTimeout(15000);
          page.on('pageerror', error => errors.push(error.message));
          page.on('request', request => {
            if (request.isNavigationRequest() && request.frame() === page.mainFrame()) documents.push(request.url());
          });
          await page.route('**/*', route => local(route.request().url()) ? route.continue() : route.abort());
          await page.route('**' + config.pathname + '*', route => {
            if (route.request().method() === 'GET') posts.gets++;
            if (route.request().method() === 'GET' && failures.query &&
                new URL(route.request().url()).searchParams.get('q') === failures.query) {
              return route.fulfill({ status: 503, body: 'Temporarily unavailable', contentType: 'text/plain' });
            }
            return route.continue();
          });
          await page.route('**/vendor/orders/receipt/*', async route => {
            if (route.request().method() !== 'POST') return route.continue();
            posts.count++;
            if (posts.failNext) {
              const status = posts.failNext;
              posts.failNext = 0;
              return route.fulfill({ status, json: status === 400 ? { error: 'csrf' } :
                { success: false, message: 'Verification indisponible. Votre note est conservee.' } });
            }
            if (posts.delayNext) { posts.delayNext = false; await new Promise(resolve => setTimeout(resolve, 600)); }
            return route.continue();
          });
          await page.goto(base + config.pathname, { waitUntil: 'domcontentloaded' });
          await ready(page, config);
          const initialDocuments = documents.length;
          await geometry(page, config, `${name}/${kind}/${width}`);
          assert.equal(await page.locator(config.rows).count(), config.firstPage, 'page is server-paginated');
          if (process.env.VENDOR_RECORDS_SCREENSHOTS_DIR && (width === 390 || width === 1440)) {
            fs.mkdirSync(process.env.VENDOR_RECORDS_SCREENSHOTS_DIR, { recursive: true });
            await page.evaluate(() => document.fonts.ready.then(() => true));
            await page.screenshot({ path: path.join(process.env.VENDOR_RECORDS_SCREENSHOTS_DIR,
              `${kind}-${name.toLowerCase()}-${width}.png`) });
          }
          if (process.env.VENDOR_RECORDS_GEOMETRY_ONLY !== '1') {
            if (kind === 'archives') await archiveDetails(page, config, width);
            if (kind === 'earnings') await receiptGeometry(page, config);
            if (width === 390 || width === 1440) {
              await searchAndPagination(page, config, state);
              await getFailure(page, config, failures);
              if (kind === 'earnings') {
                await earningsFilters(page, config, state);
                await receipt(page, config, context, state, posts);
              }
            }
            assert.equal(documents.length, initialDocuments, 'filters and dialogs keep the current document mounted');
            assert.deepEqual(errors, [], `${name}/${kind}/${width}: no uncaught errors`);
          }
          console.log(`${name} ${kind} ${width}: PASS`);
        } finally { await context.close(); }
      }
    }
    if (process.env.VENDOR_RECORDS_GEOMETRY_ONLY !== '1' && process.env.VENDOR_RECORDS_SKIP_NOJS !== '1') {
      for (const [kind, config] of selectedConfigs) {
        const context = await browser.newContext({ javaScriptEnabled: false,
          viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
        try {
          const state = await fixture(context);
          const page = await context.newPage();
          await page.route('**/*', route => local(route.request().url()) ? route.continue() : route.abort());
          await page.goto(base + config.pathname);
          await page.locator(config.search).fill(config.query);
          await page.locator(`${config.form} button[type="submit"]`).click();
          await page.waitForURL(url => new URL(url).searchParams.get('q') === config.query);
          assert.equal(await page.locator(config.rows).count(), 1, 'no-JavaScript search uses the same server route');
          if (kind === 'archives') {
            await page.locator('[data-archive-details]').click();
            assert(await page.locator('details.archive-details').evaluate(details => details.open), 'native archive details work without JavaScript');
          } else {
            await page.goto(base + config.pathname);
            const row = page.locator(`${config.rows}[data-order-id="${state.mixedOrder}"]`);
            const post = page.waitForResponse(response => response.request().method() === 'POST' &&
              new URL(response.url()).pathname.endsWith('/' + state.mixedOrder));
            await row.locator('.pay-form button[type="submit"]').click();
            await post;
            await page.waitForURL('**/vendor/earnings*');
            assert((await fixture(context, false)).confirmed.includes(state.mixedOrder), 'no-JavaScript confirmation retains real CSRF protection');
          }
          console.log(`${name} ${kind} no-JavaScript: PASS`);
        } finally { await context.close(); }
      }
    }
  } finally { await browser.close(); }
}

(async () => {
  for (const [name, engine] of [['Chromium', chromium], ['WebKit', webkit]]) await runEngine(name, engine);
})().catch(error => { console.error(error); process.exitCode = 1; });
