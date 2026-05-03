# Full-Game Variable Player Name Windows - 2026-05-03

## Scope

Research pass over the clean PM99 JUG player corpus to answer whether every
player record has the same DB-only variable-name window, then validate the
findings with the PM99 runner.

This pass intentionally separates two contracts:

- Static name-window contract: can the indexed JUG payload be rewritten while
  preserving parser anchors and fixed payload length?
- Runtime Squad Management visibility contract: will MANAGPRE show the linked
  player in the in-game Current Squad table when surfaced through Stoke?

## Static Result

Every player record does **not** have the same usable variable-name window.

Inventory from `.local/full_game_variable_name_windows_runtime_visible_20260503T_probe`:

- Indexed player records: 11,479
- Parser-backed records: 11,457
- `dd6360_gap3`: 6,419
- `dd6360_gap4`: 2,912
- `dd6361_indexed_suffix_static`: 2,126
- Opaque/unresolved: 22
- `dd6360` max prefix bytes: 10..66
- `dd6360` max visible chars with one-letter surname: 5..61
- `AB Z` shortest probe: 6,614 accepted, 2,717 rejected
- `A B` too-short probe: 2,919 accepted, 6,412 rejected
- Per-record max probe: 9,330 accepted, 1 rejected
- Max+1 probe: 9,331 rejected

Important interpretation: the Stoke-only fixed-80 proof is not a universal
limit. The full corpus contains multiple compact families and different usable
prefix windows.

## Runner Validation

Primary 30-team spot-check attempt:

- 59 sampled `dd6360` records from 30 source teams
- Families: 29 `dd6360_gap3`, 30 `dd6360_gap4`
- Target cases: 29 shortest accepted, 30 per-record max prefix
- Static validation: all three generated batch DBDAT sets reopened cleanly
- Stoke runtime audit: zero issues; only `linked_player_shared_ref` warnings

Runner tags:

- `fullgame_varwin_30teams_visible_b01_20260503T_runtime`: `success=true`, `profile_capture_ok=true`, no crash/debugger
- `fullgame_varwin_30teams_visible_b02_20260503T_runtime`: `success=false`, no crash/debugger; Current Squad table was empty
- `fullgame_varwin_30teams_visible_b02_no14079_squad_20260503T_runtime`: `success=true`, no crash/debugger; removing the largest-prefix record restored the table, but only one sampled player was visible
- `fullgame_varwin_30teams_visible_b03_squadonly_20260503T_runtime`: `success=true`, no crash/debugger; sampled rows hidden, original Stoke row remained

Follow-up unique-short-name scans:

- `fullgame_varwin_first30_scan_b01_squad_20260503T_runtime`: many renamed rows visible
- `fullgame_varwin_first30_scan_b02_squad_20260503T_runtime`: several renamed rows visible, plus original Stoke rows
- `fullgame_varwin_next34_scan_b01_squad_20260503T_runtime`: sampled rows hidden
- `fullgame_varwin_next34_scan_b02_squad_20260503T_runtime`: sampled rows hidden, original Stoke rows remained

Status-filter follow-up:

- Added non-default `--squad-enable-status-filters` support to the Stoke profile-capture lane, mirroring the multi-club route runner.
- `fullgame_varwin_first30_scan_b01_filters_squad_20260503T_runtime` did not reveal additional rows.
- `fullgame_varwin_first30_scan_b02_filters_squad_20260503T_runtime` did not reveal additional rows.

## Evidence Pack

Surfaced HTML proof:

- `docs/artifacts/full_game_variable_name_windows_20260503/index.html`
- Browser render: `docs/artifacts/full_game_variable_name_windows_20260503/page_render.png`

Key copied data:

- `docs/artifacts/full_game_variable_name_windows_20260503/data/window_summary.json`
- `docs/artifacts/full_game_variable_name_windows_20260503/data/original_spotcheck_samples.json`
- `docs/artifacts/full_game_variable_name_windows_20260503/data/first30_scan_samples.json`
- `docs/artifacts/full_game_variable_name_windows_20260503/data/next34_scan_samples.json`

Representative screenshots:

- `docs/artifacts/full_game_variable_name_windows_20260503/screens/original_batch01_squad.png`
- `docs/artifacts/full_game_variable_name_windows_20260503/screens/original_batch02_empty_squad.png`
- `docs/artifacts/full_game_variable_name_windows_20260503/screens/original_batch02_no14079_one_visible.png`
- `docs/artifacts/full_game_variable_name_windows_20260503/screens/original_batch03_stoke_only.png`
- `docs/artifacts/full_game_variable_name_windows_20260503/screens/first30_scan_batch01.png`
- `docs/artifacts/full_game_variable_name_windows_20260503/screens/first30_scan_batch02.png`
- `docs/artifacts/full_game_variable_name_windows_20260503/screens/next34_scan_batch01_empty.png`
- `docs/artifacts/full_game_variable_name_windows_20260503/screens/next34_scan_batch02_stoke_only.png`

## Conclusion

The static variable-name window research pass is complete enough to prove the
main question: no, every player record does not have the same usable DB-only
window.

The runner pass uncovered a separate blocker: Stoke-surrogate visual validation
cannot be used as a universal oracle for arbitrary player records until we model
MANAGPRE's current-squad visibility/status contract. The hidden rows are not
parser corruption and not an EXE crash; the game starts cleanly and stays stable,
but filters many linked records out of the Current Squad table.

## Next Required Contract

To reach full editor-grade coverage, the next milestone is not more name-window
probing. It is mapping the runtime squad visibility lanes used by MANAGPRE so a
runner proof can surface arbitrary records safely, or switching visual proof to
native-club route capture so players are viewed in their original squad context.
