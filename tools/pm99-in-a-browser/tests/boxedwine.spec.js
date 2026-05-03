import { expect, test } from "@playwright/test";
import { installCommonRoutes, watchConsole } from "./fixtures.js";

test.beforeEach(async ({ page }) => {
  await installCommonRoutes(page);
});

test("BoxedWine backend page builds the supplied runtime URL", async ({ page }) => {
  const errors = watchConsole(page);
  await page.goto("/boxedwine/?config=../config/boxedwine.sample.json");

  await expect(page.getByRole("heading", { name: "PM99 BoxedWine" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Launch" })).toBeEnabled();

  await page.getByRole("button", { name: "Launch" }).click();
  const runtime = page.locator("#boxedwine-mount iframe");
  await expect(runtime).toBeVisible();

  const src = await runtime.getAttribute("src");
  expect(src).toContain("/boxedwine/vendor/boxedwine.html");
  expect(src).toContain("root=boxedwine-root.zip");
  expect(src).toContain("app=pm99-app.zip");
  expect(src).toContain("bpp=16");
  expect(src).toContain("resolution=640x480");
  expect(src).toContain("p=%22C:\\files\\MANAGPRE.EXE%22");
  expect(errors).toEqual([]);
});

test("BoxedWine backend auto-launch works from query string", async ({ page }) => {
  await page.goto("/boxedwine/?config=../config/boxedwine.sample.json&launch=1");
  await expect(page.locator("#boxedwine-mount iframe")).toBeVisible();
  await expect(page.getByRole("status")).toContainText("/boxedwine/vendor/boxedwine.html");
});

test("BoxedWine query builder preserves paths, overlays, and environment flags", async ({ page }) => {
  await page.goto("/boxedwine/");
  const query = await page.evaluate(async () => {
    const module = await import("/boxedwine/static/boxedwine-launcher.js");
    return module.buildBoxedWineQuery({
      assets: {
        rootZip: "../root.zip",
        appZip: "../pm99.zip",
        overlayZips: ["../patch one.zip", "../patch two.zip"],
      },
      launch: {
        program: "D:\\PM99\\MANAGPRE.EXE",
        auto: true,
        desktop: false,
        sound: true,
        bpp: 16,
        resolution: "640x480",
        cpu: "p2",
        skipFrameFPS: 0,
        ddrawOverride: "ddraw=n,b",
        wineEnv: { WINEDLLOVERRIDES: "ddraw=n,b" },
        emscriptenEnv: { PM99_TEST: "1", PM99_TRACE: "1" },
      },
      query: {
        custom: "../custom/path",
      },
    });
  });

  expect(query).toContain("root=../root.zip");
  expect(query).toContain("overlay=../patch%20one.zip;../patch%20two.zip");
  expect(query).toContain("p=%22D:\\PM99\\MANAGPRE.EXE%22");
  expect(query).toContain("auto=true");
  expect(query).toContain("env=%22WINEDLLOVERRIDES:ddraw%3Dn%2Cb%22");
  expect(query).toContain("em-env=%22PM99_TEST:1;PM99_TRACE:1%22");
  expect(query).toContain("custom=../custom/path");
});
