# PM99 2025 Roster World Build - 2026-04-24

## Scope

Target: generate a 2025-26 English top-80 PM99 world-state and apply it to an
isolated game copy.

Policy used:

- 80 clubs: Premier League 20, Championship 24, League One 24, League Two first 12.
- Existing PM99 linked roster rows are carrier records.
- Every available carrier row is filled, capped at 20 per club.
- Division placement is not rewritten.
- Club display names are fixed-width fitted to existing carrier capacity.

## Generated Artifacts

- World-state: `.local/pm99_2025_roster_world/world_2025_top80.json`
- Source audit: `.local/pm99_2025_roster_world/source_audit_2025_top80.json`
- Slot assignment: `.local/pm99_2025_roster_world/slot_assignment_2025_top80.json`
- Name-fit report: `.local/pm99_2025_roster_world/name_capacity_report_2025_top80.json`
- Build evidence: `.local/pm99_2025_roster_world/build_evidence_latest.json`
- Dry-run proof manifest: `.local/pm99_2025_roster_world/dryrun_pm99_2025_roster_top80_final/control_manifest.json`
- Latest isolated run: `work/pm99/codex_2025_roster/pm99_2025_roster_top80_world_ready_20260424T230207Z`

## Evidence

- World-state generation: 80 clubs, 1,585 player rows, 21 squad-membership relinks, 0 generation blockers.
- Selector coverage: 80 ready, 0 blocked.
- Build wrapper: success, compile status 0, apply status 0.
- Compile plan: OK, 0 compile blockers.
- Player batch: 1,585 rows, 1,585 matched, 1,585 applied changes, 0 warnings.
- Roster relink batch: 21 rows, 21 matched, 21 linked changes, 0 warnings.
- Team edits: 80 files, 80 targeted records changed or already matched, 0 bad/warning team edits.
- Linked-name raw fallback: 4 fixed-width linked-roster-only display names patched after `team-edit` had no metadata-surface match.
- Database validation: players, teams, and coaches reopen cleanly.
- World apply readiness: OK. Required checks are player writes, roster relinks,
  team edits, and DB parser validation.
- Dry-run proof matrix: control manifest generated successfully with 80 selector-ready cases.
- Tests: boundary check OK; editor deterministic lane passed; PM99RE world/proof tests passed.

## Visual Runner Correction - 2026-04-25

The original apply/readiness result was too weak. Live PM99 runner validation
disproved game-readiness:

- Pristine baseline reached the manager/team selection screen and dashboard.
- Final 2025 build showed `MANAGPRE - Application cannot continue`.
- JUG-only and EQ-only bisects independently reproduced runtime failure.
- The first visible modal appears immediately after selecting Manager League,
  before meaningful team/rival flow, so this is database/runtime integrity, not
  a route-driver artefact.

Evidence:

- Final failing run: `upstream/pm99-runner/docs/artifacts/pm99_runner/pm99_2025_roster_visual_arsenal_clean_20260424T233758Z`
- Pristine baseline: `upstream/pm99-runner/docs/artifacts/pm99_runner/pm99_2025_visual_bisect_pristine_20260424T234211Z`
- JUG-only failure: `upstream/pm99-runner/docs/artifacts/pm99_runner/pm99_2025_visual_bisect_jug_only_build_20260424T235009Z`
- EQ-only failure: `upstream/pm99-runner/docs/artifacts/pm99_runner/pm99_2025_visual_bisect_eq_only_build_20260424T235532Z`
- One-row JUG old-writer failure: `upstream/pm99-runner/docs/artifacts/pm99_runner/pm99_2025_visual_jug_single_first_20260425T002908Z`
- One-row JUG patched-writer pass: `upstream/pm99-runner/docs/artifacts/pm99_runner/pm99_2025_visual_jug_single_patched_20260425T003620Z`

Player-file finding:

- The previous build forced `player-batch-edit --skip-roundtrip-safety`.
- The indexed player writer was canonicalizing `PlayerRecord.to_bytes()` for
  name-only edits, overwriting unknown runtime-used bytes inside the indexed
  payload.
- A single rename, `Marc OVERMARS -> David Raya`, was enough to trigger the
  modal with the old writer.
- The editor now patches indexed name-only edits in-place, preserving the
  original payload layout. The same one-row rename reaches the normal
  name/team screen and squad route with no Wine debugger.
- Stricter preflight now reports only 626 of 1,585 proposed player renames as
  layout-safe. The remaining 959 require capacity-aware slot assignment or a
  separately proven variable-length indexed-record rewrite.

Team-file finding:

- `game-ready-audit` was not optional. It correctly flagged unresolved EQ
  runtime coverage.
- The final EQ has four unresolved club-like records:
  `Liverpool`, `Nottingham F`, `Wolves`, and `Cove`.
- Name-only EQ edits are insufficient; some rows need full-club/linkage or
  roster-extractor/container work before the audit can pass.
- Raw linked-team fallback writes are now treated as investigation-only, not a
  release-ready editor surface.

Current status:

- Parser reopen is necessary but not sufficient.
- World apply readiness is now fail-closed on player preflight warnings,
  skipped player roundtrip safety, raw team fallbacks, and global
  `game-ready-audit`.
- The full 2025 roster milestone is not complete. Proven visual scope is one
  indexed player rename with the patched writer. The next product milestone is
  capacity-aware full-roster generation plus EQ audit closure, followed by
  runner screenshots for representative clubs.

## Remaining Global Audit Gap

The isolated 2025 top-80 world build now exits successfully. Separately,
`game-ready-audit` still fails its existing global team-release coverage gate:

- `team_release: club-like coverage incomplete (523/527)`
- `team_release: uncovered_club_like_summary.uncovered_count must be 0 (got 4)`

This is a release-blocking apply/readiness failure. It is no longer valid to
ignore this audit for the 2025 world-state operation. The visual runner showed
that parser validation alone can pass while PM99 still raises its runtime
`Application cannot continue` modal.

## Interpretation

The database can be parsed and edited, but the previous full rewrite was not
runtime-safe. A product-grade editor must prove every released write surface
with both parser gates and live runner gates. For the 2025 roster target, the
remaining work is not more screenshots of the broken build; it is fixing the
data-generation/editor contract so the full apply passes fail-closed preflight,
global audit, and visual PM99 startup/squad validation.
