# PM99 Documentation Index

This file is the only documentation index. Use it as the first stop.

## Current Authority

PM99RE is a research/integration workspace. Current repository-shape and agent
rules live in:
- [../AGENTS.md](../AGENTS.md)
- [../README.md](../README.md)
- [OPERATIONS.md](OPERATIONS.md)

Product truth lives in the upstream submodules listed below. Historical PM99RE
notes remain useful for provenance, but they are not implementation authority.

## Canonical Product Docs (Upstream)

Use these for current product truth:
- [../upstream/pm99-skezmod-db-editor/docs/CURRENT_ROADMAP.md](../upstream/pm99-skezmod-db-editor/docs/CURRENT_ROADMAP.md)
- [../upstream/pm99-skezmod-db-editor/docs/GETTING_STARTED.md](../upstream/pm99-skezmod-db-editor/docs/GETTING_STARTED.md)
- [../upstream/pm99-skezmod-db-editor/docs/EDITOR_README.md](../upstream/pm99-skezmod-db-editor/docs/EDITOR_README.md)
- [../upstream/pm99-skezmod-db-editor/docs/OPERATIONS.md](../upstream/pm99-skezmod-db-editor/docs/OPERATIONS.md)
- [../upstream/pm99-skezmod-db-editor/docs/ARCHITECTURE.md](../upstream/pm99-skezmod-db-editor/docs/ARCHITECTURE.md)
- [../upstream/pm99-skezmod-db-editor/docs/ARCHITECTURE_MAP.md](../upstream/pm99-skezmod-db-editor/docs/ARCHITECTURE_MAP.md)
- [../upstream/pm99-skezmod-db-editor/docs/DATA_FORMATS.md](../upstream/pm99-skezmod-db-editor/docs/DATA_FORMATS.md)
- [../upstream/pm99-skezmod-db-editor/docs/REFERENCE/PLAYER_FIELDS.md](../upstream/pm99-skezmod-db-editor/docs/REFERENCE/PLAYER_FIELDS.md)
- [../upstream/pm99-skezmod-db-editor/docs/REFERENCE/TEAM_FIELDS.md](../upstream/pm99-skezmod-db-editor/docs/REFERENCE/TEAM_FIELDS.md)
- [../upstream/pm99-skezmod-db-editor/docs/DEVELOPER_GUIDE.md](../upstream/pm99-skezmod-db-editor/docs/DEVELOPER_GUIDE.md)
- [../upstream/pm99-skezmod-db-editor/docs/PKF_STRING_SEARCHER.md](../upstream/pm99-skezmod-db-editor/docs/PKF_STRING_SEARCHER.md)

Runner product truth lives in:
- [../upstream/pm99-runner/README.md](../upstream/pm99-runner/README.md)
- [../upstream/pm99-runner/scripts/pm99_runner/README.md](../upstream/pm99-runner/scripts/pm99_runner/README.md)

## PM99RE Local Docs

Local files in this directory are research context, snapshots, and archive material.
If they diverge from upstream product docs, treat upstream as authoritative.

Local PM99RE operations and repository-shape notes:
- [OPERATIONS.md](OPERATIONS.md)
- [HANDOVER_REPO_RESTRUCTURE.md](HANDOVER_REPO_RESTRUCTURE.md) (historical snapshot)
- [HISTORY/Investigations/PM99_REPO_FORENSIC_CLEANUP_2026-04-30.md](HISTORY/Investigations/PM99_REPO_FORENSIC_CLEANUP_2026-04-30.md)

Current handover notes for upstream implementation planning:
- [HANDOVER_FINE_POSITIONS_2026-04-08.md](HANDOVER_FINE_POSITIONS_2026-04-08.md)
- [HISTORY/agent_work/2026-04-09_manchester_united_staff_two_run_validation.md](HISTORY/agent_work/2026-04-09_manchester_united_staff_two_run_validation.md)
- [HISTORY/agent_work/2026-04-09_minifoto_replace_proof_harness.md](HISTORY/agent_work/2026-04-09_minifoto_replace_proof_harness.md)

## Historical Context

These are useful for provenance and background, but they are not authoritative:
- [HISTORY/README.md](HISTORY/README.md)
- Recent retained investigations:
  [HISTORY/Investigations/ENGLISH80_MODERN_REPLACEMENT_PLAN_2026-05-01.md](HISTORY/Investigations/ENGLISH80_MODERN_REPLACEMENT_PLAN_2026-05-01.md),
  [HISTORY/Investigations/VARIABLE_LENGTH_PLAYER_NAME_CONTRACTS_2026-05-01.md](HISTORY/Investigations/VARIABLE_LENGTH_PLAYER_NAME_CONTRACTS_2026-05-01.md),
  [HISTORY/Investigations/VARIABLE_NAME_CLEANBASE_RUNTIME_MATRIX_2026-05-02.md](HISTORY/Investigations/VARIABLE_NAME_CLEANBASE_RUNTIME_MATRIX_2026-05-02.md),
  [HISTORY/Investigations/FULL_GAME_VARIABLE_NAME_WINDOWS_2026-05-03.md](HISTORY/Investigations/FULL_GAME_VARIABLE_NAME_WINDOWS_2026-05-03.md),
  [HISTORY/Investigations/STOKE_VARIABLE_NAME_LENGTH_BOUNDARIES_2026-05-03.md](HISTORY/Investigations/STOKE_VARIABLE_NAME_LENGTH_BOUNDARIES_2026-05-03.md)
- Notable retained investigations:
  [HISTORY/Investigations/PLAYER_BITMAP_ARCHIVES.md](HISTORY/Investigations/PLAYER_BITMAP_ARCHIVES.md),
  [HISTORY/Investigations/PLAYER_BITMAP_COVERAGE_AUDIT.md](HISTORY/Investigations/PLAYER_BITMAP_COVERAGE_AUDIT.md),
  [HISTORY/Investigations/MINIFOTO_WRITE_SAFETY_V1.md](HISTORY/Investigations/MINIFOTO_WRITE_SAFETY_V1.md),
  [HISTORY/Investigations/STADIUM_METADATA_DISCOVERY.md](HISTORY/Investigations/STADIUM_METADATA_DISCOVERY.md)

## Raw Archive

These are retained as archive artifacts and raw evidence, not maintained explanations:
- [archive/README.md](archive/README.md)
- [archive/UNSORTED_AUDIT.md](archive/UNSORTED_AUDIT.md)
- [archive/TEAM_FIELD_STRUCTURE_GUESS.md](archive/TEAM_FIELD_STRUCTURE_GUESS.md)
- [archive/verify.txt](archive/verify.txt)
- [archive/breadcrumbs.csv](archive/breadcrumbs.csv)

If documentation conflicts with implementation, prefer:
- editor code in [../upstream/pm99-skezmod-db-editor/](../upstream/pm99-skezmod-db-editor/)
- patcher code in [../upstream/pm99-skezmod-patcher/](../upstream/pm99-skezmod-patcher/)
- runner code in [../upstream/pm99-runner/](../upstream/pm99-runner/)
