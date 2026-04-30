import { loadScript } from "../utils.js";

export const defaultV86Config = {
  backend: "v86",
  libv86Url: "./vendor/v86/libv86.js",
  wasmPath: "./vendor/v86/v86.wasm",
  memorySizeMb: 128,
  vgaMemorySizeMb: 8,
  autostart: true,
  biosUrl: "./assets/v86/seabios.bin",
  vgaBiosUrl: "./assets/v86/vgabios.bin",
  hda: {
    url: "./assets/v86/windows98-pm99.img",
    async: true,
  },
  cdrom: {
    url: "./assets/pm99.iso",
    async: true,
  },
};

export async function launchV86({ screenContainer, config, log }) {
  const resolved = { ...defaultV86Config, ...config };
  await loadScript(resolved.libv86Url);

  const Starter = window.V86Starter || window.V86;
  if (!Starter) {
    throw new Error("v86 script loaded, but window.V86Starter/window.V86 was not found");
  }

  screenContainer.replaceChildren();

  const emulatorOptions = {
    wasm_path: resolved.wasmPath,
    memory_size: Number(resolved.memorySizeMb || 128) * 1024 * 1024,
    vga_memory_size: Number(resolved.vgaMemorySizeMb || 8) * 1024 * 1024,
    screen_container: screenContainer,
    autostart: resolved.autostart !== false,
    bios: { url: resolved.biosUrl },
    vga_bios: { url: resolved.vgaBiosUrl },
  };

  if (resolved.hda?.url) {
    emulatorOptions.hda = resolved.hda;
  }
  if (resolved.cdrom?.url) {
    emulatorOptions.cdrom = resolved.cdrom;
  }
  if (resolved.fda?.url) {
    emulatorOptions.fda = resolved.fda;
  }
  if (resolved.bootOrder) {
    emulatorOptions.boot_order = resolved.bootOrder;
  }
  if (resolved.networkRelayUrl) {
    emulatorOptions.network_relay_url = resolved.networkRelayUrl;
  }

  log(`Starting v86 with ${resolved.memorySizeMb || 128} MiB RAM`);
  const emulator = new Starter(emulatorOptions);

  return {
    emulator,
    stop() {
      if (typeof emulator.stop === "function") {
        emulator.stop();
      }
      screenContainer.replaceChildren();
    },
    async saveState() {
      if (typeof emulator.save_state !== "function") {
        throw new Error("This v86 build does not expose save_state");
      }
      return new Promise((resolve, reject) => {
        emulator.save_state((error, state) => {
          if (error) {
            reject(error);
          } else {
            resolve(state);
          }
        });
      });
    },
  };
}
