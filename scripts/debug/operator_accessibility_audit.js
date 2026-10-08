async (page) => {
  await page.route('**/operator-assets/axe-audit.js', route => route.fulfill({
    path:'C:/Users/REDX420/Desktop/recetagenial/node_modules/axe-core/axe.min.js',
    contentType:'application/javascript',
  }));
  await page.addScriptTag({url:'/operator-assets/axe-audit.js'});
  const results = [];
  for (const width of [1440,390]) {
    await page.setViewportSize({width,height:width === 390 ? 844 : 1000});
    for (const view of ['overview','workflows','history','pinterest','keywords','recipes','services','logs']) {
      if (width === 390) await page.locator('#menu').click();
      await page.locator(`nav [data-view="${view}"]`).click();
      await page.waitForFunction(view => !document.querySelector(`#view-${view}`).innerText.includes('Loading...'), view, {timeout:20000});
      const audit = await page.evaluate(async () => {
        const result = await axe.run(document, {runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}});
        return result.violations.map(v => ({id:v.id,impact:v.impact,nodes:v.nodes.map(n => ({target:n.target,summary:n.failureSummary}))}));
      });
      results.push({view,width,violations:audit});
    }
  }
  await page.locator('#new-batch').click();
  const dialog = await page.evaluate(async () => (await axe.run(document.querySelector('#command-dialog'))).violations.map(v => ({id:v.id,nodes:v.nodes.length})));
  await page.keyboard.press('Escape');
  await page.evaluate(result => console.info('OPERATOR_ACCESSIBILITY_AUDIT ' + JSON.stringify(result)), {results,dialog});
}
