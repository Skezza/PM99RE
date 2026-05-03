# Variable Name Cleanbase Runtime Matrix

Date: 2026-05-02

## Result

DB-only variable-length player names are runtime-feasible for the tested compact
JUG player contract.

This pass corrected the earlier invalid control by using a clean, internally
consistent game root:

- `MANAGPRE.EXE`: `01b845f7dc728e3813968bed51ff24810fde556fab395e97ca7649c57ee53158`
- `DBDAT/EQ98030.FDI`: `e095cb47ffdb6c8edf384983545124eb514d044fa4f0ce7d924b6bfe13252a5c`
- `DBDAT/JUG98030.FDI`: `95641e9d7fc0adb673045d43223d0ce7cfca531cd451f2f33e43425b05452844`
- `MFC42.DLL`: `85ce7d2d0444f4b37a4d056c55c9e734bfa077ba48e72a5683d35968e6bf4772`
- `MIDAS11.DLL`: `1b9ec903edeb6e91fff67539c381c4e4d55543e61aa572ce09863c270a0a2054`

The earlier `record33_valid_base_origjug_20260502` control is invalid because it
mixed original `JUG98030.FDI=95641e...` with modified `EQ98030.FDI=faca4e...`.
Its post-continue Wine debugger crash was therefore a base mismatch, not a valid
verdict on the variable-name writer.

## Evidence

HTML proof page:

- `docs/artifacts/variable_name_cleanbase_closeout_20260502/index.html`

Clean control runner:

- `upstream/pm99-runner/docs/artifacts/pm99_runner/record33_clean_vanilla_control_20260502T_runtime`
- Result: `RUN_STATUS=0`
- Reached squad/profile route without crash or Wine debugger.

Record33 static matrix:

- `.local/record33_canonical_variable_matrix_cleanbase_20260502T_probe/matrix_manifest.json`
- Target record: `33`
- Old name: `Guillermo AMOR Martínez`
- Applied/readback name: `Guillermo AMOR`
- Static build: `5/5` variants, `0` failures.

Record33 runner matrix:

| Variant | Runner tag | Result |
| --- | --- | --- |
| `ui17_pos_visible2_len73` | `record33_cleanbase_ui17_pos_visible2_len73_20260502T_runtime_r2` | PASS |
| `ui17_pos_visible2_len80` | `record33_cleanbase_ui17_pos_visible2_len80_20260502T_runtime_r2` | PASS |
| `legacy14_pos_visible2_len73` | `record33_cleanbase_legacy14_pos_visible2_len73_20260502T_runtime_r3` | PASS |
| `central9_pos_visible2_len73` | `record33_cleanbase_central9_pos_visible2_len73_20260502T_runtime_r3` | PASS |
| `ui17_pos_parser3_len73` | `record33_cleanbase_ui17_pos_parser3_len73_20260502T_runtime_r3` | PASS |

All five runner variants reached squad/profile capture with:

- `success=true`
- `crash_detected=false`
- `wine_debugger_detected=false`

The expanded-payload case grew record 33 from `73` to `80` bytes and still
passed the runtime route.

Visible in-game proof:

- Full game root: `.local/stoke_rolepreserved_varnames_visible_cleanroot_20260502T_probe`
- Runner tag: `stoke_rolepreserved_varnames_visible_cleanroot_20260502T_runtime`
- Result: `RUN_STATUS=0`
- Profiles captured: `3/3`
- Visible screenshots include:
  - `screens/31_profile_open_01.png`: `Jack BUTLAND`
  - `screens/34_profile_open_02.png`: `Phil BARDSLEY`
  - `screens/37_profile_open_03.png`: `Erik PIETERS`

## Contract Interpretation

The working compact JUG shape is:

1. Rebuild the variable name prefix.
2. Move role/metadata to the natural cursor after the variable name.
3. Preserve role/nationality/position/DOB/physical/skill semantic bytes at the
   moved cursor.
4. Preserve container/index integrity.
5. Move removed fixed-window padding to payload tail when preserving length, or
   allow indexed payload growth where the indexed writer updates offsets.

This does not require patching `MANAGPRE.EXE` for the tested contract.

## Remaining Scope

This closes the cleanbase runtime feasibility gate and visible Stoke proof gate.
It does not yet mean the editor has 100% coverage for every player payload shape
in the full database. The editor must still classify and certify all player
record families before exposing a general-purpose "edit any player name" feature.
