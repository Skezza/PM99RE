# PM99 BoxedWine Browser Scaffold

This directory is a static scaffold for testing PM99 through a locally supplied
BoxedWine Web/Emscripten build. It intentionally does not include BoxedWine,
Wine root filesystems, PM99 binaries, PM99 data files, or downloaded vendor
JavaScript.

## Layout

```text
boxedwine/
  index.html                         # Small local host page for the iframe launcher
  static/boxedwine-launcher.js       # Dependency-free launcher module
  config/pm99.example.json           # Example launch config with placeholder paths
  vendor/                            # Local BoxedWine Web build, ignored by git
  assets/rootfs/                     # Local BoxedWine Wine root zip, ignored by git
  assets/apps/                       # Local PM99 app zip, ignored by git
  assets/overlays/                   # Optional local overlay zips, ignored by git
```

Expected local-only files:

```text
vendor/boxedwine.html
vendor/boxedwine-shell.js
vendor/boxedwine.wasm
vendor/jszip.min.js                  # Only if required by the chosen BoxedWine build
assets/rootfs/boxedwine-root.zip
assets/apps/pm99-app.zip
assets/overlays/*.zip
```

The asset paths in `config/pm99.example.json` are passed to
`vendor/boxedwine.html` and are resolved relative to that HTML file. For the
layout above, paths therefore start with `../assets/...`.

## Local Smoke Run

Copy `config/pm99.example.json` to an ignored local config, adjust the asset
filenames, then serve this directory over HTTP:

```bash
cd tools/pm99-in-a-browser/boxedwine
mkdir -p local
cp config/pm99.example.json local/pm99.local.json
python3 -m http.server 8787
```

Open:

```text
http://127.0.0.1:8787/?config=local/pm99.local.json
```

Use owned PM99 installation media or an owned isolated game directory when
creating the app zip. Keep those files in ignored asset directories only.
