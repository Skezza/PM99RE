# Stoke 2015 Runtime Bisect (2026-04-10)

Goal: identify whether the `MANAGPRE: Application cannot continue.` runtime failure is caused by:

- the 20-player metadata enrichment pass,
- the Stoke 2015 squad rewrite itself,
- or another remaining DB delta.

## Control lane

The isolated remote static squad probe is now deterministic against the vanilla game.

Working control:
- `scripts/run_stoke_remote_profile_probe.sh --mode static_squad`
- artifact: `artifacts/stoke_remote_profile_probe/stoke_remote_static_control_v3_20260410T202609Z`
- result: reached `30_dashboard_enter_selected.png`
- image diff vs vanilla squad reference: `diff_average=2.1550`
- `run_status=0`

This closes the earlier harness bug. The previous failures were caused by:
- an extra final click that opened a player profile instead of stopping on `Squad Management`
- skipped OCR/classification removing enough timing slack to break the menu flow

## Metadata revert experiment

Baseline source used for reversal:
- `work/pm99/joe/stoke_2015_noinject_fast_20260410T194922Z`

Fresh isolated candidate:
- `work/pm99/joe/stoke_2015_strategy_revert_base_20260410T203851Z`

Method:
1. clone the full Stoke 2015 game root into a fresh isolated run
2. derive original metadata field values from the pristine baseline for the same player record ids
3. apply a reverse metadata batch with `scripts/stoke_2015_apply_metadata_subset.py`

Artifacts:
- reverse manifest:
  - `work/pm99/joe/stoke_2015_strategy_revert_base_20260410T203851Z/patches/stoke_2015_revert_to_strategy_only/stoke_2015_original_metadata_manifest.json`
- 20-row reverse batch:
  - `work/pm99/joe/stoke_2015_strategy_revert_base_20260410T203851Z/patches/stoke_2015_revert_to_strategy_only/apply/stoke_2015_metadata_subset_apply_result.json`
- slot-1 cleanup without weight:
  - `work/pm99/joe/stoke_2015_strategy_revert_base_20260410T203851Z/patches/stoke_2015_revert_to_strategy_only/apply_slot1_no_weight/stoke_2015_metadata_subset_apply_result.json`

Important result:
- rows `2..20` reverted cleanly in one batch
- slot `1` initially failed because donor pid `3445` has original weight `0`, and the editor rejects weight values outside `40..140`
- slot `1` then reverted cleanly for `nationality,dob,height` with weight left at `0`

Net effect:
- the candidate root now represents `Stoke 2015 squad + faces`, with the metadata enrichment effectively removed

## Runtime results

### Probe 1: strategy-only candidate

Command:
- `scripts/run_stoke_remote_profile_probe.sh --mode static_squad --skip-image-eval --local-overlay-dir work/pm99/joe/stoke_2015_strategy_revert_base_20260410T203851Z/game --run-tag stoke_2015_strategy_probe_v1_20260410T204311Z`

Artifacts:
- `artifacts/stoke_remote_profile_probe/stoke_2015_strategy_probe_v1_20260410T204311Z/summary.json`
- `artifacts/stoke_remote_profile_probe/stoke_2015_strategy_probe_v1_20260410T204311Z/screens/30_dashboard_enter_selected.png`

Result:
- still fails with `blocking_error_modal`
- modal first appears by `26_continue_after_rivals.png`
- final classification: `blocking_error_modal`

Conclusion:
- removing the 20-player metadata enrichment does **not** remove the runtime failure

### Probe 2: alternate-PID Stoke 2015 root

Source root:
- `work/stoke_2015_face_prepare_20260410T121616Z/game`

This root already contains:
- Stoke 2015 squad names in all 20 Stoke slots
- original/stable player record ids such as `Jack Butland -> pid 9404`

Command:
- `scripts/run_stoke_remote_profile_probe.sh --mode static_squad --skip-image-eval --local-overlay-dir work/stoke_2015_face_prepare_20260410T121616Z/game --run-tag stoke_2015_altpid_probe_v1_20260410T204820Z`

