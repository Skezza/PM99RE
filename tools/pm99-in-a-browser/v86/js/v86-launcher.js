const CONFIGS = [
  { label: "Windows 98 + PM99", path: "configs/windows98-pm99.json" },
  { label: "Windows 2000 + PM99", path: "configs/windows2000-pm99.json" },
];

const BOOT_ORDERS = Object.freeze({
  AUTO: 0,
  CD_FLOPPY_HARDDISK: 0x213,
  CD_HARDDISK_FLOPPY: 0x123,
  FLOPPY_CD_HARDDISK: 0x231,
  FLOPPY_HARDDISK_CD: 0x321,
  HARDDISK_CD_FLOPPY: 0x132,
});

let emulator = null;
let currentProfile = null;
let loadedLibraryPath = null;

const dom = {};

window.addEventListener("DOMContentLoaded", init);

function init() {
  bindDom();
  renderProfileOptions();
  bindEvents();
  loadSelectedProfile().catch((error) => reportError("config load failed", error));
}

function bindDom() {
  dom.profileSelect = document.getElementById("profile_select");
  dom.launchButton = document.getElementById("launch_button");
  dom.stopButton = document.getElementById("stop_button");
  dom.resetButton = document.getElementById("reset_button");
  dom.fullscreenButton = document.getElementById("fullscreen_button");
  dom.saveStateButton = document.getElementById("save_state_button");
  dom.restoreStateInput = document.getElementById("restore_state_input");
  dom.cdromInput = document.getElementById("cdrom_input");
  dom.status = document.getElementById("status");
  dom.profileSummary = document.getElementById("profile_summary");
  dom.activeProfile = document.getElementById("active_profile");
  dom.runIndicator = document.getElementById("run_indicator");
  dom.screenContainer = document.getElementById("screen_container");
  dom.eventLog = document.getElementById("event_log");
}

function bindEvents() {
  dom.profileSelect.addEventListener("change", () => {
    loadSelectedProfile().catch((error) => reportError("config load failed", error));
  });
  dom.launchButton.addEventListener("click", () => {
    launch().catch((error) => reportError("launch failed", error));
  });
  dom.stopButton.addEventListener("click", () => {
    toggleRun().catch((error) => reportError("run state change failed", error));
  });
  dom.resetButton.addEventListener("click", () => {
    if (emulator) {
      emulator.restart();
      logEvent("restart requested");
    }
  });
  dom.fullscreenButton.addEventListener("click", () => {
    if (emulator && emulator.screen_go_fullscreen) {
      emulator.screen_go_fullscreen();
    }
  });
  dom.saveStateButton.addEventListener("click", () => {
    saveState().catch((error) => reportError("state save failed", error));
  });
  dom.restoreStateInput.addEventListener("change", () => {
    restoreStateFromInput().catch((error) => reportError("state restore failed", error));
  });
  dom.cdromInput.addEventListener("change", () => {
    setCdromFromInput().catch((error) => reportError("CD-ROM update failed", error));
  });
}

function renderProfileOptions() {
  dom.profileSelect.replaceChildren(
    ...CONFIGS.map((config) => {
      const option = document.createElement("option");
      option.value = config.path;
      option.textContent = config.label;
      return option;
    }),
  );
}

async function loadSelectedProfile() {
  const response = await fetch(dom.profileSelect.value, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`${dom.profileSelect.value}: HTTP ${response.status}`);
  }
  currentProfile = await response.json();
  dom.activeProfile.textContent = currentProfile.name || "Unnamed profile";
  dom.profileSummary.textContent = summarizeProfile(currentProfile);
  setStatus(`Loaded ${currentProfile.name || dom.profileSelect.value}`);
}

