/* Use a disposable local preview. Check actual overflow without root clipping. */
const assert = require('node:assert/strict');
const { chromium, webkit } = require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');
const base = process.env.PUBLIC_PREVIEW_URL || 'http://127.0.0.1:5059';

async function run(name, engine) {
  const browser = await engine.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, serviceWorkers: 'block' });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(base + '/', { waitUntil: 'networkidle' });
    for (const width of [280, 320, 360, 390, 430, 568, 768, 769, 820, 1024, 1100, 1101, 1280, 1440, 1920, 2560, 3840]) {
      await page.setViewportSize({ width, height: width < 700 ? 844 : 1080 });
      await page.evaluate(() => { document.documentElement.style.overflowX = 'visible'; });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), true, 'overflow at ' + width);
      for (const selector of ['#hubHome', '.hub-header-inner']) {
        assert.equal(Math.round((await page.locator(selector).boundingBox()).width), width, selector + ' should fill ' + width);
      }
      const rows = await page.locator('.hub-category').evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().top));
      assert.equal(rows.filter(top => Math.abs(top - rows[0]) < 1).length, width <= 768 ? 3 : 6);
      assert.equal(await page.locator('.hub-category-label').evaluateAll(nodes => nodes.every(node => node.scrollWidth <= node.clientWidth)), true);
      for (let index = 0; index < 3; index += 1) {
        await page.locator('[data-hero-to="' + index + '"]').click();
        const button = await page.locator('.hub-hero-slide.is-active .hub-primary-btn').boundingBox();
        const controls = await page.locator('[data-hero-controls]').boundingBox();
        assert(button.y + button.height <= controls.y, 'hero controls overlap at ' + width);
      }
    }
    assert.deepEqual(errors, []);
    console.log(name + ': full width, no overflow, mobile columns and hero controls from 280 to 3840px PASS');
  } finally { await browser.close(); }
}

(async () => {
  await run('chromium', chromium);
  await run('webkit', webkit);
})().catch(error => { console.error(error); process.exitCode = 1; });
