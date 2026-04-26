# Handover: Fine Role Slot Forensics (2026-04-09)

## Objective

Close out investigation of the in-game `TACTICS` black-arrow `ROL.` dropdown and identify:

1. Where the role data is stored in database records.
2. Whether percentages are stored or computed.
3. Exact parser-safe extraction rules and reproducible artifacts for upstream ingestion.

## Closeout Status

- Investigation status: **PASS (closed)**
- Binary path validated with `ghidramcp`: **yes**
- Reproducible extraction script produced: **yes**
- Machine-readable artifacts produced: **yes**
- Upstream implementation completed in this lane: **no** (handoff-ready, not merged)

## Key Findings

1. The dropdown labels are driven by the fine-role string table at `MANAGPRE.EXE:0x00735340` (18 roles).
2. Role percentages shown in the dropdown are **computed at runtime**, not persisted in `JUG98030.FDI`.
3. Runtime percentage path:
   - `FUN_00491980 @ 0x00491980` builds the dropdown rows and renders `100 - penalty`.
   - `FUN_004b13f0 @ 0x004b13f0` computes penalty from six role slot bytes.
4. Role slot load path:
   - `FUN_004afd80 @ 0x004afd80` consumes six role bytes and writes them to player struct `+0x1d..+0x22` (slot0 mirrored to `+0x23`).
5. Editable DB datapoints are the six fine-role slot bytes (codes), not direct percentage bytes.

## Parser/Decode Contract

- Marker-shaped rows:
  - Slot window: `name_end - 1 .. name_end + 4` (6 bytes, decoded payload space).
  - Decode per byte: `xor = byte ^ 0x61`; `code = xor - 1` when `xor > 0`, else `98`.
- Indexed `dd6361` rows:
  - Slot window starts at `indexed_suffix_anchor + 2`.
  - Decode while `xor = (byte ^ 0x61)` remains in `1..18`.
  - `code = xor - 1`.

## Reproducible Script

- Script: `scripts/probe_role_slot_forensics.py`

Command used:

```bash
python3 scripts/probe_role_slot_forensics.py \
  --team-file work/stoke_capture_225942_dbdat/EQ98030.FDI \
  --player-file work/stoke_capture_225942_dbdat/JUG98030.FDI \
  --team-query Stoke \
  --output-dir work \
  --json
```

## Artifacts

- `work/stoke_city_role_slots_manifest.json`
- `work/stoke_city_role_slots_table.csv`
- `work/stoke_city_role_slots_summary.json`

Snapshot metrics from the summary artifact:

- `total_rows = 20`
- `decoded_indexed_rows = 20`
- `decoded_marker_rows = 0`
- `unresolved_rows = 0`
- `missing_rows = 0`
- `rows_with_multiple_active_roles = 13`

Example confirmation (`Larus SIGURDSSON`, Stoke slot 3):

- `record_header = dd6361`
- `indexed_anchor = 38`
- active role bytes at decoded offsets `40` and `41`
- active decoded codes `5;4` => `Inside Centre Right;Inside Centre Left`

## Primary Reference Update

The canonical player reference now includes this contract and evidence:

- `docs/REFERENCE/PLAYER_FIELDS.md`  
  section: **Fine Role Slots (Tactics `ROL.` Dropdown)**

## Upstream Ingestion Notes

This investigation is now handoff-ready for upstream implementation:

1. Add six fine-role slots as parser-backed read/write fields in editor models/API.
2. Keep percentages as derived UI values (`100 - penalty`), not writable DB fields.
3. Add regression tests using the emitted manifest/CSV fixture logic.
4. Keep marker vs indexed decode path split fail-closed as documented above.
