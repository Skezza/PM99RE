# Repository Guidelines

## Project Structure & Module Organization
PM99RE is a research/integration workspace, not the product-code home.

- `upstream/pm99-skezmod-db-editor/`: canonical editor implementation (`app/`, `tests/`, `docs/`).
- `upstream/pm99-skezmod-patcher/`: canonical patch tooling.
- `scripts/`: PM99RE orchestration and research probes (`dev_editor.sh`, `dev_patcher.sh`, `check_repo_boundary.py`, `probe_*`).
- `docs/`: PM99RE research context and handover notes; product truth lives in upstream docs.
- `DBDAT/` and `.local/`: local-only game/workspace data.

Boundary rule: PM99RE must not track product paths (`app/`, `tests/`, `pm99_database_editor.py`, `pytest.ini`) at the root.

## Build, Test, and Development Commands
- `python3 scripts/check_repo_boundary.py`: enforce PM99RE research-only boundary (also run in CI/pre-commit).
- `git submodule status`: verify editor/patcher pointers before and after changes.
- `./scripts/dev_editor.sh`: enter editor workflow (no args shows `app.cli` help).
- `./scripts/dev_editor.sh pytest -m deterministic -q`: run blocking upstream test lane.
- `./scripts/dev_editor.sh pytest -q`: run full upstream test suite.
- `./scripts/dev_patcher.sh`: enter patcher workflow (no args shows `skezmod.py` help).

## Coding Style & Naming Conventions
Use Python conventions already present in upstream code:

- 4-space indentation, snake_case for functions/modules, PascalCase for classes.
- Keep changes focused and parser-safe; prefer extending upstream library APIs over ad hoc root scripts.
- Test files should follow `test_*.py` naming.
- Preserve unknown bytes and guardrails in file-writing paths; update docs when data rules change.

## Testing Guidelines
For PM99RE-only changes, run boundary checks.  
For editor changes, test inside `upstream/pm99-skezmod-db-editor`:

- `pytest -q`
- `pytest -m deterministic -q` (release-blocking)
- `pytest -m corpus -q` (visibility lane, non-blocking)

Use markers defined in `pytest.ini`: `deterministic`, `corpus`, `integration`.

## Commit & Pull Request Guidelines
Commit style in history is concise and imperative (example: `Implement v1 game-ready contract gates...`), with optional conventional prefixes (`feat:`) when useful.

- Keep PM99RE research commits separate from upstream product commits.
- Merge in upstream repos first, then commit PM99RE submodule pointer bumps.
- PRs should state: scope, touched repo(s), commands run, and evidence (logs/JSON/screenshots for GUI or gate changes).
- Never include proprietary binaries (`*.FDI`, `*.PKF`, `*.EXE`), backups, or ad hoc exports in commits.
