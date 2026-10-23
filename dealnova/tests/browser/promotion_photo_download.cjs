/* Real catalogue cards and hub with synthetic API/media; no app or database. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { chromium, webkit } = require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');
const root = path.resolve(__dirname, '../../app');
let origin;
const productRequests = [];

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
    styles + '</head><body data-page="landing"><button data-open-universe="promotions">Promotions</button>' +
    source + '</body></html>';
}

const items = [
  { id: 101, item_type: 'product', image_url: '/static/uploads/product.jpg' },
  { id: 102, item_type: 'service', image_url: '/static/uploads/service.jpg' },
  { id: 103, item_type: 'product', image_url: '', video_url: '/static/video.mp4' },
  { id: 104, item_type: 'product', image_url: '/static/uploads/product.jpg', has_promo: false },
  { id: 105, item_type: 'product', image_url: '/static/img/placeholders/product.svg' },
  { id: 106, item_type: 'product', image_url: '/static/uploads/product.jpg', final_price: 100 },
].map(item => ({ name: 'Offre ' + item.id, stock: 3, price: 100, final_price: 75,
  has_promo: true, available: true, url: '/shop/product/' + item.id, ...item }));

const server = http.createServer((request, response) => {
  const url = new URL(request.url, origin);
  let body = '';
  let contentType = 'text/html; charset=utf-8';
  if (url.pathname === '/fixture') body = fixtureHTML();
  else if (url.pathname === '/api/catalog') {
    contentType = 'application/json';
    body = JSON.stringify({ success: true, items, facets: {},
      pagination: { page: 1, pages: 1, total: items.length, has_next: false, has_prev: false } });
  } else if (url.pathname === '/cart/api/full') {
    contentType = 'application/json';
    body = JSON.stringify({ success: true, items: [], shop_groups: [], count: 0 });
  } else if (url.pathname.startsWith('/api/product/')) {
    productRequests.push(url.pathname);
    response.statusCode = 500;
    contentType = 'application/json';
    body = JSON.stringify({ success: false });
  } else if (url.pathname.endsWith('/download')) {
    contentType = 'image/jpeg';
    body = 'watermarked-photo-fixture';
    response.setHeader('Content-Disposition', 'attachment; filename="baba-market-promotion.jpg"');
  } else if (/\.(jpg|svg)$/.test(url.pathname)) {
    contentType = 'image/svg+xml';
    body = '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="230"><rect width="300" height="230" fill="green"/></svg>';
  } else if (url.pathname.startsWith('/static/js/')) {
    const filename = path.basename(url.pathname);
    const scriptPath = path.join(root, 'static/js', filename);
    if (fs.existsSync(scriptPath)) {
      contentType = 'text/javascript';
      body = fs.readFileSync(scriptPath);
    }
  } else response.statusCode = 204;
  response.setHeader('Content-Type', contentType);
  response.end(body);
});

async function run(name, engine, width) {
  const browser = await engine.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width, height: width < 500 ? 844 : 1000 },
      reducedMotion: 'reduce', serviceWorkers: 'block', acceptDownloads: true });
    const errors = [];
    productRequests.length = 0;
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(origin + '/fixture');
    for (const script of ['public_catalog', 'ui_home_single_hub']) {
      await page.addScriptTag({ content: fs.readFileSync(path.join(root, 'static/js', script + '.js'), 'utf8') });
    }
    await page.locator('[data-open-universe="promotions"]').click();
    await page.waitForFunction(() => document.querySelectorAll('#catalogResults .catalog-item').length === 6);
    assert.equal(await page.locator('#catalogResults .promotion-photo-download').count(), 2);
    for (const id of [101, 102]) {
      const card = page.locator('#catalogResults [data-product-id="' + id + '"]');
      const link = card.locator('.promotion-photo-download');
      assert.equal(await link.isVisible(), true, 'photo download is visible');
      assert.equal(await link.getAttribute('href'), '/shop/product/' + id + '/photo/0/download');
      assert.notEqual(await link.getAttribute('download'), null);
      assert.equal(await link.evaluate(element => Boolean(element.parentElement.closest('a'))), false,
        'download link must not be nested in the card detail link');
      const beforeURL = page.url();
      const [download] = await Promise.all([page.waitForEvent('download'), link.click()]);
      assert.equal(download.url(), origin + '/shop/product/' + id + '/photo/0/download');
      assert.equal(download.suggestedFilename(), 'baba-market-promotion.jpg');
      assert.equal(await download.failure(), null);
      assert.equal(page.url(), beforeURL, 'download must not navigate the catalogue');
    }
    assert.deepEqual(productRequests, [], 'hub must not open the detail modal on download');
    assert.deepEqual(errors, []);
    console.log(name + ' ' + width + 'px: promotion product/service native download, video-only/placeholder/no-discount exclusion PASS');
  } finally {
    await browser.close();
  }
}

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  origin = 'http://127.0.0.1:' + server.address().port;
  try {
    for (const [name, engine] of [['chromium', chromium], ['webkit', webkit]]) {
      for (const width of [1440, 390]) await run(name, engine, width);
    }
  } finally {
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
