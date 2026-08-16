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

## Native-Club Runtime Closure

The follow-up closure pass switched to native-club route capture instead of the
Stoke surrogate. This validates the records in the squads where MANAGPRE already
expects them to be visible.

Builder output:

- `.local/full_game_variable_name_native_english30_20260503T_probe`
- Lean game root: `.local/full_game_variable_name_native_english30_20260503T_probe/game`
- DB readback: 30/30 selected linked roster rows show the patched target name
- Selected family: 30 `dd6361_indexed_suffix_static` records
- Target names: short variable-length synthetic names `AA A` through `BD V`

Runner output:

- `fullgame_varwin_native_english30_fast_b01_20260503T_runtime`: 10/10 clubs status `0`
- `fullgame_varwin_native_english30_fast_b02_20260503T_runtime`: 10/10 clubs status `0`
- `fullgame_varwin_native_english30_fast_b03_20260503T_runtime`: 10/10 clubs status `0`
- Total native-club proof: 30/30 clubs status `0`, no crashes, no debugger
- Capture mode: screenshot-only route proof with classification skipped to avoid
  using OCR as the gate. The slower full-OCR pass captured screenshots too, but
  some clubs were falsely marked failed because OCR saw stat rows without header
  words.

Additional runner fix:

- `upstream/pm99-runner/scripts/pm99_runner/stoke_season_driver.py` now treats a
  dense numeric squad stat table as a squad-route signal when OCR misses the
  header text.

Native proof pack:

- `docs/artifacts/full_game_variable_name_windows_20260503/native_english30_runtime.html`
- `docs/artifacts/full_game_variable_name_windows_20260503/native_english30_runtime_summary.json`
- `docs/artifacts/full_game_variable_name_windows_20260503/native_english30_runtime_page.png`
- `docs/artifacts/full_game_variable_name_windows_20260503/native_english30_screens/`

Closure interpretation:

- DB-only variable-length names are proven feasible for the sampled native
  English playable-club roster path.
- This specifically proves the `dd6361_indexed_suffix_static` linked-player
  family in-game across 30 native clubs.
- It does not turn the current editor into a full safe editor yet. Full coverage
  still needs the editor contract layer to expose both proven families:
  bounded `dd6360_gap3/gap4` compact windows and `dd6361_indexed_suffix_static`
  suffix rewrites, plus unresolved-record handling.

## Full Playable-Club And Editor Proof

Note: the editor-product proof in this section records the earlier compact-growth
prototype. It is superseded by the 2026-05-05 native-stream editor contract
update below.

Further iteration separated whole-corpus static coverage from practical playable
club runtime coverage.

Playable vanilla roster linkage:

- Playable linked roster rows: 1,865
- Clubs with linked rows: 80/80
- `dd6361_indexed_suffix_static`: 1,863 linked rows across 80/80 clubs
- `dd6360_gap3`: 1 linked row, Liverpool only
- `dd6360_gap4`: 1 linked row, Arsenal only
- `opaque_or_unresolved`: 0 linked rows

This means the native playable-club visual route is primarily a `dd6361` proof.
The rare playable `dd6360` rows are covered by the editor/runtime growth proof
below and by the static full-corpus window scan.

Existing English80 current-squad runtime proof:

- Build: `work/pm99/english80_2026_variable_names/english80_2026_variable_names_20260502T031034Z_fresh`
- Evidence HTML: `work/pm99/english80_2026_variable_names/english80_2026_variable_names_20260502T031034Z_fresh/evidence/english80_variable_name_evidence.html`
- Evidence JSON: `work/pm99/english80_2026_variable_names/english80_2026_variable_names_20260502T031034Z_fresh/evidence/english80_variable_name_evidence.json`
- Source snapshot date: 2026-05-02
- Clubs: 80/80
- Players: 1,600, 20 per club
- Target/applied name readback: 1,600/1,600
- Runner: 80/80 clubs ok
- Squad screenshot evidence: 80/80
- Valid squad-screen evidence: 80/80
- Payload growth: 22 rows, max `+8` bytes
- Payload same length: 1,578 rows
- Payload shrink: 0 rows

