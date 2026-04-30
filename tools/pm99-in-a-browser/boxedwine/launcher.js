const params = new URLSearchParams(window.location.search);
const configUrl = params.get("config") || "../config/boxedwine.local.json";
const logNode = document.querySelector("#boxedwine-log");

function log(message) {
  const stamp = new Date().toISOString().slice(11, 19);
  logNode.textContent += `[${stamp}] ${message}\n`;
  logNode.scrollTop = logNode.scrollHeight;
}

async function fetchJsonWithFallback(url) {
  try {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
  } catch (error) {
    if (url.endsWith(".local.json")) {
      log(`${url} not available, loading sample config`);
      const sample = await fetch("../config/boxedwine.sample.json", { cache: "no-store" });
      if (!sample.ok) {
        throw new Error(`sample config returned HTTP ${sample.status}`);
      }
      return sample.json();
    }
    throw error;
  }
}

function loadScript(url) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = url;
    script.async = true;
    script.addEventListener("load", resolve, { once: true });
    script.addEventListener("error", () => reject(new Error(`failed to load ${url}`)), { once: true });
    document.head.append(script);
  });
}

function dirname(path) {
  const clean = path.replace(/\\/g, "/");
  const index = clean.lastIndexOf("/");
  return index <= 0 ? "/" : clean.slice(0, index);
}

function basename(path) {
  const clean = path.replace(/\\/g, "/");
  const index = clean.lastIndexOf("/");
  return index === -1 ? clean : clean.slice(index + 1);
}

async function main() {
  const config = await fetchJsonWithFallback(configUrl);
  const canvas = document.getElementById(config.canvasId || "boxedwine-canvas");
  canvas.width = Number(config.width || 640);
  canvas.height = Number(config.height || 480);

  log(`Config: ${configUrl}`);
  log(`Module: ${config.moduleScriptUrl}`);
  log(`Args: ${(config.arguments || []).join(" ")}`);

  window.Module = {
    canvas,
    arguments: config.arguments || [],
    print: (text) => log(String(text)),
    printErr: (text) => log(String(text)),
    preRun: [
      function preloadConfiguredFiles() {
        const files = config.preloadFiles || [];
        for (const file of files) {
          if (!file.url || !file.path) {
            continue;
          }
          const dir = dirname(file.path);
          const name = basename(file.path);
          try {
            if (typeof FS_createPath === "function") {
              FS_createPath("/", dir.replace(/^\//, ""), true, true);
            }
            if (typeof FS_createPreloadedFile === "function") {
              FS_createPreloadedFile(dir, name, file.url, true, true);
              log(`Preload queued: ${file.path}`);
            } else {
              log("FS_createPreloadedFile is not available in this BoxedWine build");
            }
          } catch (error) {
            log(`Preload failed for ${file.path}: ${error.message}`);
          }
        }
      },
    ],
  };

  await loadScript(config.moduleScriptUrl);
}

main().catch((error) => log(error.stack || error.message));