Artifacts:
- `artifacts/stoke_remote_profile_probe/stoke_2015_altpid_probe_v1_20260410T204820Z/summary.json`
- `artifacts/stoke_remote_profile_probe/stoke_2015_altpid_probe_v1_20260410T204820Z/screens/30_dashboard_enter_selected.png`

Result:
- also fails with the same `blocking_error_modal`
- same failure timing around the preseason continuation boundary

Conclusion:
- the runtime failure is **not specific** to the donor-slot-1 roster lineage used in `stoke_2015_noinject_fast`
- the failure survives across at least two different Stoke 2015 database lineages

### Probe 3: slot-1-only manual replay

Fresh isolated candidate:
- `work/pm99/joe/stoke_bisect_slot1_manual_20260410T210250Z`

Method:
1. clone a pristine isolated game root
2. rename donor pid `3445` from `Roth Rothjal` to `Jack Butland`
3. repoint Stoke linked slot `1` from pid `9404` to `3445`
4. repoint Stoke authoritative same-entry slot `1` from pid `9404` to `3445`

Artifacts:
- donor rename:
  - `work/pm99/joe/stoke_bisect_slot1_manual_20260410T210250Z/patches/stoke_slot1_manual/player_edit.json`
- linked + same-entry slot-1 repoint:
  - `work/pm99/joe/stoke_bisect_slot1_manual_20260410T210250Z/patches/stoke_slot1_manual/team_roster_batch_edit.json`
- parser validation:
  - `work/pm99/joe/stoke_bisect_slot1_manual_20260410T210250Z/patches/stoke_slot1_manual/validate_database.json`

Remote runtime evidence:
- `artifacts/stoke_remote_profile_probe/stoke_bisect_slot1_manual_20260410T210250Z_probe/screens/29_dashboard_select_squad.png`

Result:
- local parser validation is clean
- the remote runtime path reaches `dashboard_select_squad`
- the probe wrapper did not emit a final summary, but it progressed materially beyond the preseason continuation boundary that kills the failing Stoke 2015 roots

Conclusion:
- slot `1` by itself is **not sufficient** to reproduce the `MANAGPRE` runtime failure

### Probe 4: full failing root with slot 1 reverted

Fresh isolated candidate:
- `work/pm99/joe/stoke_bisect_full_minus_slot1_20260410T212439Z`

Method:
1. clone the known failing Stoke 2015 root `work/pm99/joe/stoke_2015_noinject_fast_20260410T194922Z/game`
2. revert donor pid `3445` name from `Jack Butland` back to `Roth Rothjal`
3. revert Stoke linked slot `1` from pid `3445` back to `9404`
4. revert Stoke authoritative same-entry slot `1` from pid `3445` back to `9404`

Artifacts:
- donor rename reversal:
  - `work/pm99/joe/stoke_bisect_full_minus_slot1_20260410T212439Z/patches/revert_slot1/player_edit_reverse.json`
- linked + same-entry slot-1 reversal:
  - `work/pm99/joe/stoke_bisect_full_minus_slot1_20260410T212439Z/patches/revert_slot1/team_roster_batch_edit_reverse.json`
- parser validation:
  - `work/pm99/joe/stoke_bisect_full_minus_slot1_20260410T212439Z/patches/revert_slot1/validate_database.json`
- remote runtime failure frame:
  - `artifacts/stoke_remote_profile_probe/stoke_bisect_full_minus_slot1_20260410T212439Z_probe/screens/26_continue_after_rivals.png`

Result:
- local parser validation is clean after reverting slot `1`
- the remote runtime probe still dies at `26_continue_after_rivals.png`
- the synced frame is the same `MANAGPRE: Application cannot continue.` modal seen in the earlier failing Stoke 2015 probes

Conclusion:
- slot `1` is **not necessary** to reproduce the runtime failure
- the remaining blocker is in slots `2..20` and/or another non-slot-1 Stoke delta still present in the failing root
- the practical bisect target is now the non-slot-1 transformation set

### Probe 5: names-only reversal on the non-slot-1 failing root