async function launch() {
  if (!currentProfile) {
    await loadSelectedProfile();
  }

  setBusy(true);
  try {
    await destroyCurrentEmulator();
    resetScreenContainer();
    await loadV86Library(currentProfile.vendor?.libv86 || "vendor/libv86.js");

    const V86Constructor = window.V86 || window.V86Starter;
    if (!V86Constructor) {
      throw new Error("v86 global constructor not found after loading libv86.js");
    }

    const options = normalizeV86Options(currentProfile.v86 || {});
    emulator = new V86Constructor(options);
    attachEmulatorEvents(emulator);
    setRunningControls(true);
    setStatus(`Launching ${currentProfile.name || "profile"}`);
    logEvent("launch requested");
  } finally {
    setBusy(false);
  }
}

async function destroyCurrentEmulator() {
  if (!emulator) {
    return;
  }

  try {
    if (emulator.is_running && emulator.is_running()) {
      await maybePromise(emulator.stop());
    }
    if (emulator.destroy) {
      await maybePromise(emulator.destroy());
    }
  } finally {
    emulator = null;
    setRunningControls(false);
    setRunIndicator(false);
  }
}

function normalizeV86Options(rawOptions) {
  const options = structuredCloneSafe(rawOptions);
  if (typeof options.boot_order === "string") {
    const bootOrder = BOOT_ORDERS[options.boot_order];
    if (bootOrder === undefined) {
      throw new Error(`unknown boot_order ${options.boot_order}`);
    }
    options.boot_order = bootOrder;
  }

  options.screen_container = dom.screenContainer;
  options.screen = {
    ...(options.screen || {}),
    container: dom.screenContainer,
  };

  return options;
}

async function loadV86Library(path) {
  if ((window.V86 || window.V86Starter) && loadedLibraryPath === path) {
    return;
  }
  if (window.V86 || window.V86Starter) {
    loadedLibraryPath = loadedLibraryPath || path;
    return;
  }

  await new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = path;
    script.async = true;
    script.onload = () => {
      loadedLibraryPath = path;
      resolve();
    };
    script.onerror = () => reject(new Error(`could not load ${path}`));
    document.head.append(script);
  });
}

function attachEmulatorEvents(instance) {
  [
    "emulator-loaded",
    "emulator-ready",
    "emulator-started",
    "emulator-stopped",
    "ide-read-start",
    "ide-read-end",
    "ide-write-end",
  ].forEach((eventName) => {
    instance.add_listener(eventName, (payload) => {
      logEvent(`${eventName}${formatPayload(payload)}`);
      if (eventName === "emulator-started") {
        setRunIndicator(true);
      }
      if (eventName === "emulator-stopped") {
        setRunIndicator(false);
      }
    });
  });

  instance.add_listener("download-progress", (progress) => {
    if (!progress || !progress.file_name) {
      return;
    }
    const loaded = formatBytes(progress.loaded || 0);
    const total = progress.lengthComputable ? formatBytes(progress.total || 0) : "unknown";
    setStatus(`Loading ${progress.file_name}\n${loaded} / ${total}`);
  });

  instance.add_listener("download-error", (error) => {
    const name = error?.file_name || "asset";
    const status = error?.request?.status ? ` HTTP ${error.request.status}` : "";
    reportError("download failed", new Error(`${name}${status}`));
  });

  instance.add_listener("screen-set-size", (size) => {
    if (Array.isArray(size) && size.length >= 2) {
      logEvent(`screen ${size[0]}x${size[1]}`);
    }
  });
}

async function toggleRun() {
  if (!emulator) {
    return;
  }

  if (emulator.is_running && emulator.is_running()) {
    await maybePromise(emulator.stop());
    setRunIndicator(false);
    return;
  }

  await maybePromise(emulator.run());
  setRunIndicator(true);
}

