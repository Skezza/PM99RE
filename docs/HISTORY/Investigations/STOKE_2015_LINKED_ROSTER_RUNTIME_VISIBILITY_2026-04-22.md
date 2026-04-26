# Stoke 2015 Linked Roster Runtime Visibility

Date: 2026-04-22

## Summary

The Stoke 2015 squad-management failure was not explained by static roster linkage alone. The `EQ98030.FDI -> JUG98030.FDI` linked roster row can point at the intended player record and still be hidden by MANAGPRE at runtime.

The specific confirmed failure class is a short linked-player `JUG` payload. Jack Butland resolved correctly from the Stoke linked roster slot, but his indexed player payload was only 65 bytes in the failing candidate. MANAGPRE's Squad Management path applies an additional runtime current-squad filter after static roster resolution; the short payload did not satisfy that path.

## Evidence

Ghidra analysis identified the relevant runtime filter in `MANAGPRE.EXE` around `FUN_004b9e80`: current-squad rows are skipped when the loaded player runtime team/status field does not match the selected team context. An EXE bypass of the branch proved this was a visibility filter, not a missing static roster row.

The EXE bypass is not the desired editor solution. A DB-only payload repair also made Butland visible and captured the full 20-player Stoke squad without crashing.

Key artifacts:

- Failing-but-stable candidate: `work/pm99/joe/stoke_sameentry20_imbula_visible_20260422T0850Z/game`
- Proven DB-only repaired candidate: `work/pm99/joe/stoke_2015_full_visible_small_butland_team3425_20260422T0920Z/game`
- Editor-generated repaired candidate: `work/pm99/joe/stoke_editor_repair_linked_payload_20260422T212327Z/game`
- Guarded editor-generated repaired candidate: `work/pm99/joe/stoke_editor_repair_linked_payload_guarded_20260422T214056Z/game`
- Clean guarded editor runner proof: `upstream/pm99-runner/docs/artifacts/pm99_runner/stoke_editor_repair_guarded_row15_20260422T221307Z_profiles20`

The editor-generated repair produced a Butland payload byte-identical to the previously runner-proven DB-only candidate:

```text
editor length 130 head 610ddd6361dee16066614275746c616e
proven length 130 head 610ddd6361dee16066614275746c616e
payloads_equal True
```

## Editor Changes

The editor now has a scoped runtime visibility audit:

```bash
./scripts/dev_editor.sh python3 -m app.cli team-roster-runtime-audit \
  DBDAT/EQ98030.FDI \
  --player-file DBDAT/JUG98030.FDI \
  --team Stoke
```

It flags linked roster rows whose player payload is too short to certify for the Squad Management runtime path:

```text
current_squad_filter_unsafe_short_payload
```

The release audit can opt into this gate for edited teams:

```bash
./scripts/dev_editor.sh python3 -m app.cli team-release-audit \
  DBDAT/EQ98030.FDI \
  --player-file DBDAT/JUG98030.FDI \
  --coach-file DBDAT/ENT98030.FDI \
  --linked-runtime-team Stoke
```

The editor also now has a targeted repair command:

```bash
./scripts/dev_editor.sh python3 -m app.cli team-roster-repair-linked-payload \
  DBDAT/EQ98030.FDI \
  --player-file DBDAT/JUG98030.FDI \
  --team Stoke \
  --slot 1 \
  --template-player-id 32959 \
  --team-id 3425
```

For the Stoke/Butland repair, the command performs this transformation:

```text
Jack Butland pid=3445
payload length: 65 -> 130
template pid: 32959 Jonathan Walters
replacement offset: 8
text token: 'faWaltersqaJonathan Walters' -> 'faButlandqaJack Butland    '
team id written: 3425
```

The write goes through the indexed FDI staged writer, so payload lengths and directory offsets are rebuilt rather than patched in place. The command now refuses targets that already have certifiable payload lengths and refuses templates below the runtime-safety length threshold, to reduce accidental opaque-field cloning outside this failure class.

## Validation

Focused tests:

```text
./scripts/dev_editor.sh pytest -q tests/test_team_roster_linked_edit.py
20 passed

./scripts/dev_editor.sh pytest -q tests/test_team_roster_linked_edit.py tests/test_team_coach_links.py::test_build_team_release_audit_enforces_linked_runtime_team_query_matches
21 passed
```

Static checks:

```text
python3 -m py_compile app/editor_actions.py app/cli.py tests/test_team_roster_linked_edit.py
python3 scripts/check_repo_boundary.py
Boundary check OK
```

Before editor repair on the copied candidate:

```text
BEFORE False {'current_squad_filter_unsafe_short_payload': 1}
slot 1 pid 3445 len 65 Jack Butland
```

After editor repair:

```text
AFTER True {}
slot 1 pid 3445 len 130 team_id 3425 Jack Butland []
slot 17 pid 32959 len 130 team_id 0 Jonathan Walters []
slot 19 pid 33150 len 130 team_id 3425 Giannelli Imbula []
slot 20 pid 33151 len 110 team_id 3425 Steve Sidwel []
```

The linked runtime gate also passes for the repaired Stoke candidate:

```text
runtime True {} 20
linked_runtime_gate_issues []
```

The gate also fails closed when a requested linked-runtime team query matches no roster, reporting `requested_team_not_found` rather than passing an empty audit.


Clean runner proof for the guarded editor-generated candidate:

```text
RUN_TAG=stoke_editor_repair_guarded_row15_20260422T221307Z_profiles20
success True
mode guided-stoke-vanilla-profile-capture
phase dashboard_activate_squad
profile_capture_count 20
profile_capture_expected 20
profile_capture_ok True
crash_detected False
wine_debugger_detected False
process_exit_code None
final_screen squad_management_screen 0.99
profile PNGs 20
screen PNGs 90
```

The successful run used `--row-pitch 15`, matching the earlier full-profile proof. Two prior guarded validation attempts with `--row-pitch 17` reached Squad Management and did not crash, but drifted after slot 18 because slots 19 and 20 clicked below the valid squad rows. That was validation geometry, not a database/runtime failure. The PM99RE DB override profile-capture wrapper now defaults to `--row-pitch 15` while keeping the option configurable.


## Interpretation

This confirms the problem was an editor/database modeling gap, not a requirement to permanently patch the EXE. The editor must understand more than static roster membership: linked player payload shape can affect runtime Squad Management visibility.

The current repair is intentionally narrow. It is a guarded template-clone recovery for short linked-player payloads, not a semantic full-player rebuild. It copies opaque fields from the chosen template player. That is acceptable for this milestone because it reproduces the runner-proven DB-only fix, but it is not sufficient for a complete public editor.

## Remaining Coverage Gap

For 100% editor confidence, the next product milestone is to replace template cloning with a semantic linked-player payload rebuilder:

1. Map every runtime-relevant linked `JUG` payload field used by MANAGPRE Squad Management.
2. Preserve player identity, visible attributes, position, nationality, physical data, contract/status bytes, and unknown fields where known.
3. Add corpus coverage for all linked-player payload families, especially short `dd6361` variants.
4. Make release gates fail when an edited linked player cannot be certified or rebuilt safely.
5. Keep EXE bypasses as investigation-only tools, never as the default editor path.
