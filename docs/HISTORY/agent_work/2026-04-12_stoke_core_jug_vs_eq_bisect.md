# Stoke core JUG vs EQ bisect

## Summary
The remaining Stoke 2015 no-injection failure is not a process crash. It is the `MANAGPRE` blocking modal `Application cannot continue.` raised from `FUN_006aacb0` after `FUN_00408720()` succeeds through `vtable+0x118` (`FUN_00408880`) and fails at `vtable+0x11c` (`FUN_00408a70`).

## Decisive split
Using the clean Stoke control root as baseline:
- control JUG hash: `45563183103db5c2a4386099d256fa28434692332009855147f49c22d94315b8`
- control EQ hash: `9d6591d267dc8a1bb5bddfa2b035a0f699632df69e6c8e65282e78558547374e`

Failing Stoke root:
- failing JUG hash: `ad4525b03325209c5a5a251ce369d3b617c8f8cf29183b5c3bbe3d8ed738676f`
- failing EQ hash: `e095cb47ffdb6c8edf384983545124eb514d044fa4f0ce7d924b6bfe13252a5c`

Variant `stoke_eq_only_current_20260412T171500Z` was named badly; it is actually the `JUG-only` residual split:
- JUG = failing
- EQ = control

Run result:
- run tag: `stoke_eq_only_current_20260412T171500Z`
- local artifacts: `/home/joe/pm99-research/artifacts/stoke_remote_profile_probe/stoke_eq_only_current_20260412T171500Z`
- outcome: same blocking modal at `03_continue_visible`

This proves the shared Stoke `JUG98030.FDI` rewrite is sufficient by itself to trigger the modal. `EQ98030.FDI` is not required for the failure.

## Residual data shape
The shared changed JUG record ids are:
`3445, 9581, 9772, 9773, 9778, 9781, 9782, 9785, 10001, 10065, 10242, 15577, 15578, 26935, 26936, 32958, 32959, 32960, 33150, 33151`

These map to the Stoke 2015 first-team rewrite:
- Jack Butland
- Phil Bardsley
- Erik Pieters
- Marc Muniesa
- Glenn Whelan
- Stephen Ireland
- Glen Johnson
- Peter Odemwingie
- Marko Arnautovic
- Joselu Mato
- Marc Wilson
- Ibrahim Afellay
- Marco van Ginkel
- Charlie Adam
- Ryan Shawcross
- Mame Diouf
- Jonathan Walters
- Geoff Cameron
- Giannelli Imbula
- Steve Sidwell

Raw EQ analysis shows only one actual roster-link delta relative to control:
- Stoke slot `0`: `3445 -> 9404` for Jack Butland

All other apparent Stoke EQ differences were linked-name changes driven by the JUG rewrite.

## Interpretation
The current blocker lives in the Stoke core JUG payload rewrite, not in:
- runner flow
- Wine/debugger
- MANAGPRE executable mismatch
- MINIFOTO
- the earlier indexed-name serializer bug
- metadata tail rows 18..20
- the broad EQ surface

The remaining next-step investigation, if resumed later, is to bisect the 20 Stoke JUG records themselves.

## Final JUG bisect (2026-04-13)
Using the clean `JUG=failing, EQ=control` root `/home/joe/pm99-research/work/pm99/joe/stoke_eq_only_current_20260412T171500Z/game` as the source:

- restoring 17 records and leaving only `{33151, 3445, 9773}` changed succeeds
  - run tag: `stoke_jug_others_restored_eqcontrol_probe_20260412T234500Z`
- restoring the early eight of the remaining 17 still fails
  - run tag: `stoke_jug_groupA_restored_eqcontrol_probe_20260413T001500Z`
- restoring those eight plus `{10242, 15577, 15578, 26935}` still fails
  - run tag: `stoke_jug_groupA_plus_halfA_restored_eqcontrol_probe_20260413T050500Z`
- restoring those twelve plus `{32958, 32959, 32960}` still fails
  - run tag: `stoke_jug_cumulative_top3of5_restored_eqcontrol_probe_20260413T054500Z`

