import { expect, test } from "@playwright/test";
import { installCommonRoutes, watchConsole } from "./fixtures.js";

test.beforeEach(async ({ page }) => {
  await installCommonRoutes(page);
});

test("shared launcher loads assets, switches panes, and survives responsive widths", async ({ page }) => {
  const errors = watchConsole(page);
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "PM99 Browser Lab" })).toBeVisible();
  await expect(page.locator("#asset-status")).toContainText("PM99 manifest - 6/6 required");
  await expect(page.locator("#asset-status")).toContainText("BoxedWine sample config");
  await expect(page.locator("#asset-status")).toContainText("v86 sample config");
  await expect(page.locator("#asset-status")).toContainText("PM99 required files");
  await expect(page.locator("#log")).toContainText("Ready");

  await expect(page.locator("#boxedwine-pane")).toBeVisible();
  await page.getByRole("tab", { name: "v86" }).click();
  await expect(page.locator("#v86-pane")).toBeVisible();
  await expect(page.getByRole("tab", { name: "v86" })).toHaveAttribute("aria-selected", "true");

  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 820 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    for (const button of await page.locator("button:visible").all()) {
      const box = await button.boundingBox();
      expect(box?.width || 0).toBeGreaterThan(0);
      expect(box?.height || 0).toBeGreaterThan(0);
    }
  }

  expect(errors).toEqual([]);
});

test("shared BoxedWine path loads sample config and embeds backend launcher", async ({ page }) => {
  const errors = watchConsole(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Load" }).first().click();
  await expect(page.locator("#log")).toContainText("Loaded BoxedWine config");

  await page.getByRole("button", { name: "Launch" }).first().click();
  const backendFrame = page.locator("#boxedwine-screen iframe").first();
  await expect(backendFrame).toBeVisible();

  const src = await backendFrame.getAttribute("src");
  expect(src).toContain("/boxedwine/index.html");
  expect(src).toContain("launch=1");
  expect(decodeURIComponent(src || "")).toContain("/config/boxedwine.sample.json");

  await expect(page.locator("#log")).toContainText("BoxedWine iframe launched");
  await page.getByRole("button", { name: "Stop" }).first().click();
  await expect(page.locator("#boxedwine-screen iframe")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("shared BoxedWine local config fallback launches with the sample config URL", async ({ page }) => {
  await page.goto("/");
  await page.locator("#boxedwine-config-url").fill("./config/boxedwine.local.json");

  await page.getByRole("button", { name: "Load" }).first().click();
  await expect(page.locator("#log")).toContainText("Loaded BoxedWine config");

  await page.getByRole("button", { name: "Launch" }).first().click();
  const backendFrame = page.locator("#boxedwine-screen iframe").first();
  await expect(backendFrame).toBeVisible();

  const src = await backendFrame.getAttribute("src");
  expect(decodeURIComponent(src || "")).toContain("/config/boxedwine.sample.json");
});

test("shared v86 path launches against a mocked runtime and can save state", async ({ page }) => {
  const errors = watchConsole(page);
  await page.goto("/");
  await page.getByRole("tab", { name: "v86" }).click();

  await page.locator("#v86-load").click();
  await expect(page.locator("#log")).toContainText("Loaded v86 config");

  await page.locator("#v86-launch").click();
  await expect(page.locator("#v86-screen [data-fake-v86-screen='1']")).toBeVisible();
  await expect(page.locator("#log")).toContainText("Starting v86 with 128 MiB RAM");

  const options = await page.evaluate(() => window.__v86Options[0]);
  expect(options.wasm_path).toBe("./vendor/v86/v86.wasm");
  expect(options.memory_size).toBe(128 * 1024 * 1024);
  expect(options.hda.url).toBe("./v86/assets/disks/win98-pm99.img");
  expect(options.cdrom.url).toBe("./assets/pm99.iso");

  const downloadPromise = page.waitForEvent("download");
  await page.locator("#v86-save-state").click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^pm99-v86-.*\.state$/);

  await page.locator("#v86-stop").click();
  await expect(page.locator("#v86-screen [data-fake-v86-screen='1']")).toHaveCount(0);
  expect(errors).toEqual([]);
});
