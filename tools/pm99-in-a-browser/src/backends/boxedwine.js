import { fetchJson } from "../utils.js";

export const defaultBoxedWineConfig = {
  backend: "boxedwine",
  mode: "iframe",
  iframeUrl: "./boxedwine/launcher.html",
  width: 640,
  height: 480,
};

export async function launchBoxedWine({ screenContainer, config, configUrl, log }) {
  const resolved = { ...defaultBoxedWineConfig, ...config };

  screenContainer.replaceChildren();
  const iframe = document.createElement("iframe");
  iframe.title = "BoxedWine PM99 runtime";
  iframe.allow = "fullscreen; gamepad; cross-origin-isolated";
  iframe.width = String(resolved.width || 640);
  iframe.height = String(resolved.height || 480);

  const src = new URL(resolved.iframeUrl, window.location.href);
  const runtimeConfigUrl = new URL(resolved.packageUrl || configUrl, window.location.href);
  src.searchParams.set("config", runtimeConfigUrl.toString());
  iframe.src = src.toString();
  screenContainer.append(iframe);

  log(`BoxedWine iframe launched with ${runtimeConfigUrl.toString()}`);

  return {
    iframe,
    stop() {
      iframe.remove();
      screenContainer.replaceChildren();
    },
  };
}

export async function loadBoxedWineConfig(url) {
  try {
    return await fetchJson(url);
  } catch (error) {
    if (url.endsWith(".local.json")) {
      const fallbackUrl = "./config/boxedwine.sample.json";
      const config = await fetchJson(fallbackUrl);
      return {
        ...config,
        packageUrl: fallbackUrl,
      };
    }
    throw error;
  }
}
