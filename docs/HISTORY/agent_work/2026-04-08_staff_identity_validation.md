# 2026-04-08 Staff Identity Validation (Trevor Francis / In-Game Display)

## Runtime Follow-up (2026-04-09)

A clean two-run UI experiment for `Manchester Utd.` is now documented in:

- [`2026-04-09_manchester_united_staff_two_run_validation.md`](2026-04-09_manchester_united_staff_two_run_validation.md)

That run confirms non-deterministic start-of-season staff names in the UI lane
across fresh game starts for the same club.

## Scope
Validate the user-reported discrepancy:

- Is `Trevor Francis` actually encoded in the package DB?
- If yes, why is he not obviously seen in current in-game captures?

## Commands Run

```bash
./scripts/probe_start_season_staff.py \
  --json-output artifacts/staff/start_of_season_staff_20260408_validation.json

./scripts/validate_staff_name_encoding.py \
  --json-output artifacts/staff/staff_name_encoding_validation_20260408.json
```

## Deterministic Mapping Status

From `start_of_season_staff_20260408_validation.json`:

- `decoded_link_count=534/534`
- `unresolved_count=0`
- `inconsistent_count=0`
- `coverage_ratio=1.0`
- reproducibility hash:
  `6359b05965008c91c1785be585eb54d27769dc5be644010d6dab4101c6d0f94e`

Stoke focus row (deterministic slot linkage):

- `team_name=Stoke C.`
- `full_club_name=Stoke City`
- `slot_index=80`
- `coach_record_id=700`
- `coach_offset=61497`
- `coach_decoded_name=Trevor Francis`

## Package Encoding Validation

From `staff_name_encoding_validation_20260408.json`:

- `Trevor Francis` exists in decoded coach records in both:
  - `DBDAT/ENT98030.FDI`
  - `.local/premier-manager-ninety-nine/DBDAT/ENT98030.FDI`
- In both files, hit at `offset=61497`.
- Raw plaintext scan for target name in bytes is false (`raw_plaintext_target_present=false`),
  which is consistent with encoded/obfuscated storage rather than plain ASCII name strings.

## In-Game OCR Validation

Runner OCR artifact scan (`225` summary files):

- `Trevor Francis`: `0` hits
- `francis`: `0` hits
- `strachan`: `1100` hits across `48` files

This confirms the observed behavior: the package contains encoded staff names
(including Trevor Francis), but current observed in-game manager/staff display
in captured flows does not align with the present deterministic slot->name mapping.

## Premier League Proof Table (Current State)

Current manager-listing alignment remains semantically unresolved:

- rows: `20`
- surname matches: `0`
- surname mismatches: `12`
- placeholders: `7`
- missing map: `1`

This is evidence that deterministic linkage is solved structurally, but identity
semantics for start-of-season display routing are still an open reverse-engineering
task.

## Update: Post-Decode-Patch Validation (2026-04-08)

Re-run:

```bash
./scripts/validate_staff_name_encoding.py \
  --json-output artifacts/staff/staff_name_encoding_validation_20260408_after_decode_patch.json
```

Updated alignment metrics:

- rows: `20`
- surname matches: `0`
- surname mismatches: `19`
- placeholders: `0` (was `7`)
- missing map: `1` (`Charlton Athletic`)

Interpretation:

- This confirms the package lane now surfaces plaintext staff labels for the
  mapped Premier entries.
- The mismatch against real-life manager listings remains expected in this build:
  deterministic package staff names do not semantically match the manager PDF
  lane for most clubs.

Artifact:

- [`artifacts/staff/staff_name_encoding_validation_20260408_after_decode_patch.json`](/home/joe/pm99-research/artifacts/staff/staff_name_encoding_validation_20260408_after_decode_patch.json)