This reduced the pure JUG blocker to `{26936, 33150}`.

Single-record confirmation:
- only `33150` changed succeeds
  - run tag: `stoke_jug_only_33150_changed_eqcontrol_probe_20260413T064500Z`
  - local artifacts: `/home/joe/pm99-research/artifacts/stoke_remote_profile_probe/stoke_jug_only_33150_changed_eqcontrol_probe_20260413T064500Z`
- only `26936` changed fails with the same blocking modal
  - run tag: `stoke_jug_only_26936_changed_eqcontrol_probe_20260413T064500Z`
  - local artifacts: `/home/joe/pm99-research/artifacts/stoke_remote_profile_probe/stoke_jug_only_26936_changed_eqcontrol_probe_20260413T064500Z`

This isolates the remaining pure JUG blocker to record id `26936` exactly.

The separate EQ-side blocker remains the Stoke slot-`0` roster repoint `3445 -> 9404`.

## Parallel 8-lane confirmation (2026-04-13)
To remove queue noise from unrelated runner work, the same Stoke variants were re-probed under a temporary 8-lane worker config with archive/budget cleanup suppressed.

Confirmed outcomes:
- `stoke_jug_others_restored_eqcontrol_parallel8_20260413T231000Z`
  - succeeds cleanly
  - `screen_count = 31`
  - `squad_like = true`
  - `last_screenshot = 30_dashboard_enter_selected.png`
  - `best_screenshot = 30_dashboard_enter_selected.png`
  - `diff_average = 6.373183593749999`
- `stoke_eq_only_current_parallel8_20260413T231000Z`
  - fails with the same `MANAGPRE` modal signature
  - `screen_count = 31`
  - `squad_like = false`
  - `last_screenshot = 30_dashboard_enter_selected.png`
  - `best_screenshot = 04_focus_name.png`
  - `diff_average = 103.10340169270835`
- `stoke_full_repair_jug26936_only_parallel8_20260413T231000Z`
  - fails with the same signature as the `EQ`-only run
- `stoke_full_repair_jug26936_eq341_parallel8_20260413T231000Z`
  - fails with the same signature as the `EQ`-only run

This confirms the broad 17-record JUG-restored surface is not the blocker. The remaining failure surface is still the exact `JUG` record `26936` plus the independent `EQ` slot-`0` repoint `3445 -> 9404`.

## Final validation recheck (2026-04-14)
Two recent 8-lane probes separated the noisy composite root from the known-good repair surface.

Failed composite root:
- `stoke_eqslot0_repair_probe_8lane_20260414T000500Z`
- `success = false`
- `screen_count = 31`
- `squad_like = false`
- `diff_average = 103.10340169270835`
- `last_screenshot = 30_dashboard_enter_selected.png`

Successful repaired root:
- `stoke_success_root_recheck_8lane_20260414T003000Z`
- `success = true`
- `screen_count = 31`
- `squad_like = true`
- `diff_average = 6.4299088541666665`
- `last_screenshot = 30_dashboard_enter_selected.png`
- `best_screenshot = 30_dashboard_enter_selected.png`

The successful repaired root keeps the Stoke slot-0 roster at pid `3445` with the `Roth Rothjal` linked-name state, and it preserves the broader JUG restore surface that already cleared the modal on the earlier parallel sweep.

## 9581 field split (2026-04-14)
The remaining record-level ambiguity was the JUG offset `1842617` / record id `9581`.

The field split is now clean:
- name-only rename probe:
  - `stoke_9581_name_only_20260414T000528Z`
  - renaming `Peter THORNE -> Phil Bardsley`
  - fails with the same `MANAGPRE` modal at `03_continue_visible`
- alternate rename probe:
  - `stoke_9581_name_alt_20260414T001344Z`
  - renaming `Peter THORNE -> Alan Smith`
  - also fails with the same `MANAGPRE` modal
