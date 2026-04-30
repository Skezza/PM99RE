import { existsSync } from "node:fs";
import { expect, test } from "@playwright/test";

const requiredPayloads = [
  "assets/pm99-manifest.json",
  "assets/pm99.iso",
  "assets/pm99.zip",
  "boxedwine/vendor/boxedwine.html",
  "boxedwine/vendor/boxedwine.js",
  "boxedwine/vendor/boxedwine.wasm",
  "boxedwine/vendor/boxedwine-root.zip",
  "boxedwine/vendor/pm99-app.zip",
  "vendor/v86/libv86.js",
  "vendor/v86/v86.wasm",
  "v86/assets/bios/seabios.bin",
  "v86/assets/bios/vgabios.bin",
];

function hasPayloads() {
  return requiredPayloads.every((path) => existsSync(new URL(`../${path}`, import.meta.url)));
}

test.describe("live payload wiring", () => {
  test.skip(!hasPayloads(), "run prepare_pm99_assets.sh and npm run payloads:open to enable live payload smoke tests");

  test("shared launcher reports real local payloads as available", async ({ page }) => {
    await page.goto("/");

    await expect(page.locator("#asset-status")).toContainText("PM99 manifest - 6/6 required");
    await expect(page.locator("#asset-status")).toContainText("BoxedWine vendor");
    await expect(page.locator("#asset-status")).toContainText("v86 vendor");
    await expect(page.locator("#asset-status .dot.bad")).toHaveCount(0);
  });

  test("emulator and PM99 payload URLs are served with non-empty bodies", async ({ request }) => {
    const checks = [
      ["/assets/pm99-manifest.json", 100],
      ["/assets/pm99.iso", 1_000_000],
      ["/assets/pm99.zip", 1_000_000],
      ["/boxedwine/vendor/boxedwine.html", 1_000],
      ["/boxedwine/vendor/boxedwine.js", 100_000],
      ["/boxedwine/vendor/boxedwine.wasm", 100_000],
      ["/boxedwine/vendor/boxedwine-root.zip", 1_000_000],
      ["/boxedwine/vendor/pm99-app.zip", 1_000_000],
      ["/vendor/v86/libv86.js", 100_000],
      ["/vendor/v86/v86.wasm", 100_000],
      ["/v86/assets/bios/seabios.bin", 10_000],
      ["/v86/assets/bios/vgabios.bin", 10_000],
    ];

    for (const [url, minLength] of checks) {
      const response = await request.get(url);
      expect(response.ok(), `${url} should return 2xx`).toBe(true);
      const body = await response.body();
      expect(body.length, `${url} should be at least ${minLength} bytes`).toBeGreaterThanOrEqual(minLength);
    }
  });

  test("BoxedWine launch URL points at the fetched web build and staged app archive", async ({ page }) => {
    await page.goto("/boxedwine/?config=../config/boxedwine.sample.json&launch=1");

    const frame = page.locator("#boxedwine-mount iframe");
    await expect(frame).toBeVisible();

    const src = await frame.getAttribute("src");
    expect(src).toContain("/boxedwine/vendor/boxedwine.html");
    expect(src).toContain("root=boxedwine-root.zip");
    expect(src).toContain("app=pm99-app.zip");
    expect(src).toContain("p=%22C%3A%5Cfiles%5CMANAGPRE.EXE%22");
  });
});
