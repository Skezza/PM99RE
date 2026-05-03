# PM99RE (Research Workspace)

PM99RE is the research/integration repository for Premier Manager 99 reverse engineering.

## Repository Roles

- `upstream/pm99-skezmod-db-editor` is the source of truth for editor product code.
- `upstream/pm99-skezmod-patcher` is the source of truth for shipped patch tooling.
- `upstream/pm99-runner` is the source of truth for runtime/remote runner automation.
- `tools/` contains standalone research/viewer tools that are not product editor or patcher code, including the PKF viewer and browser runtime harness.
- `experiments/` contains source-only prototypes that are not ready to be promoted to `tools/`.
- PM99RE keeps research notes, probes, validation scripts, and local workspace data.

PM99RE must not carry parallel editor implementation code.

## Local Data Policy

- `DBDAT/` exists as a local drop folder.
- `.FDI`, `.PKF`, and `.EXE` files are ignored and must remain local-only.
- Browser runtime assets such as ISO/ZIP/WASM/disk images must remain local-only inside ignored tool asset directories.
- `.local/` remains the primary local game/workspace area.
- `work/`, `worktrees/`, `artifacts/`, `tbc/`, and `FDI-PKF/` are local-only scratch/artifact areas.
- `upstream/` is only for declared submodules. Put alternate checkouts and worker branches in ignored `worktrees/`.

## Daily Workflow

1. Do reverse-engineering and experiments in PM99RE.
2. Implement reusable editor changes in `upstream/pm99-skezmod-db-editor`.
3. Implement reusable patch changes in `upstream/pm99-skezmod-patcher`.
4. Implement reusable runner changes in `upstream/pm99-runner`.
5. Merge upstream repos first.
6. Bump PM99RE submodule pointers to merged commits.

Helper wrappers:
- `scripts/dev_editor.sh`
- `scripts/dev_patcher.sh`

## Guardrails

- `scripts/check_repo_boundary.py` enforces PM99RE repository boundaries.
- `scripts/check_repo_state.py` checks clean root/submodule state for reproducible handoff.
- CI runs this check on pushes and pull requests.
- Local pre-commit hook runs the same check via `.githooks/pre-commit` (hooks path: `.githooks`).

## Key Documents

- Product docs index: `upstream/pm99-skezmod-db-editor/docs/README.md`
- PM99RE docs index: `docs/README.md`