async function saveState() {
  if (!emulator || !emulator.save_state) {
    return;
  }

  const state = await saveStateCompat(emulator);
  const blob = new Blob([state], { type: "application/octet-stream" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const slug = (currentProfile?.name || "pm99-v86").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  link.href = url;
  link.download = `${slug}-${new Date().toISOString().replace(/[:.]/g, "-")}.v86state`;
  link.click();
  URL.revokeObjectURL(url);
  logEvent("state saved");
}

function saveStateCompat(instance) {
  if (instance.save_state.length === 0) {
    return instance.save_state();
  }

  return new Promise((resolve, reject) => {
    instance.save_state((error, state) => {
      if (error) {
        reject(error);
      } else {
        resolve(state);
      }
    });
  });
}

async function restoreStateFromInput() {
  if (!emulator || !dom.restoreStateInput.files.length) {
    return;
  }
  const file = dom.restoreStateInput.files[0];
  const buffer = await file.arrayBuffer();
  await maybePromise(emulator.restore_state(buffer));
  dom.restoreStateInput.value = "";
  logEvent(`state restored from ${file.name}`);
}

async function setCdromFromInput() {
  if (!emulator || !dom.cdromInput.files.length) {
    return;
  }
  if (!emulator.set_cdrom) {
    throw new Error("this v86 build does not expose set_cdrom");
  }

  const file = dom.cdromInput.files[0];
  const buffer = await file.arrayBuffer();
  await maybePromise(emulator.set_cdrom({ buffer }));
  dom.cdromInput.value = "";
  logEvent(`CD-ROM set from ${file.name}`);
}

function resetScreenContainer() {
  const text = document.createElement("div");
  const canvas = document.createElement("canvas");
  text.className = "vga-text";
  dom.screenContainer.replaceChildren(text, canvas);
}

function setRunningControls(enabled) {
  dom.stopButton.disabled = !enabled;
  dom.resetButton.disabled = !enabled;
  dom.fullscreenButton.disabled = !enabled;
  dom.saveStateButton.disabled = !enabled;
  dom.restoreStateInput.disabled = !enabled;
  dom.cdromInput.disabled = !enabled;
}

function setBusy(busy) {
  dom.launchButton.disabled = busy;
  dom.profileSelect.disabled = busy;
}

function setRunIndicator(running) {
  dom.runIndicator.textContent = running ? "running" : "stopped";
  dom.runIndicator.classList.toggle("running", running);
  dom.stopButton.textContent = running ? "Stop" : "Run";
}

function setStatus(message) {
  dom.status.textContent = message;
}

function reportError(context, error) {
  const message = error instanceof Error ? error.message : String(error);
  setStatus(`${context}\n${message}`);
  logEvent(`${context}: ${message}`);
  setBusy(false);
}

function logEvent(message) {
  const line = `[${new Date().toLocaleTimeString()}] ${message}`;
  dom.eventLog.textContent = `${line}\n${dom.eventLog.textContent}`.slice(0, 6000);
}

function summarizeProfile(profile) {
  const options = profile.v86 || {};
  return [
    profile.description || "",
    `libv86: ${profile.vendor?.libv86 || "vendor/libv86.js"}`,
    `wasm: ${options.wasm_path || "build/v86.wasm"}`,
    `bios: ${options.bios?.url || "(unset)"}`,
    `vga: ${options.vga_bios?.url || "(unset)"}`,
    `hda: ${options.hda?.url || "(unset)"}`,
    `cdrom: ${options.cdrom?.url || "(unset)"}`,
    `memory: ${formatBytes(options.memory_size || 0)}`,
    `boot: ${options.boot_order || "AUTO"}`,
  ].filter(Boolean).join("\n");
}

function formatPayload(payload) {
  if (payload === undefined || payload === null) {
    return "";
  }
  if (Array.isArray(payload)) {
    return ` ${payload.join(",")}`;
  }
  if (typeof payload === "object") {
    return ` ${JSON.stringify(payload)}`;
  }
  return ` ${payload}`;
}

function formatBytes(bytes) {
  if (!bytes) {
    return "0 B";
  }
  const units = ["B", "KiB", "MiB", "GiB"];
  let size = bytes;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(size >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function structuredCloneSafe(value) {
  if (typeof structuredClone === "function") {
    return structuredClone(value);
  }
  return JSON.parse(JSON.stringify(value));
}

async function maybePromise(value) {
  return value && typeof value.then === "function" ? value : Promise.resolve(value);
}