- metadata-only probe:
  - `stoke_9581_metadata_only_fg_20260414T001039Z`
  - keeps `Peter THORNE` but changes nationality / dob / height / weight to the Phil Bardsley values
  - succeeds through `dashboard_enter_selected` with `blocking_error_modal_detected = false`

Conclusion:
- record `9581` is rename-sensitive, but metadata-safe
- the modal is triggered by the name mutation on this record, not by the metadata fields
- the working no-injection Stoke surface therefore needs the safe `Peter THORNE` name preserved at `9581` while leaving the broader JUG restore surface intact

## Non-9581 rename control (2026-04-14)
To check whether the rename sensitivity was unique to `9581`, a separate control rename was run on a different indexed Stoke record:

- control target:
  - `pid=33150`
  - current name: `Ben PETTY`
  - offset: `3839765`
- rename probe:
  - `Ben PETTY -> Alan Smith`
  - run tag: `stoke_control_rename_petty_20260414T004000Z`
- result:
  - the runtime probe reached the same `MANAGPRE` modal path
  - `success=false`
  - `phase_reached=blocked_modal`
  - `blocking_error_modal_detected=true`

This shows the rename sensitivity is not unique to `9581`; at least one other indexed JUG record trips the same startup modal when renamed, while metadata-only edits remain safe.

## Additional rename control (2026-04-14)
A third indexed JUG record was also tested to see whether the rename-triggered modal was localized to a few records or broadly general:

- control target:
  - `pid=9772`
  - live current name: `Larus SIGURDSSON`
  - offset: `2141389`
- rename probe:
  - `Larus SIGURDSSON -> Alan Smith`
  - run tag: `stoke_control_rename_larus_20260414T055500Z`
- result:
  - the runtime probe again reached `blocked_modal`
  - `success=false`
  - `blocking_error_modal_detected=true`
  - `crash_detected=false`

This reinforces the broader conclusion: indexed JUG name mutations are generally hostile in the no-injection Stoke startup path, while metadata-only edits remain safe.

## Final safe-surface validation (2026-04-14)
The known-good Stoke surface was revalidated end-to-end from the preserved no-rename / metadata-only root:

- safe root:
  - `/home/joe/pm99-research/work/pm99/joe/stoke_jug_others_restored_eqcontrol_20260412T234500Z/game`
- run tag:
  - `stoke_final_safe_surface_20260414T061500Z`
- result:
  - `success=true`
  - `phase_reached=dashboard_enter_selected`
  - `blocking_error_modal_detected=false`
  - `crash_detected=false`

This is the final green proof that the preserved metadata-only Stoke surface still boots through the manager setup / dashboard handoff path.

## Closeout conclusion
Binary-side review of `MANAGPRE.EXE` shows `Application cannot continue.` is emitted by `FUN_006AACB0` as part of general startup/state validation (`FUN_00408720()` -> virtual `+0x118` -> virtual `+0x11C`). There are no direct player-name comparisons in that gate.

Combined with the runtime probes, the closeout conclusion is:
- metadata-only edits are safe on the working Stoke surface
- indexed JUG name mutations are broadly hostile and trip the startup gate
- the supported closeout surface is the preserved no-rename / metadata-only Stoke root

## Maximum safe named subset validation (2026-04-20)
The later multi-lane runner work resolved the remaining single-record ambiguity and then validated the maximum currently-safe named subset as one aggregate root.

Settled safe named JUG payloads:
- `3445` Jack Butland
- `9773` Marc Muniesa
- `9778` Glenn Whelan
- `9781` Stephen Ireland
- `9782` Glen Johnson
- `9785` Peter Odemwingie
- `10242` Marc Wilson
- `26935` Charlie Adam
- `33150` Giannelli Imbula
- `33151` Steve Sidwell

Settled hostile JUG name/payload mutations:
- `9581` Phil Bardsley
- `9772` Erik Pieters
- `10001` Marko Arnautovic
- `10065` Joselu Mato
- `15577` Ibrahim Afellay
- `15578` Marco van Ginkel
- `26936` Ryan Shawcross
- `32958` Mame Diouf
- `32959` Jonathan Walters
- `32960` Geoff Cameron

