/* Removed homepage previews must not poll; their catalogues remain accessible. */
const assert = require('node:assert/strict');
const { chromium, webkit } = require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');
const base = process.env.PUBLIC_PREVIEW_URL || 'http://127.0.0.1:5059';

async function run(name, engine) {
  const browser = await engine.launch({ headless: true });
  try {
    const context = await browser.newContext({
      viewport: { width: 390, height: 844 }, isMobile: true,
      hasTouch: true, serviceWorkers: 'block'
    });
    const page = await context.newPage();
    const errors = [];
    let refreshes = 0;
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => {
      if (new URL(request.url()).pathname === '/api/home-selection') refreshes += 1;
    });
    await page.clock.install();
    assert.equal((await page.goto(base + '/', { waitUntil: 'networkidle' })).status(), 200);
    assert.equal(await page.locator('[data-home-offers], [data-home-rotation-url], .hub-shops-grid').count(), 0);
    assert.equal(await page.locator('.hub-category').count(), 6);
    await page.clock.fastForward(1801000);
    assert.equal(refreshes, 0, 'removed lists must not schedule refreshes');

    for (const universe of ['products', 'services', 'shops']) {
      await page.locator('.hub-category[data-open-universe="' + universe + '"]').tap();
      await page.waitForFunction(() =>
        document.querySelector('#catalogResults').getAttribute('aria-busy') === 'false');
      assert.equal(await page.locator('#universeModalPanel').getAttribute('aria-hidden'), 'false');
      assert.equal(await page.evaluate(() => BMCatalog.snapshot().universe), universe);
      await page.keyboard.press('Escape');
      await page.waitForFunction(() =>
        document.querySelector('#universeModalPanel').getAttribute('aria-hidden') === 'true');
      await page.clock.runFor(350);
    }
    assert.deepEqual(errors, []);
    console.log(name + ': homepage previews removed, no refresh polling, catalogues accessible PASS');
  } finally { await browser.close(); }
}

(async () => {
  for (const [name, engine] of Object.entries({ chromium, webkit })) await run(name, engine);
})().catch(error => { console.error(error); process.exitCode = 1; });
