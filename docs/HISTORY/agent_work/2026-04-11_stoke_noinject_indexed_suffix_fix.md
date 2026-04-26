# Stoke no-injection indexed suffix fix

## Summary
- Fixed indexed `dd6361` player-name rebuild corruption in the clean editor checkout.
- Verified the real-file Stoke repro no longer changes indexed suffix metadata.
- Verified the no-injection Stoke runtime path now boots past the old early `continue_visible` failure boundary and proceeds into manager-name entry under the repaired dataset.

## Product changes
- `upstream/pm99-skezmod-db-editor/app/models.py`
- `upstream/pm99-skezmod-db-editor/tests/test_player_name_rebuild.py`
- `upstream/pm99-runner/scripts/pm99_runner/apply_stoke_2015_metadata_patch.py`
- `upstream/pm99-runner/scripts/pm99_runner/apply_stoke_2015_strategy.py`
- `upstream/pm99-runner/scripts/pm99_runner/stoke_guided_squad_driver.py`

## Evidence
- Repro fixed:
  - `artifacts/research/indexed_name_rebuild_bug_after_raw_preserve_fix_20260411T000000Z/summary.json`
- Isolated repaired Stoke root:
  - `work/pm99/joe/stoke_2015_noinject_fix_indexed_nosync_20260411T024458Z/game`
- Manual no-injection proof artifacts:
  - `artifacts/stoke_remote_profile_probe/stoke_2015_noinject_fix_indexed_manual_20260411T025705Z/remote_agent_startup.log`
  - `artifacts/stoke_remote_profile_probe/stoke_2015_noinject_fix_indexed_manual_20260411T025705Z/screens/00_title.png`
  - `artifacts/stoke_remote_profile_probe/stoke_2015_noinject_fix_indexed_manual_20260411T025705Z/screens/03_continue_visible.png`
  - `artifacts/stoke_remote_profile_probe/stoke_2015_noinject_fix_indexed_manual_20260411T025705Z/screens/04_focus_name.png`
  - `artifacts/stoke_remote_profile_probe/stoke_2015_noinject_fix_indexed_manual_20260411T025705Z/screens/11_O2.png`

## Current runtime state
- The repaired Stoke dataset no longer dies before manager-name entry.
- The long static-squad run was still active at capture time, so later rival/preseason traversal was not yet claimed complete in this note.
- The important milestone closed here is the serializer/root-data corruption fix and proof that no-injection boot now clears the old early crash boundary.