Fresh isolated candidate:
- `work/pm99/joe/stoke_bisect_names_reverted_20260410T214321Z`

Method:
1. clone the non-slot-1 failing root `work/pm99/joe/stoke_bisect_full_minus_slot1_20260410T212439Z/game`
2. revert only the 19 Stoke player display names in `JUG98030.FDI`
3. keep the linked/same-entry team surfaces unchanged

Local artifacts:
- 19-row reverse batch:
  - `work/pm99/joe/stoke_bisect_names_reverted_20260410T214321Z/patches/revert_names_only/player_batch_edit_reverse_names.json`
- parser validation:
  - `work/pm99/joe/stoke_bisect_names_reverted_20260410T214321Z/patches/revert_names_only/validate_database.json`

Remote runtime artifacts:
- `artifacts/stoke_remote_profile_probe/stoke_bisect_names_reverted_20260410T214321Z_probe/summary.json`
- `artifacts/stoke_remote_profile_probe/stoke_bisect_names_reverted_20260410T214321Z_probe/screens/30_dashboard_enter_selected.png`

Result:
- local parser validation is clean (`19/19` rows matched, `warnings=0`)
- the remote run still ends classified as `blocking_error_modal`
- the late screenshots remain the same repeated modal frame (`26` and `30` hash-match the known failing frame)

Conclusion:
- reverting the 19 `JUG98030.FDI` display names is **not sufficient** to remove the runtime failure
- player names alone are not the remaining blocker

## Linked roster comparison

Additional readback on 2026-04-10 tightened the non-slot-1 scope further.

Comparison roots:
- near-pristine comparator:
  - `work/pm99/joe/stoke_bisect_slot1_manual_20260410T210250Z`
- failing non-slot-1 candidate:
  - `work/pm99/joe/stoke_bisect_full_minus_slot1_20260410T212439Z`

Linked Stoke roster readback shows:
- slot `1` differs as expected (`3445 / Jack Butland` vs `9404 / Bryan SMALL`)
- slots `2..20` keep the **same linked player ids** across both roots
- slots `2..20` differ in **player display names**, not linked PID assignment

Example:
- slot `2`: pid `9581`
  - near-pristine name: `Peter THORNE`
  - failing non-slot-1 name: `Phil Bardsley`
- slot `15`: pid `26936`
  - near-pristine name: `Stuart FRASER`
  - failing non-slot-1 name: `Ryan Shawcross`

Implication:
- the non-slot-1 failure is not driven by linked-slot PID swaps
- the remaining suspects are:
  - broader indexed `JUG98030.FDI` metadata rewrites on the existing Stoke-linked pids
  - same-entry authoritative surface edits
  - another coupled non-linked delta still present in the Stoke 2015 rewrite

### Probe 5: file-level `EQ`/`JUG` split against the strategy-revert root

Baseline source used for the split:
- `work/pm99/joe/stoke_2015_strategy_revert_base_20260410T203851Z/game`

New tooling added for this split:
- `scripts/build_stoke_2015_isolated_game.sh`
  - supports `--skip-squad`, `--skip-metadata`, `--skip-faces` so exact phase-boundary roots can be materialized without ad hoc edits
- `scripts/create_stoke_2015_debug_variant.py`
  - supports `pristine_eq` and `pristine_jug` modes to restore only one DB file from the pristine fixture

Fresh split candidates:
- `work/pm99/joe/stoke_2015_strategy_revert_pristine_eq_20260410T212710Z`
  - restores `EQ98030.FDI` to pristine
  - keeps the failing-root `JUG98030.FDI`
- `work/pm99/joe/stoke_2015_strategy_revert_pristine_jug_20260410T212710Z`
  - restores `JUG98030.FDI` to pristine
  - keeps the failing-root `EQ98030.FDI`

Local validation:
- both split candidates still pass parser validation
  - `work/pm99/joe/stoke_2015_strategy_revert_pristine_eq_20260410T212710Z/patches/pristine_eq/validate_database.json`
  - `work/pm99/joe/stoke_2015_strategy_revert_pristine_jug_20260410T212710Z/patches/pristine_jug/validate_database.json`