The final unresolved singles from the 2026-04-18 batch resolved as:
- `10242` Marc Wilson: succeeds
- `15577` Ibrahim Afellay: fails with `MANAGPRE` modal
- `26935` Charlie Adam: succeeds
- `32959` Jonathan Walters: fails with `MANAGPRE` modal
- `32960` Geoff Cameron: fails with `MANAGPRE` modal
- `33150` Giannelli Imbula: succeeds

Aggregate validation:
- root: `/home/joe/pm99-research/work/pm99/joe/stoke_max_safe_named_jug_eqcontrol_20260420T183203Z/game`
- construction: source was the `JUG=failing, EQ=control` root; hostile JUG records `9581,9772,10001,10065,15577,15578,26936,32958,32959,32960` were restored to the clean control payload; the safe named JUG records listed above were left changed
- run tag: `stoke_max_safe_named_jug_eqcontrol_20260420T183500Z`
- result: `success=true`, `phase_reached=dashboard_enter_selected`, `blocking_error_modal_detected=false`, `crash_detected=false`, `classified_step_count=31`

This proves the safe named subset works together in one no-injection Stoke runtime, not just as isolated single-record probes. The full 2015 named squad is still not currently viable because the hostile set above independently trips the startup gate.

Updated closeout conclusion:
- metadata-only edits are safe on the working Stoke surface
- a specific safe subset of 10 named JUG payloads can also coexist and reach the dashboard
- the remaining 10 named JUG payloads are individually hostile or rename-hostile and trip the startup gate
- the full 2015 named Stoke squad is not yet viable without solving the hostile indexed-name/payload path

## Surface matrix and context dependency closeout (2026-04-20)
After the maximum-safe aggregate passed, a fast surface matrix was run against hostile representative records to separate name text, decoded metadata fields, exact payload bytes, and full record changes.

Hostile representative matrix:
- `26936` Ryan Shawcross: `names`, `fields`, `payload`, and `all` each reached `blocked_modal`
- `10001` Marko Arnautovic: `names`, `fields`, `payload`, and `all` each reached `blocked_modal`
- `32960` Geoff Cameron: `names`, `fields`, `payload`, and `all` each reached `blocked_modal`

Runtime evidence:
- `stoke_surface_fast_26936_names_20260420T185838Z`: `success=false`, `phase=blocked_modal`, `blocking_error_modal_detected=true`, `crash_detected=false`
- `stoke_surface_fast_26936_fields_20260420T185838Z`: `success=false`, `phase=blocked_modal`, `blocking_error_modal_detected=true`, `crash_detected=false`
- `stoke_surface_fast_26936_payload_20260420T185838Z`: `success=false`, `phase=blocked_modal`, `blocking_error_modal_detected=true`, `crash_detected=false`
- `stoke_surface_fast_26936_all_20260420T185838Z_r2`: `success=false`, `phase=blocked_modal`, `blocking_error_modal_detected=true`, `crash_detected=false`
- `stoke_surface_fast_10001_names_20260420T185838Z_r2`: `success=false`, `phase=blocked_modal`, `blocking_error_modal_detected=true`, `crash_detected=false`
- `stoke_surface_fast_10001_fields_20260420T185838Z_r2`: `success=false`, `phase=blocked_modal`, `blocking_error_modal_detected=true`, `crash_detected=false`
- `stoke_surface_fast_10001_payload_20260420T185838Z_r2`: `success=false`, `phase=blocked_modal`, `blocking_error_modal_detected=true`, `crash_detected=false`
- `stoke_surface_fast_10001_all_20260420T185838Z`: `success=false`, `phase=blocked_modal`, `blocking_error_modal_detected=true`, `crash_detected=false`
- `stoke_surface_fast_32960_names_20260420T185838Z_r2`: `success=false`, `phase=blocked_modal`, `blocking_error_modal_detected=true`, `crash_detected=false`
- `stoke_surface_fast_32960_fields_20260420T185838Z_r2`: `success=false`, `phase=blocked_modal`, `blocking_error_modal_detected=true`, `crash_detected=false`
- `stoke_surface_fast_32960_payload_20260420T185838Z_r2`: `success=false`, `phase=blocked_modal`, `blocking_error_modal_detected=true`, `crash_detected=false`
- `stoke_surface_fast_32960_all_20260420T185838Z_r2`: `success=false`, `phase=blocked_modal`, `blocking_error_modal_detected=true`, `crash_detected=false`

