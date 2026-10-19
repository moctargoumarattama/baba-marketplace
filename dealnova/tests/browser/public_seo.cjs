/* Run only against a disposable preview containing products, services and a rental.
   PUBLIC_PREVIEW_URL=http://127.0.0.1:5067 PLAYWRIGHT_PACKAGE=... node this-file */
const assert = require('node:assert/strict');
const { chromium, webkit } = require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');
const base = process.env.PUBLIC_PREVIEW_URL || 'http://127.0.0.1:5067';

async function run(name, engine) {
  const browser = await engine.launch({ headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block', isMobile: true, hasTouch: true });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const samples = {};
    for (const universe of ['products', 'services', 'locations']) {
      const response = await page.request.get(base + '/api/catalog?universe=' + universe);
      const data = await response.json();
      assert(data.items.length, 'Preview needs an offer in ' + universe);
      samples[universe] = data.items[0].url;
    }
    for (const width of [320, 390, 768, 1280, 1920]) {
      await page.setViewportSize({ width, height: 900 });
      for (const path of ['/', '/produits', '/services', '/locations', samples.products, '/shops']) {
        const response = await page.goto(base + path, { waitUntil: 'networkidle' });
        assert.equal(response.status(), 200, name + ' ' + path);
        const dimensions = await page.evaluate(() => ({ document: document.documentElement.scrollWidth, viewport: innerWidth }));
        assert(dimensions.document <= dimensions.viewport + 1, `${name} ${path} overflows at ${width}`);
        if (path === '/') {
          assert.equal(await page.locator('.hub-category').count(), 6);
          const rows = await page.locator('.hub-category').evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().top));
          assert.equal(rows.filter(top => Math.abs(top - rows[0]) < 1).length, width <= 768 ? 3 : 6);
          assert.equal(await page.locator('a.hub-category[href="/produits"]').count(), 1);
        } else if (['/produits', '/services', '/locations'].includes(path)) {
          assert.equal(new URL(await page.locator('link[rel="canonical"]').getAttribute('href')).pathname, path);
          assert(await page.locator('.public-catalog-card a[href]').count() > 0);
          assert.equal(await page.locator('.public-header').count(), 1);
        }
      }
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(base + '/', { waitUntil: 'networkidle' });
    let navigations = 0;
    page.on('request', request => { if (request.isNavigationRequest() && request.frame() === page.mainFrame()) navigations += 1; });
    await page.evaluate(() => { window.__seoDocumentToken = 'same-document'; });
    await page.locator('a.hub-category[data-open-universe="products"]').click();
    await page.waitForFunction(() => document.querySelector('#catalogResults')?.getAttribute('aria-busy') === 'false' && document.querySelector('#catalogResults .catalog-item'));
    assert.equal(await page.locator('#universeModalPanel').getAttribute('aria-hidden'), 'false');
    const title = await page.locator('#catalogResults .u-item-title').first().textContent();
    await page.locator('#catalogResults [data-open-product-detail]').first().click();
    await page.waitForFunction(() => document.querySelector('#pDetailContent')?.style.display !== 'none');
    assert.equal(await page.locator('#pDetailTitle').textContent(), title);
    await page.locator('#productDetailPanel .u-modal-close-btn[data-pdetail-close]').click();
    await page.waitForFunction(() => document.querySelector('#productDetailPanel')?.getAttribute('aria-hidden') === 'true');
    await page.waitForFunction(() => !document.querySelector('#universeModalPanel')?.inert);
    await page.locator('#universeModalPanel .u-modal-close-btn[data-u-modal-close]').click();
    await page.waitForFunction(() => document.querySelector('#universeModalPanel')?.getAttribute('aria-hidden') === 'true');
    assert.equal(navigations, 0, 'Popup flow must not reload');
    assert.equal(await page.evaluate(() => window.__seoDocumentToken), 'same-document');
    await page.goto(base + '/produits', { waitUntil: 'networkidle' });
    const next = page.locator('.public-catalog-pagination a[rel="next"]');
    assert(await next.count(), 'Preview needs at least 13 products for pagination');
    await next.click();
    assert.equal(new URL(page.url()).searchParams.get('page'), '2');
    assert.match(await page.title(), /Page 2/);
    assert.equal(errors.length, 0, errors.join('\n'));
    const nojs = await browser.newContext({ javaScriptEnabled: false, viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
    const nojsPage = await nojs.newPage();
    for (const path of ['/produits', '/services', '/locations', samples.products, samples.services, samples.locations]) {
      const response = await nojsPage.goto(base + path);
      assert.equal(response.status(), 200, 'No-JS ' + path);
      assert(await nojsPage.locator('h1').first().isVisible());
      assert.equal(await nojsPage.locator('#bm-loader').isVisible(), false, 'Startup overlay must not block no-JS browsing');
      if (['/produits', '/services', '/locations'].includes(path)) {
        await nojsPage.locator('.public-catalog-card a[href]').first().click();
        assert(await nojsPage.locator('h1').first().isVisible());
      }
    }
    await nojs.close();
    await context.close();
    console.log(name + ': five viewport widths, six cards, popup navigation, pagination and no-JS links OK');
  } finally {
    await browser.close();
  }
}
(async () => { await run('chromium', chromium); await run('webkit', webkit); })().catch(error => { console.error(error); process.exit(1); });
