async (page) => {
  const original = await (await page.request.get('http://127.0.0.1:7000/api/rankstein/status')).json();
  const snapshot = {
    ...original,
    actions: {...original.actions, production:{...original.actions?.production, alive:true, state:'running'}},
  };
  await page.route('**/api/rankstein/status', route => route.fulfill({
    status:200,contentType:'application/json',body:JSON.stringify(snapshot),
  }));
  let stops = 0;
  await page.route('**/api/rankstein/control/**', route => {
    if (!route.request().url().endsWith('/control/stop/production'))
      throw new Error('Unexpected control request during recovery test');
    stops++;
    return route.fulfill({status:200,contentType:'application/json',
      body:JSON.stringify({ok:true,stopped:true,pid:123456})});
  });
  await page.locator('#refresh').click();
  await page.waitForFunction(() => !document.querySelector('#stop-batch').disabled);
  const dialogs = [];
  for (const width of [1440,390]) {
    await page.setViewportSize({width,height:width === 390 ? 844 : 1000});
    for (const theme of ['dark','light']) {
      await page.evaluate(theme => {document.documentElement.dataset.theme=theme;}, theme);
      await page.locator('#stop-batch').click();
      await page.locator('#command-dialog').waitFor({state:'visible'});
      const violations = await page.evaluate(async () =>
        (await axe.run(document.querySelector('#command-dialog'),
          {runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}))
          .violations.map(v => ({id:v.id,impact:v.impact,nodes:v.nodes.length})));
      dialogs.push({width,theme,violations});
      if (width === 390 && theme === 'dark')
        await page.screenshot({path:'output/playwright/operator-stop-batch-dialog.png'});
      await page.keyboard.press('Escape');
      if (stops) throw new Error('Cancelled stop sent a mutation');
    }
  }
  await page.locator('#stop-batch').click();
  await page.locator('#command-submit').click();
  await page.locator('#command-dialog').waitFor({state:'hidden'});
  if (stops !== 1) throw new Error('Stop confirmation did not send exactly one mocked request');
  if (await page.locator('#log-mode').inputValue() !== 'production')
    throw new Error('Stop did not select production logs');
  await page.unroute('**/api/rankstein/status');
  await page.locator('#refresh').click();
  await page.evaluate(result => console.info('OPERATOR_RECOVERY_AUDIT ' + JSON.stringify(result)),
    {dialogs,confirmedStopMockRequests:stops,liveMutations:0});
}
