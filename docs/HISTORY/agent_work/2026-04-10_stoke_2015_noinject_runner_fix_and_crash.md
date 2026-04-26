# Stoke 2015 No-Inject Validation: Runner Popup Fix And Real Crash Point

Date: 2026-04-10

## Summary
- Implemented hermetic no-injection validation against the isolated Stoke 2015 game root at [stoke_2015_noinject_fast_20260410T194922Z](/home/joe/pm99-research/work/pm99/joe/stoke_2015_noinject_fast_20260410T194922Z).
- Fixed a runner-side environmental blocker where Fluxbox spawned `xmessage` from `fbsetbg`, covering root screenshots and confusing CV/classification.
- Re-ran the same no-injection flow after the fix and confirmed the remaining failure is a real PM99 termination after rival selection, not a runner popup.

## Code Changes
- Added ignored-popup dismissal to the native runner:
  - [native_runner.py](/home/joe/pm99-research/upstream/pm99-runner/scripts/pm99_runner/native_runner.py)
- Added a background `xmessage` killer in the Docker image entrypoint so the popup is suppressed during Fluxbox/Wine bootstrap, before Python automation starts:
  - [entrypoint.sh](/home/joe/pm99-research/upstream/pm99-runner/scripts/pm99_runner/image/entrypoint.sh)

## Validation Runs
### Pre-fix run
- Run tag: `stoke_2015_noinject_validate_20260410T201654Z`
- Observed failure was contaminated by a visible `xmessage` popup from `fbsetbg`.

### Post-fix run
- Run tag: `stoke_2015_noinject_validate4_20260410T203355Z`
- Local mirrored artifacts:
  - [artifact bundle](/home/joe/pm99-research/upstream/pm99-runner/docs/artifacts/pm99_runner/stoke_2015_noinject_validate4_20260410T203355Z)

## Findings
- The popup is gone in the rebuilt image.
- The no-injection Stoke 2015 game root boots and progresses through:
  - title screen
  - manager naming
  - second division selection
  - Stoke selection
  - rival assignment
- After [26_continue_after_rivals.png](/home/joe/pm99-research/upstream/pm99-runner/docs/artifacts/pm99_runner/stoke_2015_noinject_validate4_20260410T203355Z/screens/26_continue_after_rivals.png), PM99 disappears.
- Subsequent captures ([27_blocking_error_modal_ok.png](/home/joe/pm99-research/upstream/pm99-runner/docs/artifacts/pm99_runner/stoke_2015_noinject_validate4_20260410T203355Z/screens/27_blocking_error_modal_ok.png), [28_preseason_continue_retry.png](/home/joe/pm99-research/upstream/pm99-runner/docs/artifacts/pm99_runner/stoke_2015_noinject_validate4_20260410T203355Z/screens/28_preseason_continue_retry.png)) show only the bare Fluxbox desktop.
- Container process inspection at that point shows `MANAGPRE.EXE` is gone and only defunct Wine processes remain.
- `wine.log` does not show a useful PM99 exception; it only shows ALSA noise.

## Interpretation
- The environmental runner issue is fixed.
- The remaining blocker is a true in-game exit/crash during the transition after rival selection.
- The current evidence does not yet isolate whether the crash is caused by:
  - the Stoke roster rewrite itself
  - a specific metadata mutation
  - another data-integrity issue not caught by `validate-database`

## Incomplete Follow-Up
- I started a roster-only isolated rebuild at:
  - [stoke_2015_roster_only_20260410T204227Z](/home/joe/pm99-research/work/pm99/joe/stoke_2015_roster_only_20260410T204227Z)
- I stopped it before completion because slot-1 donor rewrite was too slow to finish inside this turn.
- That is the next clean discriminating test: roster-only no-injection validation versus roster+metadata+faces.
