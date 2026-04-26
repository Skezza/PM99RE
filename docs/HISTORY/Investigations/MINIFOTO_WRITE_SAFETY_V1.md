# MINIFOTO Write Safety V1

Date: 2026-04-09

## Scope

Define a reproducible, low-risk write contract for player mini-photo archive edits
in `DBDAT/MINIFOTO.PKF`, with enough evidence for upstream editor integration.

## Implemented Deliverables

- Safe replacement core:
  - `upstream/pm99-skezmod-db-editor/app/minifoto_bitmap_replace.py`
- Public bitmap validator for write guards:
  - `upstream/pm99-skezmod-db-editor/app/minifoto_bitmap_archive.py`
- CLI wrapper:
  - `upstream/pm99-skezmod-db-editor/scripts/replace_minifoto_bitmap.py`
- Proof harness (before/after/diff bundle):
  - `upstream/pm99-skezmod-db-editor/scripts/prove_minifoto_replace.py`
- Tests:
  - `upstream/pm99-skezmod-db-editor/tests/test_minifoto_bitmap_replace.py`
  - `upstream/pm99-skezmod-db-editor/tests/test_prove_minifoto_replace.py`
- Ghidra evidence snapshot:
  - `docs/artifacts/minifoto_write_safety/ghidra_minifoto_loader_evidence_20260409.md`

## V1 Write Contract (Enforced)

`replace_minifoto_bitmap.py` and `replace_minifoto_bitmap_in_bytes(...)` require:

- Target selection resolves exactly one record via `player_record_id` or `file_name`.
- Replacement payload parses as valid MINIFOTO BMP shape:
  - `BM` signature
  - declared size equals payload length
  - OS/2 core DIB (`dib_size == 12`)
  - `planes == 1`
  - `bits_per_pixel == 8`
  - positive `width` and `height`
  - in-bounds pixel window
- Replacement payload length is exactly equal to target `bitmap_length`.
- Replacement `width`, `height`, `bits_per_pixel`, and `pixel_offset` exactly match target.
- Archive byte length must remain unchanged post-patch.
- Post-write parse must preserve target record layout (`record_offset`, `bitmap_offset`, `bitmap_length`).
- Post-write parse must surface replacement bitmap bytes exactly.

This is intentionally strict and does not support archive repacking or offset-table
rewrite yet.

## Ghidra Evidence (DBASEPRE.EXE)

The following anchors were confirmed with GhidraMCP:

- `0x004a6910`: `"J96%05u"`
- `0x004a6934`: `"DBDAT\\MINIFOTO\\%s.bmp"`
- `FUN_0043d420 @ 0x0043d420`: `sprintf(..., "J96%05u", player_id)`
- `FUN_0043db80 @ 0x0043db80`:
  - builds `DBDAT\\MINIFOTO\\%s.bmp` via `sprintf`
  - checks file and dispatches loader call
- `FUN_00445a90 @ 0x00445a90`:
  - extension-dispatch path selects `.BMP` loader branch
  - non-BMP extensions route to different handlers

This ties runtime portrait lookup to a deterministic `J96#####.BMP` naming scheme
and explicit BMP loader dispatch.

## Usage

Dry-run validate only:

```bash
PYTHONPATH=. python3 upstream/pm99-skezmod-db-editor/scripts/replace_minifoto_bitmap.py \
  /abs/path/DBDAT/MINIFOTO.PKF \
  /abs/path/replacement.bmp \
  --player-id 15578 \
  --json
```

Copy-write patch output:

```bash
PYTHONPATH=. python3 upstream/pm99-skezmod-db-editor/scripts/replace_minifoto_bitmap.py \
  /abs/path/DBDAT/MINIFOTO.PKF \
  /abs/path/replacement.bmp \
  --player-id 15578 \
  --output /abs/path/work/MINIFOTO.patched.PKF \
  --json-output docs/artifacts/minifoto_write_safety/minifoto_replace_run.json
```

Proof bundle output:

```bash
PYTHONPATH=. python3 upstream/pm99-skezmod-db-editor/scripts/prove_minifoto_replace.py \
  /abs/path/DBDAT/MINIFOTO.PKF \
  --player-id 15578 \
  --strategy invert \
  --output-dir work/minifoto_write_safety/proof_runs/<timestamp>
```

Latest run artifact:

- `work/minifoto_write_safety/proof_runs/20260409T210403Z/proof_manifest.json`
- summary snapshot:
  `docs/artifacts/minifoto_write_safety/proof_run_latest_summary.json`
- target: `player_id=15578`, file `J9615578.BMP`
- render mode: `palette`
- diff ratio: `1.0` (full-pixel change by design for `invert`)

## Remaining Research

- Confirm if production PKF traversal has a canonical directory/index block that should
  be re-encoded for variable-length replacement support.
- Validate whether any game builds accept alternate BMP layouts beyond current
  parser guards.
- Add end-to-end runner proof that a patched portrait renders correctly in-game.
