const DEFAULT_CONFIG_PATH = "config/pm99.example.json";

const DEFAULT_BOXEDWINE_CONFIG = Object.freeze({
  boxedWineHtml: "./vendor/boxedwine.html",
  target: "#boxedwine-mount",
  title: "PM99 via BoxedWine",
  width: 800,
  height: 600,
  assets: {
    rootZip: "../assets/rootfs/boxedwine-root.zip",
    appZip: "../assets/apps/pm99-app.zip",
    overlayZips: []
  },
  launch: {
    program: "MANAGPRE.EXE",
    auto: false,
    desktop: false,
    sound: true,
    bpp: 16,
    resolution: "800x600",
    cpu: "p2",
    skipFrameFPS: 0,
    ddrawOverride: "",
    wineEnv: {},
    emscriptenEnv: {}
  },
  query: {}
});

export { DEFAULT_BOXEDWINE_CONFIG, DEFAULT_CONFIG_PATH };

export async function loadBoxedWineConfig(configUrl = DEFAULT_CONFIG_PATH) {
  const response = await fetch(configUrl, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Unable to load BoxedWine config ${configUrl}: ${response.status}`);
  }
  return normalizeBoxedWineConfig(await response.json());
}

export function normalizeBoxedWineConfig(config = {}, overrides = {}) {
  return mergeConfig(DEFAULT_BOXEDWINE_CONFIG, config, overrides);
}

export function buildBoxedWineUrl(config = {}, overrides = {}) {
  const normalized = normalizeBoxedWineConfig(config, overrides);
  const base = new URL(normalized.boxedWineHtml, getDocumentBaseUrl());
  const query = buildBoxedWineQuery(normalized);
  base.search = query ? `?${query}` : "";
  return base.toString();
}

export function mountBoxedWine(targetOrSelector, config = {}, overrides = {}) {
  const normalized = normalizeBoxedWineConfig(config, overrides);
  const target = resolveTarget(targetOrSelector || normalized.target);
  const iframe = document.createElement("iframe");
  const url = buildBoxedWineUrl(normalized);

  iframe.src = url;
  iframe.title = normalized.title;
  iframe.width = String(normalized.width);
  iframe.height = String(normalized.height);
  iframe.loading = "eager";
  iframe.allow = "autoplay; fullscreen; gamepad";
  iframe.sandbox = [
    "allow-downloads",
    "allow-forms",
    "allow-pointer-lock",
    "allow-same-origin",
    "allow-scripts"
  ].join(" ");
  iframe.dataset.backend = "boxedwine";

  target.replaceChildren(iframe);
  iframe.focus();
  return { iframe, url, config: normalized };
}

export function buildBoxedWineQuery(config = {}) {
  const params = [];
  const assets = config.assets || {};
  const launch = config.launch || {};

  addPathParam(params, "root", assets.rootZip);
  addPathParam(params, "app", assets.appZip);
  addOverlayParam(params, assets.overlayZips);

  addQuotedParam(params, "p", launch.program);
  addBooleanParam(params, "auto", launch.auto);
  addBooleanParam(params, "desktop", launch.desktop);
  addBooleanParam(params, "sound", launch.sound);
  addScalarParam(params, "bpp", launch.bpp);
  addScalarParam(params, "resolution", launch.resolution);
  addScalarParam(params, "cpu", launch.cpu);
  addScalarParam(params, "skipFrameFPS", launch.skipFrameFPS);
  addQuotedParam(params, "ddrawOverride", launch.ddrawOverride);
  addWineEnvParam(params, launch.wineEnv);
  addEmscriptenEnvParam(params, launch.emscriptenEnv);

  for (const [key, value] of Object.entries(config.query || {})) {
    addPathParam(params, key, value);
  }

  return params.map(([key, value]) => `${encodeURIComponent(key)}=${value}`).join("&");
}

function addPathParam(params, key, value) {
  if (isBlank(value)) {
    return;
  }
  params.push([key, encodeBoxedWineValue(value, { keepPath: true })]);
}

function addScalarParam(params, key, value) {
  if (isBlank(value)) {
    return;
  }
  params.push([key, encodeBoxedWineValue(value, { keepPath: false })]);
}

function addBooleanParam(params, key, value) {
  if (typeof value !== "boolean") {
    return;
  }
  params.push([key, value ? "true" : "false"]);
}

function addQuotedParam(params, key, value) {
  if (isBlank(value)) {
    return;
  }
  params.push([key, quoteBoxedWineValue(value)]);
}

function addOverlayParam(params, overlayZips) {
  if (!Array.isArray(overlayZips) || overlayZips.length === 0) {
    return;
  }
  const encoded = overlayZips
    .filter((value) => !isBlank(value))
    .map((value) => encodeBoxedWineValue(value, { keepPath: true }));
  if (encoded.length > 0) {
    params.push(["overlay", encoded.join(";")]);
  }
}

function addWineEnvParam(params, wineEnv) {
  const pair = firstEnvironmentPair(wineEnv);
  if (pair) {
    params.push(["env", quoteBoxedWineValue(pair, { keepListSeparators: true })]);
  }
}

function addEmscriptenEnvParam(params, emscriptenEnv) {
  const pairs = environmentPairs(emscriptenEnv);
  if (pairs.length > 0) {
    params.push(["em-env", quoteBoxedWineValue(pairs.join(";"), { keepListSeparators: true })]);
  }
}

function quoteBoxedWineValue(value, options = {}) {
  return `%22${encodeBoxedWineValue(value, options)}%22`;
}

function encodeBoxedWineValue(value, options = {}) {
  let encoded = encodeURIComponent(String(value));
  if (options.keepPath) {
    encoded = encoded.replace(/%2F/gi, "/").replace(/%3A/gi, ":");
  }
  if (options.keepListSeparators) {
    encoded = encoded.replace(/%3A/gi, ":").replace(/%3B/gi, ";");
  }
  return encoded;
}

function firstEnvironmentPair(value) {
  return environmentPairs(value)[0] || "";
}

function environmentPairs(value) {
  if (isBlank(value)) {
    return [];
  }
  if (typeof value === "string") {
    return value.trim() ? [value.trim()] : [];
  }
  if (!isPlainObject(value)) {
    return [];
  }
  return Object.entries(value)
    .filter(([, envValue]) => !isBlank(envValue))
    .map(([envKey, envValue]) => `${envKey}:${envValue}`);
}

function resolveTarget(targetOrSelector) {
  if (typeof targetOrSelector !== "string") {
    return targetOrSelector;
  }
  const target = document.querySelector(targetOrSelector);
  if (!target) {
    throw new Error(`BoxedWine mount target not found: ${targetOrSelector}`);
  }
  return target;
}

function mergeConfig(...configs) {
  const output = {};
  for (const config of configs) {
    if (!isPlainObject(config)) {
      continue;
    }
    for (const [key, value] of Object.entries(config)) {
      if (Array.isArray(value)) {
        output[key] = [...value];
      } else if (isPlainObject(value) && isPlainObject(output[key])) {
        output[key] = mergeConfig(output[key], value);
      } else if (isPlainObject(value)) {
        output[key] = mergeConfig(value);
      } else {
        output[key] = value;
      }
    }
  }
  return output;
}

function isBlank(value) {
  return value === undefined || value === null || String(value).trim() === "";
}

function isPlainObject(value) {
  return Object.prototype.toString.call(value) === "[object Object]";
}

function getDocumentBaseUrl() {
  if (globalThis.document?.baseURI) {
    return globalThis.document.baseURI;
  }
  if (globalThis.location?.href) {
    return globalThis.location.href;
  }
  return "http://127.0.0.1/";
}
