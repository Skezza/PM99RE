# Player Bitmap Archive Discovery Handover

Date: 2026-04-08

## Why This Exists

The actual player-bitmap discovery and extraction work was implemented inside
`upstream/pm99-skezmod-db-editor`, but the research workspace for provenance and
evidence is PM99RE. This note anchors the discovery back into PM99RE without
duplicating product code.

## What Was Proven

- Player portraits are not stored as embedded photos inside `JUG98030.FDI`.
- The player-photo corpus lives in `FDI-PKF/DBDAT/MINIFOTO.PKF`.
- `MINIFOTO.PKF` is the only `FDI-PKF/DBDAT/*.PKF` archive in the mirrored corpus
  that exposes `J96#####.BMP` player-photo records.
- Total player portraits found: `1354`
- Total indexed player records in `JUG98030.FDI`: `11479`
- Indexed players without a `MINIFOTO` portrait in this corpus: `10125`

## Validation Notes

- Stoke City was used as the first validation team.
- Reconstructed Stoke matchday coverage is `16/20` portraits present in
  `MINIFOTO.PKF`.
- Missing Stoke player IDs in the archive are:
  - `26935`
  - `26936`
  - `33150`
  - `33151`
- Graham Kavanagh is present as `J9615578.BMP` and validates the archive as a
  real portrait source rather than garbage data.

## Palette Outcome

- A grayscale fallback is enough to prove the payloads are real bitmaps, but not
  enough to recover the correct visual output.
- Loose `SIMULPCF6.PAL` renders recognisable faces with visibly wrong colours.
- The correct current render path uses an embedded RIFF palette from
  `DAT.PKF@0x225b2#ba71c6264fdd9ad0`.
- For `MINIFOTO`, that palette renders identically to the embedded palette
  `DAT.PKF@0x7f974#2d2bceb5304c1937`.

## Where The Code Lives

- Archive and palette helpers:
  [upstream/pm99-skezmod-db-editor/app/minifoto_bitmap_archive.py](/home/joe/pm99-research/upstream/pm99-skezmod-db-editor/app/minifoto_bitmap_archive.py)
- Full corpus gallery builder:
  [upstream/pm99-skezmod-db-editor/scripts/build_player_bitmap_review.py](/home/joe/pm99-research/upstream/pm99-skezmod-db-editor/scripts/build_player_bitmap_review.py)
- Focused extractor:
  [upstream/pm99-skezmod-db-editor/scripts/extract_minifoto_bitmaps.py](/home/joe/pm99-research/upstream/pm99-skezmod-db-editor/scripts/extract_minifoto_bitmaps.py)
- API/UI surface:
  [upstream/pm99-skezmod-db-editor/app/api.py](/home/joe/pm99-research/upstream/pm99-skezmod-db-editor/app/api.py)

## What Was Added In PM99RE

- Research artifact bundle:
  [artifacts/research/player_bitmap_archive_20260408T114609Z/DECISION_MEMO.md](/home/joe/pm99-research/artifacts/research/player_bitmap_archive_20260408T114609Z/DECISION_MEMO.md)
- Repro wrapper:
  [scripts/build_player_bitmap_review.sh](/home/joe/pm99-research/scripts/build_player_bitmap_review.sh)
- Coverage audit tooling:
  [scripts/audit_player_bitmap_coverage.py](/home/joe/pm99-research/scripts/audit_player_bitmap_coverage.py),
  [scripts/audit_player_bitmap_coverage.sh](/home/joe/pm99-research/scripts/audit_player_bitmap_coverage.sh)
- Coverage investigation note:
  [docs/HISTORY/Investigations/PLAYER_BITMAP_COVERAGE_AUDIT.md](/home/joe/pm99-research/docs/HISTORY/Investigations/PLAYER_BITMAP_COVERAGE_AUDIT.md)

## Recommended Workflow

1. Keep extending reusable bitmap extraction/rendering code upstream.
2. Use the PM99RE wrapper to regenerate a local gallery in `work/`.
3. Record only compact evidence and decisions in `artifacts/research/` and
   `docs/HISTORY/agent_work/`.
4. Do not commit extracted portrait BMP/PNG outputs into PM99RE.
