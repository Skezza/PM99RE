# PM99 Modern English 80 Closeout - 2026-04-28

## Scope

Close out the investigation and definition milestone for replacing the 80
manageable English PM99 clubs with modern equivalents.

This is not the final implementation milestone. The full replacement remains
blocked by runtime-safe full roster writes, team display-name writes, modern
staff/stadium/finance sourcing, and full runner validation.

## Canonical ID Policy

Binary writes must use actual EQ record IDs, not selector/UI order.

Canonical source:

- `/home/joe/pm99-research/work/parallel_recheck/team_kits/kit_manifest.json`
- `team_identifier.eq_record_id`
- corroborating kit filename contract `EQ96<eq_record_id>.BMP`

Selector artifacts are navigation/proof aids only:

- `/home/joe/pm99-research/.local/selector_maps/pm99_vanilla_english_80_selector_map.json`

The earlier mapping pass that treated selector row order as IDs was rejected.
Corrected actual manageable English IDs are `301..380`.

Ambiguous successor choices in that actual EQ range:

- `314 Wimbledon -> AFC Wimbledon`
- `351 Bury -> Bury FC`
- `374 Chester C. -> Chester FC`
- `376 Darlington -> Darlington FC`

## Existing Modern Roster State

Complete generated source data exists:

- `/home/joe/pm99-research/.local/pm99_2025_roster_world/world_2025_top80.json`
- `/home/joe/pm99-research/.local/pm99_2025_roster_world/source_audit_2025_top80.json`
- `/home/joe/pm99-research/.local/pm99_2025_roster_world/slot_assignment_2025_top80.json`
- `/home/joe/pm99-research/.local/pm99_2025_roster_world/name_capacity_report_2025_top80.json`

Generated scope:

- 80 clubs
- 1,585 target player rows
- 21 proposed squad-membership relinks
- 0 generation blockers

This complete build is not runtime-proven safe.

Safest usable baseline:

- `/home/joe/pm99-research/.local/pm99_2025_roster_world_gameready_aliasfix2_20260425T024550Z/world_2025_top80.json`
- `/home/joe/pm99-research/work/pm99/codex_2025_aliasfix2/pm99_2025_gameready_aliasfix2_20260425T024630Z/game`

Proven there:

- 695 player-name edits applied
- 695/695 matched after apply
- 0 team-name edits
- 0 roster relinks
- database/global readiness passed
- 5-club runner visual sample passed

## Kits

The 80-club current-style home/canonical kit pass is complete as an isolated
asset milestone.

Artifacts:

- `/home/joe/pm99-research/work/pm99/joe/english_2025_home_kits_20260428T151252Z/artifacts/english_2025_home_patch_summary.json`
- `/home/joe/pm99-research/work/pm99/joe/english_2025_home_kits_20260428T151252Z/artifacts/english_manageable_2025_home_contact_sheet.png`
- `/home/joe/pm99-research/work/pm99/joe/english_2025_home_kits_20260428T151252Z/artifacts/english_manageable_2025_home_gallery.html`
- `/home/joe/pm99-research/work/pm99/joe/english_2025_home_kits_20260428T151252Z/scripts/patch_english_2025_home_kits.py`

Patched:

- 80 manageable English teams
- 389 records across `BIGCAMP.PKF`, `BIGESC.PKF`, `MINIESC.PKF`,
  `NANOESC.PKF`, and `RIDIESC.PKF`

Runner validation:

- Stoke validation passed at `/home/joe/pm99-research/upstream/pm99-runner/docs/artifacts/pm99_runner/english_2025_home_kits_20260428T151252Z_stoke_validate/summary.json`

Not yet done:

- full 80-club runner validation for the kit pass
- integration into a roster/world-state build

## Safe Write Surfaces

Use released editor paths only.

Club/team metadata:

- `team-edit --release-mode`
- released fields include team name/id, stadium, capacity, car park, pitch,
  full club name, chairman, shirt sponsor, kit supplier, starting finance, and
  ground size
- text writes are fixed-span/no-growth and must be dry-run first

Players:

- `player-edit`, `player-batch-edit`, `player-rewrite-safety-pass`
- identify players by `record_id` / `payload_offset`, not name

Release-safe player fields:

- primary `position`
- `nationality`
- `birth_day`
- `birth_month`
- `attr3..attr11`

Partially safe:

- `birth_year` / age only when per-record roundtrip support passes
- `height` / `weight` only on supported rows

Not release-safe:

- `attr0..attr2`
- fine/secondary roles and foot
- probe/unknown indexed bytes
- broad raw indexed rewrites

Squad number:

- model/action layer supports it
- current CLI/world batch path does not expose it yet

Visible stats:

- `dd6361 mapped10` visible-skill patch path exists for speed, stamina,
  aggression, quality, heading, dribbling, passing, shooting, tackling, and
  handling
- this is distinct from core `PlayerRecord.attr3..attr11`

Rosters:

- use `team-roster-batch-edit`
- linked roster rows are fixed overlays
- avoid raw repair scripts unless every output is validated

Staff:

- coach rename and limited sequence-slot relink support exists
- no general semantic modern staff editor exists yet

Archives:

- exact-size bitmap replacement is acceptable
- broad PKF repacking is not proven safe

## Player Data Validation Contract

The current 2025 world-state has names/assignment only.

Missing from current generated worlds:

- nationality
- DOB
- position
- squad number
- `attr3..attr11`

Required per-player ledger fields:

- `club_key`
- `player_key`
- PM99 `record_id`
- PM99 `payload_offset`
- source identity and URLs/revisions
- candidate nationality, DOB, position, squad number, and attributes
- PM99 normalized values/codes
- source agreement verdict
- write capability/preflight verdict
- parser readback verdict
- final blocker list

Recommended source policy:

- Wikipedia/MediaWiki roster table for current squad name, number, position,
  and nationality where present
- Wikidata for DOB/citizenship cross-check
- official club/league pages as manual overrides where needed
- fail closed when sources conflict or PM99 preflight rejects the write

DOB policy remains required:

- real DOB is stored in validation evidence
- PM99 literal year support is constrained around `1900..1999`
- post-1999 modern players need a calibrated PM99 DOB/age policy before write

## Current Blockers

- Full 1,585-player roster is not runtime-proven safe.
- Team display-name writes have previously contributed to `MANAGPRE - Application cannot continue`.
- Squad number needs batch/world pipeline support.
- Player nationality/DOB/position/attribute source ledger does not exist yet.
- Modern stadium/staff/finance datasets do not exist yet.
- Staff writer is not general enough for full modern staff replacement.
- Division/competition placement writer is not released.
- Full 80-club visual/OCR runner proof matrix is not complete.

## Next Implementation Milestone

Build a fresh isolated modern-English game only after these gates are ready:

1. Generate corrected actual-EQ-ID club mapping artifact.
2. Extend 2025 source pipeline into a per-player validation ledger.
3. Extend world/batch path for squad numbers.
4. Define DOB calibration policy.
5. Generate player metadata/attribute candidate rows.
6. Run per-player capability/preflight on a temp copy.
7. Apply only passing fields to a fresh isolated game.
8. Integrate the existing 80-club kit patch.
9. Apply only team metadata that passes `team-edit --release-mode --dry-run`.
10. Run `validate-database`, `team-release-audit`, `game-ready-audit`, and
    roster/runtime audits.
11. Run PM99 runner proof matrix and surface screenshots.

## Closeout Decision

The audit/definition milestone is closed.

The implementation milestone is not closed and must start from the alias-safe
baseline plus the validated kit patch, not from the unsafe full 1,585-player
attempt.
