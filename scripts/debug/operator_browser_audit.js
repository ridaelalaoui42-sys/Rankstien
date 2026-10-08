async (page) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const results = [];
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.reload();
  await page.waitForFunction(
    () => document.querySelector("#domain").options.length > 1,
  );
  await page.locator("#auto-refresh").uncheck();
  const supervisorRunning = (await page.locator('#signals .signal-row').first().innerText()).includes('running');
  if (await page.locator('#supervisor-toggle').getAttribute('data-command') !==
      (supervisorRunning ? 'stop-supervisor' : 'supervisor'))
    throw new Error('Supervisor control does not match runtime state');
  for (const view of [
    "overview",
    "workflows",
    "history",
    "pinterest",
    "keywords",
    "recipes",
    "services",
    "logs",
  ]) {
    await page.locator(`nav [data-view="${view}"]`).click();
    await page.waitForFunction(
      (view) =>
        !document
          .querySelector(`#view-${view}`)
          .innerText.includes("Loading..."),
      view,
      { timeout: 20000 },
    );
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    );
    results.push({
      view,
      overflow,
      alerts: await page.locator(`#view-${view} .alert`).allTextContents(),
      rows: await page.locator(`#view-${view} tbody tr`).count(),
      recipes: await page.locator(`#view-${view} .recipe-item`).count(),
    });
    if (overflow) throw new Error(`Desktop overflow in ${view}`);
    if (view === "recipes" && (await page.locator("[data-recipe]").count())) {
      await page.locator("[data-recipe]").first().click();
      await page.locator("#detail-dialog").waitFor({ state: "visible" });
      await page.screenshot({
        path: "output/playwright/operator-recipe-inspector.png",
      });
      await page.keyboard.press("Escape");
    }
  }
  await page.locator('nav [data-view="overview"]').click();
  await page.locator("#domain").selectOption("recetagenial");
  if ((await page.locator("#domains .domain-item").count()) !== 1)
    throw new Error("Domain filter failed");
  let requests = 0;
  await page.route(
    "**/api/rankstein/control/start/rankstein/production?**",
    async (route) => {
      requests++;
      if (!route.request().url().includes("domain=recetagenial"))
        throw new Error("Batch domain missing");
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          pid: 123456,
          batch_id: "ui-test-only",
        }),
      });
    },
  );
  await page.locator("#new-batch").click();
  await page.locator("#command-dialog").waitFor({ state: "visible" });
  await page.keyboard.press("Escape");
  if (requests !== 0) throw new Error("Cancelled dialog sent a mutation");
  await page.locator("#new-batch").click();
  await page.locator("#batch-target").fill("2");
  await page.locator("#command-submit").click();
  await page.locator("#command-dialog").waitFor({ state: "hidden" });
  if (requests !== 1) throw new Error("Confirmed action not sent exactly once");
  await page.unroute("**/api/rankstein/control/start/rankstein/production?**");
  await page.locator('nav [data-view="workflows"]').click();
  if (await page.locator("#workflows [data-campaign]").count()) {
    await page.locator("#workflows [data-campaign]").first().click();
    await page.locator("#detail-dialog").waitFor({ state: "visible" });
    await page.screenshot({
      path: "output/playwright/operator-workflow-inspector.png",
    });
    await page.keyboard.press("Escape");
  }
  await page.locator('nav [data-view="overview"]').click();
  await page.locator("#domain").selectOption("");
  await page.locator('#toast').waitFor({state:'hidden',timeout:10000});
  await page.screenshot({ path: "output/playwright/operator-desktop.png" });
  await page.locator("#theme").click();
  await page.screenshot({ path: "output/playwright/operator-light.png" });
  await page.locator("#theme").click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "output/playwright/operator-mobile.png",
    fullPage: true,
  });
  for (const view of [
    "overview",
    "workflows",
    "history",
    "pinterest",
    "keywords",
    "recipes",
    "services",
    "logs",
  ]) {
    await page.locator("#menu").click();
    await page.locator(`nav [data-view="${view}"]`).click();
    await page.waitForFunction(
      (view) =>
        !document
          .querySelector(`#view-${view}`)
          .innerText.includes("Loading..."),
      view,
      { timeout: 20000 },
    );
    if (
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      )
    )
      throw new Error(`Mobile overflow in ${view}`);
    results.push({ view, mobileOverflow: false });
  }
  await page.locator("#new-batch").click();
  await page.screenshot({
    path: "output/playwright/operator-mobile-dialog.png",
  });
  await page.keyboard.press("Escape");
  if (errors.length) throw new Error(errors.join("\n"));
  await page.evaluate((result) => console.info('OPERATOR_BROWSER_AUDIT ' + result),
    JSON.stringify({
      results,
      errors,
      confirmedMockRequests: requests,
      liveMutations: 0,
    }),
  );
}
