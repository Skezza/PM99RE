# Valderrama Fresh Patch Runtime - 2026-04-11

## Goal
Run a clean runtime proof for the Valderrama `MANAGPRE.EXE` patch using:
- a fresh local game copy
- no database edits
- a patched `MANAGPRE.EXE`
- runner verification through the Valderrama offer path

## What was prepared
A fresh isolated local game root was created and only `MANAGPRE.EXE` was modified.

Evidence:
- `work/pm99/joe/valderrama_fresh_patch_20260411T001504Z/run_manifest.json`
- `work/pm99/joe/valderrama_fresh_patch_20260411T001504Z/patches/valderrama_guard/pre_hashes.json`
- `work/pm99/joe/valderrama_fresh_patch_20260411T001504Z/patches/valderrama_guard/post_hashes.json`
- `work/pm99/joe/valderrama_fresh_patch_20260411T001504Z/patches/valderrama_guard/patch_report.json`

Key result:
- only `MANAGPRE.EXE` changed
- database files remained pristine

## Runner-side findings
Multiple runner paths were exercised against the fresh patched tree:
- direct remote wrapper
- older `work/runner_probes/run_premier_probe.sh` path
- manual remote offer probe

The decisive finding is that the game patch is reaching the remote run root correctly, but the remote runner infrastructure is unstable.

### Proven facts
1. The patched EXE is present in the remote game root.
2. The remote artifact log shows the container starts and enters the PM99 runner entrypoint.
3. The failure is not a DB mutation issue, because this experiment used a fresh copy with no DB edits.
4. The failure is not an image-selection issue on its own, because the same problem was reproduced on `pm99-runner:latest` and `pm99-runner-codex-bisect:latest`.
5. A named debug container proved that `docker run` client processes are being killed while containers can remain alive.

### Strongest evidence
Manual Valderrama offer run startup log:
- `artifacts/valderrama_offer_probe/valderrama_freshpatch_offer_manual_20260411T014650Z/remote_agent_startup.log`

That log shows:
- `entrypoint_start`
- `xvfb_started`

Named debug container evidence:
- `artifacts/valderrama_offer_probe/valderrama_debug_kill/remote_agent_startup.log`
- `artifacts/valderrama_offer_probe/valderrama_debug_kill/inspect.txt`
- `artifacts/valderrama_offer_probe/valderrama_debug_kill/docker_ps.txt`

That debug evidence shows:
- shell-side `docker run` returned `137`
- Docker state reported `OOM=false`
- the named container remained `running`
- startup log advanced through `xvfb_ready`, `fluxbox_started`, `popup_watch_started`, and `wineboot_start`

## Isolated rerun and closeout
The earlier runner-host interference was real, but the experiment is now closed successfully.

An isolated rerun was performed with:
- a fresh local game tree
- no database edits
- the patched `MANAGPRE.EXE`
- a uniquely tagged remote image: `pm99-runner-isolated-val:20260411`
- an isolated container name prefix: `valiso`
- no broad container cleanup
- no competing guard process

Primary artifact bucket:
- `artifacts/valderrama_offer_probe/valiso_freshpatch_offer_20260411T0227/`

Low-fee submission rerun:
- `artifacts/valderrama_offer_probe/valiso_freshpatch_offer_lowfee_dbg_20260411T0249/`

Decisive evidence:
- `summary.json`
- `screens/48_inspect_valderrama_profile.png`
- `screens/49_click_contract_header.png`
- `screens/77_submit_offer.png`
- `screens/78_inspect_post_submit.png`
- `screens/90_inspect_continue_04.png`

Observed result:
- `summary.json` reports `success=true`
- the game window was detected and driven successfully
- the runner reached Valderrama's profile
- the contract header opened
- offer and wage batches were applied
- the offer was submitted
- the run continued through four post-offer continuation steps

This proves the fresh patched game boots and the Valderrama offer path is runnable when the runner host is isolated correctly.

## Offer calibration finding
The first successful isolated runtime path still failed as a football action because the scripted offer exceeded club funds.

Evidence:
- `artifacts/valderrama_offer_probe/valiso_freshpatch_offer_20260411T0227/screens/76_inspect_ready_to_submit.png`
- `artifacts/valderrama_offer_probe/valiso_freshpatch_offer_20260411T0227/screens/78_inspect_post_submit.png`

