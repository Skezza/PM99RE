# PM99 SIMULDAT PKF Viewer

Standalone local web tool for browsing SIMULDAT `.PKF` containers. It is
separate from the database editor and does not write extracted proprietary
assets by default.

## What It Does

- Scans a local SIMULDAT directory for `.PKF` files.
- Parses PKF offset tables and continuation tables.
- Shows tables, slots, offsets, lengths, descriptor bytes, hashes, kinds, and
  image dimensions.
- Streams BMP/GIF previews directly from PKF records.
- Repairs preview-only rendering for palette-indexed BMP records that omit an
  embedded BMP palette by injecting `SIMULPCF6.PAL` when available, or a
  generated grayscale palette as a last resort. The underlying PKF bytes are
  not changed.
- Shows RIFF/PAL palette swatches as JSON-driven UI.
- Profiles P3D-like binary chunks with magic class, embedded labels, first
  dwords, printable strings, and float-density clues.
- Filters P3D-like records by observed subfamily and marks duplicate payloads
  across the loaded corpus.
- Shows loader-derived P3D hints, including decoded marker counts, optional
  header dwords, record-stream offsets, and `0x80`-byte chunk estimates.
- Shows the first inner body marker after the first `0x80` object header, which
  is the next parser branch used by the game.
- Samples detected names from the first complete `0x80` chunks in each P3D
  stream.
- Provides a Menu Atlas view that groups discovered UI backgrounds, button
  strips, resource-database sprites, icons, and layout strips. Each card opens
  the exact PKF table/slot record needed for replacement work.
- Scores Menu Atlas images by luminance and color variety, then hides
  mask/blank-like records by default so the main view focuses on editable
  artwork. The hidden records remain available from the atlas toggle.

## Setup

```bash
cd tools/pkf-viewer
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
npm install
```

## Run

In one terminal:

```bash
cd tools/pkf-viewer
. .venv/bin/activate
npm run backend
```

In another terminal:

```bash
cd tools/pkf-viewer
npm run dev
```

Open the Vite URL shown by `npm run dev`.

By default the backend uses:

```text
.local/iso/Simuldat
```

Override it with:

```bash
PM99_SIMULDAT_ROOT=/path/to/SIMULDAT npm run backend
```

For the full menu atlas, point the backend at the game root that contains both
root PKFs and `Simuldat`:

```bash
PM99_SIMULDAT_ROOT=/path/to/game-root npm run backend
```

Runtime screen captures are read from `.local/runlogs/pm99_runner` by default.
Override that with `PM99_RUNLOG_ROOT` if needed.

## Menu Asset Evidence

The Menu Atlas is asset-only by default. It groups static UI assets from the
game root PKFs: `RC_DBASE.PKF`, `Recursos.pkf`,
  `Simuldat/menus.pkf`, `Img.pkf`, `Simuldat/Iconos.pkf`,
  `Simuldat/Texturas/OTROS.pkf`, and `dat.pkf`.

With `PM99_SIMULDAT_ROOT` pointed at the local game root used during the
investigation, the validated atlas contains 407 static menu/UI image records.
Many PKFs also contain near-black masks, blank states, and tiny control
fragments. The atlas keeps those records for forensic access but filters them
from the default view when their pixel data is objectively low-information.
Some large PM99 BMP records store 8-bit indices without an embedded BMP
palette. The browser would otherwise show those as black/near-black previews,
so the API uses the game palette only for preview rendering and labels the
palette source on each card.

The backend still has an optional `include_runtime=true` query flag for
debugging runner evidence, but the UI intentionally does not show runtime
screenshots in the asset atlas.

## Checks

```bash
python3 -m pytest backend/tests -q
npm run build
```