The matrix also exposed an important control caveat. Pure-control plus `10242` did not reproduce the earlier passing `10242` evidence:
- `stoke_surface_fast_10242_names_20260420T185838Z_safe`: `success=false`, `phase=blocked_modal`
- `stoke_surface_fast_10242_fields_20260420T185838Z_safe`: `success=false`, `phase=blocked_modal`
- `stoke_surface_fast_10242_payload_20260420T185838Z_safe`: `success=false`, `phase=blocked_modal`
- `stoke_surface_fast_10242_all_20260420T185838Z_safe`: `success=false`, `phase=blocked_modal`

Decoded payload comparison explains the discrepancy:
- `control` vs prior passing `10242` single root differed at JUG records `[3445, 9404, 9773, 10242, 33151]`
- `control` vs fast pure-control `10242` payload root differed only at `[10242]`
- prior passing `10242` root vs fast pure-control `10242` root differed at `[3445, 9404, 9773, 33151]`
- fast pure-control `10242` root vs max-safe aggregate differed at `[3445, 9404, 9773, 9778, 9781, 9782, 9785, 26935, 33150, 33151]`

This means the `10242` success is context-sensitive. It is safe inside a compatible Stoke cohort, including the final max-safe aggregate, but not safe as a single exact payload transplant onto the pure control root.

Structural interpretation from decoded payload inspection:
- safe records such as `26935` and `33150` share consistent suffix/face-component traits (`face=[5,1]`, `u10=6`)
- hostile `32959` is an outlier with no validated suffix anchor and no face bytes
- hostile `26936` and `15577` have only one face component
- hostile `10001` and `32960` have three face components
- team, squad, name case, and position fields do not explain the safe/hostile split

Final closeout position for this milestone:
- The runner and Ghidra-backed investigation have narrowed the failure from a generic game crash to a deterministic `MANAGPRE` startup validation modal.
- The best proven playable no-injection Stoke surface is the max-safe aggregate root with 10 named JUG payloads.
- The full 2015 Stoke named squad remains blocked by the 10 hostile JUG records listed above.
- Closing the full-squad gap requires solving the indexed suffix/face-component/cohort invariant for those hostile records, not more ad hoc runner validation of the same payloads.

Runner state after this phase:
- default worker lane had no active leases
- host free space was approximately 67 GiB after retention/recovery
- failed/blocked runs were preserved under `artifacts/stoke_remote_profile_probe/<run_tag>/`

## 26936 byte-surface closeout and writer invariant (2026-04-20 late)
A second pass focused on `26936` Ryan Shawcross after the fast surface matrix showed that the earlier parser surfaces were too broad: `names` and `fields` also changed leading decoded bytes. Five exact decoded-byte variants were built from pure control for `26936`:

- `header_only`: decoded range `[0,2)`
- `name_span_only`: decoded range `[5,31)`
- `suffix_meta_only`: decoded range `[39,49)` in the first build, with changed semantic bytes concentrated at `[42,46)` and `[47,49)`
- `attr_tail_only`: decoded range `[98,110)` in the first build, with changed semantic bytes concentrated at `[101,110)`
- `payload_minus_header`: `[5,31)`, `[39,49)`, `[98,110)` while preserving `[0,2)` from control

The first parallel wave reached partial UI states but produced no authoritative summaries because runner artifact directories disappeared while containers were still writing (`FileNotFoundError: /workspace/artifacts/window_debug`). Those runs were treated as invalid for verdict. The serial reruns are authoritative:

