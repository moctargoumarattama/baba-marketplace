/* Run against a disposable preview. APIs are fixtures; no database writes.
   PLAYWRIGHT_PACKAGE may name an existing installation. */
const assert = require('node:assert/strict');
const { chromium, webkit } = require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');
const base = process.env.PUBLIC_PREVIEW_URL || 'http://127.0.0.1:5059';
const pid = 910001;
const shopSlug = 'mobile-modal-fixture';

async function fixtures(page) {
  const counts = { catalog: 0 };
  const gates = { product: null, shop: null };
  await page.route('**/cart/api/full', route => route.fulfill({ json: {
    success: true, count: 0, total: 0, items: [], vendors: [],
  } }));
  await page.route('**/api/catalog?**', route => {
    counts.catalog++;
    return route.fulfill({ json: { success: true, facets: {}, filters: {},
      pagination: { page: 1, pages: 1, total: 18, per_page: 18, has_next: false, has_prev: false },
      items: Array.from({ length: 18 }, (_, index) => ({ id: pid + index,
        name: 'Article de test ' + index, description: 'Description du produit de demonstration.',
        item_type: 'product', kind: 'physical', stock: 3, price: 30, final_price: 30,
        available: true, image_url: '', url: '/shop/product/' + (pid + index) })) } });
  });
  await page.route('**/api/product/*', async route => {
    if (gates.product) await gates.product;
    const id = Number(new URL(route.request().url()).pathname.split('/').pop());
    return route.fulfill({ json: { success: true, product: { id, kind: 'physical',
      name: 'Article de test ' + (id - pid), description: 'Longue description. '.repeat(150),
      price: 30, final_price: 30, stock: 3, has_promo: false, images: [],
      share_url: base + '/shop/product/' + id, category: 'Test',
      shop: { id: 910099, slug: shopSlug, name: 'Boutique de test', logo: '', is_verified: false },
      whatsapp_order_url: 'https://wa.me/000' } } });
  });
  await page.route('**/api/shop/*', async route => {
    if (gates.shop) await gates.shop;
    return route.fulfill({ json: { success: true, products: [], product_count: 0,
      shop: { id: 910099, slug: shopSlug, name: 'Boutique de test', description: 'Description. '.repeat(100),
        logo: '', banner: '', address: 'Rabat', is_open: true, is_verified: false,
        review_count: 0, whatsapp_url: 'https://wa.me/000', call_url: null,
        share_url: base + '/shops/' + shopSlug } } });
  });
  return { counts, gates };
}