Remote runtime probes:
- `stoke_2015_pristine_eq_probe_20260410T212833Z`
  - artifacts on runner host: `/home/joe/pm99-runner/artifacts/stoke_2015_pristine_eq_probe_20260410T212833Z`
  - summary copied locally for review: `work/tmp/pristine_eq_live/summary.json`
- `stoke_2015_pristine_jug_probe_20260410T213059Z`
  - artifacts on runner host: `/home/joe/pm99-runner/artifacts/stoke_2015_pristine_jug_probe_20260410T213059Z`

Results:
- `pristine_eq` no longer fails at the configuration `Continue` boundary
  - it progresses through manager naming, Stoke selection, and rival assignment
  - the modal still appears later at the historical preseason boundary
  - evidence:
    - `work/tmp/pristine_eq_live/26_continue_after_rivals.png`
    - `work/tmp/pristine_eq_live/27_preseason_continue_retry.png`
    - `work/tmp/pristine_eq_live/30_dashboard_enter_selected.png`
  - `summary.json` reports:
    - `success = false`
    - `phase_reached = "blocked_modal"`
- `pristine_jug` also no longer fails at the original early boundary
  - it reaches the manager/team selection screen and advances through Stoke selection
  - last captured clean frame is:
    - `work/tmp/pristine_jug_live/16_pick_stoke.png`
  - unlike `pristine_eq`, it did not write a final summary and stopped before `continue_team`

Conclusions from the file split:
- the immediate startup/configuration-screen modal is **not** attributable to `JUG98030.FDI` alone or `EQ98030.FDI` alone
- restoring either file suppresses the earliest failure mode seen in the fully failing root
- restoring `EQ98030.FDI` is the stronger recovery:
  - it restores the runtime path all the way back to the later preseason modal boundary
- therefore the current best interpretation is:
  - the earliest modal depends on the combined `JUG` + `EQ` Stoke rewrite
  - there is still at least one later-stage blocker compatible with a modified `JUG98030.FDI`

## Face-patch exclusion

The face pipeline is not the cause of the runtime failure.

Evidence:
- `work/pm99/joe/stoke_2015_noinject_fast_20260410T194922Z/patches/stoke_2015_faces/prepare_manifest.json`

That manifest shows:
- `JUG98030.FDI`: unchanged
- `EQ98030.FDI`: unchanged
- `ENT98030.FDI`: unchanged
- only `MINIFOTO.PKF` changed

Since the modal appears before squad/profile navigation and survives on roots with different roster lineages, the current working assumption is:

- the breakage is in the Stoke 2015 team/player DB rewrite itself, not the bitmap patch and not the 20-player metadata enrichment layer

## Current closeout

What is now proven:
- vanilla isolated probe path is stable
- metadata enrichment is not the primary runtime blocker
- face bitmap patching is not the primary runtime blocker
- slot `1` alone is not sufficient to trigger the runtime failure
- slot `1` is not necessary to trigger the runtime failure
- the immediate startup modal requires more than a single-file `EQ`-only or `JUG`-only delta
- `EQ98030.FDI` is the dominant contributor to the earliest failure mode
- a later blocker remains compatible with modified `JUG98030.FDI`

## Next step

The next milestone should focus on the remaining DB deltas:

1. diff `EQ98030.FDI` between pristine and the failing Stoke roots, prioritizing the non-slot-1 rows that participate in team confirmation and preseason setup
2. close out the `JUG`-only-late-blocker path by identifying the smallest `JUG` subset that still reproduces the preseason modal with pristine `EQ`
3. keep `EQ` and `JUG` bisects separate from this point onward; the file split shows they are not contributing at the same stage

## Indexed-payload closeout follow-up

Follow-up work on 2026-04-10 tightened the failing-state reproduction further by switching from parser-backed edits to exact indexed payload restores.

New tooling:
- `scripts/create_stoke_2015_jug_bisect_variant.py`
  - now supports `--surfaces payload` for exact `JUG98030.FDI` payload restoration by selected Stoke slot range
