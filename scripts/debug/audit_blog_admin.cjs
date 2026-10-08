const assert = require('node:assert/strict');
const { readFileSync, mkdirSync, writeFileSync } = require('node:fs');
const { join } = require('node:path');
const { parseEnv } = require('node:util');
const { promisify } = require('node:util');
const { execFile } = require('node:child_process');
const { chromium } = require('C:/Users/REDX420/Desktop/recetagenial/node_modules/playwright');

const live = process.argv.includes('--live');
const preview = process.argv.includes('--preview');
const readOnly = live || preview || process.argv.includes('--read-only');
const execFileAsync = promisify(execFile);
const reportDirectory = join(__dirname, '../../data/reports/design_audit/redesign-2026/admin');
const sites = [
  { name: 'RecetaGenial', root: 'C:/Users/REDX420/Desktop/recetagenial', origin: live ? 'https://recetagenial.com' : preview ? 'https://recetagenial-z2ve-git-codex-18659d-ridaelalaoui42-sys-projects.vercel.app' : 'http://127.0.0.1:3010', cookie: 'rg_admin_session', categories: 6, allowedCategories: ['Aperitivos', 'Arroces', 'Carnes', 'Pescados', 'Ensaladas', 'Postres'] },
  { name: 'RecetaDolce', root: 'C:/Users/REDX420/Desktop/recetadolce', origin: live ? 'https://recetadolce.com' : preview ? 'https://recetadolce-com-git-codex-vi-b11d64-ridaelalaoui42-sys-projects.vercel.app' : 'http://127.0.0.1:3011', cookie: 'rd_admin_session', categories: 4, allowedCategories: ['Fresas y Nata', 'Tartas y Pasteles', 'Chocolates', 'Dulces Saludables'] },
].filter((site) => !process.argv.some((argument) => argument.startsWith('--site=')) || process.argv.includes('--site=' + site.name.toLowerCase()));

async function login(page, site, password) {
  await page.waitForLoadState('load');
  await page.getByLabel('Contraseña', { exact: true }).fill(password);
  const [authentication] = await Promise.all([
    page.waitForResponse((response) => response.url().endsWith('/api/admin/auth') && response.request().method() === 'POST', { timeout: 60000 }),
    page.getByRole('button', { name: 'Entrar', exact: true }).click(),
  ]);
  return authentication;
}

async function read(page, path) {
  return page.evaluate(async (url) => {
    const response = await fetch(url);
    return { status: response.status, body: await response.json() };
  }, path);
}

async function previewCookies(site) {
  const { stdout } = await execFileAsync(process.execPath, [
    'C:/Users/REDX420/AppData/Roaming/npm/node_modules/vercel/dist/vc.js',
    'curl', '/admin/login', '--deployment', site.origin,
    '--', '-sS', '--max-time', '60', '-H', 'x-vercel-set-bypass-cookie:true', '-D', '-', '-o', 'NUL',
  ], { cwd: site.root, timeout: 120000 });
  const cookies = stdout.split(/\r?\n/).filter((line) => /^set-cookie:/i.test(line)).map((line) => {
    const pair = line.slice(line.indexOf(':') + 1).trim().split(';')[0];
    const equal = pair.indexOf('=');
    return { name: pair.slice(0, equal), value: pair.slice(equal + 1), url: site.origin, secure: true, httpOnly: true, sameSite: 'Lax' };
  });
  assert(cookies.length, site.name + ': protected preview did not provide an automation cookie');
  return cookies;
}

