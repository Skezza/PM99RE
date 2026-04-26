# Player Bitmap Archives

Date: 2026-04-08

## Scope

Document the current research result for player portrait assets so the discovery
 does not live only inside the editor worktree.

## Core Result

- Player portraits are not stored inline in `JUG98030.FDI`.
- The current mirrored player-photo corpus lives in `FDI-PKF/DBDAT/MINIFOTO.PKF`.
- `MINIFOTO.PKF` is the only archive under `FDI-PKF/DBDAT/*.PKF` that exposes
  player-photo records in the `J96#####.BMP` family.
- Total player-photo records found: `1354`
- Total indexed players in `JUG98030.FDI`: `11479`
- Indexed players without a `MINIFOTO` portrait in this corpus: `10125`

## Validation Path

### Stoke City first-pass validation

- Stoke City was used as the first focused validation team.
- Reconstructed Stoke matchday roster coverage is `16/20` portraits present.
- Missing Stoke player IDs in `MINIFOTO.PKF`:
  - `26935`
  - `26936`
  - `33150`
  - `33151`
- Graham Kavanagh validates the archive as a real portrait source:
  - archive record: `J9615578.BMP`
  - player: `Graham KAVANAGH`

### Full-corpus validation

- A full gallery was rendered from the same archive and the same `JUG98030.FDI`
  player index mapping.
- Review output is regenerated locally into:
  `work/player_bitmap_review_<timestamp>/`
- The current generated review path is:
  `work/player_bitmap_review_20260408T114609Z/`

## Palette Findings

- A grayscale render is enough to prove the payloads are real photo-like bitmaps.
- Loose `SIMULPCF6.PAL` renders recognisable faces but with visibly wrong colours.
- The best current render path uses an embedded RIFF palette from `DAT.PKF`:
  - `DAT.PKF@0x225b2#ba71c6264fdd9ad0`
- For `MINIFOTO`, this renders identically to the embedded palette:
  - `DAT.PKF@0x7f974#2d2bceb5304c1937`

## Why This Matters

- The earlier bitmap-reference probe was useful, but incomplete for player
  portraits.
- The real contract for player mini-photos is now known to be archive-backed and
  palette-dependent.
- This should be treated as a read-only asset contract for now:
  archive ownership, export, and visual validation are understood well enough to
  browse; write semantics are still unresolved.

## Upstream Implementation

Reusable implementation lives in the editor repository:

- [app/minifoto_bitmap_archive.py](/home/joe/pm99-research/upstream/pm99-skezmod-db-editor/app/minifoto_bitmap_archive.py)
- [scripts/extract_minifoto_bitmaps.py](/home/joe/pm99-research/upstream/pm99-skezmod-db-editor/scripts/extract_minifoto_bitmaps.py)
- [scripts/build_player_bitmap_review.py](/home/joe/pm99-research/upstream/pm99-skezmod-db-editor/scripts/build_player_bitmap_review.py)
- [app/api.py](/home/joe/pm99-research/upstream/pm99-skezmod-db-editor/app/api.py)

## PM99RE Ownership

PM99RE should retain:

- this investigation note
- the artifact bundle under `artifacts/research/player_bitmap_archive_20260408T114609Z/`
- the repro wrapper `scripts/build_player_bitmap_review.sh`

PM99RE should not retain committed portrait BMP/PNG outputs; keep them under
`work/` only.