- `scripts/create_indexed_payload_restore_variant.py`
  - generic exact indexed-payload restore helper for isolated game roots
  - restores one or more record ids from a baseline root into a cloned source root

### Probe 6: exact `JUG` payload restore for Stoke slots `2..20`

Fresh isolated candidate:
- `work/pm99/joe/stoke_bisect_jug_payload_restored_20260410T223500Z`

Method:
1. clone the non-slot-1 failing root `work/pm99/joe/stoke_bisect_full_minus_slot1_20260410T212439Z/game`
2. restore the exact decoded `JUG98030.FDI` indexed payloads for Stoke-linked pids in slots `2..20`
3. keep the failing-root `EQ98030.FDI` untouched

Artifacts:
- payload restore report:
  - `work/pm99/joe/stoke_bisect_jug_payload_restored_20260410T223500Z/patches/jug_bisect/payload_restore_result.json`
- parser validation:
  - `work/pm99/joe/stoke_bisect_jug_payload_restored_20260410T223500Z/patches/jug_bisect/validate_database.json`

Result:
- all 19 restored `JUG` payloads match the baseline exactly post-write
- the remote early screenshot hashes still land on the same blocking modal
  - `04_focus_name.png` hash:
    - `98bea3e4efce464dc12e5992181eded09fdf30ea926d14d4091e459cff45dc98`
  - this is the same modal frame used by the failing Stoke 2015 branches

Conclusion:
- restoring the exact Stoke `JUG` player payloads for slots `2..20` is **not sufficient** to remove the early modal
- the remaining early blocker still depends on `EQ` or another coupled non-player surface

### Probe 7: exact Stoke `EQ` team payload restore

Fresh isolated candidate:
- `work/pm99/joe/stoke_bisect_eq_payload_restored_20260410T224800Z`

Method:
1. clone the exact-`JUG` restored branch above
2. restore indexed record id `341` from `DBDAT/EQ98030.FDI` using the near-pristine control root `work/pm99/joe/stoke_bisect_slot1_manual_20260410T210250Z/game`

Artifacts:
- payload restore report:
  - `work/pm99/joe/stoke_bisect_eq_payload_restored_20260410T224800Z/patches/indexed_payload_restore/payload_restore_result.json`
- parser validation:
  - `work/pm99/joe/stoke_bisect_eq_payload_restored_20260410T224800Z/patches/indexed_payload_restore/validate_database.json`

Important finding:
- after restoring `EQ` record `341`, the entire `EQ98030.FDI` file matches the `slot1_manual` control root exactly
- however, the early modal still appeared in the probe hashes
  - `04_focus_name.png` hash:
    - `98bea3e4efce464dc12e5992181eded09fdf30ea926d14d4091e459cff45dc98`

Interpretation:
- restoring only Stoke team record `341` is **not enough** to recreate the safe control
- the remaining mismatch was not in `EQ98030.FDI` anymore

### Residual delta to the safe `slot1_manual` control

Comparing `work/pm99/joe/stoke_bisect_eq_payload_restored_20260410T224800Z/game` against the safe control root `work/pm99/joe/stoke_bisect_slot1_manual_20260410T210250Z/game` showed:

- `EQ98030.FDI`: zero indexed payload diffs
- `JUG98030.FDI`: exactly one remaining indexed payload diff
  - record id `3445`
- core-file hash comparison showed the only remaining non-DB core delta was:
  - `DBDAT/MINIFOTO.PKF`

This identified the last Stoke-specific donor inconsistency:
- `EQ` slot `1` had been restored to point at donor pid `3445`
- but `JUG` record `3445` had not yet been restored to the same safe donor payload

### Probe 8 prep: restore `JUG` record `3445`

Fresh isolated candidate:
- `work/pm99/joe/stoke_bisect_slot1_manual_recreated_20260410T230900Z`

Method:
1. clone `work/pm99/joe/stoke_bisect_eq_payload_restored_20260410T224800Z/game`
2. restore exact `JUG98030.FDI` record id `3445` from the safe `slot1_manual` root

