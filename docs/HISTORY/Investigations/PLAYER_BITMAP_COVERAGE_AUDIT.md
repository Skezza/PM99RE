# Player Bitmap Coverage Audit

Date: 2026-04-08

## Goal

Freeze a reproducible answer to:

- how many indexed players have static bitmaps;
- where those bitmaps are sourced;
- whether missing photos are extraction misses or absent source data.

## Reproducible Method

Run the PM99RE wrapper:

```bash
./scripts/audit_player_bitmap_coverage.sh
```

That writes a timestamped artifact bundle under:

- `artifacts/research/player_bitmap_coverage_<timestamp>/summary.json`
- `artifacts/research/player_bitmap_coverage_<timestamp>/metadata.json`
- `artifacts/research/player_bitmap_coverage_<timestamp>/DECISION_MEMO.md`

The wrapper executes:

- `scripts/audit_player_bitmap_coverage.py`
- with `--include-payload-scan` for decoded JUG payload embedded-image validation;
- with executable marker checks when `DBASEPRE` is available locally.

## Evidence Contract

`summary.json` includes:

- coverage totals (`jug_players`, `combined_unique_photo_ids`, coverage percentages);
- source-family sweep (`MINIFOTO`, `BIGFOTO`, and unexpected `J96` families if any);
- file SHA256 values for reproducibility;
- executable marker evidence:
  - `J96%05u`
  - `DBDAT\\MINIFOTO\\%s.bmp`
  - `DBDAT\\BIGFOTO\\`
  - `%seq96%04d\\%s.bmp`
- payload scan outcome (`total_validated_images`) from `discover_player_bitmap_payloads`.

## Current Findings (Local Corpus)

Observed results from the 2026-04-08 audit run:

- Evidence bundle:
  `artifacts/research/player_bitmap_coverage_20260408T182419Z/`

- Indexed players in JUG: `11,479`
- `MINIFOTO` unique player IDs: `1,354`
- `BIGFOTO` unique player IDs: `1,285`
- Combined unique player IDs with any static photo: `1,355`
- Players without any static photo in JUG: `10,125`
- Combined static-photo coverage: `11.7955%`
- `MINIFOTO` mirrors are byte-identical across known corpus copies (same SHA256).
- Payload scan validates `0` embedded images in decoded JUG payloads.

Interpretation:

- In this corpus, missing player bitmaps are absent source data, not an extraction gap.

## Upstream Adoption Path

This work is directly promotable into upstream editor tooling.

Recommended upstream implementation targets:

- `upstream/pm99-skezmod-db-editor/app/minifoto_bitmap_archive.py`
- `upstream/pm99-skezmod-db-editor/app/fdi_indexed.py`
- `upstream/pm99-skezmod-db-editor/app/player_bitmap_discovery.py`

Recommended upstream deliverables:

1. Add a first-class audit command/API endpoint that emits the same `summary.json` schema.
2. Add regression tests asserting source-family detection (`MINIFOTO`/`BIGFOTO`) and coverage math stability.
3. Add a UI/readout panel for bitmap coverage and corpus evidence hashes.

## Related PM99RE Files

- [scripts/audit_player_bitmap_coverage.py](/home/joe/pm99-research/scripts/audit_player_bitmap_coverage.py)
- [scripts/audit_player_bitmap_coverage.sh](/home/joe/pm99-research/scripts/audit_player_bitmap_coverage.sh)
- [2026-04-08 player bitmap handover](/home/joe/pm99-research/docs/HISTORY/agent_work/2026-04-08_player_bitmap_archive_discovery.md)
