# Full-DB World Selector Map

The full-DB proof runner can test clubs one by one when it knows how to pick
each club in PM99's new-game menus. Keep those click coordinates in a selector
map instead of duplicating them in every world-state file.

Example:

```json
{
  "schema": "pm99-club-selector-map-v1",
  "selectors": [
    {
      "club_key": "stoke",
      "team_query": "Stoke C.",
      "division_select_x": 559,
      "division_select_y": 302,
      "team_select_x": 327,
      "team_select_y": 356,
      "runtime_routes": ["squad", "line_up", "tactics", "results", "league_tables", "fixtures"]
    }
  ]
}
```

Selector rows match world-state clubs by `club_key` first, then by `team_query`.
Coordinates in the world-state club row override the selector map when both are
present.

Check coverage without launching the game:

```bash
python3 scripts/pm99_world_state.py world-selector-coverage \
  path/to/world.json \
  --selector-map path/to/selectors.json \
  --json
```

Generate a fill-in map for a world file:

```bash
python3 scripts/pm99_world_state.py world-selector-scaffold \
  path/to/world.json \
  --output-json work/selectors.scaffold.json \
  --json
```

Merge an existing partial map while showing what is still missing:

```bash
python3 scripts/pm99_world_state.py world-selector-scaffold \
  path/to/world.json \
  --selector-map work/selectors.partial.json \
  --output-json work/selectors.scaffold.json \
  --json
```

Generate selectors from menu row indices in the world file:

```json
{
  "club_key": "stoke",
  "team_query": "Stoke C.",
  "division_menu_index": 1,
  "team_menu_index": 2
}
```

```bash
python3 scripts/pm99_world_state.py world-selector-generate \
  path/to/world.json \
  --selector-map work/selectors.partial.json \
  --output-json work/selectors.generated.json \
  --json
```

The default layout assumes:

```text
division_select_x=559 division_start_y=302 division_step_y=39
team_select_x=327 team_start_y=356 team_step_y=39
```

Override those values with `--division-start-y`, `--division-step-y`,
`--team-start-y`, or `--team-step-y` if the menu capture proves different
spacing.

Generate selectors from runner OCR/menu observations:

```bash
python3 upstream/pm99-runner/scripts/pm99_runner/selector_discovery_capture.py \
  --game-dir /path/to/isolated/PM99 \
  --artifacts-dir work/selector_discovery_capture \
  --output-discovery work/selector_discovery.json \
  --json
```

The capture command starts PM99, navigates to the new-game team selector,
clicks configured division rows and team grid cells, OCRs the selected-team
label crop, and writes `pm99-selector-discovery-v1` observations.

Validated capture geometry:

```text
division_points=78,302 78,338 562,302 562,338
team_points=178,323 209,323 240,323 271,323 302,323 333,323 364,323 395,323 426,323 457,323
            178,360 209,360 240,360 271,360 302,360 333,360 364,360 395,360 426,360 457,360
division_click_action=native_click
team_click_action=native_click
team_label_region=236,384,404,409
```

The older absolute `native_input_click` geometry can land in gaps or on the
previously highlighted kit because it is based on the root window rectangle.
Use client-coordinate `native_click` for selector discovery and proof runs.
The capture also records `selected_team_select_x/y` and
`selected_kit_highlight` so gap clicks can be identified instead of mistaken
for duplicate clubs.

Evidence run:

```text
run_tag=selector_discovery_nativeclick_4div_20260424T203201Z
artifact_dir=.local/runlogs/pm99_runner/selector_discovery_nativeclick_4div_20260424T203201Z
division_count=4
observation_count=80
coverage=20 unique OCR labels and 20 unique selectors in each division panel
run_status=0 sync_status=0 cleanup_status=0
```

GhidraMCP also confirms the four selector labels are present in `MANAGPRE.EXE`
as runtime strings: `Premier League`, `First Division`, `Second Division`, and
`Third Division`.

```json
{
  "schema": "pm99-selector-discovery-v1",
  "divisions": [
    {
      "division_key": "eng_d2",
      "division_text": "Second Division",
      "division_select_x": 559,
      "division_select_y": 302,
      "teams": [
        {
          "text": "Stoke City",
          "team_select_x": 327,
          "team_select_y": 356,
          "screenshot": "screens/stoke.png"
        }
      ]
    }
  ]
}
```

```bash
python3 upstream/pm99-runner/scripts/pm99_runner/selector_discovery.py \
  build-selector-map \
  --world-state path/to/world.json \
  --observations work/selector_discovery.json \
  --output-selectors work/selectors.generated.json \
  --output-report work/selector_discovery_report.json \
  --json
```

The discovery compiler matches observations against `club_key`, `team_query`,
`team_name`, `set_name`, `full_club_name`, `short_name`, and explicit `aliases`.
It is deliberately fail-closed: unmatched OCR rows and duplicate/ambiguous club
matches are reported instead of guessed. Use `--allow-partial` when you want to
emit the currently matched selectors while continuing to fill gaps.

If no authored world-state exists yet, export a runtime-observed selector map
directly from a successful capture:

```bash
python3 upstream/pm99-runner/scripts/pm99_runner/selector_discovery.py \
  export-observed-selector-map \
  --observations .local/runlogs/pm99_runner/selector_discovery_nativeclick_4div_20260424T203201Z/selector_discovery.json \
  --output-selectors .local/selector_maps/pm99_vanilla_english_80_selector_map.json \
  --output-report .local/selector_maps/pm99_vanilla_english_80_selector_export_report.json \
  --json
```

The closeout artifact from the validated run exported 80 selectors with zero
empty observations and zero duplicate normalized labels. A synthetic 80-club
world stub then reported `clubs=80 ready=80 blocked=0` through
`world-selector-coverage`, and the full-DB proof matrix dry-run planned 80 ready
club cases with zero selector blockers.

Run the full proof matrix with the map:

```bash
./scripts/run_full_db_world_proof_matrix.sh \
  --world-state path/to/world.json \
  --selector-map path/to/selectors.json
```

If a club has no complete selector, the final report marks that club as
`blocked_missing_selector` and the matrix exits nonzero.
