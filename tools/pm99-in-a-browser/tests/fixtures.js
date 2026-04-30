export const manifest = {
  schema: "pm99-in-a-browser-assets-v1",
  pm99_root: "/fixtures/pm99",
  required: {
    total: 6,
    present: 6,
    missing: [],
    files: [
      { path: "MANAGPRE.EXE", present: true, size: 3442176, sha256: "fixture-managpre" },
      { path: "MIDAS11.DLL", present: true, size: 160256, sha256: "fixture-midas" },
      { path: "DBDAT/JUG98030.FDI", present: true, size: 3847087, sha256: "fixture-jug" },
      { path: "DBDAT/EQ98030.FDI", present: true, size: 1097585, sha256: "fixture-eq" },
      { path: "DBDAT/ENT98030.FDI", present: true, size: 159249, sha256: "fixture-ent" },
      { path: "DBDAT/MINIFOTO.PKF", present: true, size: 1474476, sha256: "fixture-minifoto" },
    ],
  },
};

export const fakeV86Script = `
(() => {
  const optionsStore = window.__v86Options || [];
  window.__v86Options = optionsStore;
  class FakeV86 {
    constructor(options) {
      this.options = options;
      this.listeners = {};
      this.running = false;
      optionsStore.push(options);
      const marker = document.createElement("div");
      marker.dataset.fakeV86Screen = "1";
      marker.textContent = "fake v86 runtime";
      options.screen_container?.append(marker);
      setTimeout(() => {
        this.running = true;
        this.emit("emulator-started", { fake: true });
        this.emit("screen-set-size", [640, 480]);
      }, 0);
    }
    add_listener(name, callback) {
      (this.listeners[name] ||= []).push(callback);
    }
    emit(name, payload) {
      for (const callback of this.listeners[name] || []) {
        callback(payload);
      }
    }
    is_running() {
      return this.running;
    }
    stop() {
      this.running = false;
      this.emit("emulator-stopped", { fake: true });
    }
    run() {
      this.running = true;
      this.emit("emulator-started", { fake: true });
    }
    restart() {
      this.emit("emulator-ready", { restarted: true });
    }
    destroy() {
      this.destroyed = true;
    }
    screen_go_fullscreen() {
      this.fullscreen = true;
    }
    save_state(callback) {
      const state = new Uint8Array([80, 77, 57, 57]).buffer;
      if (callback) {
        callback(null, state);
        return undefined;
      }
      return Promise.resolve(state);
    }
    restore_state(buffer) {
      window.__v86RestoredBytes = buffer.byteLength;
    }
    set_cdrom(image) {
      window.__v86CdromBytes = image.buffer.byteLength;
    }
  }
  window.V86Starter = FakeV86;
  window.V86 = FakeV86;
})();
`;

export async function installCommonRoutes(page) {
  await page.route("**/favicon.ico", async (route) => {
    await route.fulfill({ status: 204, body: "" });
  });

  await page.route("**/assets/pm99-manifest.json", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(manifest),
    });
  });

  await page.route("**/vendor/boxedwine/boxedwine.js", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/javascript",
      body: "window.__boxedWineVendorProbe = true;",
    });
  });

  await page.route("**/boxedwine/vendor/boxedwine.js", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/javascript",
      body: "window.__boxedWineVendorProbe = true;",
    });
  });

  await page.route("**/boxedwine/vendor/boxedwine.html**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/html",
      body: "<!doctype html><title>Fake BoxedWine</title><body>fake boxedwine runtime</body>",
    });
  });

  await page.route("**/vendor/v86/libv86.js", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/javascript",
      body: fakeV86Script,
    });
  });

  await page.route("**/v86/vendor/libv86.js", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/javascript",
      body: fakeV86Script,
    });
  });
}

export function watchConsole(page) {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text());
    }
  });
  return errors;
}
