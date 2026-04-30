# PM99RE Repo Forensic Cleanup Closeout (2026-04-30)

## Summary

PM99RE was stabilized as a research/integration hub with canonical product work
kept in upstream submodules and standalone local tools kept under `tools/`.

Cleanup was preservation-first: local work and stale module refs were archived
under `.local/restructure-snapshots/` before orphaned directories were removed.

## Preserved Snapshots

- `editor-wip/`: dirty editor submodule patches, inventory, changed-file
  tarball, and verified bundle for `1f14d09`.
- `legacy-db-editor/`: verified bundle and refs inventory for stale
  `.git/modules/tools/db-editor`.
- `legacy-skezmod/20260430T203338Z/`: verified bundle plus archived untracked
  title-badge research files from stale `tools/skezmod` worktrees.
- `runner-isolated/20260430T203252Z/`: dirty `upstream/pm99-runner-isolated`
  patch set and suspicious runner filename audit.
- `runner-canonical-after-cleanup/20260430T205942Z/`: canonical runner diff
  snapshot for the newly visible protected runner change.
- `tools-pkf-viewer/`: source audit, dependency summary, test/build logs, and
  generated-file classification for the standalone PKF viewer.
- `root-wip/`, `root-after-implementation/`, and `final-state/`: PM99RE root
  patches, untracked inventories, checksums, and submodule status.
- `local-product-leftovers/20260430T205813Z/`: archived root `app/`/`tests/`
  leftovers and old editor copies removed from ignored local workspace paths.
- `post-cleanup-final/20260430T210224Z/`: final status, worktree lists,
  submodule status, boundary check outputs, and root patch after cleanup.
- `orphaned-root-dirs/20260430T211924Z/`: moved the first root-local
  `pm99-in-a-browser/` prototype, including local ISO/ZIP assets, into ignored
  preservation storage with inventory and checksums.
- `orphaned-root-dirs/20260430T213300Z/`: preserved the reappeared browser
  harness with its local ISO/ZIP assets, generated Playwright reports, and
  `node_modules` before promoting the clean source tree into `tools/`.
- `browser-runtime-artifacts/20260430T213648Z/`: moved regenerated
  `tools/pm99-in-a-browser` runtime payloads, symlinks, BIOS files, emulator
  vendor drops, dependency installs, and Playwright outputs back into ignored
  preservation storage after the source tree had been promoted.
- `browser-runtime-artifacts/20260430T214428Z/`: moved the post-validation
  regenerated browser runtime payloads after the final Playwright pass.
- `browser-runtime-artifacts/20260430T214732Z/`: moved the final concurrently
  regenerated PM99/browser payloads after an active local
  `prepare_pm99_assets.sh` run completed.
- `browser-runtime-artifacts/20260430T215016Z/`: moved the full live
  browser-payload validation state after the optional payload Playwright lane
  completed with `.last-run.json` status `passed`.

## Removed Local Orphans

- Ignored root `app/` and `tests/` directories.
- Old ignored editor copies:
  - `work/pm99-skezmod-db-editor-copy`
  - `work/pm99-skezmod-db-editor-sandbox-20260312`
- Generated PKF viewer outputs:
  - `tools/pkf-viewer/node_modules`
  - `tools/pkf-viewer/dist`
  - pytest/Python cache directories under `tools/pkf-viewer`
- Stale legacy module storage and worktrees after verified bundles:
  - `.git/modules/tools`
  - `worktrees/pm99-skezmod-patcher-article-seed`
  - `worktrees/pm99-skezmod-patcher-title-badge-worker`
- Clean temporary merge/publish worktrees under `/tmp`.
- Tracked zero-byte junk filename at the PM99RE root.
- Root-local `pm99-in-a-browser/` prototype payloads and generated runtime
  state, preserved under `.local/`; clean source now lives at
  `tools/pm99-in-a-browser/`.

## Guardrail Updates

- `scripts/check_repo_boundary.py` now blocks tracked product paths, local
  artifact roots, PM99 binary/backup extensions, and has `--check-local` for
  root product-shaped leftovers and misplaced browser harness directories.
- `scripts/check_repo_state.py` checks clean root/submodule state for
  reproducible handoff.
- Shared ignore policy now lives in `.gitignore` for `work/`, `worktrees/`,
  `artifacts/`, `docs/artifacts/`, `tbc/`, `FDI-PKF/`, and generated web
  outputs.
- Local stale `submodule.tools/*` config and local `submodule.*.ignore=all`
  masks were removed so submodule drift is visible.

## Review Lanes

- Editor WIP is committed on
  `wip/editor-snapshot-20260426-apply-hang` at `6acec07` for upstream review.
- Runner WIP is committed on
  `wip/runner-snapshot-20260426-apply-hang` at `4e45832` for upstream review.
- Runner isolated recovery work is committed on `codex/stoke-guided-fix` at
  `6c54053` in the runner linked worktree.
- Patcher is clean at `0486f83`.
- PM99RE root records the submodule pointers plus cleanup/tooling work on
  `wip/research-snapshot-20260426-apply-hang`.