async function settled(page) {
  await page.waitForFunction(() => document.querySelector('#catalogResults')?.getAttribute('aria-busy') === 'false');
}
async function openCatalog(page) {
  await page.locator('.hub-categories [data-open-universe="products"]').tap();
  await settled(page);
  await page.waitForTimeout(300);
}
function closeButton(page, panel, attr) { return page.locator(panel + ' button[' + attr + ']').first(); }
async function hidden(page, selector) {
  await page.waitForFunction(selector => document.querySelector(selector).hidden, selector);
}
async function trace(page, selector) {
  await page.evaluate(selector => {
    const node = document.querySelector(selector);
    const state = window.__modalTrace = { stop: false, frames: [] };
    function frame() {
      const rect = node.getBoundingClientRect();
      const parent = document.querySelector('#universeModalPanel');
      state.frames.push({ y: rect.y, height: rect.height, hidden: node.hidden,
        closing: node.classList.contains('is-closing'), parentY: parent.getBoundingClientRect().y,
        parentHidden: parent.hidden, locked: document.body.style.position === 'fixed' ||
          getComputedStyle(document.body).overflowY === 'hidden' ||
          getComputedStyle(document.documentElement).overflowY === 'hidden' });
      if (!state.stop) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }, selector);
}
async function stopTrace(page) {
  return page.evaluate(() => { window.__modalTrace.stop = true; return window.__modalTrace.frames; });
}
function assertExit(frames, message, minimumY) {
  const visible = frames.filter(frame => !frame.hidden && frame.height > 0);
  assert(visible.length > 1, message + ': sampled exit frames');
  if (minimumY !== undefined) assert(visible[0].y >= minimumY - 3, message + ': no snap back before exit');
  for (let index = 1; index < visible.length; index++) {
    assert(visible[index].y >= visible[index - 1].y - 2, message + ': exit moves down continuously');
  }
  assert(visible.every(frame => frame.locked), message + ': background stays locked until hidden');
}

async function run(name, engine) {
  const browser = await engine.launch({ headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 },
      isMobile: true, hasTouch: true, serviceWorkers: 'block' });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const { counts, gates } = await fixtures(page);
    await page.goto(base + '/', { waitUntil: 'networkidle' });
    await openCatalog(page);
    assert(parseFloat(await page.locator('#uModalSearchInput').evaluate(el => getComputedStyle(el).fontSize)) >= 16,
      'catalogue search avoids small input text on mobile');

    // Parent content must survive an entire nested product and shop visit.
    const trigger = page.locator('#catalogResults .u-item-title-link').nth(6);
    await trigger.scrollIntoViewIfNeeded();
    await trigger.focus();
    await page.evaluate(() => {
      window.__savedCatalogCard = document.querySelectorAll('#catalogResults .u-item-title-link')[6];
      window.__savedCatalogScroll = document.querySelector('#uModalBody').scrollTop;
    });
    const catalogCount = counts.catalog;
    let releaseProduct;
    gates.product = new Promise(resolve => { releaseProduct = resolve; });
    await trigger.tap();
    const productPanel = page.locator('#productDetailPanel');
    await productPanel.waitFor({ state: 'visible' });
    await page.waitForTimeout(300);
    const loadingHeight = (await productPanel.boundingBox()).height;
    releaseProduct(); gates.product = null;
    await page.waitForFunction(() => document.querySelector('#pDetailContent').style.display === 'block');
    await page.waitForTimeout(100);
    assert(Math.abs((await productPanel.boundingBox()).height - loadingHeight) <= 1,
      'product keeps its height when long details arrive');
    assert.equal(await page.locator('#universeModalPanel').evaluate(el => el.hidden), false, 'parent remains mounted and visible');
    assert.equal(await page.locator('#universeModalPanel').getAttribute('aria-hidden'), 'true');

    let releaseShop;
    gates.shop = new Promise(resolve => { releaseShop = resolve; });
    await page.locator('#pDetailShopBtn').tap();
    const shopPanel = page.locator('#shopDetailPanel');
    await shopPanel.waitFor({ state: 'visible' });
    await page.waitForTimeout(300);
    const shopLoadingHeight = (await shopPanel.boundingBox()).height;
    releaseShop(); gates.shop = null;
    await page.waitForFunction(() => document.querySelector('#shopDetailContent').style.display === 'block');
    assert(Math.abs((await shopPanel.boundingBox()).height - shopLoadingHeight) <= 1,
      'shop keeps its height when long details arrive');
    await trace(page, '#shopDetailPanel');
    await closeButton(page, '#shopDetailPanel', 'data-shop-close').tap();
    await hidden(page, '#shopDetailPanel');
    assertExit(await stopTrace(page), name + ' shop close');
    assert.equal(await productPanel.getAttribute('aria-hidden'), 'false');
    await page.waitForTimeout(80);

    const indexBefore = await page.evaluate(() => history.state.bmHub.index);
    await trace(page, '#productDetailPanel');
    await closeButton(page, '#productDetailPanel', 'data-pdetail-close').dblclick();
    await hidden(page, '#productDetailPanel');
    const productExit = await stopTrace(page);
    assertExit(productExit, name + ' nested product close');
    assert(productExit.filter(frame => !frame.hidden).every(frame => !frame.parentHidden), 'parent never disappears during child exit');
    assert.equal(await page.evaluate(() => history.state.bmHub.index), indexBefore - 1, 'double close consumes one history entry');
    assert.equal(await page.locator('#universeModalPanel').getAttribute('aria-hidden'), 'false');
    assert.equal(counts.catalog, catalogCount, 'back to unchanged catalogue does not reload it');
    assert.equal(await page.evaluate(() => window.__savedCatalogCard.isConnected &&
      window.__savedCatalogCard === document.querySelectorAll('#catalogResults .u-item-title-link')[6]), true,
      'back keeps the original catalogue DOM');
    assert(Math.abs(await page.locator('#uModalBody').evaluate(el => el.scrollTop) -
      await page.evaluate(() => window.__savedCatalogScroll)) <= 2, 'back restores catalogue scroll');
    assert.equal(await page.evaluate(() => document.activeElement === window.__savedCatalogCard), true,
      'back restores focus to the item that opened the detail');

    // True pointer gesture; dismiss must continue from the dragged position.
    const handle = page.locator('#universeModalPanel [data-sheet-drag]');
    let rect = await handle.boundingBox();
    await page.mouse.move(rect.x + rect.width / 2, rect.y + 12);
    await page.mouse.down();
    await page.mouse.move(rect.x + rect.width / 2, rect.y + 170, { steps: 8 });
    const draggedY = (await page.locator('#universeModalPanel').boundingBox()).y;
    await trace(page, '#universeModalPanel');
    await page.mouse.up();
    await hidden(page, '#universeModalPanel');
    assertExit(await stopTrace(page), name + ' swipe close', draggedY);

    await openCatalog(page);
    for (const cancelEvent of ['pointercancel', 'lostpointercapture']) {
      rect = await handle.boundingBox();
      await handle.evaluate(el => el.addEventListener('pointerdown', event => {
        window.__dragPointerId = event.pointerId;
      }, { once: true }));
      await page.mouse.move(rect.x + rect.width / 2, rect.y + 12);
      await page.mouse.down();
      await page.mouse.move(rect.x + rect.width / 2, rect.y + 70, { steps: 4 });
      const pointerId = await page.evaluate(() => window.__dragPointerId);
      await handle.dispatchEvent(cancelEvent, { pointerId, pointerType: 'mouse', isPrimary: true, button: 0 });
      await page.mouse.up();
      await page.waitForTimeout(300);
      assert.equal(await page.locator('#universeModalPanel').getAttribute('aria-hidden'), 'false', cancelEvent + ' leaves sheet open');
      assert.equal(await page.locator('#universeModalPanel').evaluate(el => el.style.transform), '', cancelEvent + ' clears drag transform');
      assert.equal(await page.locator('#universeModalPanel').evaluate(el => el.style.transition), '', cancelEvent + ' clears temporary transition');
    }

    // Native browser Back/Forward while an exit is still running cannot leave an old hide timer.
    await page.goBack();
    await page.goForward();
    await settled(page);
    await page.waitForTimeout(500);
    assert.equal(await page.locator('#universeModalPanel').evaluate(el => el.hidden), false, 'rapid history reopen survives old exit timer');
    assert.equal(await page.locator('#universeModalPanel').getAttribute('aria-hidden'), 'false');
    await closeButton(page, '#universeModalPanel', 'data-u-modal-close').tap();
    await hidden(page, '#universeModalPanel');

    // Lock a scrolled background using the real fixed mobile cart trigger.
    await page.evaluate(() => {
      const spacer = document.createElement('div'); spacer.style.height = '1800px';
      spacer.id = 'test-scroll-spacer'; document.body.appendChild(spacer);
      window.scrollTo({ top: 500, behavior: 'instant' });
    });
    await page.waitForFunction(() => Math.abs(scrollY - 500) < 2);
    await page.locator('.hub-bottom-nav [data-open-cart]').tap();
    await page.waitForTimeout(300);
    await trace(page, '#cartDrawerPanel');
    await closeButton(page, '#cartDrawerPanel', 'data-cart-close').tap();
    await hidden(page, '#cartDrawerPanel');
    assertExit(await stopTrace(page), name + ' cart close');
    await page.waitForFunction(() => Math.abs(scrollY - 500) < 2);
    assert.equal(await page.evaluate(() => document.body.style.position === 'fixed'), false, 'background releases after exit');

    // A controlled visualViewport covers keyboard/rotation layout without pretending to open an OS keyboard.
    const viewportPage = await context.newPage();
    viewportPage.on('pageerror', error => errors.push(error.message));
    await viewportPage.addInitScript(() => {
      const viewport = new EventTarget();
      let height = null;
      let width = null;
      Object.defineProperties(viewport, {
        height: { get: () => height === null ? innerHeight : height, set: value => { height = value; } },
        width: { get: () => width === null ? innerWidth : width, set: value => { width = value; } },
      });
      Object.assign(viewport, { offsetTop: 0, offsetLeft: 0, pageTop: 0, pageLeft: 0, scale: 1 });
      Object.defineProperty(window, 'visualViewport', { configurable: true, value: viewport });
    });
    await fixtures(viewportPage);
    await viewportPage.goto(base + '/', { waitUntil: 'networkidle' });
    await openCatalog(viewportPage);
    const beforeHeight = await viewportPage.evaluate(() => document.documentElement.style.getPropertyValue('--hub-visual-height'));
    await closeButton(viewportPage, '#universeModalPanel', 'data-u-modal-close').evaluate(el => {
      el.addEventListener('pointerdown', () => setTimeout(() => {
        visualViewport.height = 480;
        visualViewport.dispatchEvent(new Event('resize'));
        requestAnimationFrame(() => requestAnimationFrame(() => {
          window.__heightDuringExit = document.documentElement.style.getPropertyValue('--hub-visual-height');
        }));
      }, 30), { once: true });
    });
    await closeButton(viewportPage, '#universeModalPanel', 'data-u-modal-close').tap();
    await viewportPage.waitForFunction(() => !!window.__heightDuringExit);
    assert.equal(await viewportPage.evaluate(() => window.__heightDuringExit), beforeHeight,
      'viewport changes wait until exit transition finishes');
    await hidden(viewportPage, '#universeModalPanel');
    await viewportPage.waitForFunction(() => parseFloat(document.documentElement.style.getPropertyValue('--hub-visual-height')) === 480);
    await openCatalog(viewportPage);
    await viewportPage.locator('#uModalSearchInput').tap();
    const keyboardClose = closeButton(viewportPage, '#universeModalPanel', 'data-u-modal-close');
    const keyboardCloseRect = await keyboardClose.boundingBox();
    const touch = { pointerId: 991, pointerType: 'touch', isPrimary: true, button: 0,
      clientX: keyboardCloseRect.x + keyboardCloseRect.width / 2,
      clientY: keyboardCloseRect.y + keyboardCloseRect.height / 2 };
    await keyboardClose.dispatchEvent('pointerdown', touch);
    await viewportPage.evaluate(() => {
      visualViewport.height = 844;
      visualViewport.dispatchEvent(new Event('resize'));
    });
    await viewportPage.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert(Math.abs((await keyboardClose.boundingBox()).y - keyboardCloseRect.y) <= 1,
      'keyboard resize between touch down and up keeps the close target still');
    await keyboardClose.dispatchEvent('pointerup', touch);
    await hidden(viewportPage, '#universeModalPanel');
    assert.equal(await viewportPage.locator('#universeModalPanel').getAttribute('aria-hidden'), 'true', 'focused search closes with one tap');

    await viewportPage.locator('#homeSearchInput').fill('Article');
    await viewportPage.locator('#homeSearchInput').press('Enter');
    await viewportPage.waitForFunction(() => document.querySelector('#universeModalPanel').getAttribute('aria-hidden') === 'false');
    await settled(viewportPage);
    await viewportPage.waitForFunction(() => !document.querySelector('#universeModalPanel').classList.contains('is-opening'));
    await viewportPage.keyboard.press('Escape');
    await hidden(viewportPage, '#universeModalPanel');
    assert.equal(await viewportPage.locator('#homeSearchInput').evaluate(el => document.activeElement === el), true,
      'Enter then Escape restores the search input after an earlier touch dismissal');

    for (const viewport of [{ width: 844, height: 390 }, { width: 390, height: 844 }]) {
      await viewportPage.evaluate(viewport => Object.assign(visualViewport, viewport), viewport);
      await viewportPage.setViewportSize(viewport);
      await viewportPage.evaluate(() => visualViewport.dispatchEvent(new Event('resize')));
      await viewportPage.waitForTimeout(100);
      await openCatalog(viewportPage);
      const bounds = await viewportPage.locator('#universeModalPanel').boundingBox();
      assert(bounds.x >= -1 && bounds.y >= -1 && bounds.x + bounds.width <= viewport.width + 1 &&
        bounds.y + bounds.height <= viewport.height + 1, 'sheet fits after orientation change');
      await closeButton(viewportPage, '#universeModalPanel', 'data-u-modal-close').click();
      await hidden(viewportPage, '#universeModalPanel');
    }
    await viewportPage.emulateMedia({ reducedMotion: 'reduce' });
    await openCatalog(viewportPage);
    await closeButton(viewportPage, '#universeModalPanel', 'data-u-modal-close').tap();
    await viewportPage.waitForFunction(() => document.querySelector('#universeModalPanel').hidden, null, { timeout: 1000 });
    assert.deepEqual(errors, []);
    await context.close();
    console.log(name + ': stable loading/exit/drag/history/parent/focus/background/viewport/reduced-motion PASS');
  } finally { await browser.close(); }
}

(async () => { for (const [name, engine] of Object.entries({ chromium, webkit })) await run(name, engine); })()
  .catch(error => { console.error(error); process.exitCode = 1; });
