# Stoke 2015 Face Capture via Late DBDAT Injection (2026-04-10)

## Goal
Capture Stoke player profile pages with Stoke 2015 name/photo overrides without triggering startup `MANAGPRE: Application cannot continue` modal.

## Problem
Direct pre-launch override of 2015 `JUG/EQ/MINIFOTO` causes deterministic startup modal before squad/profile navigation.

## Implemented runner changes
- `upstream/pm99-runner/scripts/pm99_runner/stoke_vanilla_profile_capture_driver.py`
  - Added optional late override args:
    - `--late-dbdat-override-dir`
    - `--late-dbdat-files`
  - Added live copy stage: once dashboard is reached, copy selected files into `game/DBDAT`.
  - Added summary fields:
    - `late_dbdat_override_requested`
    - `late_dbdat_override_applied`
    - `late_dbdat_override`
- `scripts/run_stoke_profile_capture_with_dbdat_overrides.sh`
  - Added options:
    - `--late-dbdat-dir`
    - `--late-dbdat-files`
  - Added remote upload/mount path for late override files and passed new driver args.

## Inputs used
- Stable startup base DBDAT:
  - `/home/joe/pm99-research/work/stoke_2015_faces_milestone_20260410T120934Z/game/DBDAT`
- Late injected Stoke 2015 face set:
  - `/home/joe/pm99-research/work/stoke_2015_face_prepare_20260410T121616Z/game/DBDAT`

## Validation run
- Run tag: `stoke_2015_faces_lateinject_v2_20260410T131057Z`
- Local artifacts:
  - `/home/joe/pm99-research/upstream/pm99-runner/docs/artifacts/pm99_runner/stoke_2015_faces_lateinject_v2_20260410T131057Z`
- Summary highlights:
  - `late_dbdat_override_applied = true`
  - `profile_capture_count = 20`
  - `profile_capture_ok = false` (slot 20 open step landed on squad screen)
  - For patched-face slots (16 total), profile screenshots were captured and are usable.

## Gallery output
- HTML:
  - `/home/joe/pm99-research/work/stoke_2015_face_prepare_20260410T121616Z/stoke_2015_face_gallery_lateinject_v2.html`
- Builder command:
  - `python3 scripts/build_stoke_2015_face_gallery_html.py --prepare-manifest ... --runner-artifacts-dir ... --output-html ...`
- Cards rendered: `16` (skips 4 no-bitmap slots by design)
