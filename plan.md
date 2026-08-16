# English 80 Replacement Execution Plan

Last updated: 2026-05-06

## Goal

Create and evidence a modern 80-club English PM99 structure covering the Premier League, First Division, Second Division, and Third Division replacement set. Existing PM99 clubs are relinked or carrier-patched rather than recreated by bulk-renaming unrelated players; missing or new modern clubs receive researched modern replacements and kit records.

## Completed Scope

- [x] Build a division-structured English 80 candidate from the 2025/26 English league source snapshot.
- [x] Allocate 80 clubs and 1,600 player records.
- [x] Preserve squad role shape: goalkeepers in goal, defenders in defence, midfielders in midfield, forwards in attack.
- [x] Patch player semantic fields: visible position, nationality, date of birth, height/weight where available, and deterministic PM99-safe attributes.
- [x] Cap linked rosters to 20 visible players per club so legacy carrier rows do not leak into squad screens.
- [x] Audit all 80 visible club carriers against original PM99 identity and kit records.
- [x] Patch the kit archives so Stoke City remains in the modern First Division while the visible carrier receives Stoke kit art instead of Wolverhampton art.
- [x] Generate the rich HTML evidence page with kit previews, selector screenshots, visual squad proofs, and the full 80-club matrix.
- [x] Run a dense selector sweep across all four English divisions.
- [x] Correct lower-division selector coordinates for Wrexham, AFC Wimbledon, Bromley, and Crawley Town.
- [x] Capture focused in-game selector and squad screenshots for Arsenal, Liverpool, Manchester United, Stoke City, Wrexham, AFC Wimbledon, Bromley, and Crawley Town.

## Current Artifacts

- Game build: `work/pm99/english80_2026_division_structured/english80_2026_division_structured_20260501T212554Z/game/`
- Build manifest: `work/pm99/english80_2026_division_structured/english80_2026_division_structured_20260501T212554Z/division_structured_build_manifest.json`
- Kit patch manifest: `work/pm99/english80_2026_division_structured/english80_2026_division_structured_20260501T212554Z/kit_patch/english80_division_kit_patch_summary.json`
- Corrected selector world: `artifacts/english80_kit_corrected_20260501/english80_corrected_selector_world_dense_20260506.json`
- Dense selector sweep: `upstream/pm99-runner/docs/artifacts/pm99_runner/english80_kit_corrected_selector_dense_20260506/`
- Corrected lower-division visual proof run: `upstream/pm99-runner/docs/artifacts/pm99_runner/english80_kit_corrected_lower_coord_proofs_20260506/`
- HTML evidence page: `artifacts/english80_kit_corrected_20260501/index.html`
- Evidence manifest: `artifacts/english80_kit_corrected_20260501/evidence_manifest.json`

## Evidence Status

- Build manifest: `ok=true`, 80 clubs, 1,600 players.
- Kit patch manifest: `kit_patch_ok=true`.
- Semantic readback: `readback_ok=true`, 1,600 rows.
- Dense selector sweep: `success=true`, 4 divisions, 296 observations.
- Targeted visual proofs: 8/8 verified in the HTML evidence page.
- Lower-division correction proof: Wrexham and AFC Wimbledon are selected in Second Division; Bromley and Crawley Town are selected in Third Division.

## Residual Notes

- PM99 division/competition-byte writes remain deliberately out of scope; the executable contract is the new-game selector and linked roster mapping.
- Attributes are deterministic PM99-safe generated values rather than one-for-one third-party rating imports.
- The older lower-division coordinate drift screenshots are superseded by the 2026-05-06 dense selector sweep and focused lower-division proof run.