Observed values:
- cash available: `6 mil.`
- scripted offer: `10.25 mil.`
- in-game rejection: `You do not have enough money to make this offer.`

The low-fee rerun corrected this by reducing the transfer-fee ladder.

Evidence:
- `artifacts/valderrama_offer_probe/valiso_freshpatch_offer_lowfee_dbg_20260411T0249/summary.json`
- `artifacts/valderrama_offer_probe/valiso_freshpatch_offer_lowfee_dbg_20260411T0249/screens/71_inspect_ready_to_submit.png`
- `artifacts/valderrama_offer_probe/valiso_freshpatch_offer_lowfee_dbg_20260411T0249/screens/73_inspect_post_submit.png`
- `artifacts/valderrama_offer_probe/valiso_freshpatch_offer_lowfee_dbg_20260411T0249/screens/77_inspect_dashboard_before_continue.png`

Corrected values:
- cash available: `6 mil.`
- scripted offer: `1.54 mil.`
- yearly wage: `2.94 mil.`
- runner result: `DRIVER_RC=0`, `summary.success=true`

This proves a financially valid Valderrama offer can be submitted on the fresh patched game copy.

## Current conclusion
The Valderrama patch is runtime-valid on a fresh unmodified database.

The actual root cause of the earlier failed attempts was runner-host interference:
- attached `docker run` clients were being killed
- generic PM99 runner cleanup and container collisions were contaminating runs
- a fresh isolated image/container identity resolved the issue

So the correct closeout is:
- patch deployment: valid
- fresh-copy runtime boot: valid
- Valderrama offer workflow: valid
- financially valid offer submission: valid
- remaining engineering action: preserve isolation defaults in runner workflows

## Scripts updated during this investigation
- `scripts/run_valderrama_offer_probe_direct.sh`
- `scripts/run_stoke_runtime_probe_direct.sh`
- `work/runner_probes/launch_manual_remote_offer_probe.sh`

## Practical next step
Preserve the isolated-run pattern in runner automation:
- `work/runner_probes/launch_manual_remote_offer_probe.sh <run-tag> <local-game-dir> foreground`

Recommended isolation env:
- `PM99_RUNNER_REMOTE_IMAGE=pm99-runner-isolated-val:20260411`
- `PM99_RUNNER_CONTAINER_PREFIX=valiso`
- `PM99_RUNNER_ENABLE_GUARD=0`
- `PM99_RUNNER_GLOBAL_CONTAINER_CLEANUP=0`

The patched fresh local game dir to use is:
- `work/pm99/joe/valderrama_fresh_patch_20260411T001504Z/game`

## Strong-Offer Resolution Lane

Additional isolated runner work on 2026-04-11 established a stronger and cleaner contract-state result.

Evidence:
- `valderrama_signhunt8_20260411T032721Z`
- `valderrama_signhunt9_20260411T033749Z`

What is now proven:
- A stronger affordable offer path (`offer 5.25 mil.`, `yearly wage 4 mil.`) can be driven to completion on the fresh patched copy.
- The corrected route exits the contract pane, exits `OFFERS`, exits `TRANSFER MARKET`, advances the season, dismisses the lineup warning modal, and reaches a real dashboard `CURRENT OFFERS` screen.
- In `valderrama_signhunt9_20260411T033749Z`, the Week 2 `CURRENT OFFERS` list is empty. That proves the Valderrama offer is no longer outstanding.

What is still not proven:
- The empty `CURRENT OFFERS` state does not, by itself, distinguish acceptance from rejection.
- I do not yet have a truthful screenshot showing Valderrama on Arsenal's books.

Why the final ownership proof is still missing:
- Multiple later confirmation reruns (`signhunt10`, `signhunt11`) were interrupted by shared-host container disappearance before the new ownership-check route could complete.
- That is now the main blocker, not route design or patch validity.


## Runner Hardening Follow-up

The remaining instability in the late ownership-check runs was operational, not game-specific.
The runner lane has now been tightened in two ways:
- shared host lock default reduced to a single active holder (`PM99_RUNNER_HOST_LOCK_CONCURRENCY=1`)

That does not retroactively prove Valderrama signed for Arsenal, but it does close out the engineering finding: the unresolved gap is runner-host stability, not patch validity.
