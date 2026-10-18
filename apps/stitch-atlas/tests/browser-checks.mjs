/** Optional Playwright smoke suite: run with STITCH_ATLAS_BASE_URL after the site starts. */
import assert from 'node:assert/strict';
let playwright;
try { playwright=await import('@playwright/test'); } catch {console.log('Playwright not installed; see staging CI for full browser audit');process.exit(0)}
const browser=await playwright.chromium.launch({headless:true});
try{
 for(const width of [360,390,768,1024,1440]){
  const page=await browser.newPage({viewport:{width,height:900},reducedMotion:'reduce'});
  const failures=[];page.on('pageerror',e=>failures.push(e.message));
  const response=await page.goto(process.env.STITCH_ATLAS_BASE_URL||'http://localhost:3000',{waitUntil:'networkidle'});
  assert.equal(response.status(),200,`Homepage HTTP response at ${width}`);
  assert.equal(await page.locator('h1').count(),1,'Exactly one homepage H1');
  const documentWidth=await page.evaluate(()=>document.documentElement.scrollWidth-window.innerWidth);
  assert(documentWidth<=1,`Horizontal overflow ${documentWidth}px at ${width}`);
  if(width<1024){const button=page.getByRole('button',{name:'Open navigation'});await button.click();assert.equal(await page.getByRole('navigation',{name:'Main navigation'}).isVisible(),true);await page.keyboard.press('Escape')}
  assert.equal(failures.length,0,JSON.stringify(failures));
  await page.goto((process.env.STITCH_ATLAS_BASE_URL||'http://localhost:3000')+'/patterns',{waitUntil:'domcontentloaded'});
  await page.locator('#search-topics').fill('moss');assert.equal(await page.locator('.topic-card').count(),1);
  await page.goto((process.env.STITCH_ATLAS_BASE_URL||'http://localhost:3000')+'/tools',{waitUntil:'domcontentloaded'});
  await page.getByRole('button',{name:'Increase row count'}).click();assert.equal(await page.locator('#counter-output').textContent(),'1');
  assert.equal(await page.locator('[data-testid="yarn-estimate"]').textContent(),'159 g');
  assert.equal(await page.locator('[data-testid="repeat-estimate"]').textContent(),'80 or 86 stitches');
  await page.getByLabel('Your approximate target').fill('80');
  assert.equal(await page.locator('[data-testid="repeat-estimate"]').textContent(),'80 stitches');
  await page.getByLabel('Your approximate target').fill('1');
  assert.equal(await page.locator('[data-testid="repeat-estimate"]').textContent(),'8 stitches');
  // With no database, the studio remains a browser-local, never-published workbench.
  const studio=await page.goto((process.env.STITCH_ATLAS_BASE_URL||'http://localhost:3000')+'/studio',{waitUntil:'domcontentloaded'});
  assert.equal(studio.status(),200);
  await page.getByTestId('offline-studio').waitFor();
  await page.getByText('Publishing is locked').waitFor();
  assert.equal(await page.getByRole('button',{name:/^publish/i}).count(),0,'No browser-local publish action');
  const slug='original-yarn-note-'+width;
  await page.getByLabel('Working headline').fill('A thoughtful original crochet yarn note');
  await page.getByLabel('URL slug').fill(slug);
  await page.getByLabel('Editorial summary').fill('An original tutorial draft about keeping accurate crochet row counts and interpreting turning chains for new crocheters.');
  await page.getByRole('button',{name:'Save local draft'}).click();
  await page.getByText('Draft saved in this browser only.',{exact:false}).waitFor();
  await page.reload({waitUntil:'domcontentloaded'});
  await page.getByTestId('offline-studio').waitFor();
  await page.getByRole('button',{name:/A thoughtful original crochet yarn note/}).click();
  assert.equal(await page.getByLabel('URL slug').inputValue(),slug);
  await page.getByRole('button',{name:'Private reading preview'}).click();
  await page.getByText('UNPUBLISHED DRAFT / LOCAL PREVIEW').waitFor();
  assert.equal(await page.getByRole('button',{name:/^publish/i}).count(),0);
  const overflowStudio=await page.evaluate(()=>document.documentElement.scrollWidth-window.innerWidth);
  assert(overflowStudio<=1,`Studio horizontal overflow ${overflowStudio}px at ${width}`);
  const unpublished=await page.goto((process.env.STITCH_ATLAS_BASE_URL||'http://localhost:3000')+'/patterns/untested-celtic-bag',{waitUntil:'domcontentloaded'});
  assert.equal(unpublished.status(),404,'No unpublished fake patterns may be publicly available');
  await page.close();
 }
 console.log('Stitch Atlas cross-viewport browser checks passed.');
}finally{await browser.close()}
