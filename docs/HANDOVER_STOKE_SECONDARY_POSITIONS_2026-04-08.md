# Handover: Stoke Secondary Positions (2026-04-08)

Purpose: provide a reproducible, parser-contract-backed extraction of Stoke City
fine-position slots and secondary-position coverage from linked EQ->JUG rows.

## Status Snapshot

- Investigation lane status: `PASS`
- Team resolved: `Stoke C.` (`eq_record_id=341`, `full_club_name=Stoke City`)
- Roster rows decoded: `20 / 20`
- Marker-backed rows: `14`
- Indexed rows: `6`
- Marker alignment checks (DOB/year/height anchor): `14 / 14` pass
- Players with surfaced secondary positions: `6`
- Players without surfaced secondary positions: `14`
- Players confirmed single-role: `14`
- Rows with non-position marker tail byte (`slot5`): `8`
- Larus Sigurdsson row present: `yes`

Primary evidence bundle:
- `work/stoke_secondary_positions/stoke_secondary_positions_summary.json`
- `work/stoke_secondary_positions/stoke_secondary_positions_manifest.json`
- `work/stoke_secondary_positions/player_multi_position_investigation_audit_stoke_lane.json`

Capture-backed rerun evidence (copied from the exact guided/profile run DB files):
- `work/stoke_capture_225942_dbdat/EQ98030.FDI`
- `work/stoke_capture_225942_dbdat/JUG98030.FDI`
- `work/stoke_secondary_positions_capture_225942/stoke_secondary_positions_summary.json`
- `work/stoke_secondary_positions_capture_225942/stoke_secondary_positions_manifest.json`
- `work/stoke_secondary_positions_capture_225942/stoke_secondary_positions_table.csv`
- `work/stoke_secondary_positions_capture_225942/stoke_secondary_positions_table.md`

## Strict Decode Contract

1. Resolve Stoke rows from parser-backed linked roster extraction:
- `load_eq_linked_team_rosters(team_file=EQ98030.FDI, player_file=JUG98030.FDI)`

2. Decode per-row fine-position slots:
- Marker-backed rows:
  - Find `name_end` with `PlayerRecord._find_name_end_in_data(raw)`.
  - Decode six slot bytes from `name_end-1 .. name_end+4` using:
    - `code = ((byte ^ 0x61) - 1)` when xor value `> 0`, else `98`.
  - Slot semantics used in this lane:
    - `slot0` = primary fine position
    - `slot1..slot4` = secondary candidates
    - `slot5` = non-position tail (excluded from secondary-position decode)
- Indexed rows:
  - Use `indexed_face_component0` decode (`anchor+2 .. anchor+7`, xor in `[1,18]`).
  - `slot0` = primary fine position, `slot1..` = secondary candidates.

3. Candidate filtering:
- Secondary labels are emitted only for codes in `0..17`, excluding `98` and duplicate/primary values.
- No external reconciliation data is used in slot interpretation.

## Binary Evidence Notes (Ghidra)

- `MANAGPRE.EXE` `FUN_004afd80 @ 0x004afd80` consumes six consecutive role-like bytes and writes them into player struct slot fields (`+0x1d..+0x22`), then mirrors slot0 into `+0x23`.
- The same function then reads DOB/year/height bytes in the following stream segment; this is used as the alignment anchor proof for marker rows.

## Repro Command

```bash
python3 scripts/probe_stoke_secondary_positions.py --json
```

Default output directory:
- `work/stoke_secondary_positions/stoke_secondary_positions_manifest.json`
- `work/stoke_secondary_positions/stoke_secondary_positions_summary.json`

Capture-run pinned repro (uses the exact files from run tag `stoke_vanilla_profiles_20260408T225942Z`):

```bash
python3 scripts/probe_stoke_secondary_positions.py \
  --team-file work/stoke_capture_225942_dbdat/EQ98030.FDI \
  --player-file work/stoke_capture_225942_dbdat/JUG98030.FDI \
  --team-query Stoke \
  --output-dir work/stoke_secondary_positions_capture_225942
```

## Stoke Results

| Slot | Player | Decode Source | Primary | Secondary Positions | Single Role |
| ---: | --- | --- | --- | --- | ---: |
| 1 | Bryan SMALL | marker | Inside Centre Left | - | yes |
| 2 | Peter THORNE | marker | Centre Forward | - | yes |
| 3 | Larus SIGURDSSON | marker | Inside Centre Left | - | yes |
| 4 | Ray WALLACE | marker | Inside Right | - | yes |
| 5 | Carl MUGGLETON | marker | Keeper | - | yes |
| 6 | Richard FORSYTH | indexed | Central Mid. | Inside Left, Mid. Left | no |
| 7 | Kevin KEEN | marker | Inside Right | - | yes |
| 8 | Simon STURRIDGE | marker | Centre Forward | - | yes |
| 9 | Phillip ROBINSON | indexed | Central Mid. | Inside Centre Left, Inside Centre Right | no |
| 10 | Charles OLDFIELD | marker | Inside Right | - | yes |
| 11 | Kyle LIGHTBOURNE | indexed | Centre Forward | Right Winger, Left Winger | no |
| 12 | Chris SHORT | marker | Right Back | - | yes |
| 13 | Graham KAVANAGH | indexed | Central Mid. | Striker, Centre Forward | no |
| 14 | Clive CLARKE | marker | Right Back | - | yes |
| 15 | Stuart FRASER | marker | Keeper | - | yes |
| 16 | John WOODS | indexed | Inside Centre Right | Inside Centre Left, Left Back | no |
| 17 | Neil David | marker | Inside Right | - | yes |
| 18 | Anthony CROWE | indexed | Left Winger | Right Winger, Centre Forward | no |
| 19 | Ben PETTY | marker | Right Back | - | yes |
| 20 | Robert HEATH | marker | Central Mid. | - | yes |

## Closeout

- Ambiguous slot-selection logic has been removed from this lane.
- External reconciliation dependencies have been removed from this lane.
- Secondary-position coverage for Stoke is now contract-backed and deterministic:
  - `6` rows with explicit secondary positions
  - `14` rows with no decoded secondary positions under strict parser contract
- Non-position marker tail values are preserved as evidence (`non_position_tail_code`) but not promoted as role semantics.

## UI Validation Caveat (Critical)

- The profile screen `ROL.` label (for example `LEFT BACK`, `INS. CENT. RIGHT`) is a tactical lineup-role presentation and does not serve as a direct read of intrinsic fine-position slot bytes.
- Evidence run:
  - `upstream/pm99-runner/docs/artifacts/pm99_runner/stoke_vanilla_profiles_20260408T225942Z/summary.json`
  - `.../profiles/01.png`, `.../profiles/03.png`, `.../profiles/10.png`
- Practical impact for upstream:
  - Treat the six-slot decode contract from `JUG98030.FDI` as source-of-truth for intrinsic fine/secondary roles.
  - Treat profile `ROL.` OCR as UI-state evidence only (line-up context), not parser truth.
