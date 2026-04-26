# MINIFOTO Replace Proof Harness (2026-04-09)

## Scope

Close the next milestone after V1 write-safety by shipping a reproducible proof
bundle generator for one-record MINIFOTO replacements.

## What Landed

- Added upstream script:
  - `upstream/pm99-skezmod-db-editor/scripts/prove_minifoto_replace.py`
- Added tests:
  - `upstream/pm99-skezmod-db-editor/tests/test_prove_minifoto_replace.py`
- Script docs updated:
  - `upstream/pm99-skezmod-db-editor/scripts/README.md`

The proof harness now:

- picks one `player_id` record from `MINIFOTO.PKF`
- synthesizes a replacement bitmap (`invert` or `xor`) with preserved BMP shape
- applies V1 safe replacement to a patched archive copy
- writes before/after BMP + rendered PNG + diff PNG
- emits `proof_manifest.json` with hashes and pixel-diff metrics

## Verification

Executed:

```bash
pytest -q tests/test_prove_minifoto_replace.py tests/test_minifoto_bitmap_replace.py tests/test_minifoto_bitmap_archive.py
```

Result: `15 passed`.

## Real Corpus Proof Run

Executed:

```bash
PYTHONPATH=. python3 scripts/prove_minifoto_replace.py \
  /home/joe/pm99-research/FDI-PKF/DBDAT/MINIFOTO.PKF \
  --player-id 15578 \
  --strategy invert \
  --output-dir /home/joe/pm99-research/work/minifoto_write_safety/proof_runs/20260409T210403Z \
  --json-output /home/joe/pm99-research/work/minifoto_write_safety/proof_runs/20260409T210403Z/proof_manifest.json
```

Output highlights:

- target file: `J9615578.BMP`
- patched archive path:
  `work/minifoto_write_safety/proof_runs/20260409T210403Z/MINIFOTO.patched.PKF`
- diff ratio: `1.0`
- different pixels: `102400 / 102400`
- palette source:
  `.../FDI-PKF/DAT.PKF@0x225b2#ba71c6264fdd9ad0`
- docs summary snapshot:
  `docs/artifacts/minifoto_write_safety/proof_run_latest_summary.json`

## Notes

This milestone validates replacement safety + artifact reproducibility at archive
level. It does not yet prove in-engine rendering on a gameplay screen.
