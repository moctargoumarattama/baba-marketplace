/* Real image enhancement and card rendering against local synthetic media. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const { chromium, webkit } = require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');
const root = path.resolve(__dirname, '../../app');
let origin;
const mediaRequests = [];
const shapes = { portrait: [240, 480], landscape: [600, 260], square: [400, 400] };

function card(group, shape, promotion = true) {
  const isHome = group === 'home';
  const photo = '/media/' + shape + (promotion ? '-large' : '-thumb') + '.svg';
  const frame = isHome ? 'hub-product-media' : 'public-catalog-card-media';
  const badge = isHome ? 'hub-offer-tag' : 'public-catalog-card-badge';
  const tag = isHome ? 'a' : 'div';
  return '<article class="' + (isHome ? 'hub-product' : 'public-catalog-card') + '">' +
    (isHome ? '' : '<a class="public-catalog-card-link" href="#">') +
    '<' + tag + (isHome ? ' href="#"' : '') + ' id="' + group + '-' + shape + '-' + promotion + '" class="' + frame +
    (promotion ? ' promotion-photo-frame' : '') + '"><img src="' + photo +
    '" alt="' + shape + ' photo" width="' + (isHome ? '300' : '480') + '" height="' + (isHome ? '300' : '360') + '" loading="lazy">' +
    (promotion ? '<span class="' + badge + ' promotion-highlight">Promotion</span>' : '') +
    '</' + tag + '><div class="' + (isHome ? 'hub-product-info' : 'public-catalog-card-content') + '">' +
    shape + ' — 45 DH</div>' + (isHome ? '' : '</a>') + '</article>';
}

function fixtureHTML() {
  const styles = ['ui_home_single_hub', 'home_refresh', 'catalog_panel', 'pages/public_catalog', 'promotion_highlight']
    .map(name => '<style>' + fs.readFileSync(path.join(root, 'static/css', name + '.css'), 'utf8') + '</style>').join('');
  let cards = '';
  for (const [group, grid] of [['home', 'hub-products-grid'], ['public', 'public-catalog-grid']]) {
    cards += '<h2>' + group + '</h2><section class="' + grid + '">' +
      Object.keys(shapes).map(shape => card(group, shape)).join('') + card(group, 'portrait', false) +
      card(group, 'broken') + '</section>';
  }
  return '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
    styles + '<style>body{margin:0;padding:16px;background:#f6f8f5;font-family:Arial,sans-serif}' +
    'main{max-width:1000px;margin:auto}.catalog-results{display:grid;gap:12px}' +
    '.hub-product-info{color:#20382d}h2{margin:24px 0 12px}</style></head><body data-page="landing"><main>' +
    cards + '<h2>Popup catalogue</h2><section id="popup" class="catalog-results"></section></main></body></html>';
}

const server = http.createServer((request, response) => {
  const url = new URL(request.url, origin);
  response.setHeader('Cache-Control', 'public, max-age=3600');
  if (url.pathname === '/fixture') {
    response.setHeader('Content-Type', 'text/html; charset=utf-8');
    response.end(fixtureHTML());
  } else if (url.pathname.startsWith('/media/')) {
    mediaRequests.push(url.pathname);
    if (url.pathname.includes('broken')) { response.statusCode = 404; response.end(); return; }
    const [width, height] = shapes[path.basename(url.pathname).split('-')[0]] || shapes.square;
    response.setHeader('Content-Type', 'image/svg+xml');
    response.end('<svg xmlns="http://www.w3.org/2000/svg" width="' + width + '" height="' + height +
      '"><defs><linearGradient id="g"><stop stop-color="#f4ba45"/><stop offset="1" stop-color="#184e3f"/>' +
      '</linearGradient></defs><rect width="100%" height="100%" fill="url(#g)"/>' +
      '<rect x="6" y="6" width="' + (width - 12) + '" height="' + (height - 12) +
      '" rx="15" fill="none" stroke="#fff5d6" stroke-width="9"/>' +
      '<circle cx="50%" cy="50%" r="80" fill="#f6eedc"/><circle cx="50%" cy="50%" r="55" fill="#ae582b"/>' +
      '<text x="50%" y="52%" text-anchor="middle" font-size="24" fill="white">Photo entière</text></svg>');
  } else { response.statusCode = 204; response.end(); }
});

async function run(name, engine, width) {
  const browser = await engine.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width, height: 1000 }, reducedMotion: 'reduce', serviceWorkers: 'block' });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    mediaRequests.length = 0;
    await page.goto(origin + '/fixture');
    for (const script of ['home_refresh', 'public_catalog']) {
      await page.addScriptTag({ content: fs.readFileSync(path.join(root, 'static/js', script + '.js'), 'utf8') });
    }
    await page.evaluate(() => {
      const shapes = ['portrait', 'landscape', 'square', 'broken'];
      shapes.forEach((shape, index) => {
        const card = window.BMCatalog.createCard({ id: 101 + index, item_type: index === 1 ? 'service' : 'product',
          name: 'Promotion ' + shape, stock: 3, available: true, price: 60, final_price: 45, has_promo: true,
          image_url: '/media/' + shape + '-thumb.svg', image_preview_url: '/media/' + shape + '-large.svg',
          url: '/shop/product/' + (101 + index) });
        card.id = 'popup-' + shape;
        document.getElementById('popup').appendChild(card);
      });
      const ordinary = window.BMCatalog.createCard({ id: 999, item_type: 'product', name: 'Ordinary cover',
        stock: 3, available: true, price: 60, final_price: 60, has_promo: false,
        image_url: '/media/portrait-thumb.svg', image_preview_url: '/media/portrait-large.svg', url: '/shop/product/999' });
      ordinary.id = 'popup-ordinary';
      document.getElementById('popup').appendChild(ordinary);
      document.querySelectorAll('img').forEach(image => { image.loading = 'eager'; });
    });
    await page.waitForFunction(() => Array.from(document.images).every(image => image.complete));
    await page.waitForLoadState('networkidle');
    for (const group of ['home', 'public', 'popup']) {
      for (const shape of Object.keys(shapes)) {
        const frame = page.locator(group === 'popup' ? '#popup-' + shape + ' .promotion-photo-frame' : '#' + group + '-' + shape + '-true');
        const image = frame.locator('img');
        const backdrop = frame.locator('.promotion-photo-backdrop');
        assert.equal(await image.evaluate(el => getComputedStyle(el).objectFit), 'contain', group + ': full photo retained');
        assert.equal(await backdrop.count(), 1, group + ': exactly one decorative layer');
        assert.equal(await backdrop.getAttribute('aria-hidden'), 'true');
        assert.match(await backdrop.evaluate(el => getComputedStyle(el).filter), /blur\(14px\)/);
        assert.match(await backdrop.evaluate(el => getComputedStyle(el).backgroundImage), new RegExp(shape + '-large\\.svg'));
        assert.equal(await image.evaluate(el => el.naturalWidth / el.naturalHeight), shapes[shape][0] / shapes[shape][1]);
        const boxes = await frame.evaluate(el => {
          const frameBox = el.getBoundingClientRect(), imageBox = el.querySelector('img').getBoundingClientRect();
          return { frameWidth: frameBox.width, frameHeight: frameBox.height, imageWidth: imageBox.width, imageHeight: imageBox.height };
        });
        assert.ok(boxes.frameWidth > 100 && boxes.frameHeight > 70);
        const expectedRatio = group === 'public' ? 4 / 3 : group === 'popup' ? 1.2 : width < 500 ? 1.12 : 1.5;
        assert.ok(Math.abs(boxes.frameWidth / boxes.frameHeight - expectedRatio) < 0.02,
          group + ': portrait source must not expand the existing frame');
        assert.ok(Math.abs(boxes.frameWidth - boxes.imageWidth) < 1 && Math.abs(boxes.frameHeight - boxes.imageHeight) < 1,
          group + ': CSS contains the photo inside its existing frame');
        const badge = group === 'popup' ? page.locator('#popup-' + shape + ' .promotion-highlight') : frame.locator('.promotion-highlight');
        assert.equal(await badge.isVisible(), true);
        await frame.evaluate(el => window.BMPromotionPhotos.enhance(el, el.querySelector('img')));
        assert.equal(await backdrop.count(), 1, 'enhancement stays idempotent');
      }
      const ordinary = page.locator(group === 'popup' ? '#popup-ordinary .catalog-media' : '#' + group + '-portrait-false');
      assert.equal(await ordinary.locator('img').evaluate(el => getComputedStyle(el).objectFit), 'cover');
      assert.equal(await ordinary.locator('.promotion-photo-backdrop').count(), 0);
      assert.equal(await ordinary.locator('img').evaluate(el => new URL(el.src).pathname), '/media/portrait-thumb.svg');
      const broken = page.locator(group === 'popup' ? '#popup-broken .catalog-media' : '#' + group + '-broken-true');
      assert.equal(await broken.locator('.promotion-photo-backdrop').count(), 0, 'failed images leave no blurred decoration');
      if (group !== 'public') assert.equal(await broken.locator('img:visible').count(), 0);
    }
    const initialSizes = await page.locator('.promotion-photo-frame').evaluateAll(frames => frames.map(el => {
      const box = el.getBoundingClientRect(); return [box.width, box.height];
    }));
    const count = mediaRequests.length;
    await page.setViewportSize({ width: width - 30, height: 1000 });
    await page.setViewportSize({ width, height: 1000 });
    await page.waitForLoadState('networkidle');
    assert.equal(mediaRequests.length, count, 'resize must reuse the loaded photo');
    assert.deepEqual(await page.locator('.promotion-photo-frame').evaluateAll(frames => frames.map(el => {
      const box = el.getBoundingClientRect(); return [box.width, box.height];
    })), initialSizes, 'frame dimensions remain stable after resizing back');
    assert.deepEqual(errors, []);
    const screenshot = path.join(os.tmpdir(), 'babamarket-promotion-photo-' + name + '-' + width + '.png');
    await page.screenshot({ path: screenshot, fullPage: true });
    console.log(name + ' ' + width + 'px: full photos + blur, ordinary covers, errors, stable dimensions and resize cache PASS; ' + screenshot);
  } finally { await browser.close(); }
}

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  origin = 'http://127.0.0.1:' + server.address().port;
  try {
    for (const [name, engine] of [['chromium', chromium], ['webkit', webkit]]) {
      for (const width of [390, 1440]) await run(name, engine, width);
    }
  } finally { await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error); process.exitCode = 1; });
