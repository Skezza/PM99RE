# PM99RE Restructure Handover (2026-03-09)

Historical snapshot: this handover records the March 2026 split state. The
current PM99RE layout also includes `upstream/pm99-runner` and a tracked
`tools/` area for standalone research/viewer tools. Treat this file as
provenance, not current operating authority.

## Objective
Complete the repo split so PM99RE is research/integration only, with product code developed in upstream submodules.

## Current Architecture
- Parent repo (`PM99RE`) role: research notes, probes, integration scripts, local workspace.
- Editor product repo: `upstream/pm99-skezmod-db-editor` (submodule).
- Patcher product repo: `upstream/pm99-skezmod-patcher` (submodule).

## Confirmed State
- Submodules are configured in `.gitmodules` with SSH remotes:
  - `upstream/pm99-skezmod-db-editor -> git@github.com:Skezza/pm99-skezmod-db-editor`
  - `upstream/pm99-skezmod-patcher -> git@github.com:Skezza/pm99-skezmod-patcher`
- Parent boundary check exists and passes:
  - `scripts/check_repo_boundary.py`
  - It enforces no tracked `app/`, `tests/`, `pm99_database_editor.py`, `pytest.ini` in PM99RE.
- Parent ignores proprietary binaries and local game state:
  - `*.EXE`, `*.FDI`, `*.PKF`
  - `.local/`
  - `DBDAT/*` with `DBDAT/.gitkeep` retained.
- Parent README and docs have been adjusted toward the new split.

## Snapshot (at handover time)
- Parent git status:
  - Modified: `README.md`, `docs/CURRENT_ROADMAP.md`, `docs/DEVELOPER_GUIDE.md`, `docs/README.md`, `scripts/patch_managpre_valderrama_guard.py`
  - Submodule pointer dirty: `upstream/pm99-skezmod-db-editor`
- Submodule pointers from parent:
  - `upstream/pm99-skezmod-db-editor`: `fa1844f7a115f5a7eb699c7a99cfcc3f4c2c9902` (`main`)
  - `upstream/pm99-skezmod-patcher`: `eef2864632eae46db1155af3da28d6fc65b9aad3` (`main`, tag lineage `v0.1.0-*`)
- Editor submodule (`upstream/pm99-skezmod-db-editor`) has local uncommitted work:
  - Modified: `app/scripts/player_editor.py`, `docs/DEVELOPER_GUIDE.md`, `docs/GETTING_STARTED.md`, `docs/README.md`, `pytest.ini`, `scripts/README.md`
  - Untracked: `app/__main__.py`, `docs/ARCHITECTURE_MAP.md`, `tests/test_entrypoints.py`

## What Is Done vs Not Done
Done:
- Structural split to upstream submodules.
- Parent boundary policy and local-data ignore policy.
- Parent no longer tracks root product code paths blocked by boundary check.

Not done:
- Final cleanup/commit sequence for current dirty state (parent + editor submodule).
- Final reconcile of doc updates in parent vs upstream docs.
- History rewrite for previously committed binaries in PM99RE.

## Critical Outstanding Risk
PM99RE git history still contains proprietary binary paths (`.FDI/.PKF/.EXE`), even though current ignore rules prevent new commits.

Evidence command:
`git rev-list --objects --all | rg -i '\.(fdi|pkf|exe)$'`

## Recommended Next Actions (Order)
1. Stabilize working tree before any history rewrite.
2. In `upstream/pm99-skezmod-db-editor`, decide which current local changes to keep, commit, and push.
3. In PM99RE, update submodule pointer to the merged editor commit.
4. In PM99RE, commit boundary/docs changes together (excluding experimental patch work if not intended).
5. Decide history strategy for binary purge:
   - If yes, run coordinated rewrite with `git filter-repo`, force-push, then coordinate all clones.
   - If no, keep current model and document that pre-restructure history contains binaries.

## Suggested History Rewrite Plan (If Approved)
- Create a fresh backup clone.
- Use `git filter-repo` to remove `*.FDI`, `*.PKF`, `*.EXE` and legacy binary folders from all history.
- Force-push rewritten branches/tags.
- Invalidate old clones and require fresh clone for all contributors.

## Operational Commands
- Boundary check:
  - `python3 scripts/check_repo_boundary.py`
- Check parent tracked product-path violations:
  - `git ls-files | rg '^(app/|tests/|pm99_database_editor.py|pytest.ini)'`
- Check parent binary history leakage:
  - `git rev-list --objects --all | rg -i '\.(fdi|pkf|exe)$'`
- Submodule status:
  - `git submodule status`
- Commit/push inside editor submodule:
  - `git -C upstream/pm99-skezmod-db-editor status`
  - `git -C upstream/pm99-skezmod-db-editor add ...`
  - `git -C upstream/pm99-skezmod-db-editor commit -m "..."`
  - `git -C upstream/pm99-skezmod-db-editor push origin main`
- Bump submodule pointer in parent:
  - `git add upstream/pm99-skezmod-db-editor`
  - `git commit -m "Bump db-editor submodule"`

## Notes For Next Agent
- Treat `scripts/patch_managpre_valderrama_guard.py` as active research work, not part of restructure completion criteria.
- Do not run destructive git history operations until user explicitly confirms rewrite window and collaborator impact.
