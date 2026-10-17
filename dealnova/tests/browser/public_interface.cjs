/* Run against a disposable preview database, never a production session.
   PUBLIC_PREVIEW_URL=http://127.0.0.1:5057
   PLAYWRIGHT_PACKAGE may point to an existing Playwright installation. */
const assert = require('node:assert/strict');
const { chromium, webkit } = require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');
const base = process.env.PUBLIC_PREVIEW_URL || 'http://127.0.0.1:5057';
const query = process.env.CATALOG_TEST_QUERY || '';

async function run(engine, name) {
  const browser = await engine.launch({ headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, serviceWorkers: 'block' });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => { errors.push(error.message); console.error(name, page.url(), error.stack || error.message); });
    async function settled() {
      await page.waitForFunction(() => document.querySelector('#catalogResults')?.getAttribute('aria-busy') === 'false');
    }
    for (const path of ['/login', '/forgot-password', '/shops']) {
      const response = await page.goto(base + path, { waitUntil: 'networkidle' });
      assert.equal(response.status(), 200, path);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, path + ' overflows');
      assert.equal(await page.locator('.public-header').count(), 1);
    }
    await page.goto(base + '/', { waitUntil: 'networkidle' });
    await page.locator('#homeSearchInput').fill(query || 'kar');
    await page.waitForTimeout(350);
    assert.equal(await page.locator('#universeModalPanel').getAttribute('aria-hidden'), 'true');
    await page.locator('#homeSearchForm').evaluate(form => form.requestSubmit());
    await settled();
    assert.equal(await page.locator('#universeModalPanel').getAttribute('aria-hidden'), 'false');
    assert.equal(await page.locator('#uModalSearchInput').inputValue(), query || 'kar');
    await page.waitForFunction(() => !document.querySelector('#universeModalPanel').classList.contains('is-opening'));
    await page.keyboard.press('Escape');
    await page.waitForTimeout(80);
    assert.equal(await page.locator('#universeModalPanel').getAttribute('aria-hidden'), 'true');
    assert.equal(await page.locator('#universeModalPanel').evaluate(el => el.hidden), false, 'exit transition must finish before display:none');
    await page.waitForTimeout(280);
    assert.equal(await page.locator('#universeModalPanel').evaluate(el => el.hidden), true);

    await page.goto(base + '/?open=products' + (query ? '&q=' + encodeURIComponent(query) : ''), { waitUntil: 'networkidle' });
    await settled();
    const initial = await page.request.get(base + '/api/catalog?universe=products&q=' + encodeURIComponent(query));
    const initialData = await initial.json();
    assert.equal(initialData.success, true);
    if (query) assert(initialData.pagination.total > 60, 'fixture must contain more than 60 offers');
    if (query && initialData.pagination.total > 72) {
      await page.goto(base + '/?open=products&q=' + encodeURIComponent(query) + '&page=7', { waitUntil: 'networkidle' });
      await settled();
      assert.match(await page.locator('#catalogPageStatus').innerText(), /Page 7/);
      assert.equal(await page.locator('#catalogResults .catalog-item').count(), Math.min(12, initialData.pagination.total - 72));
      await page.goto(base + '/?open=products&q=' + encodeURIComponent(query), { waitUntil: 'networkidle' });
      await settled();
    }
    await page.locator('#catalogSort').selectOption('low');
    await settled();
    await page.locator('#catalogFilterToggle').click();
    await page.locator('#catalogFilters [name=min_price]').fill('20');
    await page.locator('#catalogFilters [name=max_price]').fill('40');
    await page.locator('#catalogFilters').evaluate(form => form.requestSubmit());
    await settled();
    const prices = await page.locator('#catalogResults .u-item-price').allTextContents();
    assert(prices.every(text => { const value = Number(text.replace(/[^\d,.]/g, '').replace(',', '.')); return value >= 20 && value <= 40; }));
    assert(page.url().includes('min_price=20') && page.url().includes('max_price=40'));
    if (initialData.pagination.total > 12) {
      const firstNames = await page.locator('#catalogResults .u-item-title').allTextContents();
      await page.locator('#catalogNext').click();
      await settled();
      assert.match(await page.locator('#catalogPageStatus').innerText(), /Page 2/);
      const secondNames = await page.locator('#catalogResults .u-item-title').allTextContents();
      assert(secondNames.every(name => !firstNames.includes(name)));
    }
    const firstDetail = page.locator('#catalogResults [data-open-product-detail]').first();
    if (await firstDetail.count()) {
      await page.locator('#uModalBody').evaluate(el => el.scrollTop = 160);
      await firstDetail.click();
      await page.waitForFunction(() => document.querySelector('#pDetailContent').style.display === 'block');
      assert.equal(await page.locator('#productDetailPanel').getAttribute('aria-hidden'), 'false');
      await page.goBack();
      await settled();
      assert.equal(await page.locator('#universeModalPanel').getAttribute('aria-hidden'), 'false');
      assert(page.url().includes('min_price=20'));
    }
    await page.locator('#uModalSearchInput').fill('zz_no_match_zz');
    await page.waitForTimeout(350); await settled();
    assert.match(await page.locator('#catalogResults').innerText(), /Aucun résultat/);
    await page.locator('#catalogResults .hub-primary-btn').click(); await settled();
    assert.equal(await page.locator('#uModalSearchInput').inputValue(), '');
    assert(!page.url().includes('min_price'));
    for (let index = 0; index < 18; index++) {
      await page.keyboard.press('Tab');
      assert.equal(await page.evaluate(() => document.querySelector('#universeModalPanel').contains(document.activeElement)), true);
    }
    if (name === 'chromium') {
      const handle = page.locator('#universeModalPanel [data-sheet-drag]');
      const bounds = await handle.boundingBox();
      await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + 12);
      await page.mouse.down(); await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + 155, { steps: 7 }); await page.mouse.up();
      await page.waitForTimeout(350);
      assert.equal(await page.locator('#universeModalPanel').getAttribute('aria-hidden'), 'true', 'swipe dismiss');
    } else { await page.keyboard.press('Escape'); await page.waitForTimeout(350); }
    await page.goto(base + '/?open=services', { waitUntil: 'networkidle' }); await settled();
    assert.equal(await page.locator('#catalogResults [data-cart-add-btn]').count(), 0);
    await page.goto(base + '/?open=locations', { waitUntil: 'networkidle' }); await settled();
    await page.locator('#catalogFilterToggle').click();
    assert.equal(await page.locator('#catalogFilters [name=listing_type]').isVisible(), true);
    assert.equal(await page.locator('#catalogFilters [name=stock]').isVisible(), false);
    await page.locator('#catalogFilterToggle').click();
    const rental = page.locator('#catalogResults [data-item-type=location] .u-btn-detail').first();
    if (await rental.count()) {
      await rental.click(); await page.waitForLoadState('networkidle');
      assert.equal(await page.locator('.public-rental-detail').count(), 1);
      assert.equal(await page.locator('.public-header').count(), 1);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      const inquiry = page.locator('a[href$="/inquiry"]').first();
      await inquiry.click(); await page.waitForLoadState('networkidle');
      assert.equal(await page.locator('.inq-card').count(), 1);
      assert.equal(await page.locator('input[name=csrf_token]').count() > 0, true);
      assert.equal(await page.locator('#phone').getAttribute('type'), 'tel');
    }
    await page.goto(base + '/?open=delivery', { waitUntil: 'networkidle' });
    assert.equal(await page.locator('#uDeliveryBody').isVisible(), true);
    assert.equal(await page.locator('#catalogToolbar').isVisible(), false);
    await page.goto(base + '/?open=cart', { waitUntil: 'networkidle' });
    assert.equal(await page.locator('#cartDrawerPanel').getAttribute('aria-hidden'), 'false');
    await page.route('**/api/catalog?*', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ success: false, message: 'Veuillez réessayer.' }) }));
    await page.goto(base + '/?open=products', { waitUntil: 'networkidle' }); await settled();
    assert.match(await page.locator('#catalogResults').innerText(), /momentanément indisponible/);
    await page.unroute('**/api/catalog?*');
    await page.locator('#catalogResults .hub-primary-btn').click(); await settled();
    assert.equal(await page.locator('#catalogResults .catalog-item').count() > 0, true, 'retry recovers after a failed request');
    await page.goto(base + '/?open=shops', { waitUntil: 'networkidle' }); await settled();
    const shop = page.locator('#catalogResults [data-open-shop-detail]').first();
    if (await shop.count()) {
      await shop.click();
      await page.waitForFunction(() => document.querySelector('#shopDetailContent').style.display === 'block');
      const shopId = await page.locator('#shopDetailExplore').getAttribute('data-shop-id');
      await page.locator('#shopDetailSearchInput').fill(query || 'kar');
      await page.locator('#shopDetailSearchBox').evaluate(form => form.requestSubmit()); await settled();
      assert.equal(await page.locator('#universeModalPanel').getAttribute('aria-hidden'), 'false');
      assert(page.url().includes('shop=' + shopId));
      assert.equal(await page.locator('#uModalSearchInput').inputValue(), query || 'kar');
    }
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const reducedDuration = await page.locator('#universeModalPanel').evaluate(el => parseFloat(getComputedStyle(el).transitionDuration));
    assert(reducedDuration <= 0.001, 'reduced motion must remove visible transitions');
    const indexBeforeReducedClose = await page.evaluate(() => history.state.bmHub.index);
    await page.keyboard.press('Escape');
    await page.waitForFunction(expectedIndex => {
      const sheet = document.querySelector('#universeModalPanel');
      // A covered catalogue stays mounted behind its parent after Back.
      return history.state.bmHub.index === expectedIndex && sheet.inert &&
        sheet.getAttribute('aria-hidden') === 'true' &&
        !sheet.classList.contains('is-opening') && !sheet.classList.contains('is-closing');
    }, indexBeforeReducedClose - 1, { timeout: 1000 });
    assert.equal(errors.length, 0, errors.join('\n'));
    await context.close();
    console.log(name + ': public forms, filters, pagination, focus, history, empty states and sheets passed');
  } finally { await browser.close(); }
}
(async () => { await run(chromium, 'chromium'); await run(webkit, 'webkit'); })().catch(error => { console.error(error); process.exitCode = 1; });
