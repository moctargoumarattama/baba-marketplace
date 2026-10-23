/* Real catalogue cards and hub with synthetic API/media; no app or database. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { chromium, webkit } = require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');
const root = path.resolve(__dirname, '../../app');
let origin;
const productRequests = [];
const downloadRequests = [];

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
    const id = Number(url.pathname.split('/').pop());
    const item = items.find(candidate => candidate.id === id);
    contentType = 'application/json';
    if (!item) {
      response.statusCode = 404;
      body = JSON.stringify({ success: false });
    } else {
      const images = [101, 102].includes(id) ? ['photo-' + id + '-0.jpg', 'photo-' + id + '-1.jpg'] : [];
      body = JSON.stringify({ success: true, product: {
        ...item, kind: item.item_type === 'service' ? 'service' : 'physical',
        description: 'Offre de test en promotion', category: 'Promotion', images,
        image_download_urls: images.map((_image, index) => '/shop/product/' + id + '/photo/' + index + '/download'),
        video_url: id === 103 ? '/static/video.mp4' : '', shop: null,
        promo_type: 'percentage', promo_value: 25, booking_url: '/book/' + id,
        whatsapp_order_url: '/contact/' + id, share_url: origin + item.url,
      } });
    }
  } else if (url.pathname.endsWith('/download')) {
    downloadRequests.push(url.pathname);
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
    downloadRequests.length = 0;
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(origin + '/fixture');
    for (const script of ['public_catalog', 'ui_home_single_hub']) {
      await page.addScriptTag({ content: fs.readFileSync(path.join(root, 'static/js', script + '.js'), 'utf8') });
    }
    await page.locator('[data-open-universe="promotions"]').click();
    await page.waitForFunction(() => document.querySelectorAll('#catalogResults .catalog-item').length === 6);
    assert.equal(await page.locator('#catalogResults a[download]').count(), 0,
      'promotion catalogue cards must leave photo downloads in the detail modal');
    for (const id of [101, 102]) {
      const card = page.locator('#catalogResults [data-product-id="' + id + '"]');
      await card.getByRole('link', { name: 'Détails', exact: true }).click();
      await page.waitForFunction(expected => document.querySelector('#pDetailTitle').textContent === 'Offre ' + expected,
        id);
      const panel = page.locator('#productDetailPanel');
      assert.equal(await panel.getAttribute('aria-hidden'), 'false');
      assert.equal(await page.locator('#pDetailPromoBadge').isVisible(), true,
        'the opened product or service detail is a promotion');
      const link = panel.locator('#pDetailPhotoDownload');
      for (const index of [0, 1]) {
        if (index) await panel.locator('#pDetailThumbs img').nth(index).click();
        assert.equal(await link.isVisible(), true, 'photo download is visible inside the promotion detail');
        assert.equal(await link.getAttribute('href'), '/shop/product/' + id + '/photo/' + index + '/download');
        assert.notEqual(await link.getAttribute('download'), null);
        const beforeURL = page.url();
        const [download] = await Promise.all([page.waitForEvent('download'), link.click()]);
        assert.equal(download.url(), origin + '/shop/product/' + id + '/photo/' + index + '/download');
        assert.equal(download.suggestedFilename(), 'baba-market-promotion.jpg');
        assert.equal(await download.failure(), null);
        assert.equal(page.url(), beforeURL, 'download must not navigate away from the detail');
        assert.equal(await panel.getAttribute('aria-hidden'), 'false');
      }
      await panel.getByRole('button', { name: 'Retour', exact: true }).click();
      await page.waitForFunction(() => document.querySelector('#universeModalPanel').getAttribute('aria-hidden') === 'false');
    }
    await page.locator('#catalogResults [data-product-id="103"]').getByRole('link', { name: 'Détails', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#pDetailTitle').textContent === 'Offre 103');
    assert.equal(await page.locator('#pDetailMainVideo').isVisible(), true);
    assert.equal(await page.locator('#pDetailPhotoDownload').isVisible(), false,
      'video-only promotions must not offer a photo download');
    assert.equal(await page.locator('#pDetailPhotoDownload').getAttribute('href'), null);
    assert.deepEqual(productRequests, ['/api/product/101', '/api/product/102', '/api/product/103']);
    assert.deepEqual(downloadRequests, [101, 102].flatMap(id => [0, 1].map(index =>
      '/shop/product/' + id + '/photo/' + index + '/download')));
    assert.deepEqual(errors, []);
    console.log(name + ' ' + width + 'px: no card download; product/service promotion detail photo 0/1 native download; video-only exclusion PASS');
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
