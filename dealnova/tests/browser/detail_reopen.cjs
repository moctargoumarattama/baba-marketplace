/* Public detail reopening regression with real modal markup/assets and a local
   synthetic API. No application instance, database, or external requests. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { chromium, webkit } = require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');
const root = path.resolve(__dirname, '../../app');
let origin;
let requests = [];
let queues = new Map();

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
  return '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
    styles + '</head><body data-page="landing"><main>' + [1, 2, 3, 7]
      .map(id => '<button data-open-product-detail="' + id + '">Article ' + id + '</button>').join('') +
    '<button data-open-shop-detail="test-shop">Boutique</button>' +
    '<button data-open-shop-detail="5">Boutique par identifiant</button></main>' + source + '</body></html>';
}

function product(id = 1, changes = {}) {
  return { id, name: 'Article ' + id, kind: id === 7 ? 'service' : 'physical',
    stock: 3, price: 40, final_price: 40, description: 'Description detaillee. '.repeat(100),
    category: 'Demonstration', images: ['detail-a.svg', 'detail-b.svg'],
    image_download_urls: ['/shop/product/' + id + '/photo/0/download', '/shop/product/' + id + '/photo/1/download'],
    video_url: '/static/demo.mp4', shop: { id: 5, slug: 'test-shop', name: 'Boutique test', is_verified: true },
    booking_url: '/booking/' + id, whatsapp_order_url: 'https://wa.me/000',
    share_url: origin + '/shop/product/' + id, ...changes };
}
function shop(changes = {}) {
  return { id: 5, slug: 'test-shop', name: 'Boutique test', is_open: true,
    address: 'Rabat', description: 'Notre boutique. '.repeat(90), whatsapp_url: 'https://wa.me/000',
    call_url: 'tel:000', share_url: origin + '/shop/test-shop', ...changes };
}
function enqueue(endpoint, options = {}) {
  const entry = { status: 200, ...options, endpoint, received: false, sent: false };
  if (!queues.has(endpoint)) queues.set(endpoint, []);
  queues.get(endpoint).push(entry);
  return entry;
}
function release(entry) {
  assert(entry.received, entry.endpoint + ' has been requested');
  if (entry.sent) return;
  entry.sent = true;
  if (entry.networkError) return entry.response.destroy();
  if (!entry.response.destroyed) {
    entry.response.writeHead(entry.status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
    entry.response.end(JSON.stringify(entry.payload || { success: false }));
  }
}
async function received(entry) {
  for (let attempt = 0; attempt < 100 && !entry.received; attempt++) {
    await new Promise(resolve => setTimeout(resolve, 20));
  }
  assert.equal(entry.received, true, 'Expected request: ' + entry.endpoint);
}

const server = http.createServer((request, response) => {
  const url = new URL(request.url, origin);
  if (url.pathname === '/fixture') {
    response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    return response.end(fixtureHTML());
  }
  if (/^\/api\/(product|shop)\//.test(url.pathname)) {
    requests.push(url.pathname);
    const entry = queues.get(url.pathname)?.shift();
    if (!entry) {
      response.writeHead(500, { 'Content-Type': 'application/json' });
      return response.end(JSON.stringify({ success: false, error: 'Unexpected synthetic request: ' + url.pathname }));
    }
    entry.received = true;
    entry.response = response;
    if (!entry.wait) release(entry);
    return;
  }
  if (url.pathname === '/cart/api/full') {
    response.writeHead(200, { 'Content-Type': 'application/json' });
    return response.end(JSON.stringify({ success: true, items: [], shop_groups: [], count: 0 }));
  }
  if (/\.svg$/.test(url.pathname)) {
    response.writeHead(200, { 'Content-Type': 'image/svg+xml' });
    return response.end('<svg xmlns="http://www.w3.org/2000/svg" width="500" height="400"><rect width="500" height="400" fill="#008060"/></svg>');
  }
  response.writeHead(204);
  response.end();
});

async function close(page, kind = 'product') {
  await page.keyboard.press('Escape');
  await page.waitForFunction(kind => document.querySelector(kind === 'product' ? '#productDetailPanel' : '#shopDetailPanel')?.getAttribute('aria-hidden') === 'true', kind);
}
async function openProduct(page, id, gate, expected = 'Article ' + id) {
  await page.locator('[data-open-product-detail="' + id + '"]').click();
  if (gate) await received(gate);
  await page.waitForFunction(expected => document.querySelector('#pDetailContent')?.style.display === 'block' &&
    document.querySelector('#pDetailTitle')?.textContent === expected, expected);
}
async function assertCached(page, prefix) {
  assert.equal(await page.locator('#' + prefix + 'Loading').isVisible(), false, 'cached detail must not show a spinner');
  assert.equal(await page.locator('#' + prefix + 'Content').isVisible(), true, 'cached detail remains readable');
}

async function run(name, engine, width) {
  requests = [];
  queues = new Map();
  const browser = await engine.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width, height: width < 500 ? 844 : 1000 },
      reducedMotion: 'reduce', serviceWorkers: 'block' });
    page.setDefaultTimeout(5000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(origin + '/fixture');
    for (const script of ['public_catalog', 'ui_home_single_hub']) {
      await page.addScriptTag({ content: fs.readFileSync(path.join(root, 'static/js', script + '.js'), 'utf8') });
    }

    enqueue('/api/product/1', { payload: { success: true, product: product() } });
    await openProduct(page, 1);
    await close(page);

    // A held response proves that the visible data came from memory, not the network.
    let gate = enqueue('/api/product/1', { wait: true, payload: { success: true,
      product: product(1, { price: 52, final_price: 52, stock: 0 }) } });
    await openProduct(page, 1, gate);
    await assertCached(page, 'pDetail');
    assert.equal(await page.locator('#pDetailPriceFinal').textContent(), '40.00 DH');
    await page.locator('#pDetailThumbs .u-pdetail-thumb').nth(2).click();
    assert.match(await page.locator('#pDetailMainImg').getAttribute('src'), /detail-b\.svg$/);
    assert.equal(await page.locator('#pDetailPhotoDownload').getAttribute('href'), '/shop/product/1/photo/1/download');
    const scrollBefore = await page.locator('#pDetailBody').evaluate(body => {
      body.scrollTop = 200;
      window.__detailImage = document.querySelector('#pDetailMainImg');
      return body.scrollTop;
    });
    release(gate);
    await page.waitForFunction(() => document.querySelector('#pDetailPriceFinal').textContent === '52.00 DH');
    assert.match(await page.locator('#pDetailStockBadge').textContent(), /Indisponible/);
    assert.equal(await page.locator('#pDetailBtnCart').isDisabled(), true, 'fresh availability updates the action');
    assert.match(await page.locator('#pDetailMainImg').getAttribute('src'), /detail-b\.svg$/, 'refresh keeps selected photo');
    assert.equal(await page.locator('#pDetailBody').evaluate(body => body.scrollTop), scrollBefore, 'refresh keeps reading position');
    assert.equal(await page.evaluate(() => document.querySelector('#pDetailMainImg') === window.__detailImage), true);
    await close(page);

    gate = enqueue('/api/product/1', { wait: true, networkError: true });
    await openProduct(page, 1, gate);
    await assertCached(page, 'pDetail');
    release(gate);
    await page.locator('#productDetailPanel [data-detail-refresh-retry]').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#pDetailPriceFinal').textContent(), '52.00 DH', 'temporary failure preserves recent data');
    gate = enqueue('/api/product/1', { wait: true, payload: { success: true, product: product(1, { final_price: 53, price: 53 }) } });
    await page.locator('#productDetailPanel [data-detail-refresh-retry]').click();
    await received(gate);
    await assertCached(page, 'pDetail');
    release(gate);
    await page.waitForFunction(() => document.querySelector('#pDetailPriceFinal').textContent === '53.00 DH');
    await close(page);

    // Confirmed removals must clear details and their cache, unlike temporary errors.
    for (const status of [404, 403]) {
      gate = enqueue('/api/product/1', { wait: true, status });
      await openProduct(page, 1, gate);
      release(gate);
      await page.waitForFunction(() => document.querySelector('#pDetailContent').style.display === 'none');
      assert.equal(await page.locator('#pDetailBtnCart').isVisible(), false);
      assert.equal(await page.locator('#pDetailPhotoDownload').isVisible(), false);
      await close(page);
      gate = enqueue('/api/product/1', { wait: true, payload: { success: true, product: product() } });
      await page.locator('[data-open-product-detail="1"]').click();
      await received(gate);
      assert.equal(await page.locator('#pDetailContent').isVisible(), false, status + ' evicts cached details');
      assert.equal(await page.locator('#pDetailLoading').isVisible(), true);
      release(gate);
      await page.waitForFunction(() => document.querySelector('#pDetailContent').style.display === 'block');
      await close(page);
    }

    // Other IDs and aborted responses cannot populate a different visible detail.
    gate = enqueue('/api/product/2', { wait: true, payload: { success: true, product: product(2) } });
    await page.locator('[data-open-product-detail="2"]').click();
    await received(gate);
    assert.equal(await page.locator('#pDetailContent').isVisible(), false, 'new ID never shows the previous product');
    const current = enqueue('/api/product/3', { wait: true, payload: { success: true, product: product(3) } });
    await page.locator('[data-open-product-detail="3"]').evaluate(button => button.click());
    await received(current);
    release(current);
    await page.waitForFunction(() => document.querySelector('#pDetailTitle').textContent === 'Article 3');
    release(gate);
    await page.waitForTimeout(80);
    assert.equal(await page.locator('#pDetailTitle').textContent(), 'Article 3', 'late response cannot overwrite the current detail');
    await close(page);
    gate = enqueue('/api/product/3', { wait: true, payload: { success: true, product: product(3, { name: 'Late closed response' }) } });
    await openProduct(page, 3, gate);
    await close(page);
    release(gate);
    await page.waitForTimeout(80);
    assert.equal(await page.locator('#productDetailPanel').getAttribute('aria-hidden'), 'true', 'late response never reopens a closed detail');

    enqueue('/api/product/7', { payload: { success: true, product: product(7) } });
    await openProduct(page, 7);
    await close(page);
    gate = enqueue('/api/product/7', { wait: true, payload: { success: true, product: product(7, { final_price: 65 }) } });
    await openProduct(page, 7, gate);
    await assertCached(page, 'pDetail');
    assert.equal(await page.locator('#pDetailBtnBook').isVisible(), true);
    assert.equal(await page.locator('#pDetailBtnBook').getAttribute('href'), '/booking/7');
    release(gate);
    await page.waitForFunction(() => document.querySelector('#pDetailPriceFinal').textContent === '65.00 DH');
    await close(page);

    const shopPayload = { success: true, shop: shop(), products: [product(1)], product_count: 1 };
    enqueue('/api/shop/test-shop', { payload: shopPayload });
    await page.locator('[data-open-shop-detail="test-shop"]').click();
    await page.waitForFunction(() => document.querySelector('#shopDetailContent').style.display === 'block');
    await close(page, 'shop');
    gate = enqueue('/api/shop/5', { wait: true, payload: { ...shopPayload, shop: shop({ name: 'Boutique actualisee', is_open: false }) } });
    await page.locator('[data-open-shop-detail="5"]').click();
    await received(gate);
    await assertCached(page, 'shopDetail');
    assert.equal(await page.locator('#shopDetailName').textContent(), 'Boutique test', 'ID and slug share the same recent public shop');
    release(gate);
    await page.waitForFunction(() => document.querySelector('#shopDetailName').textContent === 'Boutique actualisee');
    assert.match(await page.locator('#shopDetailStatusPill').textContent(), /Ferm/);
    await close(page, 'shop');
    gate = enqueue('/api/shop/test-shop', { wait: true, status: 503 });
    await page.locator('[data-open-shop-detail="test-shop"]').click();
    await received(gate);
    await assertCached(page, 'shopDetail');
    assert.equal(await page.locator('#shopDetailName').textContent(), 'Boutique actualisee');
    release(gate);
    await page.locator('#shopDetailPanel [data-detail-refresh-retry]').waitFor({ state: 'visible' });
    await close(page, 'shop');
    gate = enqueue('/api/shop/test-shop', { wait: true, status: 404 });
    await page.locator('[data-open-shop-detail="test-shop"]').click();
    await received(gate);
    release(gate);
    await page.waitForFunction(() => document.querySelector('#shopDetailContent').style.display === 'none');
    assert.equal(await page.locator('#shopDetailWaBtn').isVisible(), false, 'removed shop cannot remain contactable');
    await close(page, 'shop');
    gate = enqueue('/api/shop/5', { wait: true, payload: shopPayload });
    await page.locator('[data-open-shop-detail="5"]').click();
    await received(gate);
    assert.equal(await page.locator('#shopDetailContent').isVisible(), false, 'removal evicts all aliases');
    release(gate);
    await page.waitForFunction(() => document.querySelector('#shopDetailContent').style.display === 'block');

    await close(page, 'shop');
    await page.clock.setFixedTime(new Date(await page.evaluate(() => Date.now()) + 301000));
    gate = enqueue('/api/product/7', { wait: true, payload: { success: true, product: product(7) } });
    await page.locator('[data-open-product-detail="7"]').click();
    await received(gate);
    assert.equal(await page.locator('#pDetailContent').isVisible(), false, 'details older than five minutes are not reused');
    assert.equal(await page.locator('#pDetailLoading').isVisible(), true);
    release(gate);
    await page.waitForFunction(() => document.querySelector('#pDetailContent').style.display === 'block');

    assert.deepEqual(errors, [], 'no JavaScript errors');
    console.log(name + ' ' + width + 'px: instant product/service/shop reopen; quiet fresh price/stock; gallery/scroll; retry; 403/404 eviction; alias, expiry and aborted-request protection PASS');
  } finally {
    for (const queue of queues.values()) for (const entry of queue) if (entry.received) release(entry);
    await browser.close();
  }
}

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  origin = 'http://127.0.0.1:' + server.address().port;
  try {
    for (const [name, engine] of [['chromium', chromium], ['webkit', webkit]]) {
      if (process.env.DETAIL_REOPEN_BROWSER && process.env.DETAIL_REOPEN_BROWSER !== name) continue;
      for (const width of [390, 1440]) await run(name, engine, width);
    }
  } finally {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
