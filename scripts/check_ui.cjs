// Browser integration checks. Requires Playwright and a running local API on a fresh database:
//   COGNITION_DB=/tmp/ui.db COGNITION_CORE_AGENTS=false cognition serve --port 8010
//   COGNITION_UI_URL=http://127.0.0.1:8010 node scripts/check_ui.cjs
// The offline reference harness is used. Nothing here calls a model.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const assert = require("node:assert/strict");

const base = process.env.COGNITION_UI_URL || "http://127.0.0.1:8000";
const shots = process.env.COGNITION_QA_DIR || "output/playwright";

async function api(page, method, path, body) {
  return page.evaluate(
    async ([m, p, b]) => {
      const response = await fetch(p, {
        method: m,
        headers: { "content-type": "application/json" },
        body: b ? JSON.stringify(b) : undefined,
      });
      return { status: response.status, body: await response.json().catch(() => null) };
    },
    [method, path, body],
  );
}

async function noOverflow(page, label) {
  assert.ok(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    `${label}: horizontal overflow`,
  );
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}),
    args: [
      "--no-sandbox",
      "--enable-webgl",
      "--use-gl=angle",
      "--use-angle=swiftshader",
      "--enable-unsafe-swiftshader",
    ],
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));

  // Plants page: one card per seeded plant, four core lamps each, search narrows the list.
  await page.goto(`${base}/fleet`);
  await page.locator("#fleet-cards .fl-card").first().waitFor();
  assert.equal(await page.locator("#fleet-cards .fl-card").count(), 3);
  for (const card of await page.locator("#fleet-cards .fl-card").all()) {
    assert.equal(await card.locator(".fl-cores .fl-core").count(), 4);
  }
  await page.locator("#fleet-card-search").fill("chemical");
  await page.waitForFunction(
    () => document.querySelectorAll("#fleet-cards .fl-card:not([hidden])").length === 1,
  );
  await page.locator("#fleet-card-search").fill("");
  await page.screenshot({ path: `${shots}/fleet-desktop.png`, fullPage: true });

  // A live fault turns a core lamp from green. The world clock ticks the plant on its own.
  const cement = page.locator("#fleet-cards .fl-card", { hasText: /cement/i }).first();
  const lamps = cement.locator(".fl-cores .fl-core");
  assert.equal((await api(page, "POST", "/api/plants/cement-demo/world/start", { interval_seconds: 0.5 })).status, 200);
  const injected = await api(page, "POST", "/api/plants/cement-demo/faults", {
    kind: "kiln_drive_bearing_wear",
    severity: 0.9,
    ramp_ticks: 3,
  });
  assert.equal(injected.status, 201);
  await page.waitForFunction(
    (el) => [...el.querySelectorAll(".fl-core")].some((n) => ["warn", "crit"].includes(n.dataset.level)),
    await cement.locator(".fl-cores").elementHandle(),
    { timeout: 30000 },
  );
  assert.ok((await lamps.evaluateAll((all) => all.map((n) => n.dataset.level))).length === 4);

  // Specialist Faculties page: Overview (world controls, faults and bus cards, four core summaries, Stop all
  // idle until a run exists), then one tab per core with its own workspace.
  await page.goto(`${base}/faculties?plant=cement-demo`);
  assert.equal(await page.locator('[data-nav="faculties"]').getAttribute("aria-current"), "page");
  await page.locator("#faculties-host .ov-stats").waitFor();
  assert.equal(await page.locator("#faculties-tab-overview").getAttribute("aria-selected"), "true");
  assert.equal(await page.locator("#faculties-host .ov-core").count(), 4);
  await page.locator("#faculties-host .cr-card--activity").waitFor();
  assert.equal(await page.locator("#faculties-host .cr-card--faults").count(), 0);
  await page.screenshot({ path: `${shots}/faculties-overview-desktop.png`, fullPage: true });
  for (const [tab, card] of [["learning", "signals-live"], ["vision", "vision-live"], ["robot", "robot-live"], ["optimization", "opt-live"]]) {
    await page.locator(`#faculties-tab-${tab}`).click();
    assert.equal(await page.locator(`#faculties-tab-${tab}`).getAttribute("aria-selected"), "true");
    const view = { "signals-live": ".lv-rack", "vision-live": ".vv-viewer", "robot-live": ".rv-mapcard", "opt-live": ".ox-hero" }[card];
    await page.locator(`#faculties-host ${view}`).waitFor();
    assert.equal(await page.locator("#faculties-host .cr-core").count(), 1);
    assert.equal(await page.locator("#faculties-host .cr-card--faults").count(), 0);
  }
  await page.screenshot({ path: `${shots}/faculties-optimization-desktop.png`, fullPage: true });
  // Old links to the studio Cores tab land on the Specialist Faculties page.
  await page.goto(`${base}/studio?plant=cement-demo&view=cores`);
  await page.waitForURL(/\/faculties/);

  // Impact page: nav state, hero (OEE rings and KPI tiles) and the six cards. The plant comes from the studio selection.
  await page.goto(`${base}/impact?plant=cement-demo`);
  await page.locator("#impact-host .ix-hero").waitFor();
  assert.equal(await page.locator('[data-nav="impact"]').getAttribute("aria-current"), "page");
  assert.equal(await page.locator("#impact-host .ix-tile").count(), 8);
  assert.equal(await page.locator("#impact-host .ix-card").count(), 6);
  await page.screenshot({ path: `${shots}/impact-desktop.png`, fullPage: true });

  // Mobile width: no horizontal overflow on the new pages.
  await page.setViewportSize({ width: 390, height: 844 });
  await noOverflow(page, "impact");
  await page.goto(`${base}/faculties?plant=cement-demo&tab=learning`);
  await page.locator("#faculties-host .lv-rack").waitFor();
  await noOverflow(page, "faculties");
  await page.goto(`${base}/fleet`);
  await page.locator("#fleet-cards .fl-card").first().waitFor();
  await noOverflow(page, "fleet");
  await page.screenshot({ path: `${shots}/fleet-mobile.png`, fullPage: true });

  // Leave the plant as found.
  await api(page, "DELETE", "/api/plants/cement-demo/automation");
  await api(page, "POST", "/api/plants/cement-demo/world/stop");
  await api(page, "POST", "/api/plants/cement-demo/reset");

  assert.deepEqual(errors, []);
  console.log("UI passed: plant cards and core lamps, Specialist Faculties page and its core tabs, Impact page, mobile layout; no page errors");
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
