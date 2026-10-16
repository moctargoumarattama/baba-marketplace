/* Exercise the homepage banner on a disposable preview. */
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
    await page.clock.install();
    await page.goto(base + '/', { waitUntil: 'networkidle' });
    const hero = page.locator('[data-hero-carousel]');
    const dots = hero.locator('[data-hero-to]');
    const pause = hero.locator('[data-hero-pause]');
    async function selected() { return Number(await hero.locator('[data-hero-to][aria-pressed="true"]').getAttribute('data-hero-to')); }
    assert.equal(await selected(), 0);
    await page.clock.fastForward(6500);
    assert.equal(await selected(), 1);
    await page.clock.fastForward(6500);
    assert.equal(await selected(), 2);
    await pause.tap();
    await page.clock.fastForward(12000);
    assert.equal(await selected(), 2);
    await pause.tap();
    await page.clock.runFor(50);
    await page.clock.fastForward(6500);
    assert.equal(await selected(), 0);

    for (const width of [320, 390, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      let height;
      for (let index = 0; index < 3; index += 1) {
        await dots.nth(index).tap();
        await page.clock.runFor(650);
        const box = await hero.boundingBox();
        if (height) assert(Math.abs(box.height - height) < 1, 'slides must keep a stable height');
        height = box.height;
        assert.equal(await selected(), index);
        assert.equal(await hero.locator('[data-hero-slide]:not([inert])').count(), 1);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
        const button = await hero.locator('.is-active [data-open-universe]').boundingBox();
        const controls = await hero.locator('[data-hero-controls]').boundingBox();
        assert(button.y + button.height <= controls.y, 'controls must not overlap the action');
        if (name === 'chromium' && width === 390 && index > 0) {
          await hero.screenshot({ animations: 'disabled', path: 'audits/2026-10-16-interface-publique/banniere-' + (index === 1 ? 'services' : 'hebergements') + '-mobile.png' });
        }
      }
    }

    await page.setViewportSize({ width: 390, height: 844 });
    await dots.nth(0).tap();
    const box = await hero.boundingBox();
    await page.mouse.move(box.x + box.width - 25, box.y + 100);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width - 130, box.y + 105, { steps: 6 });
    await page.mouse.up();
    assert.equal(await selected(), 1, 'horizontal swipe advances the banner');
    await hero.focus();
    await page.keyboard.press('ArrowRight');
    assert.equal(await selected(), 2);

    for (const [index, title] of [[1, 'Services'], [2, 'Locations']]) {
      await dots.nth(index).tap();
      await page.clock.runFor(650);
      await hero.locator('.is-active [data-open-universe]').tap();
      await page.waitForFunction(() => document.querySelector('#universeModalPanel').getAttribute('aria-hidden') === 'false');
      assert.equal(await page.locator('#uModalTitle').textContent(), title);
      await page.clock.fastForward(12000);
      assert.equal(await selected(), index);
      await page.keyboard.press('Escape');
      await page.clock.runFor(350);
    }

    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.reload({ waitUntil: 'networkidle' });
    assert.equal(await pause.getAttribute('aria-pressed'), 'true');
    await page.clock.fastForward(18000);
    assert.equal(await selected(), 0, 'reduced motion disables automatic rotation');
    await dots.nth(2).tap();
    assert.equal(await selected(), 2, 'manual navigation remains available');
    assert.deepEqual(errors, []);
    console.log(name + ': autoplay, pause, layout, swipe, keyboard, category links and reduced motion PASS');
  } finally { await browser.close(); }
}

(async () => {
  for (const [name, engine] of Object.entries({ chromium, webkit })) await run(name, engine);
})().catch(error => { console.error(error); process.exitCode = 1; });
