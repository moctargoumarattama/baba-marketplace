/* Run against a disposable public preview database. */
const assert = require('node:assert/strict');
const { chromium, webkit } = require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');
const base = process.env.PUBLIC_PREVIEW_URL || 'http://127.0.0.1:5059';

async function run(name, engine) {
  const browser = await engine.launch({ headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true,
                                               hasTouch: true, serviceWorkers: 'block' });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base + '/', { waitUntil: 'networkidle' });
    const input = page.locator('#homeSearchInput');
    const panel = page.locator('#homeSearchForm [data-search-panel]');
    const options = panel.locator('[role="option"]');
    const logo = page.locator('.hub-brand-logo');
    assert.equal(await logo.evaluate(el => el.complete && el.naturalWidth > 0), true);
    assert.equal(await page.locator('.hub-search button[type="submit"]').count(), 0);
    for (const width of [320, 390, 1280]) {
      await page.setViewportSize({ width, height: 844 });
      await input.fill('kar');
      await panel.locator('[role="listbox"][aria-busy="false"] [role="option"]').first().waitFor();
      assert(await options.count() > 0 && await options.count() <= 6);
      assert.equal(await input.evaluate(el => document.activeElement === el), true);
      assert.equal(await page.locator('#universeModalPanel').getAttribute('aria-hidden'), 'true');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      const rect = await panel.boundingBox();
      assert(rect.x >= 0 && rect.x + rect.width <= width + 1);
      if (name === 'chromium' && width === 390) {
        await page.screenshot({ path: 'audits/2026-10-16-interface-publique/logo-recherche-mobile.png' });
      }
      await page.locator('#homeSearchClear').click();
      assert.equal(await input.inputValue(), '');
      assert.equal(await panel.isVisible(), false);
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await input.fill('kar');
    await panel.locator('[aria-busy="false"] [data-open-product-detail]').first().waitFor();
    await panel.locator('[data-open-product-detail]').first().tap();
    await page.waitForFunction(() => document.querySelector('#productDetailPanel').getAttribute('aria-hidden') === 'false');
    await page.keyboard.press('Escape');
    await page.waitForTimeout(350);
    assert.equal(await input.evaluate(el => document.activeElement === el), true);
    assert.equal(await panel.isVisible(), false);

    await input.fill('kar');
    await options.first().waitFor();
    await input.press('ArrowDown');
    assert.equal(await input.getAttribute('aria-activedescendant'), await options.first().getAttribute('id'));
    await input.press('Enter');
    await page.waitForFunction(() => document.querySelector('#productDetailPanel').getAttribute('aria-hidden') === 'false');
    await page.keyboard.press('Escape');
    await page.waitForTimeout(350);
    await input.fill('kar');
    await options.first().waitFor();
    await panel.locator('[data-search-all]').tap();
    await page.waitForFunction(() => document.querySelector('#catalogResults').getAttribute('aria-busy') === 'false');
    assert.equal(await page.locator('#universeModalPanel').getAttribute('aria-hidden'), 'false');
    assert.equal(await page.locator('#uModalSearchInput').inputValue(), 'kar');
    await page.keyboard.press('Escape');
    await page.waitForTimeout(350);

    await input.fill('zzzz_no_such_product_zzzz');
    await page.waitForFunction(() => document.querySelector('#homeSearchForm [data-search-status]').textContent.startsWith('Aucun'));
    assert.equal(await options.count(), 0);
    assert.equal(await panel.locator('[data-search-all]').isVisible(), false);
    await input.press('Escape');
    assert.equal(await panel.isVisible(), false);

    const fixture = await (await page.request.get(base + '/api/catalog?universe=search&q=kar&per_page=6')).json();
    let oldStarted;
    const started = new Promise(resolve => { oldStarted = resolve; });
    await page.route('**/api/catalog?**', async route => {
      const query = new URL(route.request().url()).searchParams.get('q');
      if (!['older', 'latest', 'failure'].includes(query)) return route.continue();
      if (query === 'failure') return route.fulfill({ status: 503, body: 'Unavailable' });
      const response = structuredClone(fixture);
      response.items[0].name = query === 'older' ? 'Obsolete' : '<b>Resultat recent</b>';
      if (query === 'older') {
        oldStarted();
        await new Promise(resolve => setTimeout(resolve, 900));
      }
      await route.fulfill({ json: response }).catch(() => {});
    });
    await input.fill('older');
    await started;
    await input.fill('latest');
    await page.waitForFunction(() => document.querySelector('.hub-live-search-copy strong')?.textContent === '<b>Resultat recent</b>');
    await page.waitForTimeout(1000);
    assert.equal(await options.first().locator('strong').textContent(), '<b>Resultat recent</b>');
    assert.equal(await options.first().locator('b').count(), 0);
    await input.fill('failure');
    await page.waitForFunction(() => document.querySelector('#homeSearchForm [data-search-status]').textContent.startsWith('Recherche indisponible'));
    await input.fill('kar');
    await options.first().waitFor();
    await page.locator('#homeSearchClear').click();

    let compositionRequests = 0;
    page.on('request', request => { if (request.url().includes('/api/catalog?')) compositionRequests += 1; });
    await input.dispatchEvent('compositionstart');
    await input.fill('ka');
    await page.waitForTimeout(400);
    assert.equal(compositionRequests, 0);
    await input.dispatchEvent('compositionend');
    await options.first().waitFor();
    assert.equal(compositionRequests, 1);

    for (const path of ['/login', '/forgot-password', '/support/help', '/shops']) {
      await page.goto(base + path, { waitUntil: 'networkidle' });
      assert.equal(await page.locator('[data-live-search], .nav-search').count(), 0, 'homepage search excluded from ' + path);
      assert.equal(await page.locator('script[src*="public_live_search.js"]').count(), 0);
      assert.equal(await page.locator('.hub-brand-logo').evaluate(el => el.complete && el.naturalWidth > 0), true);
    }
    assert.deepEqual(errors, []);
    console.log(name + ': logo, live search, keyboard, links, stale responses, empty/error and IME PASS');
  } finally { await browser.close(); }
}

(async () => {
  for (const [name, engine] of Object.entries({ chromium, webkit })) await run(name, engine);
})().catch(error => { console.error(error); process.exitCode = 1; });
