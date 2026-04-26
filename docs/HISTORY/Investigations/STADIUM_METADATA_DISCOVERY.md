# Stadium Metadata Discovery

Date: 2026-04-08

## Scope

Document the current research result for stadium-related team data so the
discovery does not live only inside the editor submodule worktree or scratch
artifact directories.

This note captures:

- what is directly extracted from `EQ98030.FDI`
- what is currently derived from traced manager-side defaults
- where the reusable implementation lives
- how PM99RE should retain and reproduce the research output

## Core Result

The stadium-discovery track is now split into two proven layers.

### Direct EQ extraction

Indexed `EQ98030.FDI` payloads expose stable stadium lanes for every team:

- stadium name
- seated capacity
- standing capacity
- total capacity

Current full-corpus counts from the PM99RE export bundle:

- `team_count = 534`
- `league_count = 67`
- `unique_stadium_count = 521`
- `seated_capacity_present_count = 534`
- `standing_capacity_present_count = 534`
- `standing_capacity_nonzero_count = 91`
- only zero seated-capacity placeholder: `Free players`

### Derived manager-default facilities

Tracing the manager-side facility constructor and seed selection path makes it
possible to derive a default stadium-facility state for every team:

- `car_park_spaces_default`
- `pitch_condition_current_default`
- `pitch_condition_max_default`
- `pitch_quality_default`
- `manager_ground_display_capacity_default`

Current derived-default counts:

- `facility_seed_present_count = 534`
- `facility_seed_missing_count = 0`
- `car_park_spaces_nonzero_count = 377`
- `pitch_optimum_count = 377`
- `pitch_normal_count = 157`

## What Is Direct vs Derived

This distinction matters and should remain explicit in every consumer.

### Directly extracted from EQ

These come from indexed `EQ98030.FDI` payload parsing:

- `stadium`
- `seated_capacity`
- `standing_capacity`
- `total_capacity`

### Derived from traced manager behavior

These are not lifted directly from one EQ scalar lane. They are derived from the
traced default manager facility path using a roster-linked player-strength proxy:

- `facility_seed_proxy`
- `car_park_spaces_default`
- `pitch_condition_current_default`
- `pitch_condition_max_default`
- `pitch_quality_default`
- `manager_ground_display_capacity_default`

They are valid research outputs, but they should be labelled as
manager-default-derived values rather than raw EQ fields.

## Representative Validations

- Manchester Utd.: `Old Trafford`, seated `55300`, standing `0`, car park `0`,
  pitch `NORMAL`
- Stoke C.: `Britannia Stadium`, seated `24054`, standing `9650`, total `33704`,
  car park `0`, pitch `NORMAL`
- F.C. Barcelona: `Camp Nou`, seated `120000`, standing `0`, car park `2000`,
  pitch `OPTIMUM`
- Real Madrid C.F.: `Santiago Bernabéu`, seated `87000`, standing `0`, car park
  `2000`, pitch `OPTIMUM`
- Juventus: `Delle Alpi`, seated `69041`, standing `0`, car park `2000`,
  pitch `OPTIMUM`

## Why This Was Easy To Lose

The discovery work was real, but it had been stranded in:

- upstream editor scripts and tests
- upstream scratch artifacts under `docs/artifacts/session_smell/`
- ad hoc operator notes

That was enough to prove the work, but not enough to make it durable in PM99RE.

The effective correction is:

1. keep reusable extraction code upstream
2. keep PM99RE wrappers thin
3. keep PM99RE artifacts compact and reproducible
4. keep one durable investigation note in PM99RE docs

## Upstream Implementation

Reusable implementation lives in the editor repository:

- [export_stadium_metadata_full.py](/home/joe/pm99-research/upstream/pm99-skezmod-db-editor/scripts/export_stadium_metadata_full.py)
- [export_league_stadium_capacities.py](/home/joe/pm99-research/upstream/pm99-skezmod-db-editor/scripts/export_league_stadium_capacities.py)
- [test_export_stadium_metadata_full.py](/home/joe/pm99-research/upstream/pm99-skezmod-db-editor/tests/test_export_stadium_metadata_full.py)

The product repo remains the source of truth for implementation and tests.

## PM99RE Ownership

PM99RE should retain:

- this investigation note
- the dated handover note in `docs/HISTORY/agent_work/`
- the repro wrapper:
  [export_stadium_metadata.sh](/home/joe/pm99-research/scripts/export_stadium_metadata.sh)
- the research artifact bundle:
  [stadium_metadata_20260408T122449Z](/home/joe/pm99-research/artifacts/research/stadium_metadata_20260408T122449Z)

The canonical compact files in that bundle are:

- [summary.json](/home/joe/pm99-research/artifacts/research/stadium_metadata_20260408T122449Z/summary.json)
- [metadata.json](/home/joe/pm99-research/artifacts/research/stadium_metadata_20260408T122449Z/metadata.json)
- [stadium_metadata_full.json](/home/joe/pm99-research/artifacts/research/stadium_metadata_20260408T122449Z/stadium_metadata_full.json)

## Reproduction Workflow

Run the PM99RE wrapper:

```bash
./scripts/export_stadium_metadata.sh
```

The wrapper:

1. resolves local `EQ98030.FDI` and `JUG98030.FDI` from `DBDAT/`, with
   `FDI-PKF/DBDAT/` as fallback
2. snapshots those files into `work/stadium_metadata_inputs_<timestamp>/`
3. calls the upstream exporter
4. writes a timestamped research bundle to `artifacts/research/`

This keeps the research run insulated from concurrent edits to the live local
database files.

## Recommended Cascade Pattern

Use this model for similar discovery tracks:

1. prove the contract and add tests upstream
2. expose a reusable upstream script
3. add a thin PM99RE wrapper
4. generate a compact artifact bundle in `artifacts/research/`
5. write one stable PM99RE investigation note

That keeps PM99RE as the research ledger while preventing implementation drift
outside the upstream repos.