async function auditSite(browser, site) {
  const environment = parseEnv(readFileSync(join(site.root, '.env.local'), 'utf8'));
  const { resolveCategory } = require(join(site.root, 'lib/categories.ts'));
  assert(environment.ADMIN_PASSWORD, site.name + ': admin password is not configured locally');
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  context.setDefaultTimeout(60000);
  context.setDefaultNavigationTimeout(120000);
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const result = { site: site.name, origin: site.origin, checks: {}, errors };
  let draftId;

  try {
    console.log(site.name + ': checking authentication');
    const bypassCookies = preview ? await previewCookies(site) : [];
    if (bypassCookies.length) await context.addCookies(bypassCookies);
    for (const path of ['/api/admin/settings', '/api/admin/posts', '/api/admin/newsletter/send', '/api/admin/seo/audit']) {
      const response = await context.request.get(site.origin + path);
      assert.equal(response.status(), 401, site.name + ': anonymous private API must reject access');
    }
    result.checks.anonymousApis = true;
    await context.addCookies([{ name: site.cookie, value: 'authenticated', url: site.origin }]);
    await page.goto(site.origin + '/admin', { waitUntil: 'domcontentloaded' });
    assert.equal(new URL(page.url()).pathname, '/admin/login', site.name + ': forged cookie must be rejected');
    await context.clearCookies();
    if (bypassCookies.length) await context.addCookies(bypassCookies);
    result.checks.forgedCookie = true;

    await page.goto(site.origin + '/admin/settings', { waitUntil: 'domcontentloaded' });
    assert.equal(new URL(page.url()).pathname, '/admin/login');
    if (!readOnly) {
      const badLogin = await login(page, site, 'invalid-admin-audit-' + Date.now());
      assert.equal(badLogin.status(), 401);
      await page.getByRole('alert').filter({ hasText: 'Contraseña incorrecta' }).waitFor();
      result.checks.incorrectPassword = true;
    }
    const authentication = await login(page, site, environment.ADMIN_PASSWORD);
    result.loginStatus = authentication.status();
    if (authentication.status() !== 200) {
      result.checks.login = false;
      return result;
    }
    await page.waitForURL((url) => url.pathname === '/admin/settings', { timeout: 15000 });
    await page.getByRole('heading', { name: 'Ajustes del Sistema', exact: true }).waitFor();
    result.checks.loginAndReturnPath = true;

    const settings = await read(page, '/api/admin/settings');
    const posts = await read(page, '/api/admin/posts');
    const subscribers = await read(page, '/api/admin/newsletter/send');
    const audit = await read(page, '/api/admin/seo/audit');
    for (const response of [settings, posts, subscribers, audit]) assert.equal(response.status, 200);
    assert.equal(settings.body.site_name, site.name);
    assert(Array.isArray(posts.body) && posts.body.length > 0);
    assert(Array.isArray(subscribers.body.subscribers));
    assert(Array.isArray(audit.body) && audit.body.length > 0);
    result.checks.authenticatedReads = true;
    console.log(site.name + ': authenticated API reads passed');
    result.recipeCount = posts.body.length;
    result.publishedCount = posts.body.filter((post) => post.status === 'published').length;
    result.draftCount = posts.body.filter((post) => post.status === 'draft').length;
    result.invalidPublishedCategories = posts.body.filter((post) => post.status === 'published' && !resolveCategory(post.category)).length;
    assert.equal(result.invalidPublishedCategories, 0, site.name + ': published category mismatch');
    result.checks.publishedCategoryAssignments = true;
    result.subscriberCount = subscribers.body.total;

    await page.goto(site.origin + '/admin');
    await page.getByRole('heading', { name: 'Panel Editorial', exact: true }).waitFor();
    assert.equal(await page.locator('tbody tr').count(), posts.body.length);
    assert.equal((await page.getByText('Categorías', { exact: true }).locator('..').innerText()).trim().split(/\s+/).at(-1), String(site.categories));
    assert.equal(await page.getByRole('complementary', { name: 'Preferencias de cookies' }).count(), 0);
    await page.screenshot({ path: join(reportDirectory, site.name.toLowerCase() + '-dashboard.png') });
    const existingPost = posts.body.find((post) => post.status === 'published' && post.recipe_schema);
    assert(existingPost, site.name + ': no published recipe available to check');
    await page.goto(site.origin + '/admin/edit/' + existingPost.id);
    await page.getByRole('heading', { name: 'Editar Receta', exact: true }).waitFor();
    assert((await page.locator('#title').inputValue()).length > 0);
    assert((await page.locator('#recipe_schema').inputValue()).length > 0);
    result.checks.dashboardAndExistingEditor = true;

    if (!readOnly) {
      console.log(site.name + ': checking temporary draft workflow');
      await page.goto(site.origin + '/admin/new');
      assert.equal(await page.locator('#category option').count(), site.categories);
      const title = 'Verificacion temporal del panel ' + site.name + ' ' + Date.now();
      await page.locator('#title').fill(title);
      await page.locator('#excerpt').fill('Registro temporal de verificacion del editor.');
      await page.locator('#content').fill('Registro temporal de verificacion. Se elimina al terminar la comprobacion.');
      const [response] = await Promise.all([
        page.waitForResponse((response) => response.url().endsWith('/api/admin/posts') && response.request().method() === 'POST'),
        page.getByRole('button', { name: 'Guardar borrador', exact: true }).click(),
      ]);
      assert.equal(response.status(), 201, site.name + ': draft creation failed');
      draftId = (await response.json()).data.id;
      await page.waitForURL((url) => url.pathname === '/admin');
      await page.goto(site.origin + '/admin/edit/' + draftId);
      const updatedTitle = title + ' editado';
      await page.locator('#title').fill(updatedTitle);
      const [updated] = await Promise.all([
        page.waitForResponse((r) => r.url().endsWith('/api/admin/posts/' + draftId) && r.request().method() === 'PATCH'),
        page.getByRole('button', { name: 'Guardar Cambios', exact: true }).click(),
      ]);
      assert.equal(updated.status(), 200);
      await page.waitForURL((url) => url.pathname === '/admin');
      const stored = await read(page, '/api/admin/posts');
      assert(stored.body.some((post) => post.id === draftId && post.title === updatedTitle && post.status === 'draft'));
      page.once('dialog', (dialog) => dialog.accept());
      const [deleted] = await Promise.all([
        page.waitForResponse((r) => r.url().endsWith('/api/admin/posts/' + draftId) && r.request().method() === 'DELETE'),
        page.locator('tbody tr').filter({ hasText: updatedTitle }).getByRole('button', { name: 'Eliminar', exact: true }).click(),
      ]);
      assert.equal(deleted.status(), 200);
      const remaining = await read(page, '/api/admin/posts');
      assert(!remaining.body.some((post) => post.id === draftId));
      draftId = undefined;
      result.checks.draftCreateEditDelete = true;

      await page.goto(site.origin + '/admin/new');
      await page.locator('#title').fill('Verificacion de validacion sin publicar');
      await page.locator('#content').fill('Datos temporales para comprobar la validacion de publicacion.');
      await page.locator('#featured_image').fill(site.origin + '/og-image.jpg');
      await page.locator('#status').selectOption('published');
      const [rejected] = await Promise.all([
        page.waitForResponse((r) => r.url().endsWith('/api/admin/posts') && r.request().method() === 'POST'),
        page.getByRole('button', { name: 'Publicar Receta', exact: true }).click(),
      ]);
      assert.equal(rejected.status(), 422);
      await page.getByRole('alert').filter({ hasText: 'Añade los datos de la receta' }).waitFor();
      result.checks.incompletePublicationBlocked = true;

      await page.goto(site.origin + '/admin/settings');
      await page.getByRole('heading', { name: 'Ajustes del Sistema', exact: true }).waitFor();
      page.once('dialog', (dialog) => dialog.accept());
      const [saved] = await Promise.all([
        page.waitForResponse((r) => r.url().endsWith('/api/admin/settings') && r.request().method() === 'POST'),
        page.getByRole('button', { name: 'Guardar Configuración', exact: true }).click(),
      ]);
      assert.equal(saved.status(), 200, site.name + ': unchanged settings save failed');
      const after = await read(page, '/api/admin/settings');
      for (const key of Object.keys(settings.body).filter((key) => !['created_at', 'updated_at'].includes(key))) {
        assert.deepEqual(after.body[key], settings.body[key], site.name + ': settings save changed ' + key);
      }
      result.checks.settingsSave = true;
    }

    await page.goto(site.origin + '/admin/newsletter');
    await page.getByRole('heading', { name: 'Boletín y suscriptores' }).waitFor();
    await page.locator('table').waitFor();
    if (subscribers.body.total > 0) {
      const [download] = await Promise.all([
        page.waitForEvent('download'),
        page.getByRole('button', { name: /Exportar (CSV|página)/ }).click(),
      ]);
      assert.equal(download.suggestedFilename(), 'suscriptores.csv');
      result.checks.newsletterCsv = true;
    }
    await page.getByLabel('Buscar por email').fill('admin-audit-no-match-' + Date.now());
    await page.getByText('No hay coincidencias.', { exact: true }).waitFor();
    result.checks.newsletterSearch = true;
    await page.goto(site.origin + '/admin/seo-audit');
    await page.locator('a[aria-label^="Editar "]').first().waitFor();
    assert((await page.locator('a[aria-label^="Editar "]').first().getAttribute('href')).startsWith('/admin/edit/'));
    assert(!((await page.locator('a[aria-label^="Ver "]').first().getAttribute('href')).startsWith('/recetas/')));
    result.checks.seoAuditAndLinks = true;
    console.log(site.name + ': editorial workflows passed; checking responsive layouts');

    await page.route('**/api/admin/settings', (route) => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'Temporary verification failure' }) }));
    await page.goto(site.origin + '/admin/settings');
    await page.getByRole('alert').filter({ hasText: 'No se pudo cargar la configuración' }).waitFor();
    assert(await page.getByRole('button', { name: 'Guardar Configuración', exact: true }).isDisabled());
    await page.unroute('**/api/admin/settings');
    await page.route('**/api/admin/seo/audit', (route) => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'Temporary verification failure' }) }));
    await page.goto(site.origin + '/admin/seo-audit');
    await page.getByRole('alert').filter({ hasText: 'No se pudo cargar la auditoría' }).waitFor();
    await page.unroute('**/api/admin/seo/audit');
    await page.route('**/api/admin/newsletter/send*', (route) => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'Temporary verification failure' }) }));
    await page.goto(site.origin + '/admin/newsletter');
    await page.getByRole('alert').filter({ hasText: 'No se pudieron cargar los suscriptores' }).waitFor();
    await page.unroute('**/api/admin/newsletter/send*');
    result.checks.apiFailureStates = true;

    if (!live) {
      const failures = [];
      for (const width of [320, 390]) {
        await page.setViewportSize({ width, height: 844 });
        for (const route of ['/admin', '/admin/new', '/admin/settings', '/admin/newsletter', '/admin/seo-audit']) {
          await page.goto(site.origin + route);
          await page.waitForTimeout(600);
          const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
          if (overflow > 1) failures.push({ route, width, overflow });
          assert.equal(await page.getByRole('complementary', { name: 'Preferencias de cookies' }).count(), 0);
        }
        await page.goto(site.origin + '/admin/settings');
        await page.getByRole('heading', { name: 'Ajustes del Sistema', exact: true }).waitFor();
        for (const tab of ['Categorías', 'Social', 'Analíticas', 'Código', 'Navegación', 'Anuncios', 'Herramientas SEO']) {
          await page.getByRole('button', { name: tab, exact: true }).click();
          const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
          if (overflow > 1) failures.push({ route: '/admin/settings', tab, width, overflow });
        }
      }
      result.mobileOverflow = failures;
      assert.equal(failures.length, 0, site.name + ': mobile admin overflow ' + JSON.stringify(failures));
      result.checks.mobileLayouts = true;
    }

    await page.goto(site.origin + '/admin');
    page.once('dialog', (dialog) => dialog.accept());
    await page.getByRole('button', { name: 'Cerrar Sesión', exact: true }).click();
    await page.waitForURL((url) => url.pathname === '/');
    await page.goto(site.origin + '/admin/new');
    assert.equal(new URL(page.url()).pathname, '/admin/login');
    result.checks.logout = true;
    assert.equal(errors.length, 0, site.name + ': browser runtime error');
    result.passed = true;
    return result;
  } catch (error) {
    result.failure = error.message;
    result.failurePath = new URL(page.url()).pathname;
    result.alerts = await page.getByRole('alert').allTextContents();
    result.passed = false;
    return result;
  } finally {
    if (draftId) {
      const response = await page.evaluate(async (id) => (await fetch('/api/admin/posts/' + id, { method: 'DELETE' })).status, draftId);
      result.draftCleanupStatus = response;
    }
    await context.close();
  }
}

