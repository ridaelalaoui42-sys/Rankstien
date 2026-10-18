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
  await page.close();
 }
 console.log('Stitch Atlas cross-viewport browser checks passed.');
}finally{await browser.close()}
