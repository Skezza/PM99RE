import { launchBoxedWine, loadBoxedWineConfig } from "./backends/boxedwine.js";
import { defaultV86Config, launchV86 } from "./backends/v86.js";
import { appendLog, el, fetchJson, setChildren, urlExists } from "./utils.js";

const nodes = {
  log: document.querySelector("#log"),
  assetStatus: document.querySelector("#asset-status"),
  refreshAssets: document.querySelector("#refresh-assets"),
  tabBoxedWine: document.querySelector("#tab-boxedwine"),
  tabV86: document.querySelector("#tab-v86"),
  boxedWinePane: document.querySelector("#boxedwine-pane"),
  v86Pane: document.querySelector("#v86-pane"),
  boxedWineConfigUrl: document.querySelector("#boxedwine-config-url"),
  boxedWineLoad: document.querySelector("#boxedwine-load"),
  boxedWineLaunch: document.querySelector("#boxedwine-launch"),
  boxedWineStop: document.querySelector("#boxedwine-stop"),
  boxedWineScreen: document.querySelector("#boxedwine-screen"),
  v86ConfigUrl: document.querySelector("#v86-config-url"),
  v86Load: document.querySelector("#v86-load"),
  v86Launch: document.querySelector("#v86-launch"),
  v86Stop: document.querySelector("#v86-stop"),
  v86SaveState: document.querySelector("#v86-save-state"),
  v86Screen: document.querySelector("#v86-screen"),
};

let boxedWineConfig = null;
let boxedWineRuntime = null;
let v86Config = null;
let v86Runtime = null;

function log(message) {
  appendLog(nodes.log, message);
}

function selectBackend(name) {
  const boxedWine = name === "boxedwine";
  nodes.tabBoxedWine.classList.toggle("active", boxedWine);
  nodes.tabBoxedWine.setAttribute("aria-selected", String(boxedWine));
  nodes.boxedWinePane.classList.toggle("active", boxedWine);

  nodes.tabV86.classList.toggle("active", !boxedWine);
  nodes.tabV86.setAttribute("aria-selected", String(!boxedWine));
  nodes.v86Pane.classList.toggle("active", !boxedWine);
}

function statusItem(label, ok, extra = "") {
  const dot = el("span", { className: `dot ${ok ? "ok" : "bad"}` });
  const text = el("span", {}, `${label}${extra ? ` - ${extra}` : ""}`);
  const row = el("div", { className: "status-item" });
  row.append(dot, text);
  return row;
}

async function refreshAssets() {
  const checks = [];
  let manifest = null;

  try {
    manifest = await fetchJson("./assets/pm99-manifest.json");
    checks.push(statusItem("PM99 manifest", true, `${manifest.required.present}/${manifest.required.total} required`));
  } catch {
    checks.push(statusItem("PM99 manifest", false, "run scripts/prepare_pm99_assets.sh"));
  }

  checks.push(statusItem("BoxedWine sample config", await urlExists("./config/boxedwine.sample.json")));
  checks.push(statusItem("v86 sample config", await urlExists("./config/v86.sample.json")));
  checks.push(statusItem("BoxedWine vendor", await urlExists("./boxedwine/vendor/boxedwine.js")));
  checks.push(statusItem("v86 vendor", await urlExists("./vendor/v86/libv86.js")));

  if (manifest?.required?.missing?.length) {
    checks.push(statusItem("PM99 required files", false, manifest.required.missing.join(", ")));
  } else if (manifest) {
    checks.push(statusItem("PM99 required files", true));
  }

  setChildren(nodes.assetStatus, checks);
}

async function loadBoxedWine() {
  const url = nodes.boxedWineConfigUrl.value.trim();
  boxedWineConfig = await loadBoxedWineConfig(url);
  log(`Loaded BoxedWine config from ${url}`);
}

async function loadV86() {
  const url = nodes.v86ConfigUrl.value.trim();
  try {
    v86Config = await fetchJson(url);
    log(`Loaded v86 config from ${url}`);
  } catch (error) {
    if (url.endsWith(".local.json")) {
      v86Config = await fetchJson("./config/v86.sample.json");
      log(`Loaded v86 sample config because ${url} was not found`);
    } else {
      throw error;
    }
  }
}

async function launchCurrentBoxedWine() {
  if (!boxedWineConfig) {
    await loadBoxedWine();
  }
  if (boxedWineRuntime) {
    boxedWineRuntime.stop();
  }
  boxedWineRuntime = await launchBoxedWine({
    screenContainer: nodes.boxedWineScreen,
    config: boxedWineConfig,
    configUrl: nodes.boxedWineConfigUrl.value.trim(),
    log,
  });
}

async function launchCurrentV86() {
  if (!v86Config) {
    await loadV86();
  }
  if (v86Runtime) {
    v86Runtime.stop();
  }
  v86Runtime = await launchV86({
    screenContainer: nodes.v86Screen,
    config: { ...defaultV86Config, ...v86Config },
    log,
  });
}

async function saveV86State() {
  if (!v86Runtime) {
    log("v86 is not running");
    return;
  }

  const state = await v86Runtime.saveState();
  const blob = new Blob([state], { type: "application/octet-stream" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `pm99-v86-${new Date().toISOString().replace(/[:.]/g, "")}.state`;
  link.click();
  URL.revokeObjectURL(url);
  log("v86 state saved");
}

function bindEvents() {
  nodes.refreshAssets.addEventListener("click", () => refreshAssets().catch((error) => log(error.message)));
  nodes.tabBoxedWine.addEventListener("click", () => selectBackend("boxedwine"));
  nodes.tabV86.addEventListener("click", () => selectBackend("v86"));

  nodes.boxedWineLoad.addEventListener("click", () => loadBoxedWine().catch((error) => log(error.message)));
  nodes.boxedWineLaunch.addEventListener("click", () => launchCurrentBoxedWine().catch((error) => log(error.message)));
  nodes.boxedWineStop.addEventListener("click", () => {
    boxedWineRuntime?.stop();
    boxedWineRuntime = null;
    log("BoxedWine stopped");
  });

  nodes.v86Load.addEventListener("click", () => loadV86().catch((error) => log(error.message)));
  nodes.v86Launch.addEventListener("click", () => launchCurrentV86().catch((error) => log(error.message)));
  nodes.v86Stop.addEventListener("click", () => {
    v86Runtime?.stop();
    v86Runtime = null;
    log("v86 stopped");
  });
  nodes.v86SaveState.addEventListener("click", () => saveV86State().catch((error) => log(error.message)));
}

bindEvents();
refreshAssets().catch((error) => log(error.message));
log("Ready");
