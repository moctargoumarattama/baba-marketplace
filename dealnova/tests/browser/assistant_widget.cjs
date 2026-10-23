/* Exercise the real widget assets with mocked API responses, without a database.
   PLAYWRIGHT_PACKAGE may point to an existing Playwright installation.
   Optional ASSISTANT_SCREENSHOT_DIR saves mobile and desktop component previews. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium, webkit } = require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');
const app = path.resolve(__dirname, '../../app');
const origin = 'https://assistant.test';
const menu = [
  { label: 'Trouver un produit', display_label: 'Produits', detail: 'Articles et repas', icon: 'bi-bag', action: 'find_products' },
  { label: 'Trouver un service', display_label: 'Services', detail: 'Tous les métiers', icon: 'bi-tools', action: 'find_services' },
  { label: 'Trouver une location', display_label: 'Locations', detail: 'Un lieu à louer', icon: 'bi-house-door', action: 'find_locations' },
  { label: 'Trouver une boutique', display_label: 'Boutiques', detail: 'Nos commerçants', icon: 'bi-shop', action: 'find_shops' },
  { label: 'Devenir vendeur', detail: 'Ma boutique', icon: 'bi-shop-window', action: 'become_vendor' },
  { label: 'Organiser une livraison', display_label: 'Livraison', detail: 'Envoyer un colis', icon: 'bi-box-seam', action: 'help_delivery' },
  { label: 'Contacter un conseiller', action: 'handoff' },
];
const welcome = {
  text: 'Bonjour ! Essayez « studio à Rabat » ou « coiffeur pas cher », ou choisissez ci-dessous.',
  quick_replies: menu,
  quick_layout: 'menu',
};

function documentFixture(inline) {
  let widget = fs.readFileSync(path.join(app, 'templates/partials/_assistant_widget.html'), 'utf8')
    .replace(/\{\{ url_for\('assistant_api.bootstrap'\) \}\}/g, '/api/assistant/bootstrap')
    .replace(/\{\{ url_for\('assistant_api.message'\) \}\}/g, '/api/assistant/message')
    .replace(/\{\{ \{'response': assistant_welcome\(\)\} \| tojson \}\}/g, JSON.stringify({ response: welcome }));
  if (!inline) widget = widget.replace(/<script type="application\/json" id="bmAssistantInitial">[^]*?<\/script>/, '');
  const styles = ['vendor/bootstrap/5.3.3/css/bootstrap.min.css',
    'vendor/bootstrap-icons/1.11.1/font/bootstrap-icons.css', 'fonts/public.css',
    'css/ui_shell.css', 'css/ui_home_single_hub.css', 'css/assistant/widget.css',
    'css/home_refresh.css'];
  return `<!doctype html><html lang="fr"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
    ${styles.map(file => `<link rel="stylesheet" href="/static/${file}">`).join('')}
    </head><body data-page="landing">
    <main style="height:1200px;padding:24px"><h1>Baba Market</h1></main>
    <nav class="hub-bottom-nav" data-home-bottom-tabs><a>Accueil</a><a>Explorer</a><a>Panier</a><a>Vendeur</a></nav>
    ${widget}<script src="/static/js/assistant/widget.js"></script></body></html>`;
}

async function fixture(context, { bootstrapDelay = 0, inline = true } = {}) {
  const page = await context.newPage();
  const errors = [];
  const requests = [];
  let bootstraps = 0;
  await page.addInitScript(() => {
    window.__pendingShows = 0;
    addEventListener('DOMContentLoaded', () => {
      const pending = document.querySelector('#bmAssistantPending');
      new MutationObserver(records => {
        for (const record of records) {
          if (record.attributeName === 'hidden' && !pending.hidden) window.__pendingShows += 1;
        }
      }).observe(pending, { attributes: true });
    });
  });
  page.on('pageerror', error => errors.push(error.message));
  await page.route(origin + '/**', async route => {
    const url = new URL(route.request().url());
    const reply = response => route.fulfill({ json: { ok: true, response } });
    if (url.pathname === '/api/assistant/bootstrap') {
      bootstraps += 1;
      if (bootstrapDelay) await new Promise(resolve => setTimeout(resolve, bootstrapDelay));
      return reply(welcome);
    }
    if (url.pathname === '/api/assistant/message') {
      const values = Object.fromEntries(url.searchParams);
      requests.push(values);
      if (values.message === 'réponse bloquée') return; // Simulate a server that never answers.
      if (values.message === 'réponse lente') {
        await new Promise(resolve => setTimeout(resolve, 550));
        return reply({ text: 'Voici les résultats.', quick_replies: [{ label: 'Menu principal', action: 'start' }] });
      }
      await new Promise(resolve => setTimeout(resolve, 180));
      if (values.message === 'panne réseau') return route.fulfill({ status: 503, body: 'unavailable' });
      if (values.action === 'find_products') return reply({ text: 'Quel produit recherchez-vous ?',
        quick_replies: [{ label: 'Épicerie', action: 'catalog_query', value: 'epicerie' }] });
      return reply({ text: 'Voici des offres pour vous.', items: Array.from({ length: 5 }, (_, index) => ({
        title: `Résultat ${index + 1} : ` + 'Une très longue description de produit '.repeat(5),
        subtitle: 'Disponible auprès de votre commerçant', meta: '120 DH',
        url: `/shop/product/${index + 1}`, cta: 'Voir les détails',
      })), more: { label: 'Voir tous les produits', url: '/produits?categorie=epicerie' },
        quick_replies: [...menu.slice(0, 3), { label: 'Menu principal', action: 'start' }] });
    }
    if (url.pathname.startsWith('/static/')) {
      const file = path.resolve(app, '.' + url.pathname);
      assert(file.startsWith(app + path.sep), 'Fixture assets must stay inside app');
      const ext = path.extname(file);
      const contentType = { '.css': 'text/css', '.js': 'text/javascript', '.woff2': 'font/woff2' }[ext];
      return route.fulfill({ body: fs.readFileSync(file), contentType: contentType || 'application/octet-stream' });
    }
    return route.fulfill({ contentType: 'text/html; charset=utf-8', body: documentFixture(inline) });
  });
  await page.goto(origin, { waitUntil: 'networkidle' });
  return { page, errors, requests, bootstraps: () => bootstraps };
}

async function settled(page) {
  await page.waitForFunction(() => document.querySelector('#bmAssistantMessages').getAttribute('aria-busy') === 'false');
}

async function insideViewport(page, height) {
  const bounds = await page.locator('#bmAssistantPanel').boundingBox();
  const width = await page.evaluate(() => innerWidth);
  assert(bounds && bounds.x >= 0 && bounds.x + bounds.width <= width + 1, 'Panel overflows horizontally');
  assert(bounds.y >= 0 && bounds.y + bounds.height <= height + 1,
    'Panel overflows the visible viewport: ' + JSON.stringify({ bounds, height,
      state: await page.evaluate(() => ({ classes: document.querySelector('#bmAssistant').className,
        width: innerWidth, height: innerHeight, visualHeight: visualViewport.height,
        visualTop: visualViewport.offsetTop, scrollY,
        root: document.querySelector('#bmAssistant').getBoundingClientRect().toJSON(),
        toggle: document.querySelector('#bmAssistantToggle').getBoundingClientRect().toJSON(),
        bottom: getComputedStyle(document.querySelector('#bmAssistant')).bottom,
        panelBottom: getComputedStyle(document.querySelector('#bmAssistantPanel')).bottom,
        mobileMedia: matchMedia('(max-width: 768px)').matches })) }));
  for (const selector of ['.bm-assistant-header', '.bm-assistant-content', '.bm-assistant-composer']) {
    assert(await page.locator(selector).evaluate(el => el.scrollWidth <= el.clientWidth + 1), selector + ' overflows');
  }
}

async function run(name, engine) {
  const browser = await engine.launch({ headless: true });
  try {
    for (const width of [320, 390, 768, 1440]) {
      const height = width === 320 ? 568 : 900;
      const mobile = width <= 768;
      const context = await browser.newContext({ viewport: { width, height },
        isMobile: mobile, hasTouch: mobile, reducedMotion: 'reduce', serviceWorkers: 'block' });
      const { page, errors, requests, bootstraps } = await fixture(context);
      const panel = page.locator('#bmAssistantPanel');
      assert.equal(await panel.isVisible(), false, 'Widget must start closed');
      await page.locator('#bmAssistantToggle').click();
      await settled(page);
      assert.equal(await panel.isVisible(), true);
      assert.equal(await page.locator('#bmAssistantInput').getAttribute('placeholder'), 'Décrivez ce que vous cherchez…');
      assert.equal(await page.locator('#bmAssistantQuick button').count(), 7);
      assert.equal(bootstraps(), 0, 'Inline welcome must render without any initialization request');
      assert.equal(await page.locator('#bmAssistantQuick').evaluate(el => el.classList.contains('is-menu')), true);
      assert.equal(await page.getByRole('button', { name: 'Trouver un produit', exact: true }).locator('.bm-assistant-option-text').textContent(), 'ProduitsArticles et repas');
      assert.equal(await page.locator('#bmAssistantQuick').isVisible(), true);
      const welcomeView = await page.locator('#bmAssistantContent').evaluate(content => {
        const welcome = content.querySelector('.bm-assistant-msg.bot').getBoundingClientRect();
        const bounds = content.getBoundingClientRect();
        return { top: welcome.top, bottom: welcome.bottom, contentTop: bounds.top, contentBottom: bounds.bottom };
      });
      assert(welcomeView.top >= welcomeView.contentTop && welcomeView.bottom <= welcomeView.contentBottom,
        'The welcome and its natural-language examples must be visible on opening');
      assert.equal(await page.evaluate(() => document.activeElement.id), mobile ? 'bmAssistantPanel' : 'bmAssistantInput');
      await insideViewport(page, height);
      const gap = await page.evaluate(() => {
        const message = document.querySelector('.bm-assistant-msg').getBoundingClientRect();
        return document.querySelector('#bmAssistantQuick').getBoundingClientRect().top - message.bottom;
      });
      assert(gap >= 0 && gap <= 20, 'Welcome and choices must stay together');
      if (process.env.ASSISTANT_SCREENSHOT_DIR && name === 'chromium' && [390, 1440].includes(width)) {
        fs.mkdirSync(process.env.ASSISTANT_SCREENSHOT_DIR, { recursive: true });
        await panel.screenshot({ path: path.join(process.env.ASSISTANT_SCREENSHOT_DIR, `assistant-${mobile ? 'mobile' : 'desktop'}.png`) });
      }
      for (let index = 0; index < 3; index += 1) {
        await page.locator('#bmAssistantClose').click();
        assert.equal(await panel.isVisible(), false);
        assert.equal(await page.evaluate(() => document.activeElement.id), 'bmAssistantToggle');
        await page.locator('#bmAssistantToggle').click();
        await settled(page);
      }
      assert.equal(bootstraps(), 0, 'Reopening must not fetch the welcome');
      assert.equal(await page.locator('.bm-assistant-msg.bot').count(), 1);
      await page.getByRole('button', { name: 'Trouver un produit', exact: true }).click();
      assert.equal(await page.locator('#bmAssistantPending').isVisible(), false, 'Fast responses must not flash a loading indicator');
      assert.equal(await page.locator('#bmAssistantSend').isDisabled(), true);
      await page.evaluate(() => document.querySelector('#bmAssistantForm').requestSubmit());
      await settled(page);
      assert.equal(requests.length, 1, 'Busy state prevents duplicate requests');
      assert.equal(requests[0].message, 'Trouver un produit', 'Presentation must preserve the original message');
      assert.equal(requests[0].action, 'find_products');
      assert.equal(requests[0].fresh, '1', 'First real message starts a clean backend conversation');
      assert.equal(await page.evaluate(() => window.__pendingShows), 0);
      const pageScrollBeforeResults = await page.evaluate(() => scrollY);
      await page.getByRole('button', { name: 'Épicerie', exact: true }).click();
      await settled(page);
      assert.equal(requests[1].value, 'epicerie');
      assert.equal(requests[1].fresh, undefined, 'Following messages keep the established conversation');
      assert.equal(await page.locator('.bm-assistant-card a').first().getAttribute('href'), '/shop/product/1');
      assert.equal(await page.locator('.bm-assistant-card').count(), 5);
      const resultsView = await page.evaluate(() => {
        const content = document.querySelector('#bmAssistantContent');
        const bounds = content.getBoundingClientRect();
        const responses = document.querySelectorAll('.bm-assistant-msg.bot');
        const answer = responses[responses.length - 1].getBoundingClientRect();
        const cards = document.querySelectorAll('.bm-assistant-card');
        return { answerTop: answer.top, contentTop: bounds.top,
          paddingTop: parseFloat(getComputedStyle(content).paddingTop),
          contentBottom: bounds.bottom, firstTop: cards[0].getBoundingClientRect().top,
          lastTop: cards[cards.length - 1].getBoundingClientRect().top };
      });
      assert(Math.abs(resultsView.answerTop - resultsView.contentTop - resultsView.paddingTop) <= 2,
        'A catalogue response must start at the top of the conversation');
      assert(resultsView.firstTop < resultsView.contentBottom, 'The first result must be visible immediately');
      assert(resultsView.lastTop > resultsView.contentBottom, 'Showing five results must not jump to the last one');
      assert.equal(await page.evaluate(() => scrollY), pageScrollBeforeResults,
        'Showing results must not scroll the surrounding page');
      assert.equal(await page.locator('.bm-assistant-more').getAttribute('href'), '/produits?categorie=epicerie');
      assert.equal(await page.locator('.bm-assistant-more').getAttribute('target'), null, 'Catalog links preserve ordinary same-page navigation');
      assert.equal(await page.locator('#bmAssistantQuick').evaluate(el => el.classList.contains('is-menu')), false,
        'Three catalog suggestions do not imply the main menu');
      assert.equal(await page.locator('.bm-assistant-quick-heading').count(), 0);
      assert.equal(await page.locator('.bm-assistant-option-icon').count(), 0);
      await insideViewport(page, height);
      await page.getByRole('button', { name: 'Menu principal', exact: true }).click();
      assert.equal(requests.length, 2, 'Returning to the menu must be immediate and local');
      assert.equal(await page.locator('.bm-assistant-msg.bot').count(), 1);
      assert.equal(await page.locator('#bmAssistantQuick button').count(), 7);
      assert.equal(await page.locator('#bmAssistantContent').evaluate(content => content.scrollTop), 0,
        'A local menu reset must show the welcome from the top');
      await page.locator('#bmAssistantInput').fill('panne réseau');
      await page.locator('#bmAssistantForm').evaluate(el => el.requestSubmit());
      await settled(page);
      assert.equal(await page.locator('#bmAssistantSend').isDisabled(), false);
      assert.equal(await page.locator('#bmAssistantQuick button').count(), 7, 'Failure must restore choices');
      assert.match(await page.locator('.bm-assistant-msg.bot').last().textContent(), /Impossible/);
      assert.equal(requests[2].fresh, '1', 'A local reset marks the next request as fresh');
      await page.getByRole('button', { name: 'Trouver un produit', exact: true }).click();
      await settled(page);
      assert.equal(requests[3].fresh, '1', 'A failed first request must retain the pending backend reset');
      await page.locator('#bmAssistantInput').fill('réponse lente');
      await page.locator('#bmAssistantForm').evaluate(el => el.requestSubmit());
      await page.locator('#bmAssistantPending').waitFor({ state: 'visible' });
      await settled(page);
      assert.equal(await page.locator('#bmAssistantPending').isVisible(), false);
      assert.equal(requests[4].fresh, undefined);
      if (mobile) {
        await page.evaluate(() => {
          window.__originalViewportDescriptor = Object.getOwnPropertyDescriptor(window, 'visualViewport');
          Object.defineProperty(window, 'visualViewport', { configurable: true, value: {
            width: innerWidth, height: 300, offsetTop: 0, offsetLeft: 0,
          } });
          window.dispatchEvent(new Event('resize'));
        });
        await insideViewport(page, 300);
        const composer = await page.locator('.bm-assistant-composer').boundingBox();
        assert(composer.y + composer.height <= 300, 'Composer stays above the simulated keyboard');
        await page.evaluate(() => {
          Object.defineProperty(window, 'visualViewport', window.__originalViewportDescriptor);
          window.dispatchEvent(new Event('resize'));
        });
        await page.setViewportSize({ width: 844, height: 390 });
        await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
        await insideViewport(page, 390);
      }
      await page.locator('#bmAssistantInput').focus();
      await page.keyboard.press('Escape');
      assert.equal(await panel.isVisible(), false);
      assert.equal(await page.evaluate(() => document.activeElement.id), 'bmAssistantToggle');
      assert.equal(await page.evaluate(() => document.body.style.overflow), '');
      assert.deepEqual(errors, []);
      await context.close();
      console.log(`${name} ${width}px: inline menu, contextual choices, fresh state, local reset, delayed spinner, errors, closing${mobile ? ', keyboard and rotation' : ''} OK`);
    }
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: 'reduce' });
    const { page, errors, bootstraps } = await fixture(context, { inline: false, bootstrapDelay: 350 });
    await page.locator('#bmAssistantToggle').click();
    await page.locator('#bmAssistantClose').click();
    await settled(page);
    assert.equal(await page.locator('#bmAssistantPanel').isVisible(), false);
    assert.equal(await page.evaluate(() => document.activeElement.id), 'bmAssistantToggle', 'Late response must not steal focus');
    assert.equal(bootstraps(), 1);
    assert.deepEqual(errors, []);
    await page.locator('#bmAssistantToggle').click();
    await settled(page);
    await page.clock.install();
    await page.locator('#bmAssistantInput').fill('réponse bloquée');
    await page.locator('#bmAssistantForm').evaluate(el => el.requestSubmit());
    assert.equal(await page.locator('#bmAssistantSend').isDisabled(), true);
    await page.clock.fastForward(25000);
    await settled(page);
    assert.equal(await page.locator('#bmAssistantSend').isDisabled(), false, 'A stalled response must not lock the composer');
    assert.equal(await page.locator('#bmAssistantQuick button').count(), 7);
    assert.match(await page.locator('.bm-assistant-msg.bot').last().textContent(), /Impossible/);
    assert.deepEqual(errors, []);
    await context.close();
    console.log(name + ': closing during initialization and stalled request recovery OK');
  } finally {
    await browser.close();
  }
}

(async () => { await run('chromium', chromium); await run('webkit', webkit); })()
  .catch(error => { console.error(error); process.exit(1); });