async function auditSharedSessions(browser) {
  const context = await browser.newContext();
  try {
    for (const site of sites) {
      const environment = parseEnv(readFileSync(join(site.root, '.env.local'), 'utf8'));
      const response = await context.request.post(site.origin + '/api/admin/auth', { data: { password: environment.ADMIN_PASSWORD } });
      assert.equal(response.status(), 200);
    }
    for (const site of sites) assert.equal((await context.request.get(site.origin + '/api/admin/settings')).status(), 200);
    await context.request.delete(sites[0].origin + '/api/admin/auth');
    assert.equal((await context.request.get(sites[0].origin + '/api/admin/settings')).status(), 401);
    assert.equal((await context.request.get(sites[1].origin + '/api/admin/settings')).status(), 200);
    return { passed: true, separateSessions: true, independentLogout: true };
  } finally {
    await context.close();
  }
}

(async () => {
  mkdirSync(reportDirectory, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const results = [];
  let sharedSessions;
  try {
    for (const site of sites) {
      const result = await auditSite(browser, site);
      results.push(result);
      console.log(JSON.stringify(result));
    }
    if (!preview && !live && sites.length === 2) sharedSessions = await auditSharedSessions(browser);
  } finally {
    await browser.close();
  }
  const mode = live ? 'live' : preview ? 'preview' : 'local';
  const suffix = sites.length === 1 ? '-' + sites[0].name.toLowerCase() : '';
  const file = join(reportDirectory, 'admin-audit-' + mode + suffix + '.json');
  writeFileSync(file, JSON.stringify({ timestamp: new Date().toISOString(), readOnly, results, sharedSessions }, null, 2));
  if (results.some((result) => !result.passed)) process.exitCode = 1;
})().catch((error) => { console.error(error.message); process.exitCode = 1; });
