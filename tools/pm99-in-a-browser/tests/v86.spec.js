import { expect, test } from "@playwright/test";
import { fakeV86Script, installCommonRoutes, watchConsole } from "./fixtures.js";

test.beforeEach(async ({ page }) => {
  await installCommonRoutes(page);
});

test("standalone v86 backend loads profiles, launches, and exposes controls", async ({ page }) => {
  const errors = watchConsole(page);
  await page.goto("/v86/");

  await expect(page.getByRole("heading", { name: "PM99 v86 Backend" })).toBeVisible();
  await expect(page.locator("#active_profile")).toHaveText("Windows 98 + PM99");
  await expect(page.locator("#profile_summary")).toContainText("win98-pm99.img");
  await expect(page.locator("#launch_button")).toBeEnabled();

  await page.locator("#launch_button").click();
  await expect(page.locator("#screen_container [data-fake-v86-screen='1']")).toBeVisible();
  await expect(page.locator("#run_indicator")).toContainText("running");
  await expect(page.locator("#event_log")).toContainText("launch requested");
  await expect(page.locator("#event_log")).toContainText("screen 640x480");

  const options = await page.evaluate(() => window.__v86Options[0]);
  expect(options.wasm_path).toBe("vendor/v86.wasm");
  expect(options.boot_order).toBe(0x132);
  expect(options.screen_container).toBeTruthy();

  await expect(page.locator("#stop_button")).toBeEnabled();
  await expect(page.locator("#reset_button")).toBeEnabled();
  await expect(page.locator("#save_state_button")).toBeEnabled();
  await expect(page.locator("#restore_state_input")).toBeEnabled();
  await expect(page.locator("#cdrom_input")).toBeEnabled();

  expect(errors).toEqual([]);
});

test("standalone v86 profile switch loads Windows 2000 config", async ({ page }) => {
  await page.goto("/v86/");
  await page.locator("#profile_select").selectOption("configs/windows2000-pm99.json");
  await expect(page.locator("#active_profile")).toHaveText("Windows 2000 + PM99");
  await expect(page.locator("#profile_summary")).toContainText("win2000-pm99.img");
  await expect(page.locator("#profile_summary")).toContainText("256 MiB");
});

test("standalone v86 state and CD-ROM controls call runtime APIs", async ({ page }) => {
  await page.goto("/v86/");
  await page.locator("#launch_button").click();
  await expect(page.locator("#screen_container [data-fake-v86-screen='1']")).toBeVisible();

  const downloadPromise = page.waitForEvent("download");
  await page.locator("#save_state_button").click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^windows-98-pm99-.*\.v86state$/);

  await page.locator("#restore_state_input").setInputFiles({
    name: "restore.v86state",
    mimeType: "application/octet-stream",
    buffer: Buffer.from([1, 2, 3, 4, 5]),
  });
  await expect.poll(() => page.evaluate(() => window.__v86RestoredBytes)).toBe(5);

  await page.locator("#cdrom_input").setInputFiles({
    name: "pm99.iso",
    mimeType: "application/octet-stream",
    buffer: Buffer.from([9, 8, 7]),
  });
  await expect.poll(() => page.evaluate(() => window.__v86CdromBytes)).toBe(3);
});

test("standalone v86 reports a missing runtime clearly", async ({ page }) => {
  await page.route("**/v86/vendor/libv86.js", async (route) => {
    await route.fulfill({ status: 404, contentType: "text/plain", body: "missing" });
  });
  await page.route("**/vendor/v86/libv86.js", async (route) => {
    await route.fulfill({ status: 404, contentType: "text/plain", body: "missing" });
  });

  await page.goto("/v86/");
  await page.locator("#launch_button").click();
  await expect(page.locator("#status")).toContainText("launch failed");
  await expect(page.locator("#status")).toContainText("could not load vendor/libv86.js");
});

test("shared v86 script loader avoids duplicate runtime script tags", async ({ page }) => {
  await page.route("**/vendor/v86/libv86.js", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/javascript",
      body: `${fakeV86Script}\nwindow.__fakeV86LoadCount = (window.__fakeV86LoadCount || 0) + 1;`,
    });
  });

  await page.goto("/");
  await page.getByRole("tab", { name: "v86" }).click();
  await page.locator("#v86-launch").click();
  await expect(page.locator("#v86-screen [data-fake-v86-screen='1']")).toBeVisible();
  await page.locator("#v86-launch").click();

  const counts = await page.evaluate(() => ({
    scriptTags: document.querySelectorAll('script[data-loader-url="./vendor/v86/libv86.js"]').length,
    loadCount: window.__fakeV86LoadCount,
    launches: window.__v86Options.length,
  }));
  expect(counts.scriptTags).toBe(1);
  expect(counts.loadCount).toBe(1);
  expect(counts.launches).toBe(2);
});
