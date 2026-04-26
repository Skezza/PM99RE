# Start-of-Season Staff Milestone (2026-04-08)

## Scope Clarification (2026-04-09)

This milestone establishes deterministic slot linkage and deterministic decoded
package rows. It does **not** prove deterministic in-game staff UI names for
fresh new-game starts.

Updated runtime validation is documented in:

- [`2026-04-09_manchester_united_staff_two_run_validation.md`](2026-04-09_manchester_united_staff_two_run_validation.md)

## Deliverable

Added a repeatable probe script to surface deterministic start-of-season staff
mapping:

- [`scripts/probe_start_season_staff.py`](/home/joe/pm99-research/scripts/probe_start_season_staff.py)

The script joins `EQ98030.FDI` team slots to `ENT98030.FDI` indexed coach
slots using the current deterministic slot-aligned contract and emits:

- audit metrics (`coverage`, `unresolved`, `inconsistent`, reproducibility hash),
- focused club rows (default includes Stoke City),
- England Premier League DB slice rows,
- Premier League manager-listing aligned rows (when
  `.local/PM99RE-demo-pdfs/Premier League Managers.pdf` is available),
- unresolved-placeholder counts for staff names.

## Run

```bash
./scripts/probe_start_season_staff.py \
  --json-output artifacts/staff/start_of_season_staff_20260408.json
```

## Current Snapshot (from run above)

- deterministic link audit: `ok=True`
- `team_count=534`
- `coach_slot_count=556`
- `decoded_link_count=534`
- `unresolved_count=0`
- `inconsistent_count=0`
- `coverage_ratio=1.0`
- `reproducibility_hash=6359b05965008c91c1785be585eb54d27769dc5be644010d6dab4101c6d0f94e`

Stoke City focus row:

- `Stoke C.` (`First Division`) -> `Trevor Francis`
- `slot_index=80`, `coach_record_id=700`, `coach_offset=61497`

Premier League snapshots:

- DB slice rows: `22`
- DB slice placeholder staff names: `8`
- manager-listing aligned rows: `20`
- manager-listing aligned unresolved names: `7`
- note: current DB slice includes duplicated/artefact-like club labels in this
  range (`Wimbledon` and `Sheffield W.` appear twice by slot), so the
  manager-listing aligned view remains the 20-club reference lane.

Artifact:

- [`artifacts/staff/start_of_season_staff_20260408.json`](/home/joe/pm99-research/artifacts/staff/start_of_season_staff_20260408.json)

## Notes

- Linkage determinism is now automated/repeatable for staff slot mapping.
- Human-readable manager identity coverage is still incomplete for a subset of
  slots (placeholder labels remain in both the raw DB slice and listing-aligned
  view).

## Update: Plaintext Staff Surface (2026-04-08, post-decode patch)

After extending payload name extraction in
[`scripts/probe_start_season_staff.py`](/home/joe/pm99-research/scripts/probe_start_season_staff.py),
the same deterministic linkage lane now surfaces plaintext names for all
Premier League rows present in the DB slice.

Command:

```bash
./scripts/probe_start_season_staff.py \
  --json-output artifacts/staff/start_of_season_staff_20260408_recheck_after_decode_patch.json
```

Snapshot:

- deterministic linkage: unchanged (`decoded_link_count=534/534`, coverage `1.0`)
- Stoke focus row: `Stoke C.` -> `Trevor Francis` (`slot_index=80`)
- Premier League DB slice rows: `22`
- Premier League DB slice placeholder names: `0` (was `8`)
- manager-listing aligned rows: `20`
- manager-listing aligned unresolved names: `0` (was `7`)
- listing map gap remains: `Charlton Athletic` unresolved (`mapped=NONE`) because
  no direct Premier-slice row match in this DB snapshot

Updated artifact:

- [`artifacts/staff/start_of_season_staff_20260408_recheck_after_decode_patch.json`](/home/joe/pm99-research/artifacts/staff/start_of_season_staff_20260408_recheck_after_decode_patch.json)
