const assert = require('node:assert/strict');
const { writeFileSync, mkdirSync } = require('node:fs');
const { join } = require('node:path');
const { chromium } = require('C:/Users/REDX420/Desktop/recetagenial/node_modules/playwright');
const { sites, previewCookies, reportDirectory } = require('./audit_blog_admin.cjs');

async function audit(browser, site) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  context.setDefaultTimeout(60000);
  context.setDefaultNavigationTimeout(120000);
  const page = await context.newPage();
  const result = { site: site.name, origin: site.origin, routes: [], errors: [], hydrationErrors: [] };
  page.on('pageerror', (error) => result.errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error' && /hydrat|did not match|server rendered/i.test(message.text())) {
      result.hydrationErrors.push(message.text());
    }
  });
  try {
    await context.addCookies(await previewCookies(site));
    await context.addCookies([{ name: site.name === 'RecetaGenial' ? 'rg_cookie_consent' : 'rd_cookie_consent', value: 'true', url: site.origin }]);
    const category = site.name === 'RecetaGenial' ? 'arroces' : 'dulces-saludables';
    const publicOrigin = site.name === 'RecetaGenial' ? 'https://recetagenial.com' : 'https://recetadolce.com';
    const author = site.name === 'RecetaGenial' ? '/author/equipo-editorial' : '/author/atelier-editorial';
    await page.goto(site.origin + '/categoria/' + category);
    const recipe = await page.locator('#main-content article a[href]').first().getAttribute('href');
    assert(recipe && recipe.startsWith('/'), site.name + ': no category recipe link');
    const paths = ['/', '/categoria/' + category, '/search?q=chocolate', '/about', author, '/contact', '/privacy', '/terms', '/cookies', '/favorites', '/shopping-list', recipe];
    for (const path of paths) {
      const response = await page.goto(site.origin + path, { waitUntil: 'domcontentloaded' });
      assert.equal(response.status(), 200, site.name + ': public route failed ' + path);
      await page.locator('h1').first().waitFor();
      const metadata = await page.evaluate(() => ({
        title: document.title,
        description: document.querySelector('meta[name="description"]')?.getAttribute('content'),
        canonical: document.querySelector('link[rel="canonical"]')?.getAttribute('href'),
        overflow: document.documentElement.scrollWidth - window.innerWidth,
      }));
      assert(metadata.title && metadata.description, site.name + ': incomplete metadata ' + path);
      assert.equal(metadata.overflow, 0, site.name + ': public desktop overflow ' + path);
      if (metadata.canonical) assert.equal(new URL(metadata.canonical).origin, publicOrigin, site.name + ': wrong canonical origin');
      result.routes.push({ path, status: response.status(), ...metadata });
    }
    const schemas = await page.locator('script[type="application/ld+json"]').evaluateAll((scripts) => scripts.flatMap((script) => {
      const parsed = JSON.parse(script.textContent || 'null');
      return Array.isArray(parsed) ? parsed : parsed?.['@graph'] || [parsed];
    }));
    const recipeSchema = schemas.find((schema) => schema && (schema['@type'] === 'Recipe' || schema['@type']?.includes?.('Recipe')));
    assert(recipeSchema && recipeSchema.name && recipeSchema.recipeIngredient?.length && recipeSchema.recipeInstructions?.length, site.name + ': incomplete representative recipe schema');
    result.recipeSchema = { name: recipeSchema.name, ingredients: recipeSchema.recipeIngredient.length, steps: recipeSchema.recipeInstructions.length };
    const sitemap = await context.request.get(site.origin + '/sitemap.xml');
    assert.equal(sitemap.status(), 200);
    const locations = await page.evaluate((xml) => {
      const document = new DOMParser().parseFromString(xml, 'application/xml');
      if (document.querySelector('parsererror')) throw new Error('Invalid sitemap XML');
      return Array.from(document.getElementsByTagName('loc'), (node) => node.textContent);
    }, await sitemap.text());
    assert(locations.length > 10 && locations.every((url) => url && new URL(url).origin === publicOrigin), site.name + ': sitemap origin or entries failed');
    result.sitemapEntries = locations.length;
    const robots = await context.request.get(site.origin + '/robots.txt');
    assert.equal(robots.status(), 200);
    assert((await robots.text()).includes('/admin'));
    result.robots = true;
    const favicon = await page.locator('link[rel~="icon"]').first().getAttribute('href');
    assert(favicon, site.name + ': favicon metadata missing');
    assert.equal((await context.request.get(new URL(favicon, site.origin).href)).status(), 200);
    result.favicon = true;
    const redirect = await context.request.get(site.origin + '/sobre-nosotros', { maxRedirects: 0 });
    assert([301, 308].includes(redirect.status()));
    assert.equal(new URL(redirect.headers().location, site.origin).pathname, '/about');
    result.legacyRedirect = true;
    await page.goto(site.origin + '/');
    const firstImage = page.locator('img').first();
    await firstImage.waitFor();
    await firstImage.evaluate((image) => image.decode());
    const brokenImages = await page.locator('img').evaluateAll((images) => images.filter((image) => image.complete && image.naturalWidth === 0).map((image) => image.getAttribute('src')));
    assert.deepEqual(brokenImages, []);
    result.homepageImages = true;
    await page.screenshot({ path: join(reportDirectory, site.name.toLowerCase() + '-preview-home.png') });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(site.origin + '/');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth), 0);
    await page.screenshot({ path: join(reportDirectory, site.name.toLowerCase() + '-preview-mobile.png') });
    result.mobileHomepage = true;
    const missing = await page.goto(site.origin + '/admin-audit-public-missing-route');
    assert([200, 404].includes(missing.status()));
    await page.getByText(/no encontr|perdid|404/i).first().waitFor();
    await page.locator('meta[name="robots"][content*="noindex"]').first().waitFor({ state: 'attached' });
    result.notFoundStatus = missing.status();
    result.notFoundNoindex = true;
    result.notFound = true;
    assert.deepEqual(result.errors, []);
    assert.deepEqual(result.hydrationErrors, []);
    result.passed = true;
  } catch (error) {
    result.failure = error.message;
    result.failurePath = new URL(page.url()).pathname;
    result.passed = false;
  } finally {
    await context.close();
  }
  return result;
}

(async () => {
  mkdirSync(reportDirectory, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const results = [];
  try {
    for (const site of sites) {
      const result = await audit(browser, site);
      results.push(result);
      console.log(JSON.stringify(result));
    }
  } finally {
    await browser.close();
  }
  writeFileSync(join(reportDirectory, 'public-preview-audit.json'), JSON.stringify({ timestamp: new Date().toISOString(), results }, null, 2));
  if (results.some((result) => !result.passed)) process.exitCode = 1;
})().catch((error) => { console.error(error.message); process.exitCode = 1; });
