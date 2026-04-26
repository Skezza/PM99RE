# Stoke Vanilla UI + Byte Mapping Handover (2026-04-08)

## Scope
- Create a fresh manager game (vanilla DB, no squad rewrite).
- Navigate to Stoke City and reach `SQUAD MANAGEMENT`.
- Inspect player profile screens and reconcile with byte-level position extraction.

## Repro Lane (Vanilla, no prelaunch mutation)
Run tag:
- `stoke_vanilla_guided_20260408T220842Z`

Remote artifact root:
- `/home/joe/pm99-runner/artifacts/stoke_vanilla_guided_20260408T220842Z`

Local mirror:
- `/home/joe/pm99-research/upstream/pm99-runner/docs/artifacts/pm99_runner/stoke_vanilla_guided_20260408T220842Z`

### Screen path reached
From `summary.json` and screenshots:
1. `title_screen`
2. `configuration_screen`
3. `name_team_screen` (name entry + division/team selection)
4. `preseason_setup_screen` (rival assignment)
5. `club_dashboard_screen`
6. `squad_management_screen`

Evidence:
- Final screenshot: `screens/29_dashboard_activate_squad.png`
- Final classified screen: `squad_management_screen`
- Summary shows phase reached at dashboard-to-squad transition.

## Automated Profile Capture Driver (new)
New script added:
- `upstream/pm99-runner/scripts/pm99_runner/stoke_vanilla_profile_capture_driver.py`

Purpose:
- Reuse guided navigation to squad management.
- Iterate Stoke rows, open profile, capture `profiles/<slot>.png`, return to squad.

Current run evidence (partial capture):
- Run tag: `stoke_vanilla_profiles_20260408T222951Z`
- Captured profile images: `profiles/01.png`, `profiles/02.png`, `profiles/03.png`
- Additional profile-open evidence in step screenshots up to:
  - `screens/40_profile_open_04.png` (Larus SIGURDSSON profile visible)

Extended run evidence (20-slot loop, one non-profile terminal row):
- Run tag: `stoke_vanilla_profiles_20260408T225942Z`
- Summary:
  - `upstream/pm99-runner/docs/artifacts/pm99_runner/stoke_vanilla_profiles_20260408T225942Z/summary.json`
  - `profile_capture_count = 20`
  - `profile_capture_ok = false` (slot 20 stayed on squad screen)
- Profile images:
  - `.../profiles/01.png` .. `.../profiles/19.png` show player profiles
  - `.../profiles/20.png` is squad screen (non-profile)

## Byte Extraction Rerun on Vanilla Files
Vanilla files copied from run root:
- `work/vanilla_stoke_extract/EQ98030.FDI`
- `work/vanilla_stoke_extract/JUG98030.FDI`

Probe execution:
- `python3 scripts/probe_stoke_secondary_positions.py --team-file work/vanilla_stoke_extract/EQ98030.FDI --player-file work/vanilla_stoke_extract/JUG98030.FDI --team-query Stoke --output-dir work/stoke_secondary_positions_vanilla`

Outputs:
- `work/stoke_secondary_positions_vanilla/stoke_secondary_positions_manifest.json`
- `work/stoke_secondary_positions_vanilla/stoke_secondary_positions_summary.json`

Summary status:
- `PASS`
- `Secondary positions: 6 / 20`

## Current Gap Identified
UI profile evidence and byte-decoded labels are not yet fully aligned.

Observed examples from captured UI:
- `profiles/01.png`: `Carl MUGGLETON` => `KEEPER`
- `profiles/02.png`: `Clive CLARKE` => `INS.CENT.RIGHT`
- `profiles/03.png`: `Bryan SMALL` => `LEFT BACK`
- `screens/40_profile_open_04.png`: `Larus SIGURDSSON` => `INS.CENT.RIGHT`

This indicates remaining mapping/slot interpretation work is required between:
- byte slot decode (`name_end-1..name_end+4` lane), and
- UI role strings on profile screens.

Follow-up from this run:
- The profile `ROL.` label is a tactical lineup-role UI field, not a direct intrinsic fine-position byte rendering.
- Intrinsic role extraction remains byte-contract-backed via `scripts/probe_stoke_secondary_positions.py`.

## Repro Commands for Upstream Worker
1. Ensure no competing PM99 runner containers are active.
2. Run vanilla guided lane to squad management:
   - Use `stoke_guided_squad_driver.py` directly on a clean source copy (no apply phase).
3. Run profile capture driver:
   - `python3 /workspace/repo/scripts/pm99_runner/stoke_vanilla_profile_capture_driver.py --game-dir /workspace/game --artifacts-dir /workspace/artifacts`
4. Compare each captured profile role string against:
   - `work/stoke_secondary_positions_vanilla/stoke_secondary_positions_manifest.json`
5. Update fine-position mapping and/or slot interpretation until all 20 Stoke rows align.

## Closeout Criteria (not yet met)
- 20/20 Stoke profiles captured in one uninterrupted run.
- 20/20 UI role strings reconciled to byte decode outputs.
- Documented byte offsets/slot semantics that reproduce the UI roles deterministically.

## Slot-20 Open Attempts (Post-run)

Attempts:
- `stoke_vanilla_slot20_try2_20260408T232100Z`
- `stoke_vanilla_slot20_try3_20260408T232711Z`
- `stoke_vanilla_slot20_try4_20260408T233957Z` (with keyboard fallback patch)

Observed:
- Bottom-row (`Heath`) open from squad screen remained non-deterministic under current click path; fallback key path still retained squad screen in captured artifact.
- Driver now includes a fallback key step (`profile_open_fallback_*`) when double-click does not open.
