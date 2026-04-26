# PM99 Runner Baseline Cache Alert

Date: 2026-04-10

The sealed baseline cache is now implemented in both active PM99 runner trees:

- [upstream/pm99-runner/scripts/pm99_runner](/home/joe/pm99-research/upstream/pm99-runner/scripts/pm99_runner)
- [upstream/pm99-skezmod-db-editor/scripts/pm99_runner](/home/joe/pm99-research/upstream/pm99-skezmod-db-editor/scripts/pm99_runner)

What changes for operators:

- New fresh `run_stoke_smoke.sh`, `run_stoke_new_game.sh`, and prelaunch `run_stoke_guided_squad.sh` launches now resolve a shared sealed baseline under `/home/joe/pm99-runner/shared/bases/<manifest-hash>`.
- The cache key is strict: source fingerprint plus local repo fingerprint(s) plus the effective apply recipe.
- A cache miss builds the baseline once, seals it read-only, then future matching launches reuse it automatically.

Immediate action for agents with work in flight:

1. Do not disturb an already-running PM99 lane. Mid-flight runs are unchanged.
2. Before the next fresh PM99 runner launch, resync the updated scripts.
3. Run `prepare_game_source.sh` once without `--skip-prepare` so the shared source metadata exists:

```bash
./scripts/pm99_runner/prepare_game_source.sh
```

4. After that, normal fresh covered runs will pick up the cache automatically.

Known bypass cases by design:

- `--reuse-run-tag`
- `run_stoke_guided_squad.sh --late-apply`

Artifact changes:

- Local mirrored artifact dirs now include `baseline_cache.json`.
- `apply/summary.json` and the main run summary gain a `baseline_cache` block.
