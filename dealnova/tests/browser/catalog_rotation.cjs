/* Self-contained public catalogue rotation regression: real modal/assets,
   synthetic API data, no server, database or external requests. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium, webkit } = require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');
const root = path.resolve(__dirname, '../../app');
const origin = 'https://catalog-rotation.test';
const interval = 1800;

function fixtureHTML() {
  let source = fs.readFileSync(path.join(root, 'templates/home.html'), 'utf8');
  source = source.slice(source.indexOf('<div class="u-modal-backdrop"'));
  source = source.slice(0, source.indexOf('<div class="u-modal-backdrop u-cart-backdrop"'));
  source = source.replace("{% include 'partials/_catalog_panel.html' %}",
    fs.readFileSync(path.join(root, 'templates/partials/_catalog_panel.html'), 'utf8'));
  source = source.replace(/\{\{\s*t\((['"])([\s\S]*?)\1\)\s*\}\}/g, (_match, _quote, label) => label);
  source = source.replace(/\{%[\s\S]*?%\}|\{\{[\s\S]*?\}\}/g, '');
  const styles = ['ui_home_single_hub', 'home_refresh', 'catalog_panel', 'promotion_highlight'].map(name =>
    '<style>' + fs.readFileSync(path.join(root, 'static/css', name + '.css'), 'utf8') + '</style>').join('');
  return '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' + styles + '</head>' +
    '<body data-page="landing"><main>' + ['products', 'services', 'promotions', 'locations']
      .map(universe => '<button data-open-universe="' + universe + '">' + universe + '</button>').join('') +
    '</main>' + source + '</body></html>';
}

async function fixture(context, realClock = false) {
  const page = await context.newPage();
  const requests = [];
  const errors = [];
  const flags = { fail: false };
  page.on('pageerror', error => errors.push(error.message));
  if (!realClock) await page.clock.install({ time: new Date('2026-10-23T12:00:00Z') });
  await page.route(origin + '/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/fixture') {
      return route.fulfill({ contentType: 'text/html; charset=utf-8', body: fixtureHTML() });
    }
    if (url.pathname === '/api/catalog') {
      const params = Object.fromEntries(url.searchParams);
      requests.push(params);
      if (flags.fail) return route.fulfill({ status: 503, json: { success: false } });
      const now = await page.evaluate(() => Date.now() / 1000);
      const slot = Number(params.rotation_slot || Math.floor(now / interval));
      const pageNumber = Number(params.page || 1);
      const rotating = params.sort === 'discover' &&
        ['products', 'services', 'promotions', 'locations'].includes(params.universe) && !params.q;
      const itemType = params.universe === 'locations' ? 'location' : params.universe === 'services' ? 'service' : 'product';
      const offset = ((slot % 20) + pageNumber * 20) * 12;
      return route.fulfill({ json: { success: true, facets: {}, filters: params,
        rotation: rotating ? { slot, interval, refresh_at: (slot + 1) * interval,
          refresh_in: Math.max(1, (slot + 1) * interval - now) } : null,
        pagination: { page: pageNumber, pages: 2, per_page: 12, total: 24,
          has_next: pageNumber < 2, has_prev: pageNumber > 1 },
        items: Array.from({ length: 12 }, (_, index) => ({
          id: 910000 + offset + index, item_type: itemType,
          kind: itemType === 'service' ? 'service' : 'physical', stock: 3,
          name: params.universe + ' slot ' + slot + ' article ' + (offset + index),
          description: 'Offre de demonstration pour verifier la rotation du catalogue.',
          price: 40, final_price: 40, available: true, image_url: '',
          url: '/shop/product/' + (910000 + offset + index),
        })) } });
    }
    if (url.pathname.startsWith('/api/product/')) {
      const id = Number(url.pathname.split('/').pop());
      return route.fulfill({ json: { success: true, product: { id,
        name: 'Article ouvert ' + id, kind: 'physical', stock: 3,
        price: 40, final_price: 40, description: 'Details de cette offre.',
        images: [], shop: null, category: 'Test',
        whatsapp_order_url: 'https://wa.me/000', share_url: origin + '/shop/product/' + id,
      } } });
    }
    if (url.pathname === '/cart/api/full') {
      return route.fulfill({ json: { success: true, items: [], shop_groups: [], count: 0 } });
    }
    return route.fulfill({ status: 204, body: '' });
  });
  await page.goto(origin + '/fixture');
  await page.addScriptTag({ content: fs.readFileSync(path.join(root, 'static/js/public_catalog.js'), 'utf8') });
  await page.addScriptTag({ content: fs.readFileSync(path.join(root, 'static/js/ui_home_single_hub.js'), 'utf8') });
  return { page, requests, errors, flags };
}

async function settled(page) {
  await page.waitForFunction(() => document.querySelector('#catalogResults')?.getAttribute('aria-busy') === 'false' &&
    document.querySelector('#catalogResults .catalog-item'));
}
async function idle(page, top = true) {
  await page.mouse.move(0, 0);
  await page.evaluate(top => {
    document.activeElement?.blur();
    if (top) document.querySelector('#uModalBody').scrollTop = 0;
  }, top);
  await page.clock.fastForward(3000);
  await page.clock.runFor(50);
}
async function open(page, universe = 'products') {
  await page.locator('[data-open-universe="' + universe + '"]').click();
  await page.clock.runFor(100);
  await settled(page);
  await idle(page);
}
async function nextRotation(page) {
  await page.clock.fastForward(1801000);
  await page.clock.fastForward(3000);
  await page.clock.runFor(50);
}
async function waitCount(page, requests, expected, label = '') {
  for (let attempt = 0; attempt < 20 && requests.length < expected; attempt++) {
    await page.clock.fastForward(500);
    await page.waitForTimeout(20);
  }
  assert.equal(requests.length, expected, label);
  await settled(page);
}

async function run(name, engine) {
  const browser = await engine.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 390, height: 844 },
    isMobile: true, hasTouch: true, serviceWorkers: 'block', reducedMotion: 'reduce' });
  const fixtures = [];
  async function fresh() { const item = await fixture(context); fixtures.push(item); return item; }
  try {
    if (process.env.CATALOG_ROTATION_SMOKE) {
      const { page, errors } = await fixture(context, true);
      await page.locator('[data-open-universe="products"]').click();
      await settled(page);
      await page.waitForTimeout(500);
      console.log(name + ' real-clock select visible: ' + await page.locator('#catalogSort').isVisible());
      await page.locator('#catalogSort').selectOption('low', { timeout: 3000 });
      await settled(page);
      assert.deepEqual(errors, []);
      console.log(name + ': native select smoke PASS');
      return;
    }
    for (const universe of ['products', 'services', 'promotions', 'locations']) {
      const { page, requests } = await fresh();
      await open(page, universe);
      assert.equal(requests[0].sort, 'discover', universe + ' starts in discovery mode');
      assert.equal(await page.locator('#catalogSort').inputValue(), 'discover');
      assert.equal((await page.evaluate(() => BMCatalog.snapshot())).filters.rotation_slot,
        String(Math.floor(Date.parse('2026-10-23T12:00:00Z') / 1000 / interval)));
      if (universe === 'products') {
        const media = await page.evaluate(() => ['product', 'service', 'location'].map(itemType => {
          const card = BMCatalog.createCard({ id: 920001, item_type: itemType, name: 'Offre avec video',
            stock: 2, price: 20, final_price: 20, video_url: '/static/fixture.mp4', url: '/shop/product/920001' });
          const video = card.querySelector('video');
          return { itemType, hasVideo: Boolean(video), autoplay: video?.autoplay,
            preload: video?.preload, badge: Boolean(card.querySelector('.catalog-video-badge')) };
        }));
        for (const item of media) assert.deepEqual(item, { itemType: item.itemType,
          hasVideo: true, autoplay: false, preload: 'metadata', badge: true }, 'video-only card has an economical preview');
      }
      await page.keyboard.press('Escape');
      await nextRotation(page);
      assert.equal(requests.length, 1, 'closed catalogue must not poll');
      await page.close();
    }

    for (const sort of ['new', 'low', 'high']) {
      const { page, requests } = await fresh();
      await open(page);
      await page.locator('#catalogSort').selectOption(sort);
      await settled(page);
      await idle(page);
      assert.equal(requests.at(-1).sort, sort);
      assert.equal(requests.at(-1).rotation_slot, undefined, 'manual order has no rotation slot');
      const before = requests.length;
      await nextRotation(page);
      assert.equal(requests.length, before, 'manual ' + sort + ' order must remain stable');
      await page.close();
    }

    {
      const { page, requests } = await fresh();
      await open(page);
      const slot = (await page.evaluate(() => BMCatalog.snapshot())).filters.rotation_slot;
      await page.locator('#catalogNext').click();
      await settled(page);
      assert.equal(requests.at(-1).page, '2');
      assert.equal(requests.at(-1).rotation_slot, slot, 'page 2 keeps the same rotation');
      const before = requests.length;
      await nextRotation(page);
      assert.equal(requests.length, before, 'reading page 2 does not reorder its results');
      await page.close();
    }

    {
      const { page, requests } = await fresh();
      await open(page);
      const firstTitle = await page.locator('.catalog-item .u-item-title').first().textContent();
      await page.evaluate(() => { window.__firstCard = document.querySelector('.catalog-item'); });
      const currentURL = page.url();
      await nextRotation(page);
      await waitCount(page, requests, 2, 'idle catalogue rotates once');
      assert.equal(requests.at(-1).rotation_slot, undefined, 'fresh rotation asks for current server slot');
      assert.notEqual(await page.locator('.catalog-item .u-item-title').first().textContent(), firstTitle);
      assert.equal(await page.locator('#uModalBody').evaluate(el => el.scrollTop), 0);
      assert.equal(page.url(), currentURL, 'silent refresh leaves browser history and URL intact');
      await page.clock.fastForward(10000);
      assert.equal(requests.length, 2, 'one refresh per rotation boundary');
      await page.close();
    }

    for (const blocker of ['scroll', 'hidden', 'detail', 'pointer']) {
      const { page, requests } = await fresh();
      await open(page);
      await page.evaluate(() => { window.__originalCard = document.querySelector('.catalog-item'); });
      if (blocker === 'scroll') {
        await page.locator('#uModalBody').evaluate(el => { el.scrollTop = 180; });
        assert(await page.locator('#uModalBody').evaluate(el => el.scrollTop) > 8);
      } else if (blocker === 'hidden') {
        await page.evaluate(() => {
          Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
          Object.defineProperty(document, 'hidden', { configurable: true, value: true });
          document.dispatchEvent(new Event('visibilitychange'));
        });
      } else if (blocker === 'detail') {
        await page.locator('#catalogResults .u-item-title-link').first().click();
        await page.clock.runFor(100);
        await page.waitForFunction(() => document.querySelector('#pDetailContent').style.display === 'block');
      } else {
        await page.locator('#catalogResults .u-item-title-link').first().dispatchEvent('pointerdown', {
          pointerId: 901, pointerType: 'touch', isPrimary: true, button: 0,
        });
      }
      await nextRotation(page);
      assert.equal(requests.length, 1, blocker + ' defers rotation');
      assert.equal(await page.evaluate(() => window.__originalCard.isConnected), true,
        blocker + ' keeps original card nodes while the client is reading/interacting');
      if (blocker === 'hidden') {
        await page.evaluate(() => {
          Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
          Object.defineProperty(document, 'hidden', { configurable: true, value: false });
          document.dispatchEvent(new Event('visibilitychange'));
        });
      } else if (blocker === 'detail') {
        await page.keyboard.press('Escape');
        await page.clock.runFor(200);
      } else if (blocker === 'pointer') {
        await page.locator('#catalogResults .u-item-title-link').first().dispatchEvent('pointercancel', {
          pointerId: 901, pointerType: 'touch', isPrimary: true, button: 0,
        });
      }
      await idle(page);
      await waitCount(page, requests, 2, blocker + ' resumes overdue rotation');
      await page.close();
    }

    {
      const { page, requests, flags } = await fresh();
      await open(page);
      const original = await page.locator('#catalogResults').innerHTML();
      flags.fail = true;
      await nextRotation(page);
      assert.equal(requests.length, 2);
      assert.equal(await page.locator('#catalogResults').innerHTML(), original,
        'failed background refresh keeps readable offers instead of an error or skeleton');
      await page.close();
    }

    for (const item of fixtures) assert.deepEqual(item.errors, [], name + ' JavaScript errors');
    console.log(name + ': discovery, manual sorting, pinned pagination, idle refresh, scroll/visibility/detail/pointer guards and failure preservation PASS');
  } finally { await browser.close(); }
}

(async () => {
  for (const [name, engine] of Object.entries({ chromium, webkit })) {
    if (!process.env.CATALOG_ROTATION_BROWSER || process.env.CATALOG_ROTATION_BROWSER === name) await run(name, engine);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
