# Stadium Metadata Discovery Handover

Date: 2026-04-08

## Why This Exists

The stadium-capacity and facility-discovery work was implemented inside
`upstream/pm99-skezmod-db-editor`, but PM99RE is the correct home for the
research trail, frozen-input orchestration, and compact evidence.

This note anchors that discovery back into PM99RE and defines the repeatable
cascade path for similar reverse-engineering tracks.

## What Was Proven

- Indexed `EQ98030.FDI` payloads expose direct stadium lanes for every team:
  - stadium name
  - seated capacity
  - standing capacity
  - total capacity
- The current full export covers all `534` teams across `67` league buckets.
- The corpus currently contains `521` unique stadium names.
- `91` teams have non-zero standing capacity in the exported lane.
- Manager-default facility data can be derived for all `534` teams once the
  traced facility seed path is applied to roster-linked player strength proxies.
- That yields full-corpus defaults for:
  - `car_park_spaces_default`
  - `pitch_condition_current_default`
  - `pitch_condition_max_default`
  - `pitch_quality_default`

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

## Where The Code Lives

- Full upstream exporter:
  [upstream/pm99-skezmod-db-editor/scripts/export_stadium_metadata_full.py](/home/joe/pm99-research/upstream/pm99-skezmod-db-editor/scripts/export_stadium_metadata_full.py)
- Supporting capacity-only exporter:
  [upstream/pm99-skezmod-db-editor/scripts/export_league_stadium_capacities.py](/home/joe/pm99-research/upstream/pm99-skezmod-db-editor/scripts/export_league_stadium_capacities.py)
- Focused coverage:
  [upstream/pm99-skezmod-db-editor/tests/test_export_stadium_metadata_full.py](/home/joe/pm99-research/upstream/pm99-skezmod-db-editor/tests/test_export_stadium_metadata_full.py)

## What Was Added In PM99RE

- PM99RE wrapper:
  [scripts/export_stadium_metadata.sh](/home/joe/pm99-research/scripts/export_stadium_metadata.sh)
- Research artifact bundle:
  [artifacts/research/stadium_metadata_20260408T122449Z/DECISION_MEMO.md](/home/joe/pm99-research/artifacts/research/stadium_metadata_20260408T122449Z/DECISION_MEMO.md)
- Export summary:
  [artifacts/research/stadium_metadata_20260408T122449Z/summary.json](/home/joe/pm99-research/artifacts/research/stadium_metadata_20260408T122449Z/summary.json)
- Export metadata:
  [artifacts/research/stadium_metadata_20260408T122449Z/metadata.json](/home/joe/pm99-research/artifacts/research/stadium_metadata_20260408T122449Z/metadata.json)
- Full stadium export:
  [artifacts/research/stadium_metadata_20260408T122449Z/stadium_metadata_full.json](/home/joe/pm99-research/artifacts/research/stadium_metadata_20260408T122449Z/stadium_metadata_full.json)

## How The Cascade Should Work

The effective split is now clear:

1. Do extraction design, parser work, and tests in the upstream editor repo.
2. Keep PM99RE wrappers thin. They should freeze local inputs and call upstream
   scripts rather than reimplement extraction logic.
3. Store compact evidence in `artifacts/research/<timestamped_bundle>/`.
4. Store human handover context in `docs/HISTORY/agent_work/`.
5. Do not leave the only copy of a discovery in
   `upstream/pm99-skezmod-db-editor/docs/artifacts/session_smell/`.

That last point is the actual failure mode we hit here. The discovery was real,
but it was stranded in the product repo’s scratch-artifact area instead of the
research workspace.

## Recommended Workflow

1. Extend or correct the reusable extractor upstream.
2. Run `./scripts/export_stadium_metadata.sh` from PM99RE.
3. Review `summary.json` for the compact counts and focus-club checks.
4. Use `stadium_metadata_full.json` when you need the full per-team export.
5. Add one dated PM99RE note when a discovery materially changes the known data
   model or workflow.