- `stoke_26936_byte_header_only_20260420T203505Z_serial`: `success=false`, `phase=blocked_modal`, first modal at `continue_visible`
- `stoke_26936_byte_name_span_only_20260420T203505Z_serial`: `success=false`, `phase=blocked_modal`, first modal at `continue_visible`
- `stoke_26936_byte_suffix_meta_only_20260420T203505Z_serial`: `success=false`, `phase=blocked_modal`, first modal at `continue_visible`
- `stoke_26936_byte_attr_tail_only_20260420T203505Z_serial`: `success=false`, `phase=blocked_modal`, first modal at `continue_visible`
- `stoke_26936_byte_payload_minus_header_20260420T203505Z_serial`: `success=false`, `phase=blocked_modal`, first modal at `continue_visible`

This rules out a single simple byte group as the whole repair. For `26936`, every tested mutation class independently trips the same startup gate.

Ghidra-backed interpretation:

- `FUN_006aacb0` is the startup gate that emits `Application cannot continue.` after lower-level initialization returns failure.
- `FUN_004b57b0` loads JUG first via `FUN_004b6a50`, then EQ (`dbdat\\eq98%03u.fdi`), builds team/player indexing, then proceeds into save directory setup.
- `FUN_004b6a50` loads `dbdat\\jug98%03u.fdi`, iterates indexed JUG directory entries, decodes each payload with `FUN_00678120`, and parses each candidate through `FUN_004afc90` / `FUN_004afd80`.
- `FUN_004afc90` reads a decoded payload header, allocates a player object, calls `FUN_004afd80`, and rejects records on parser/cursor/size failure.
- `FUN_00677e30` is the string parser used by the JUG player loader. It reads a 16-bit length and XORs string bytes with `0x61` into the destination buffer. This confirms indexed JUG player strings are not safe fixed-width printable runs even when printable substrings are visible in the decoded payload.

Additional repair probes:

- `stoke_26936_display_safe_name_20260420T212248Z_serial` changed only the apparent `26936` display substring from `Stuart FRASER` to the 13-byte-safe `R. Shawcross ` while preserving leading bytes, suffix metadata, and skills. Result: `success=false`, `phase=blocked_modal`, first modal at `continue_visible`.
- `stoke_relocate_ryan_to_9772_20260420T213311Z_serial` changed only the apparent display substring in known-safe-width record `9772` from `Larus SIGURDSSON` to `Ryan Shawcross`. Result: `success=false`, `phase=blocked_modal`, first modal at `continue_visible`.
- `stoke_transplant_ryan26936_to_9772_20260420T214305Z_serial` repacked `JUG98030.FDI`, preserving the indexed directory format while moving the full donor payload from `26936` into directory slot `9772`. Result: `success=false`, `phase=blocked_modal`, first modal at `continue_visible`.

Interpretation:

- Direct printable-run name editing is not a valid repair path for this indexed JUG layout. It creates game-invalid payloads even when the editor-side parser can still see the intended display string.
- Complete donor payload transplantation does not rescue the Ryan Shawcross donor payload, so the available `26936` donor payload is itself incompatible with the current boot cohort or violates a loader/team invariant outside simple directory repacking.
- Exact donor payloads remain proven-safe for only the max-safe subset. The full 2015 named squad should not be pursued by blind JUG string writes; it needs a correct indexed-JUG player payload constructor or a solved cohort invariant for the hostile donor records.

Current milestone status:

- Achieved: deterministic crash path isolated to `MANAGPRE` startup validation after JUG/EQ load; max-safe no-injection Stoke surface reaches dashboard; hostile `26936` byte classes and naive relocation/transplant strategies are ruled out by serial runner evidence.
- Not achieved: full 2015 Stoke squad display with all correct players. The remaining blocker is product/data-format work: implement or derive a game-valid indexed JUG name/payload writer for hostile records, then validate aggregate and capture the squad screen.
