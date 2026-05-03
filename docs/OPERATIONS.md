# PM99RE Operations Guide

This is PM99RE-local orchestration guidance for research probes, runner launches,
and handoff hygiene. Current editor, patcher, and runner product truth lives in
the corresponding `upstream/` repositories.

## Safety Defaults

- Always work on a copy of `DBDAT/`.
- Keep backups created by the editor until you have verified the result.
- Prefer dry-run modes before any bulk operation.
- Direct mutating CLI commands now run parser-backed post-write reopen validation by default;
  only use `--skip-validate` for investigative workflows.
- Never commit `.FDI`, `.backup*`, generated CSVs, or ad hoc exports.

## Worktree Placement

- Keep `upstream/` limited to declared submodules from `.gitmodules`.
- Put alternate checkouts and worker branches under ignored `worktrees/`.
- Use `git worktree move` when relocating an existing linked worktree so Git
  metadata stays consistent.
- Run `python3 scripts/check_repo_boundary.py --check-local` before handoff to
  catch misplaced root product directories or undeclared `upstream/` checkouts.

## PM99 Runner Host Coordination

When using `pm99-runner` against the shared remote host, assume the host is now
coordinated by a shared per-lock queue in the runner scripts.

- If a run is queued for the remote host lock, that is expected and healthy.
- Contending launches now stay alive in a FIFO queue and emit periodic queue position/ETA
  updates, including a parseable `PM99_RUNNER_QUEUE_STATUS {json}` line for agents.
- The default lock concurrency is `1` active holder per `PM99_RUNNER_HOST_LOCK_NAME`.
  Only raise `PM99_RUNNER_HOST_LOCK_CONCURRENCY` for lock domains that are genuinely safe to run in
  parallel; the shared PM99 Docker host should be treated as single-tenant by default.
  The queue still preserves FIFO order and reports `active_holders` plus `concurrency` in its status output.
- Restart long-lived workers or saved shells before fresh runner work so they pick up the
  updated lock-aware scripts.
- Older workers started from pre-fix checkouts can still collide until they are stopped and
  relaunched.
- Do not force-break the host lock unless the recorded holder is confirmed dead.

Background and implementation detail live in:

- [2026-04-11_pm99_runner_shared_host_collision_note.md](/home/joe/pm99-research/docs/HISTORY/agent_work/2026-04-11_pm99_runner_shared_host_collision_note.md)

## Protected PM99 Runner Launch Workflow

Use `./scripts/run_pm99_experiment.sh` for routine PM99 experiments. It is the supported front door for the protected runner checkout.

- Launch from the research repo or another control shell, not from inside `upstream/pm99-runner`.
- Always pass `--worker <name>`; the launcher hard-blocks if the runner checkout is dirty or the cwd is inside the runner tree unless you deliberately add `--allow-dirty-runner` or `--allow-runner-cwd`.
- Default local artifacts land under `.local/runlogs/pm99_runner/<run-tag>`. Use `--artifact-root` only when you need to redirect output elsewhere.
- Use `--dry-run` to write `control_launch.json` and inspect the exact wrapper command before starting a real run.
- For paired comparisons, use `staff-determinism`; the launcher adapts that wrapper through the runner's `--run-tag-prefix` interface.

Examples:

- `./scripts/run_pm99_experiment.sh smoke --worker lane-a --dry-run`
- `./scripts/run_pm99_experiment.sh season-experiment --worker lane-a -- --ai-manager --chatgpt-oauth-store /path/to/oauth.json --openai-model gpt-5.4-mini`

## Standard Single-Record Workflow

1. Copy the target `DBDAT/` directory to a disposable working folder.
2. Open the upstream editor GUI with `./scripts/dev_editor.sh python3 -m app.gui` or use the CLI through `./scripts/dev_editor.sh`.
3. Make one player, team, or coach edit at a time.
4. Save changes and confirm a backup was created.
5. Re-open the edited files and verify the change before doing more work.
6. Prefer the parser-backed validation pass before calling the edit safe:
   - `./scripts/dev_editor.sh python3 -m app.cli validate-database --players DBDAT/JUG98030.FDI --teams DBDAT/EQ98030.FDI --coaches DBDAT/ENT98030.FDI`

## Bulk Player Rename Workflow

1. Dry-run first:
   - `./scripts/dev_editor.sh python3 scripts/bulk_rename_players.py --data-dir DBDAT --map-output rename_map.csv --dry-run`
2. Review the generated mapping CSV.
3. Run the write:
   - `./scripts/dev_editor.sh python3 scripts/bulk_rename_players.py --data-dir DBDAT --map-output rename_map.csv`
4. Verify the editor and game can still load the modified files.

## Bulk Revert Workflow

1. Dry-run validation first:
   - `./scripts/dev_editor.sh python3 scripts/bulk_rename_revert.py --data-dir DBDAT --map-input rename_map.csv --dry-run`
2. Run the revert:
   - `./scripts/dev_editor.sh python3 scripts/bulk_rename_revert.py --data-dir DBDAT --map-input rename_map.csv`
3. Re-open the files and confirm the original names are restored.

## Parser-Backed Roster Inspection

Use the read-first roster tools before trusting any team-level data mutation:

- `./scripts/dev_editor.sh python3 -m app.cli team-roster-linked --team "Stoke C"`
- `./scripts/dev_editor.sh python3 -m app.cli team-roster-extract --team "Stoke C"`
- `./scripts/dev_editor.sh python3 -m app.cli team-roster-extract --include-fallbacks --team "Manchester Utd"`

Guideline:
- Default authoritative output is for editor-facing work.
- Fallback or heuristic output is only for investigation.

## Smoke Checks Before Calling a Change “Safe”

## Automated

- `python3 -m py_compile` succeeds for changed Python files.
- `pytest` is installed and runnable.
- Relevant unit tests for the touched workflow pass.

## Manual

- GUI loads without exceptions.
- Target edit can be staged and saved.
- Save creates a backup.
- Re-opening the file shows the updated value.
- `validate-database` passes for the files you changed.

## Release Hygiene

- No game data files or backups are staged in git.
- Limitations are documented before relying on a workflow operationally.
- If a write path is not parser-backed and tested, treat it as investigative only.
