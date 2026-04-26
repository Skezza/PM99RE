# PM99 Runner Shared Host Collision Note

Date: 2026-04-11

## Problem

Multiple PM99 agents were colliding on the same remote runner host at `192.168.1.175`.
The failures were not game-specific. They were runner-environment collisions caused by
different local shells reusing the same remote repo/image/display state at the same time.

Observed symptoms:

- one worker rebuilt or replaced the remote repo while another run was active
- image/build state changed underneath an in-flight run
- screenshots and OCR captures suddenly belonged to the wrong session
- apparently clean fresh runs became nondeterministic or died mid-flow
- custom probe wrappers bypassed the main runner protections and could still stomp state

## Root Cause

The active runner scripts did not have a host-wide lease for the shared remote host.
Individual runs had their own local run tags, but there was no single remote lock that
serialized all top-level entrypoints and local probe wrappers using the same remote
workspace.

## Fix

Host-wide remote locking now lives in:

- [common.sh](/home/joe/pm99-research/upstream/pm99-runner/scripts/pm99_runner/common.sh)

The new lock behavior covers:

- shared remote lease under `shared/locks/runner-host`
- configurable slot-based concurrency via `PM99_RUNNER_HOST_LOCK_CONCURRENCY` (default `1`)
- heartbeat updates while the holder is active
- per-lock FIFO queue state under `shared/queues/<lock-name>`
- periodic human + machine-readable queue updates for contending launches
- wait and timeout behavior for contending launches
- stale-lock cleanup
- orphan reaping when the recorded local owner PID is dead

Related cleanup:

- fixed an existing shell syntax bug in `pm99_runner_cleanup_remote_state()`
- added lock acquire/release to the top-level runner entrypoints
- updated local probe wrappers to use the same lock and the normal
  `pm99_runner_prepare_remote_run_root` path instead of their older full-tree copy path

Files updated:

- [common.sh](/home/joe/pm99-research/upstream/pm99-runner/scripts/pm99_runner/common.sh)
- [build_runner_image.sh](/home/joe/pm99-research/upstream/pm99-runner/scripts/pm99_runner/build_runner_image.sh)
- [setup_remote_host.sh](/home/joe/pm99-research/upstream/pm99-runner/scripts/pm99_runner/setup_remote_host.sh)
- [prepare_game_source.sh](/home/joe/pm99-research/upstream/pm99-runner/scripts/pm99_runner/prepare_game_source.sh)
- [run_premier_offer_capture.sh](/home/joe/pm99-research/upstream/pm99-runner/scripts/pm99_runner/run_premier_offer_capture.sh)
- [run_stoke_smoke.sh](/home/joe/pm99-research/upstream/pm99-runner/scripts/pm99_runner/run_stoke_smoke.sh)
- [run_stoke_new_game.sh](/home/joe/pm99-research/upstream/pm99-runner/scripts/pm99_runner/run_stoke_new_game.sh)
- [run_stoke_guided_squad.sh](/home/joe/pm99-research/upstream/pm99-runner/scripts/pm99_runner/run_stoke_guided_squad.sh)
- [run_stoke_exploration.sh](/home/joe/pm99-research/upstream/pm99-runner/scripts/pm99_runner/run_stoke_exploration.sh)
- [run_stoke_route_capture.sh](/home/joe/pm99-research/upstream/pm99-runner/scripts/pm99_runner/run_stoke_route_capture.sh)
- [run_stoke_season_experiment.sh](/home/joe/pm99-research/upstream/pm99-runner/scripts/pm99_runner/run_stoke_season_experiment.sh)
- [run_stoke_staff_extract.sh](/home/joe/pm99-research/upstream/pm99-runner/scripts/pm99_runner/run_stoke_staff_extract.sh)
- [run_stoke_staff_determinism.sh](/home/joe/pm99-research/upstream/pm99-runner/scripts/pm99_runner/run_stoke_staff_determinism.sh)
- [cleanup_remote_host.sh](/home/joe/pm99-research/upstream/pm99-runner/scripts/pm99_runner/cleanup_remote_host.sh)
- [run_premier_query_probe.sh](/home/joe/pm99-research/work/runner_probes/run_premier_query_probe.sh)
- [run_native_steps_probe.sh](/home/joe/pm99-research/work/runner_probes/run_native_steps_probe.sh)

## What Agents Should Do Now

1. Restart any long-lived worker or shell that launches PM99 runner jobs.
2. Relaunch from this updated checkout before starting fresh runner work.
3. Do not rely on older local copies of helper scripts or saved shell sessions.
4. If a run is queued on the host lock, let it wait unless you have confirmed the holder is dead.

## Important Caveat

The lock only protects launches that come from the updated scripts.
Any already-running worker started from an older checkout can still interfere until it is
stopped and restarted.

That means "I still saw a collision once" does not automatically mean the lock failed.
The first thing to check is whether another agent was still using an older local script
copy.

## Practical Guidance

- If you see queue status for the remote host lock, that is expected and healthy.
- Agents can surface the parseable `PM99_RUNNER_QUEUE_STATUS {json}` line directly to users.
- The queue remains FIFO even when `PM99_RUNNER_HOST_LOCK_CONCURRENCY` is set above `1`;
  only the number of simultaneous holders changes. For the shared PM99 Docker host, `1` is now the safe default and higher values should be treated as an explicit operator override.
- If a previous local owner process died, the next acquire attempt should reap the orphaned
  lock automatically.
- Only force-break the remote host lock when the recorded holder is confirmed dead and you
  have checked that no valid PM99 run is still active on the host.

## Validation Summary

The updated lock behavior was validated by:

- holding the lock in one process and confirming another waits
- raising concurrency to `2` and confirming two holders run while a third queues
- confirming `PM99_RUNNER_HOST_LOCK_WAIT_SECONDS=0` times out instead of barging through
- confirming orphaned locks from dead local owner PIDs are reaped automatically
- leaving the host clean afterward with no active shared lock present

