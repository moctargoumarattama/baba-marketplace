/* Run only against admin_responsive_server.py and its temporary database. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { chromium, webkit } = require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');
const base = process.env.ADMIN_RESPONSIVE_PREVIEW_URL || 'http://127.0.0.1:5084';
const widths = (process.env.ADMIN_RESPONSIVE_WIDTHS || '320,375,390,768,1024,1440').split(',').map(Number);
const screenshots = fs.mkdtempSync(path.join(os.tmpdir(), 'babamarket-admin-responsive-screens-'));

async function geometry(page, name, path, width) {
  const state = await page.evaluate(() => {
    const rect = node => node?.getBoundingClientRect().toJSON();
    const cards = Array.from(document.querySelectorAll('.aud-card, .stat-tile'));
    const body = document.body;
    return {
      viewport: innerWidth,
      scroll: document.documentElement.scrollWidth,
      bodyScroll: body.scrollWidth,
      safeTop: getComputedStyle(document.documentElement).getPropertyValue('--admin-safe-top'),
      mainSafeTop: getComputedStyle(document.querySelector('.main-content')).getPropertyValue('--admin-safe-top'),
      mainPadding: getComputedStyle(document.querySelector('.main-content')).paddingTop,
      headerTop: getComputedStyle(document.querySelector('.top-bar')).top,
      header: rect(document.querySelector('.top-bar')),
      hamburger: rect(document.getElementById('menuToggle')),
      cards: cards.map(node => ({ ...rect(node), label: node.innerText, scroll: node.scrollWidth,
        client: node.clientWidth, overflow: getComputedStyle(node).overflow,
        children: Array.from(node.children).map(child => ({ label: child.innerText,
          width: child.getBoundingClientRect().width, scroll: child.scrollWidth })) })),
      audienceColumns: document.querySelector('.aud-shell') && getComputedStyle(document.querySelector('.aud-shell')).gridTemplateColumns,
      dashboardColumns: document.querySelector('.stats-grid') && getComputedStyle(document.querySelector('.stats-grid')).gridTemplateColumns,
    };
  });
  const label = `${name}/${width}${path}`;
  assert(state.scroll <= state.viewport + 1, `${label}: document overflow ${state.scroll}/${state.viewport}`);
  assert(state.bodyScroll <= state.viewport + 1, `${label}: body overflow ${state.bodyScroll}/${state.viewport}`);
  for (const card of state.cards) {
    assert(card.width >= 115, `${label}: readable KPI width, got ${card.width}`);
    for (const child of card.children) {
      assert(child.width <= card.client + 1 && child.scroll <= child.width + 1,
        `${label}: readable card content ${JSON.stringify(child)}`);
    }
  }
  if (width <= 1024) {
    assert(state.hamburger.width >= 42 && state.hamburger.height >= 42, label + ': menu is a usable touch target');
    assert(state.hamburger.top >= 43, label + ': menu clears the simulated iPhone safe area ' + JSON.stringify(state));
    assert(state.header.height <= 84, label + ': mobile header stays compact');
    assert(state.hamburger.left >= 0 && state.hamburger.right <= width, label + ': menu is inside screen');
    if (path.includes('audience')) assert.equal(state.audienceColumns.split(' ').length, 1, label + ': audience panels stack');
  }
}

async function menus(page, label, width) {
  if (width > 1024) return;
  const toggle = page.locator('#menuToggle');
  await toggle.click();
  await page.waitForFunction(() => document.getElementById('sidebar').classList.contains('show'));
  await page.waitForFunction(() => document.getElementById('sidebar').getBoundingClientRect().left >= -1);
  const sidebar = page.locator('#sidebar');
  const state = await sidebar.evaluate(node => {
    const bounds = node.getBoundingClientRect();
    return { left: bounds.left, right: bounds.right, width: innerWidth,
      activeInside: node.contains(document.activeElement),
      firstTop: node.querySelector('button, a')?.getBoundingClientRect().top };
  });
  assert(state.activeInside, label + ': sidebar receives keyboard focus');
  assert(state.left >= -1 && state.right <= state.width + 1, label + ': sidebar fits screen');
  assert(state.firstTop >= 43, label + ': sidebar controls clear safe area');
  await page.keyboard.press('Shift+Tab');
  assert(await sidebar.evaluate(node => node.contains(document.activeElement)), label + ': reverse Tab remains in sidebar');
  await page.keyboard.press('Tab');
  assert(await sidebar.evaluate(node => node.contains(document.activeElement)), label + ': Tab remains in sidebar');
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => !document.getElementById('sidebar').classList.contains('show'));
  assert(await toggle.evaluate(node => document.activeElement === node), label + ': sidebar returns focus to trigger');
  await toggle.click();
  await page.locator('#sidebarClose').click();
  await page.waitForFunction(() => !document.getElementById('sidebar').classList.contains('show'));
  await toggle.click();
  await page.locator('#sidebarBackdrop').click({ position: { x: width - 5, y: 300 } });
  await page.waitForFunction(() => !document.getElementById('sidebar').classList.contains('show'));

  const more = page.locator('#adminActionsToggle');
  await more.click();
  assert.equal(await more.getAttribute('aria-expanded'), 'true', label + ': Plus expands');
  assert(await page.locator('#adminHeaderActions').isVisible(), label + ': Plus actions visible');
  const popup = await page.locator('#adminHeaderActions').boundingBox();
  assert(popup.x >= 0 && popup.x + popup.width <= width + 1, label + ': Plus fits screen');
  await page.keyboard.press('Escape');
  assert.equal(await more.getAttribute('aria-expanded'), 'false', label + ': Escape closes Plus');
  assert(await more.evaluate(node => document.activeElement === node), label + ': Plus restores focus');
}

async function run(name, engine) {
  const browser = await engine.launch({ headless: true });
  try {
    for (const width of widths) {
      const context = await browser.newContext({ viewport: { width, height: 844 },
        isMobile: width <= 768, hasTouch: width <= 768, serviceWorkers: 'block', reducedMotion: 'reduce' });
      try {
        assert((await context.request.get(base + '/__admin_responsive_fixture__')).ok());
        const page = await context.newPage();
        await page.addInitScript(() => {
          const setInsets = () => {
            if (!document.documentElement) return false;
            document.documentElement.style.setProperty('--admin-safe-top', '44px');
            document.documentElement.style.setProperty('--admin-safe-bottom', '34px');
            return true;
          };
          if (!setInsets()) {
            const observer = new MutationObserver(() => { if (setInsets()) observer.disconnect(); });
            observer.observe(document, { childList: true, subtree: true });
          }
        });
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        page.setDefaultTimeout(10000);
        await page.route('**/*', route => new URL(route.request().url()).origin === new URL(base).origin
          ? route.continue() : route.abort());
        const routes = width === 390 ? ['/admin/', '/admin/audience', '/admin/users', '/admin/shops'] : ['/admin/', '/admin/audience'];
        for (const path of routes) {
          await page.goto(base + path, { waitUntil: 'domcontentloaded' });
          if (path.includes('audience')) await page.locator('#audMainCards .aud-card').first().waitFor();
          await page.waitForTimeout(100);
          await geometry(page, name, path, width);
          await menus(page, `${name}/${width}${path}`, width);
          if (width === 390 || width === 1440) await page.screenshot({
            path: require('node:path').join(screenshots, `${name}-${width}-${path.split('/').filter(Boolean).at(-1) || 'dashboard'}.png`),
            fullPage: true,
          });
          if (path.includes('audience')) {
            for (const scope of ['internal', 'all', 'clients']) {
              await page.locator(`[data-scope="${scope}"]`).click();
              await geometry(page, name, path + '/' + scope, width);
            }
          } else {
            const range = page.locator('select[name="range"]');
            if (await range.count()) {
              assert.equal(await page.locator('input[name="date_from"]').isVisible(), false, 'dates hidden for predefined range');
              await range.selectOption('custom');
              assert(await page.locator('input[name="date_from"]').isVisible(), 'custom date start visible');
              assert(await page.locator('input[name="date_to"]').isVisible(), 'custom date end visible');
              await geometry(page, name, path + '/custom', width);
              await range.selectOption('month');
            }
          }
          console.log(`${name} ${width} ${path}: PASS`);
        }
        assert.deepEqual(errors, [], `${name}/${width}: no uncaught JavaScript errors`);
      } finally { await context.close(); }
    }
  } finally { await browser.close(); }
}

(async () => {
  const engines = process.env.ADMIN_RESPONSIVE_ENGINE ? [[process.env.ADMIN_RESPONSIVE_ENGINE,
    process.env.ADMIN_RESPONSIVE_ENGINE === 'webkit' ? webkit : chromium]] : [['chromium', chromium], ['webkit', webkit]];
  for (const [name, engine] of engines) await run(name, engine);
  console.log('Admin screenshots: ' + screenshots);
})().catch(error => { console.error(error); process.exitCode = 1; });