Artifacts:
- payload restore report:
  - `work/pm99/joe/stoke_bisect_slot1_manual_recreated_20260410T230900Z/patches/indexed_payload_restore/payload_restore_result.json`

Result:
- `JUG98030.FDI` now has zero indexed payload diffs versus `slot1_manual`
- `EQ98030.FDI` still has zero indexed payload diffs versus `slot1_manual`
- the only remaining core-file hash delta versus the safe control is:
  - `DBDAT/MINIFOTO.PKF`

### Probe 9 prep: full-core control recreation

Fresh isolated candidate:
- `work/pm99/joe/stoke_bisect_full_core_control_20260410T231500Z`

Method:
1. clone `work/pm99/joe/stoke_bisect_slot1_manual_recreated_20260410T230900Z/game`
2. restore `DBDAT/MINIFOTO.PKF` from the safe `slot1_manual` root

Result:
- the recreated branch is now hash-identical to the safe `slot1_manual` control for all core files:
  - `DBDAT/JUG98030.FDI`
  - `DBDAT/EQ98030.FDI`
  - `DBDAT/MINIFOTO.PKF`
  - `MANAGPRE.EXE`

Implication:
- if the runner still behaves differently on this recreated full-core control, the remaining discrepancy is no longer in the game data under investigation and the next target is the probe/wrapper path itself
- if the recreated control behaves like the original `slot1_manual` root, the remaining causal chain is fully explained by the donor-coupled `EQ` + `JUG` + `MINIFOTO` state

### Control parity reprobe

Two direct reprobes were run with the same static-squad flow:

- recreated full-core control:
  - `work/pm99/joe/stoke_bisect_full_core_control_20260410T231500Z/game`
  - artifacts: `artifacts/stoke_remote_profile_probe/stoke_bisect_full_core_control_20260410T231500Z_probe`
- original safe control:
  - `work/pm99/joe/stoke_bisect_slot1_manual_20260410T210250Z/game`
  - artifacts: `artifacts/stoke_remote_profile_probe/stoke_bisect_slot1_manual_control_reprobe_20260410T233500Z`

Results:
- both runs emitted `31` screenshots
- both runs reached:
  - `30_dashboard_enter_selected.png`
- both wrapper runs reported:
  - `image_eval_skipped=true`
  - `success=true`
  - `run_status=1`

Screenshot parity:
- comparing the full screenshot sets shows only one hash difference:
  - `00_title.png`
- screenshots `01..30` hash-match between the recreated full-core control and the original safe control

Conclusion:
- the recreated full-core control is runtime-equivalent to the original safe control for the static Stoke squad path
- the DB-side recreation is therefore sound; the earlier failures were not caused by an unobserved runner-only discrepancy

### `MINIFOTO`-only delta follow-up

To isolate the final non-DB core surface, the branch that differs from the safe control only in `DBDAT/MINIFOTO.PKF` was reprobed:

- candidate:
  - `work/pm99/joe/stoke_bisect_slot1_manual_recreated_20260410T230900Z/game`
- run tag:
  - `stoke_bisect_minifoto_only_delta_reprobe_20260410T235500Z`

Remote evidence before wrapper failure:
- the run progressed through:
  - `continue_team`
  - rival assignment
  - `continue_after_rivals`
  - `preseason_continue_retry`

This is materially beyond the early `focus_name` modal seen in the failing Stoke 2015 branches.

Conclusion:
- `MINIFOTO.PKF` alone does **not** reproduce the early runtime blocker
- the face archive is still not the primary cause of the early modal

### Current best interpretation

What is now closed:
- the safe control can be recreated exactly from the failing lineage by restoring:
  - Stoke `JUG` slots `2..20`
  - Stoke `EQ` record `341`
  - donor `JUG` record `3445`
  - `MINIFOTO.PKF`
- the recreated control is runtime-parity-clean against the original safe control
- `MINIFOTO` by itself is not the early blocker

What remained most likely at that point:
- the early blocker was thought to be driven by the donor-coupled `JUG` record `3445` state in combination with the Stoke team rewrite lineage
- the next decisive probe was a one-record branch that flips only `JUG` record `3445` away from the safe full-core control while keeping `EQ` and `MINIFOTO` fixed

