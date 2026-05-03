# Stoke Variable Name Length Boundaries - 2026-05-03

## Scope

Stoke-only runtime proof for the compact `dd6360` fixed-80-byte linked-player
payload contract. This pass intentionally proves the smallest and largest names
we can currently certify for the Stoke squad path without patching
`MANAGPRE.EXE`.

This is not a global all-player or all-club limit. It is the current Stoke
compact payload contract: the variable name prefix must fit before the existing
role/metadata block, and shortened names move fixed-window padding to the tail
while preserving the total payload length.

## Result

Certified working range for this Stoke compact contract:

- Shortest accepted: `AB Z`
- Shortest accepted visible length: 4 characters
- Shortest accepted encoded prefix: 9 bytes
- Longest accepted: `ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE Z`
- Longest accepted visible length: 33 characters
- Longest accepted encoded prefix: 38 bytes

Rejected adjacent boundary probes:

- Too short: `A B`, 3 visible characters, 8-byte prefix
- Too short failure: `Parser name_end mismatch for 'A B': expected 19, got 20`
- Too long: `ABCDEFGHIJKLMNOPQRSTUVWXYZABCDEF Z`, 34 visible characters, 39-byte prefix
- Too long failure: `Natural variable prefix for 'ABCDEFGHIJKLMNOPQRSTUVWXYZABCDEF Z' exceeds compact name window: new_role_start=47, old_role_start=46`

## Runtime Evidence

Final runner tag:

- `stoke_varname_length_boundaries_20260503T_runtime_r2`

Runner summary:

- `success=true`
- `profile_capture_ok=true`
- `profile_capture_count=2`
- `profile_capture_expected=2`
- `crash_detected=false`
- `wine_debugger_detected=false`

Visual proof screenshots:

- `upstream/pm99-runner/docs/artifacts/pm99_runner/stoke_varname_length_boundaries_20260503T_runtime_r2/screens/31_profile_open_01.png`
- `upstream/pm99-runner/docs/artifacts/pm99_runner/stoke_varname_length_boundaries_20260503T_runtime_r2/screens/34_profile_open_02.png`

Surfaced HTML proof:

- `docs/artifacts/stoke_variable_name_length_boundaries_20260503/index.html`
- Browser render: `docs/artifacts/stoke_variable_name_length_boundaries_20260503/page_render.png`

## Static Evidence

Generated Stoke proof root:

- `.local/stoke_variable_name_length_boundaries_20260503T_probe`

Copied proof data:

- `docs/artifacts/stoke_variable_name_length_boundaries_20260503/data/boundary_manifest.json`
- `docs/artifacts/stoke_variable_name_length_boundaries_20260503/data/validate_database.json`
- `docs/artifacts/stoke_variable_name_length_boundaries_20260503/data/team_roster_runtime_audit.json`
- `docs/artifacts/stoke_variable_name_length_boundaries_20260503/data/team_roster_linked.json`
- `docs/artifacts/stoke_variable_name_length_boundaries_20260503/data/runner_summary.json`

Static gates:

- `validate-database`: all valid
- Stoke `team-roster-runtime-audit`: `issue_count=0`, `warning_count=0`
- Stoke linked roster slot 1: `AB Z`
- Stoke linked roster slot 2: `ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE Z`

JUG hash after proof generation:

- `145d3becff362aaa760b858f949e642a9cbe8702558ff0dda030794fb16e0f48`

## Commands

```bash
python3 scripts/probe_stoke_variable_name_length_boundaries.py \
  --out-game .local/stoke_variable_name_length_boundaries_20260503T_probe \
  --force

./scripts/dev_editor.sh python3 -m app.cli validate-database \
  --players /home/joe/pm99-research/.local/stoke_variable_name_length_boundaries_20260503T_probe/DBDAT/JUG98030.FDI \
  --teams /home/joe/pm99-research/.local/stoke_variable_name_length_boundaries_20260503T_probe/DBDAT/EQ98030.FDI \
  --coaches /home/joe/pm99-research/.local/stoke_variable_name_length_boundaries_20260503T_probe/DBDAT/ENT98030.FDI \
  --json

./scripts/dev_editor.sh python3 -m app.cli team-roster-runtime-audit \
  /home/joe/pm99-research/.local/stoke_variable_name_length_boundaries_20260503T_probe/DBDAT/EQ98030.FDI \
  --player-file /home/joe/pm99-research/.local/stoke_variable_name_length_boundaries_20260503T_probe/DBDAT/JUG98030.FDI \
  --team Stoke --json

TAG=stoke_varname_length_boundaries_20260503T_runtime_r2
PM99_RUNNER_WORKER_LANE_COUNT=2 PM99_RUNNER_DOCKER_TIMEOUT_SECONDS=1800 \
./scripts/run_stoke_profile_capture_with_dbdat_overrides.sh \
  --game-root .local/stoke_variable_name_length_boundaries_20260503T_probe \
  --run-tag "$TAG" \
  --profile-count 2 \
  --skip-setup --skip-build --skip-prepare \
  --cleanup-on-failure
```

## Caveat

The high bound is constrained by the current DB-only compact writer preserving
the existing fixed-80 payload and the role/metadata cursor. It does not prove
that every PM99 player record has the same available name-prefix window, nor
that longer names are impossible with a broader indexed-payload rewrite or an
EXE-level contract change.
