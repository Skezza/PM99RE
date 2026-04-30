export function appendLog(node, message) {
  const stamp = new Date().toISOString().slice(11, 19);
  node.textContent += `[${stamp}] ${message}\n`;
  node.scrollTop = node.scrollHeight;
}

export async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`${url} returned HTTP ${response.status}`);
  }
  return response.json();
}

export function loadScript(url) {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[data-loader-url="${CSS.escape(url)}"]`);
    if (existing) {
      resolve(existing);
      return;
    }

    const script = document.createElement("script");
    script.src = url;
    script.async = true;
    script.dataset.loaderUrl = url;
    script.addEventListener("load", () => resolve(script), { once: true });
    script.addEventListener("error", () => reject(new Error(`Failed to load ${url}`)), { once: true });
    document.head.append(script);
  });
}

export async function urlExists(url) {
  try {
    const head = await fetch(url, { method: "HEAD", cache: "no-store" });
    if (head.ok) {
      return true;
    }
    if (head.status !== 405 && head.status !== 501) {
      return false;
    }
  } catch {
    // Fall through to a tiny GET. Some local servers do not implement HEAD.
  }

  try {
    const response = await fetch(url, {
      cache: "no-store",
      headers: { Range: "bytes=0-0" },
    });
    return response.ok || response.status === 206;
  } catch {
    return false;
  }
}

export function setChildren(node, children) {
  node.replaceChildren(...children);
}

export function el(tag, attrs = {}, text = "") {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "className") {
      node.className = value;
    } else if (key === "dataset") {
      Object.assign(node.dataset, value);
    } else {
      node.setAttribute(key, value);
    }
  }
  if (text) {
    node.textContent = text;
  }
  return node;
}
