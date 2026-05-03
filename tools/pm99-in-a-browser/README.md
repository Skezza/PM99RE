# PM99 In A Browser

Research harness for testing two browser-hosted PM99 routes:

- BoxedWine: run the Win32 game through Wine compiled for the browser.
- v86: run a Windows 98/2000 guest in a browser x86 emulator, then launch PM99 inside it.

This directory intentionally contains no PM99 binaries, Windows images, Wine
filesystems, BIOS files, or downloaded emulator builds. Put those under
`assets/` and `vendor/`; both are ignored here.

## Quick Start

```bash
cd tools/pm99-in-a-browser
./scripts/prepare_pm99_assets.sh --source ../../work/fixtures/premier-manager-ninety-nine-pristine
./scripts/serve.sh
```

Open `http://127.0.0.1:8099/`.

The page works as a launcher/checklist even before emulator assets are present.
Use `config/*.sample.json` as the starting point for local configs:

- copy `config/boxedwine.sample.json` to `config/boxedwine.local.json`
- copy `config/v86.sample.json` to `config/v86.local.json`

Open-source emulator payloads can be fetched locally:

```bash
npm install
npm run payloads:open
npm test
```

This copies the npm `v86` runtime, downloads v86 BIOS blobs from upstream, and
downloads/extracts the latest BoxedWine Web release. It does not fetch Windows
disk images or PM99 binaries.

For the v86 route, prepare a local Windows 98 raw disk image with
`scripts/prepare_win98_disk.sh` and inject PM99 with
`scripts/inject_pm99_into_win98_disk.py`. See `docs/WIN98_DISK.md`.

When the ignored payload files are present, the Playwright suite also runs live
reachability checks against the staged PM99 zip/ISO, v86 runtime/BIOS, and
BoxedWine Web build. In a clean checkout those live checks skip until the two
asset commands above have been run.

## What "Done" Means Here

This is a concrete harness, not a guaranteed compatibility result. It gives us:

- a shared browser shell with separate BoxedWine and v86 launch paths
- local asset staging from the existing PM99 fixture
- generated PM99 manifest checks
- sample backend configs
- a static server that can load WASM and disk assets by URL

The first real pass/fail is whether each backend reaches the PM99 title screen
with `MANAGPRE.EXE` and the known `640x480x16` DirectDraw path.

## Directory Layout

- `index.html`, `styles.css`, `src/`: shared browser UI and backend adapters
- `boxedwine/`: BoxedWine iframe/module wrapper
- `v86/`: v86 helper notes and local config conventions
- `config/`: sample backend configs
- `scripts/`: asset preparation, validation, and local serving
- `assets/`: ignored PM99/game/generated browser assets
- `vendor/`: ignored downloaded or built emulator runtimes
- `docs/`: notes on each backend and next test plan

## Safety

Do not commit generated `assets/` or `vendor/` contents. The repository root
boundary check still blocks direct PM99 binaries such as `.EXE`, `.FDI`, `.PKF`,
and `.DLL`, but this subdirectory also ignores broader browser payloads such as
`.zip`, `.iso`, `.img`, `.wasm`, and `.data`.
