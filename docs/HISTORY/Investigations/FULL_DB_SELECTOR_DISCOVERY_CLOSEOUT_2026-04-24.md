# Full-DB Selector Discovery Closeout - 2026-04-24

## Result

The runner can now discover and reuse PM99's English new-game club selector
coordinates for all four visible division panels.

Evidence run:

```text
run_tag=selector_discovery_nativeclick_4div_20260424T203201Z
artifact_dir=.local/runlogs/pm99_runner/selector_discovery_nativeclick_4div_20260424T203201Z
run_status=0
sync_status=0
cleanup_status=0
```

Coverage:

```text
Premier League: 20 observations, 20 unique OCR labels, 20 unique selectors
First Division: 20 observations, 20 unique OCR labels, 20 unique selectors
Second Division: 20 observations, 20 unique OCR labels, 20 unique selectors
Third Division: 20 observations, 20 unique OCR labels, 20 unique selectors
Total: 80 observations, 80 exported selectors, 0 empty observations
```

Reusable artifacts:

```text
.local/selector_maps/pm99_vanilla_english_80_selector_map.json
.local/selector_maps/pm99_vanilla_english_80_selector_export_report.json
.local/selector_maps/pm99_vanilla_english_80_selector_coverage.json
.local/selector_maps/pm99_vanilla_english_80_world_stub.json
.local/selector_maps/dryrun_full_db_selector_80/control_manifest.json
.local/runlogs/pm99_runner/selector_discovery_nativeclick_4div_20260424T203201Z/selector_screenshot_index.html
.local/runlogs/pm99_runner/selector_discovery_nativeclick_4div_20260424T203201Z/selector_coverage_report.json
```

## What went wrong before

The failed captures were not evidence of DB corruption. They were runner input
geometry failures:

- `native_input_click` uses an absolute cursor position based on the root window
  rectangle.
- On the selector grid this can land between kits or leave the previous kit
  selected.
- OCR then reports the previous highlighted team, creating false duplicates.

The fix is to use client-coordinate `native_click` for selector probes and to
persist the selected-kit highlight center separately from the attempted probe
coordinate.

## Validated Geometry

```text
division points:
  Premier League: 78,302
  First Division: 78,338
  Second Division: 562,302
  Third Division: 562,338

team points:
  178,323 209,323 240,323 271,323 302,323 333,323 364,323 395,323 426,323 457,323
  178,360 209,360 240,360 271,360 302,360 333,360 364,360 395,360 426,360 457,360

input mode:
  --division-click-action native_click
  --team-click-action native_click
```

## Runner/Tooling Added

- `selector_discovery_capture.py` captures OCR labels plus selected-kit
  highlight metadata.
- `run_selector_discovery_capture.sh` runs the capture through a protected
  remote runner lane.
- `run_pm99_experiment.sh selector-discovery-capture` exposes it from PM99RE.
- `selector_discovery.py export-observed-selector-map` exports a selector map
  directly from runtime observations when no authored world-state exists yet.

## Full-DB Proof Status

Selector coverage is closed for the vanilla English 80-club selector surface:

```text
world-selector-coverage over the generated 80-club world stub:
  clubs=80 ready=80 blocked=0

full-DB proof matrix dry-run over the same selector map:
  planned club cases=80
  selector blockers=0
```

This means the runner can now plan per-club runtime proof cases across the full
visible English selector surface.

## What Is Not Closed

This does not mean the whole editor is production-complete. A true 100% DB
editor still needs field-by-field parser/write coverage and runtime proof routes
for every intended data family. Current known unresolved production-editor gaps:

- Authored full world-state data for every club/player is not present in this
  repo.
- Division placement writes still fail closed when they differ from baseline;
  the released editor write surface for competition/division bytes is not done.
- Full player-field coverage requires explicit contracts for every editable
  field, not only selector/runtime navigation.
- OCR aliases still need a curated canonical-name layer for some labels
  (`chariton ath`, `newcastle litd`, `bristol revers`, `nerthampton t`, etc.) if
  matching against a human-authored world-state.

## GhidraMCP Check

GhidraMCP string searches against `MANAGPRE.EXE` confirmed the selector labels
exist in the executable/runtime strings:

```text
Premier League
First Division
Second Division
Third Division
```