Editor product-path proof:

- Proof output: `.local/editor_variable_name_english80_1600_20260503T150757Z`
- Input build: `work/pm99/english80_2026_division_structured/english80_2026_division_structured_20260502T025541Z_fresh`
- Targets: 1,600 FootballSquads-backed names
- Plan result: ok, 842 ready writes, 758 noops, 0 blocked
- Apply result: ok, 842 writes, 0 post-write failures
- Family counts: 842 `dd6360_gap3_compact_move`, 758 noops
- Payload growth: 22 rows, max `+8` bytes

The editor now exposes the proven DB-only contracts instead of leaving them only
in research scripts:

- `dd6360_gap3/gap4` compact name rewrites, including proven payload growth up
  to `+8` bytes.
- `dd6361` indexed suffix rewrites.
- Short/opaque payloads and `dd6360` growth beyond the proven `+8` byte runtime
  contract remain fail-closed.

Validation:

- `./scripts/dev_editor.sh pytest tests/test_player_variable_names.py -q`: 9 passed
- `./scripts/dev_editor.sh pytest -m deterministic -q`: 438 passed, 3 skipped, 47 deselected
- `./scripts/dev_editor.sh pytest -q`: 445 passed, 44 skipped
- `python3 scripts/check_repo_boundary.py`: pass

Current closure boundary:

- The practical playable-club variable-name milestone is proven for all 80
  playable English clubs and the 1,600-player current-squad replacement build.
- The editor path can now plan/apply the same 1,600-name target set with no
  blocked rows and no post-write readback failures.
- This is still not a claim that every one of the 11,479 indexed JUG rows has
  been visually opened in-game. The full static scan covers those rows; runtime
  proof is scoped to playable clubs/current squads, while 22 opaque/unresolved
  rows remain preserve-only.

## Native-Stream Editor Contract Update - 2026-05-05

The compact-growth `dd6360` writer was replaced with the MANAGPRE-native stream
contract. This is the current product contract.

Current supported editor families:

- `dd6360_native_stream_gap3`
- `dd6360_native_stream_gap4`
- `dd6361_indexed_suffix`

Important correction:

- `dd6360` is now a fixed native-window rewrite, not an arbitrary payload-growth
  path. The game consumes bytes `5..7`, then reads two XOR/u16 strings starting
  at byte `8`. The semantic role/metadata block follows those strings.
- The product writer rewrites the native strings, moves the semantic block left
  for shorter names, preserves payload length, and blocks any target that would
  push the semantic block beyond the original native role start.
- `dd6361` remains an indexed suffix rewrite and can resize safely because the
  `DMFIv1.0` directory is rebuilt.

Full real-DB editor proof:

- Input: `DBDAT/JUG98030.FDI`
- Target rows: 11,457 parser-backed indexed player records
- Plan: 11,457 ready, 0 blocked, 0 noop
- Apply: 11,457 applied, 0 post-write failures
- Payload same length: 9,331
- Payload shrank: 2,126
- Payload grew: 0
- Family counts:
  - `dd6360_native_stream_gap3`: 6,419
  - `dd6360_native_stream_gap4`: 2,912
  - `dd6361_indexed_suffix`: 2,126
- Reopen validation: `all_valid=true`, `valid_count=11457`,
  `uncertain_count=0`, detail `re-opened cleanly`

The target-only proof intentionally avoided stale `current_name` guards because
12 rows in older research target artifacts had stale expected names from prior
experimental edits. With `current_name` supplied, those rows fail closed as
`stale_current_name_mismatch`, which is the desired editor behavior.

Upstream product implementation note:

- `upstream/pm99-skezmod-db-editor/docs/PLAYER_VARIABLE_NAME_EDITOR_CONTRACT.md`

Validation:

- `./scripts/dev_editor.sh pytest tests/test_player_variable_names.py -q`:
  10 passed
- `./scripts/dev_editor.sh pytest -m deterministic -q`: 440 passed
- `./scripts/dev_editor.sh pytest -q`: 446 passed, 44 skipped
- `python3 scripts/check_repo_boundary.py`: pass
