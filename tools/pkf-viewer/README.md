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

## Checks

```bash
python3 -m pytest backend/tests -q
npm run build
```
