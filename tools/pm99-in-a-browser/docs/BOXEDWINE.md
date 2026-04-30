# BoxedWine Browser Prototype

This is the BoxedWine backend scaffold for `pm99-in-a-browser`. It is only a
local integration harness: PM99 binaries, PM99 data, Wine filesystems, and
downloaded BoxedWine Web builds must stay outside git.

## Backend Contract

The scaffold assumes a locally supplied BoxedWine Web/Emscripten build whose
HTML accepts the current BoxedWine query parameters:

```text
root=../assets/rootfs/boxedwine-root.zip
app=../assets/apps/pm99-app.zip
overlay=../assets/overlays/optional.zip
p=%22MANAGPRE.EXE%22
auto=false
desktop=false
sound=true
bpp=16
resolution=800x600
cpu=p2
```

`tools/pm99-in-a-browser/boxedwine/static/boxedwine-launcher.js` builds that URL and
embeds it in an iframe. The module does not instantiate Wasm directly; it lets
the supplied BoxedWine HTML/glue own Emscripten `Module`, the canvas, IDBFS,
and Wine startup.

## Asset Contract

Use this local-only layout:

```text
tools/pm99-in-a-browser/boxedwine/
  vendor/boxedwine.html
  vendor/boxedwine-shell.js
  vendor/boxedwine.wasm
  vendor/jszip.min.js
  assets/rootfs/boxedwine-root.zip
  assets/apps/pm99-app.zip
  assets/overlays/*.zip
```

The `vendor/` and `assets/` payload locations are ignored. The checked-in files
only describe where assets go.

The PM99 app zip should be made from an owned local install. It should preserve
the installed file layout expected by Wine and launch `MANAGPRE.EXE` by default.
Do not copy `.EXE`, `.FDI`, `.PKF`, Wine filesystem zips, or generated PM99 app
zips into tracked paths.

## Local Run

```bash
cd tools/pm99-in-a-browser/boxedwine
mkdir -p local
cp config/pm99.example.json local/pm99.local.json
python3 -m http.server 8787
```

Edit `local/pm99.local.json` to match the local filenames, then open:

```text
http://127.0.0.1:8787/?config=local/pm99.local.json
```

Add `&launch=1` to auto-embed the iframe after the config loads. BoxedWine may
still require a user gesture for browser audio.

The top-level `../index.html` uses `../config/boxedwine.sample.json` and embeds
this backend page automatically. Copy that sample to
`../config/boxedwine.local.json` when driving both backends from the shared
launcher.

`boxedwine/launcher.html` is a lower-level direct Emscripten `Module` wrapper
kept as a fallback for BoxedWine builds that do not ship a query-driven HTML
shell.

## Current Assumptions

- The first backend milestone is iframe embedding of a supplied BoxedWine Web
  build, not rebuilding or vendoring BoxedWine.
- BoxedWine resolves `root`, `app`, and `overlay` paths relative to
  `vendor/boxedwine.html`.
- `MANAGPRE.EXE` is the default PM99 runtime executable.
- Browser persistence is owned by BoxedWine IDBFS in the supplied build.
- v86 can be prototyped beside this later, but this scaffold deliberately owns
  only the BoxedWine backend paths.
