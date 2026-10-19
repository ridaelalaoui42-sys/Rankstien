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
  const guides=await page.goto((process.env.STITCH_ATLAS_BASE_URL||'http://localhost:3000')+'/guides',{waitUntil:'domcontentloaded'});
  assert.equal(guides.status(),200,'Guide library must be accessible');
  assert.equal(await page.locator('.guide-card').count(),12);
  await page.getByLabel('Find a guide').fill('US vs UK');
  assert.equal(await page.locator('.guide-card').count(),1,'US/UK guide search should match exactly once');
  await page.locator('.guide-card').first().click();
  await page.getByRole('heading',{level:1,name:/US vs UK crochet terms/}).waitFor();
  assert.equal(await page.locator('.guide-body-section').count(),5);
  assert.equal(await page.locator('.guide-table-wrap tbody tr').count(),6);
  assert.equal(await page.locator('.guide-related .guide-card').count(),3);
  const guideOverflow=await page.evaluate(()=>document.documentElement.scrollWidth-window.innerWidth);
  assert(guideOverflow<=1,`Guide horizontal overflow ${guideOverflow}px at ${width}`);
  const gauge=await page.goto((process.env.STITCH_ATLAS_BASE_URL||'http://localhost:3000')+'/guides/how-to-measure-crochet-gauge',{waitUntil:'domcontentloaded'});
  assert.equal(gauge.status(),200);
  assert.equal(await page.locator('h1').count(),1);
  assert.equal((await page.locator('meta[name="robots"]').getAttribute('content')).includes('noindex'),true);
  assert.equal(await page.locator('script[type="application/ld+json"]').count(),0,'Stage must not emit live Article schema');
  const missingGuide=await page.goto((process.env.STITCH_ATLAS_BASE_URL||'http://localhost:3000')+'/guides/fictional-tested-bag',{waitUntil:'domcontentloaded'});
  assert.equal(missingGuide.status(),404,'Unknown guide must never return a fake content page');
  // Academy: lesson paths, visual quiz grading, progress persistence and badges.
  const academy=await page.goto((process.env.STITCH_ATLAS_BASE_URL||'http://localhost:3000')+'/academy',{waitUntil:'domcontentloaded'});
  assert.equal(academy.status(),200);
  assert.equal(await page.locator('.academy-path-card').count(),3,'Three academy journeys available');
  await page.locator('.academy-path-card').first().getByRole('link',{name:/Explore the journey/}).click();
  // Next.js client navigation is asynchronous; wait for the destination and its content.
  await page.waitForURL(/\/academy\/first-stitches(?:[/?#]|$)/);
  await page.locator('.academy-route-step').first().waitFor({state:'visible'});
  assert.equal(await page.locator('.academy-route-step').count(),4,'All four learning steps should render');
  await page.getByRole('link',{name:/Start lesson/}).first().click();
  await page.locator('.academy-quiz-fieldset').waitFor();
  await page.locator('.academy-quiz-option').nth(0).click();
  await page.getByRole('button',{name:/Check my answer/}).click();
  await page.locator('.academy-answer-note').waitFor();
  await page.getByRole('button',{name:/Next question/}).click();
  await page.locator('.academy-quiz-option').nth(1).click();
  await page.getByRole('button',{name:/Check my answer/}).click();
  await page.getByRole('button',{name:/Next question/}).click();
  await page.locator('.academy-quiz-option').nth(1).click();
  await page.getByRole('button',{name:/Check my answer/}).click();
  await page.getByRole('button',{name:/Finish checkpoint/}).click();
  await page.getByTestId('academy-result').getByText('3/3 answers right').waitFor();
  await page.goto((process.env.STITCH_ATLAS_BASE_URL||'http://localhost:3000')+'/academy',{waitUntil:'domcontentloaded'});
  assert.match(await page.getByTestId('academy-completed').textContent(),/1\/12/);
  assert.equal(await page.getByTestId('academy-xp').textContent(),'75');
  assert.equal(await page.locator('.academy-badge.academy-earned').count(),2,'First Loop + Perfect Swatch');
  await page.reload({waitUntil:'domcontentloaded'});
  assert.match(await page.getByTestId('academy-completed').textContent(),/1\/12/);
  const overflowAcademy=await page.evaluate(()=>document.documentElement.scrollWidth-window.innerWidth);
  assert(overflowAcademy<=1,`Academy horizontal overflow ${overflowAcademy}px at ${width}`);
  const missingPath=await page.goto((process.env.STITCH_ATLAS_BASE_URL||'http://localhost:3000')+'/academy/not-real',{waitUntil:'domcontentloaded'});
  assert.equal(missingPath.status(),404);
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