## `JUG` record `3445` probe reclassification

The original `3445` probe conclusions were polluted by two wrapper defects:

- PM99RE root scripts were calling `/workspace/repo/scripts/pm99_runner/...` even though the runner lives under `upstream/pm99-runner/...`
- the namespaced remote repo was stale and not reliably writable for full repo rsync

Those wrappers are now repaired to stage the runner package directly into the per-run remote home directory and execute from:

- `/workspace/home/pm99_runner/native_runner.py`
- `/workspace/home/pm99_runner/stoke_vanilla_profile_capture_driver.py`

With that repaired lane, the `3445` branch was reprobed as a compact source-relative core overlay:

- run tag:
  - `stoke_bisect_jug3445_only_bad_20260411T001000Z_probe_core_overlay`
- overlay contents:
  - `DBDAT/JUG98030.FDI`
  - `DBDAT/EQ98030.FDI`
  - `DBDAT/MINIFOTO.PKF`
  - `MANAGPRE.EXE`

Observed result:

- `31` screenshots were emitted
- screenshots `01..30` are hash-identical to the safe control reprobe
- only `00_title.png` differs, which matches the known control parity pattern
- `window_state_after.json` still contains a `MANAGPRE` window

Crucial control comparison:

- the supposedly safe control reprobe also contains the same latent `MANAGPRE` window in `window_state_after.json`
- both summaries report:
  - `blocking_error_modal_detected=true`
  - `step_count=30`
- both runs reach:
  - `30_dashboard_enter_selected.png`

Conclusion:

- `JUG` record `3445` alone is **not** a runtime blocker on the repaired lane
- the current `blocking_error_modal_detected` flag is over-sensitive for this route and cannot be used as a failure verdict by itself
- screenshot parity against the safe control is the stronger truth source for this probe family

This materially changes the interpretation of earlier results. The next valid target is the real Stoke 2015 roster state, reprobed on the same compact overlay lane and judged against screenshot parity, not the latent modal flag alone.

## Milestone ladder

The next 20 milestones should now follow a single reproducible lane rather than ad hoc probing:

1. rerun the actual Stoke 2015 `nofaces` roster state on the repaired compact-overlay lane
2. compare its screenshot hashes against the safe control and identify the first divergent frame, if any
3. rerun the exact current local metadata state on the same compact-overlay lane once its source-relative overlay is materialized
4. normalize probe verdicts around screenshot parity and reached phase, not `blocking_error_modal_detected` alone
5. update all Stoke runtime helper scripts to use staged `/workspace/home/pm99_runner/*` entrypoints
6. add a thin probe result normalizer that emits `phase_reached`, screenshot count, and first divergent frame against a control artifact set
7. materialize a compact source-relative overlay builder for runtime-critical core files
8. probe the `roster_only` Stoke 2015 branch on the compact lane
9. probe the `strategy_only_exact` Stoke 2015 branch on the compact lane
10. compare `nofaces`, `roster_only`, and `strategy_only_exact` first-divergence frames to identify the first harmful mutation family
11. if the harmful family is still broad, split the affected Stoke `JUG` slot ranges on top of the full-core control
12. bisect any failing slot range into quarter ranges
13. reduce any failing quarter to per-slot indexed payload replays
14. reduce any failing slot to per-record `JUG` or `EQ` payload replays when the slot crosses both surfaces
15. add a manifest-backed corpus of known-safe and known-divergent Stoke runtime branches
16. codify the slot `1` donor-coupling rule as a documented invariant even though `3445` alone is now cleared
17. encode exact indexed-payload restore recipes for all remaining runtime-critical Stoke branches
18. generalize the compact runtime-bisect workflow to the broader Stoke 2015 squad rewrite
19. map any surviving runtime divergence to the smallest set of upstream editor operations that can generate it
20. convert those operations into editor-side safety gates or contract failures
21. publish the final upstream handover package with scripts, manifests, branch roots, and runtime proof artifacts
