# PM99 2025 Roster Alias-Safe Closeout - 2026-04-25

## Status

This milestone is **runtime-proven for an alias-safe partial 2025 roster**, not a complete 100% 2025 database replacement.

Delivered proof:

- 80-club 2025 world-state generated.
- 695 parser-safe player name edits applied to an isolated PM99 game copy.
- 695/695 expected player edits matched after apply.
- Team-name writes suppressed by default because they are runtime-unsafe in the current write surface.
- No roster relinks or division rewrites were applied in the game-ready build.
- Runner visual sample passed for 5 clubs and produced squad-screen screenshots showing 2025 surnames in-game.

## Why this was necessary

Two separate runtime-only failure modes were found:

1. EQ team-name edits can pass parser/global validation but crash MANAGPRE during the new-game transition. These writes are now opt-in investigation work, not default game-ready output.
2. JUG full-name edits can pass parser validation while squad tables still show old names. PM99 reads a fixed runtime alias/surname token from the JUG prefix for squad rows, so the writer now patches that token as well when it can do so without changing payload length.

This means the earlier issue was not a generally corrupted baseline database. The baseline parsed and audited cleanly. The gap was that the editor understood parser-visible names before it understood every runtime-visible name surface used by MANAGPRE.

## Key Artifacts

- World state: `/home/joe/pm99-research/.local/pm99_2025_roster_world_gameready_aliasfix2_20260425T024550Z/world_2025_top80.json`
- Isolated game root: `/home/joe/pm99-research/work/pm99/codex_2025_aliasfix2/pm99_2025_gameready_aliasfix2_20260425T024630Z/game`
- Build manifest: `/home/joe/pm99-research/work/pm99/codex_2025_aliasfix2/pm99_2025_gameready_aliasfix2_20260425T024630Z/patches/full_db_world_build_manifest.json`
- Apply/readiness result: `/home/joe/pm99-research/work/pm99/codex_2025_aliasfix2/pm99_2025_gameready_aliasfix2_20260425T024630Z/patches/full_db_world/apply/apply_result.json`
- Runner visual summary: `/home/joe/pm99-research/upstream/pm99-runner/docs/artifacts/pm99_runner/pm99_2025_aliasfix2_visual5_20260425T024758Z/summary.json`

## Visual Evidence

Runner result: `success: true`.

Visual cases:

- Arsenal: status 0, 28 screenshots, team query `Arsenal`.
- Liverpool: status 0, 28 screenshots, team query `Liverpool`.
- Manchester United: status 0, 28 screenshots, team query `Manchester Utd.`.
- Coventry City: status 0, 31 screenshots, team query `Coventry`.
- Burnley: status 0, 28 screenshots, team query `Sheffield W.` because team renames are suppressed and Burnley is carried by the original Sheffield Wednesday slot.

Representative squad screenshots:

- `/home/joe/pm99-research/upstream/pm99-runner/docs/artifacts/pm99_runner/pm99_2025_aliasfix2_visual5_20260425T024758Z/clubs/arsenal/screens/023_squad_inspect_retry.png`
- `/home/joe/pm99-research/upstream/pm99-runner/docs/artifacts/pm99_runner/pm99_2025_aliasfix2_visual5_20260425T024758Z/clubs/liverpool/screens/023_squad_inspect_retry.png`
- `/home/joe/pm99-research/upstream/pm99-runner/docs/artifacts/pm99_runner/pm99_2025_aliasfix2_visual5_20260425T024758Z/clubs/manchester_united/screens/023_squad_inspect_retry.png`
- `/home/joe/pm99-research/upstream/pm99-runner/docs/artifacts/pm99_runner/pm99_2025_aliasfix2_visual5_20260425T024758Z/clubs/coventry_city/screens/026_squad_inspect.png`
- `/home/joe/pm99-research/upstream/pm99-runner/docs/artifacts/pm99_runner/pm99_2025_aliasfix2_visual5_20260425T024758Z/clubs/burnley/screens/023_squad_inspect_retry.png`

## Code Changes

- `upstream/pm99-skezmod-db-editor/app/file_writer.py`
  - Added runtime alias/surname token patching for player-name writes.
  - Preserves decoded payload length.
  - Refuses alias expansion if the runtime token cannot fit.
- `upstream/pm99-skezmod-db-editor/tests/test_file_writer.py`
  - Added tests covering runtime alias token update and alias-expansion refusal.
- `scripts/build_2025_roster_world_state.py`
  - Default suppresses team renames.
  - Adds alias-safety filtering for generated player edits.
- `scripts/run_2025_roster_visual_sample.sh`
  - Fixed multi-case loop handling.
  - Summary success now requires all visual cases to pass.

## Verification Run

Commands passing after the final hardening pass:

```bash
./scripts/dev_editor.sh pytest tests/test_file_writer.py -q
python3 -m py_compile upstream/pm99-skezmod-db-editor/app/file_writer.py scripts/build_2025_roster_world_state.py
bash -n scripts/run_2025_roster_visual_sample.sh
./scripts/dev_editor.sh pytest -m deterministic -q
pytest -q scripts/test_pm99_world_state.py scripts/test_run_full_db_world_proof_matrix.py scripts/test_pm99_runner_modes.py
python3 scripts/check_repo_boundary.py
```

Results:

- `tests/test_file_writer.py`: 4 passed.
- Deterministic editor lane: 386 passed, 47 deselected, 1 warning.
- PM99RE runner/world-state tests: 16 passed.
- Boundary check: OK.

## Remaining Gap To 100% 2025 Editor Coverage

To move from this milestone to true full-DB 2025 roster coverage, the next milestone must cover:

- Runtime-visible alias handling for every player payload family, not just strict alias-safe cases.
- A deliberate policy for surnames that do not fit the old runtime alias token.
- Apostrophe/CP1252 punctuation handling in game-visible names.
- Runtime-safe team display-name writes, or a clearly scoped MANAGPRE patch if the original fixed-width/name-index mechanism cannot support the target team names safely.
- Full runner matrix/OCR validation across all edited clubs, not only the 5-club visual proof sample.
