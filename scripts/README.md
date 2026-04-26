# Scripts

This directory is now PM99RE research/orchestration only.

Product development wrappers:
- `dev_editor.sh` runs commands in `upstream/pm99-skezmod-db-editor`
- `dev_patcher.sh` runs commands in `upstream/pm99-skezmod-patcher`
- `check_repo_boundary.py` enforces that PM99RE does not track editor product paths
- `create_pm99_isolated_run.sh` materializes the canonical read-only pristine fixture from the source ZIP and clones a writable per-run PM99 game root under `work/pm99/`
- `assert_pm99_isolated_input.py` validates fixture/game-root/DBDAT inputs and hard-fails legacy `.local/premier-manager-ninety-nine` usage
- `build_player_bitmap_review.sh` builds the full local player-photo gallery via the upstream editor script and writes outputs into `work/`
- `audit_player_bitmap_coverage.sh` runs a reproducible player-photo coverage audit and writes a timestamped evidence bundle into `artifacts/research/`
- `audit_player_bitmap_coverage.py` computes the deterministic audit summary (coverage, source-family scan, executable markers, optional payload image scan)
- `build_team_kit_review.sh` builds deterministic team-kit review artifacts (DAT palette + mask0) into `work/`
- `export_stadium_metadata.sh` snapshots local EQ/JUG inputs, runs the upstream full stadium export, and writes a compact research bundle into `artifacts/research/`
- `probe_player_fine_positions.py` extracts fine-grained player positions from `JUG98030.FDI` with manifest/codebook/summary JSON outputs for upstream handover and regression checks
- `probe_role_slot_forensics.py` emits per-player fine-role slot forensic extracts (absolute decoded offsets, raw/xor/code values, labels) as manifest/CSV/summary artifacts for upstream editor ingestion
- `probe_stoke_secondary_positions.py` extracts Stoke City's linked roster fine-position slots using strict parser contracts (`marker name_end-1..+4` and indexed-face decode), emitting deterministic primary/secondary coverage plus non-position tail evidence
- `stoke_2015_apply_metadata.py` applies parser-backed Stoke 2015 metadata enrichment (DOB/nationality/height/weight), writing reproducible manifest/CSV/apply/verification artifacts for upstream ingestion
- `stoke_2015_apply_metadata_subset.py` reapplies a manifest-backed subset of Stoke 2015 metadata to isolated game roots, which is useful for runtime bisects by slot and field group
- `build_stoke_2015_isolated_game.sh` materializes an isolated Stoke 2015 game root and can now stop at phase boundaries (`--skip-squad`, `--skip-metadata`, `--skip-faces`) for byte-accurate runtime bisects
- `create_stoke_2015_debug_variant.py` forks an isolated/failing Stoke 2015 root and restores specific layers (`nofaces`, `roster_only`, `pristine_eq`, `pristine_jug`) for runtime split testing
- `create_stoke_2015_jug_bisect_variant.py` forks an isolated Stoke 2015 root and reverts selected Stoke `JUG98030.FDI` slot ranges back to a baseline root or pristine fixture, covering names, metadata, or exact indexed payload restoration. Its manifest now records `reverted_slots`, `source_modified_slots`, and `variant_modified_slots` explicitly because `slots` alone is ambiguous in bisect work.
- `create_indexed_payload_restore_variant.py` clones an isolated game root and restores exact indexed payloads by record id from a baseline root; this is the low-level helper for `EQ`/`JUG` runtime bisects
- `repro_indexed_name_rebuild_bug.py` copies pristine `JUG98030.FDI`, applies name-only batch edits for selected Stoke manifest slots, and emits a before/after JSON bundle that proves indexed suffix metadata corruption without touching shared upstream files
- `run_stoke_remote_profile_probe.sh` mirrors an isolated game root into the canonical remote runner and executes the deterministic static Stoke squad probe; it now defaults to a private `PM99_RUNNER_NAMESPACE` plus a matching namespaced host lock and image tag, keeps shared source assets under `/home/joe/pm99-runner/shared`, and rejects legacy `.local` inputs
- `run_stoke_runtime_probe_direct.sh` runs the static Stoke native flow directly against the stable remote image (`pm99-runner:latest`), stages the runner package into the per-run remote home directory, and skips setup/sync/prepare by default, which makes it the preferred fast lane for repeated runtime bisects
- `probe_start_season_staff.py` audits deterministic team->staff slot linkage and emits Stoke + Premier League staff mapping evidence bundles (including plaintext payload-name recovery for compact slots)
- `validate_staff_name_encoding.py` validates package-encoded staff identity claims (for example `Trevor Francis`) against decoded coach payloads and in-game OCR artifacts
- `run_pm99_experiment.sh` is the primary launch wrapper for routine PM99 experiments; it hard-blocks a dirty or in-repo runner checkout by default, writes control manifests under `.local/runlogs/pm99_runner`, and dispatches by experiment name from outside the protected runner tree
- `build_pm99_ddraw_trace_overlay.sh` builds the PM99 log-only DirectDraw proxy with the existing remote runner image and writes a source-relative overlay under `.local/runner-overlays/ddraw-trace`
- `run_pm99_ddraw_trace_probe.sh` runs the static PM99/Stoke flow on the remote runner with the DirectDraw trace overlay, `WINEDLLOVERRIDES=ddraw=n,b`, and `PM99_DDRAW_TRACE_LOG` routed into artifacts. Its `--normalize-display-mode` option is an explicit experiment that makes the shim report `640x480x16` from `GetDisplayMode`.
- `summarize_pm99_ddraw_trace.py` summarizes `pm99-ddraw.log` plus runner artifacts into a compact JSON failure-stage report

Research/probe scripts:
- `probe_*`, `profile_*`, `reconcile_*`, and targeted patch/probe helpers remain here
- Documented live workflows must consume the pristine fixture or an isolated run root under `work/pm99/`
- Legacy `.local/premier-manager-ninety-nine` is unsafe shared state and should not be used as an input
