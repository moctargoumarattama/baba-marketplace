/* Real catalogue and modal assets, synthetic responses: no database or network. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium, webkit } = require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');
const root = path.resolve(__dirname, '../../app');
const origin = 'https://catalog-refresh.test';

function html() {
  let source = fs.readFileSync(path.join(root, 'templates/home.html'), 'utf8');
  source = source.slice(source.indexOf('<div class="u-modal-backdrop"'));
  source = source.slice(0, source.indexOf('<div class="u-modal-backdrop u-cart-backdrop"'));
  source = source.replace("{% include 'partials/_catalog_panel.html' %}",
    fs.readFileSync(path.join(root, 'templates/partials/_catalog_panel.html'), 'utf8'));
  source = source.replace(/\{\{\s*t\((['"])([\s\S]*?)\1\)\s*\}\}/g, (_, _quote, label) => label);
  source = source.replace(/\{%[\s\S]*?%\}|\{\{[\s\S]*?\}\}/g, '');
  const styles = ['ui_home_single_hub', 'home_refresh', 'catalog_panel', 'promotion_highlight']
    .map(name => '<style>' + fs.readFileSync(path.join(root, 'static/css', name + '.css'), 'utf8') + '</style>').join('');
  return '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' + styles +
    '</head><body data-page="landing"><button data-open-universe="products">Produits</button>' + source + '</body></html>';
}

async function setup(context) {
  const page = await context.newPage(), requests = [], errors = [], pending = [];
  const flags = { hold: false, status: 200, price: 40, facets: {} };
  page.on('pageerror', error => errors.push(error.message));
  await page.clock.install({ time: new Date('2026-10-23T12:00:00Z') });
  await page.route(origin + '/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/fixture') return route.fulfill({ contentType: 'text/html; charset=utf-8', body: html() });
    if (url.pathname === '/api/catalog') {
      const params = Object.fromEntries(url.searchParams); requests.push(params);
      if (flags.hold) await new Promise(resolve => pending.push(resolve));
      if (flags.status !== 200) return route.fulfill({ status: flags.status, json: { success: false, message: 'Critères non disponibles.' } });
      const now = await page.evaluate(() => Date.now() / 1000);
      const slot = Number(params.rotation_slot || Math.floor(now / 1800)), pageNumber = Number(params.page || 1);
      const itemType = params.universe === 'services' ? 'service' : params.universe === 'locations' ? 'location' : 'product';
      return route.fulfill({ json: { success: true, facets: flags.facets,
        rotation: params.sort === 'discover' && !params.q ? { slot, interval: 1800, refresh_at: (slot + 1) * 1800, refresh_in: Math.max(1, (slot + 1) * 1800 - now) } : null,
        pagination: { page: pageNumber, pages: 2, total: 24, has_next: pageNumber === 1, has_prev: pageNumber === 2 },
        items: Array.from({ length: 12 }, (_, index) => ({
          id: pageNumber * 100 + index, item_type: itemType, name: (params.q || params.universe) + ' offre ' + (pageNumber * 100 + index),
          stock: flags.price === 65 && index === 0 ? 0 : 3, available: true, price: flags.price, final_price: flags.price,
          description: 'Offre publique du catalogue pour vérifier les retours.', image_url: '', url: '/shop/product/' + (pageNumber * 100 + index),
        })) } });
    }
    if (url.pathname.startsWith('/api/product/')) return route.fulfill({ json: { success: true, product: {
      id: Number(url.pathname.split('/').pop()), name: 'Produit', stock: 3, price: 40, final_price: 40,
      kind: 'physical', images: [], shop: null, category: 'Test', description: 'Fiche produit',
    } } });
    if (url.pathname === '/cart/api/full') return route.fulfill({ json: { success: true, items: [], shop_groups: [], count: 0 } });
    return route.fulfill({ status: 204, body: '' });
  });
  await page.goto(origin + '/fixture');
  await page.addScriptTag({ content: fs.readFileSync(path.join(root, 'static/js/public_catalog.js'), 'utf8') });
  await page.addScriptTag({ content: fs.readFileSync(path.join(root, 'static/js/ui_home_single_hub.js'), 'utf8') });
  const release = () => { flags.hold = false; pending.splice(0).forEach(resolve => resolve()); };
  return { page, requests, errors, flags, release };
}
async function settled(page) {
  await page.waitForFunction(() => document.querySelector('#catalogResults').getAttribute('aria-busy') === 'false');
}
async function begin(page) {
  await page.locator('[data-open-universe="products"]').click();
  await page.clock.runFor(100); await settled(page);
}
async function mark(page) {
  return page.evaluate(() => {
    window.originalCards = Array.from(document.querySelectorAll('#catalogResults .catalog-item'));
    const body = document.querySelector('#uModalBody'); body.scrollTop = 180;
    const link = window.originalCards[0].querySelector('.u-item-title-link'); link.focus({ preventScroll: true });
    window.originalFocus = link; return body.scrollTop;
  });
}
async function staleReturn(page) {
  await page.evaluate(() => BMCatalog.pause());
  await page.clock.fastForward(25000);
  await page.evaluate(() => BMCatalog.resume());
}
async function waitRequests(page, requests, count) {
  for (let attempt = 0; attempt < 30 && requests.length < count; attempt++) await page.waitForTimeout(10);
  assert.equal(requests.length, count);
}

async function run(name, engine, width) {
  const browser = await engine.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width, height: width < 600 ? 844 : 1000 },
    isMobile: width < 600, hasTouch: width < 600, serviceWorkers: 'block', reducedMotion: 'reduce' });
  const fixtures = [];
  async function fresh() { const item = await setup(context); fixtures.push(item); return item; }
  try {
    {
      const { page, requests, flags, release } = await fresh(); await begin(page);
      await page.evaluate(() => { window.originalCards = Array.from(document.querySelectorAll('#catalogResults .catalog-item')); });
      await page.locator('#catalogResults .u-item-title-link').first().click();
      await page.clock.runFor(100);
      await page.waitForFunction(() => document.querySelector('#pDetailContent').style.display === 'block');
      await page.clock.fastForward(25000); flags.hold = true;
      await page.keyboard.press('Escape'); await page.clock.runFor(100);
      await waitRequests(page, requests, 2);
      assert.equal(await page.locator('.catalog-skeleton').count(), 0, 'return from a real detail modal never blanks the catalogue');
      assert.equal(await page.evaluate(() => originalCards.every(card => card.isConnected)), true);
      release(); await settled(page); await page.close();
    }
    {
      const { page, requests, flags, release } = await fresh(); await begin(page);
      const scroll = await mark(page); flags.hold = true;
      await staleReturn(page); await waitRequests(page, requests, 2);
      assert.equal(await page.locator('.catalog-skeleton').count(), 0, 'expired cache keeps the cards');
      assert.equal(await page.evaluate(() => originalCards.every(card => card.isConnected)), true);
      assert.equal(await page.evaluate(() => document.activeElement === originalFocus), true);
      assert.equal(await page.locator('#uModalBody').evaluate(el => el.scrollTop), scroll);
      release(); await settled(page);
      assert.equal(await page.evaluate(() => originalCards.every(card => card.isConnected)), true, 'identical payload preserves every card node');
      assert.equal(await page.evaluate(() => document.activeElement === originalFocus), true);
      assert.equal(requests[1].rotation_slot, requests[0].rotation_slot || (await page.evaluate(() => BMCatalog.snapshot())).filters.rotation_slot);
      await page.close();
    }
    {
      const { page, requests, flags, release } = await fresh(); await begin(page);
      const scroll = await mark(page); flags.hold = true; flags.price = 65;
      await staleReturn(page); await waitRequests(page, requests, 2);
      assert.match(await page.locator('.u-item-price').first().textContent(), /40/);
      release(); await settled(page);
      assert.match(await page.locator('.u-item-price').first().textContent(), /65/);
      assert.equal(await page.locator('.u-btn-cart').first().isDisabled(), true, 'stock refresh disables the cart action');
      assert.equal(await page.evaluate(() => document.activeElement.textContent.includes('produits') || document.activeElement.classList.contains('u-item-title-link')), true);
      assert.equal(await page.locator('#uModalBody').evaluate(el => el.scrollTop), scroll);
      await page.close();
    }
    {
      const { page, requests, flags, release } = await fresh(); await begin(page);
      flags.hold = true; flags.facets = { categories: [{ id: 9, name: 'Catégorie actualisée' }] };
      await staleReturn(page); await waitRequests(page, requests, 2);
      await page.locator('#catalogFilterToggle').click();
      await page.locator('#catalogFilters [name="city"]').fill('Ville saisie');
      release(); await settled(page);
      assert.equal(await page.locator('#catalogFilters [name="city"]').inputValue(), 'Ville saisie', 'background refresh preserves unfinished filter input');
      assert.equal(await page.evaluate(() => document.activeElement.name), 'city');
      await page.close();
    }
    {
      const { page, requests, flags, release } = await fresh(); await begin(page); await mark(page);
      flags.hold = true; flags.status = 503;
      await staleReturn(page); await waitRequests(page, requests, 2); release(); await settled(page);
      assert.equal(await page.evaluate(() => originalCards.every(card => card.isConnected)), true, 'network failure keeps readable results');
      assert.equal(await page.locator('[role="status"]').filter({ hasText: 'Actualisation impossible' }).isVisible(), true);
      flags.status = 200; flags.price = 65;
      await page.locator('button').filter({ hasText: /^Réessayer$/ }).click(); await settled(page);
      assert.match(await page.locator('.u-item-price').first().textContent(), /65/);
      await page.close();
    }
    {
      const { page, requests, flags, release } = await fresh(); await begin(page);
      flags.hold = true;
      await page.evaluate(() => BMCatalog.open('services', '', { sort: 'new' }));
      await waitRequests(page, requests, 2);
      assert.equal(await page.locator('.catalog-item').count(), 0, 'different universe does not show products');
      assert.equal(await page.locator('.catalog-skeleton').count(), 6);
      release(); await settled(page);
      assert.match(await page.locator('.u-item-title').first().textContent(), /services/);
      flags.hold = true;
      await page.evaluate(() => BMCatalog.open('services', 'coiffure', { sort: 'new' }));
      await waitRequests(page, requests, 3);
      assert.equal(await page.locator('.catalog-item').count(), 0, 'different query does not borrow older results');
      release(); await settled(page);
      assert.match(await page.locator('.u-item-title').first().textContent(), /coiffure/);
      await page.clock.fastForward(25000); flags.hold = true;
      await page.evaluate(() => BMCatalog.open('services', '', { sort: 'new' }));
      await waitRequests(page, requests, 4);
      assert.match(await page.locator('.u-item-title').first().textContent(), /services/, 'reopening another exact cached context shows its own results immediately');
      assert.equal(await page.locator('.catalog-skeleton').count(), 0);
      release(); await settled(page);
      flags.status = 400; flags.hold = true;
      await staleReturn(page); await waitRequests(page, requests, 5); release(); await settled(page);
      assert.equal(await page.locator('.catalog-item').count(), 0, '4xx response removes stale results');
      assert.equal(await page.locator('.catalog-empty').count(), 1);
      await page.close();
    }
    {
      const { page, requests, flags, release } = await fresh(); await begin(page);
      flags.hold = true;
      await page.locator('#catalogNext').click(); await waitRequests(page, requests, 2);
      assert.equal(await page.locator('.catalog-item').count(), 0, 'uncached page 2 never presents page 1 cards as its own');
      release(); await settled(page);
      const slot = requests.at(-1).rotation_slot;
      await page.evaluate(() => BMCatalog.pause()); await page.clock.fastForward(1801000);
      flags.hold = true; await page.evaluate(() => BMCatalog.resume());
      await waitRequests(page, requests, 3);
      assert.equal(requests.at(-1).page, '2'); assert.equal(requests.at(-1).rotation_slot, slot, 'page 2 refresh keeps its rotation');
      assert.equal(await page.locator('.catalog-item').count(), 0, 'snapshots older than five minutes are no longer reused');
      release(); await settled(page);
      await page.close();
    }
    for (const fixture of fixtures) assert.deepEqual(fixture.errors, [], 'JavaScript errors');
    console.log(name + ' ' + width + ': stale return, stable DOM/focus/scroll, price/stock refresh, retry, context isolation, 4xx and pinned pagination PASS');
  } finally { await browser.close(); }
}
(async () => {
  for (const [name, engine] of Object.entries({ chromium, webkit })) {
    if (process.env.CATALOG_REFRESH_BROWSER && process.env.CATALOG_REFRESH_BROWSER !== name) continue;
    for (const width of [390, 1440]) await run(name, engine, width);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
