# Graham Kavanagh Smiley Runner Validation (2026-04-09)

## Goal
- Validate in-game that a one-record `MINIFOTO.PKF` replacement for Graham Kavanagh
  (player id `15578`) renders with a yellow smiley overlay.

## Patch Source
- Patched archive:
  - `work/minifoto_smiley_validation/20260409T211409Z/MINIFOTO_smiley.patched.PKF`
- Patch manifest:
  - `work/minifoto_smiley_validation/20260409T211409Z/smiley_patch_manifest.json`

## Runner Lane
- Deterministic manual lane script:
  - `scripts/run_kavanagh_smiley_manual_probe.sh`
- Target row used for Graham in this lane:
  - `--row-y 280` (slot 10 in the captured Stoke profile order)

## Baseline vs Patched Runs
- Baseline run tag:
  - `kavanagh_row10_baseline_20260409T231137Z`
- Patched run tag:
  - `kavanagh_row10_smiley_20260409T231935Z`

Local artifacts:
- `upstream/pm99-runner/docs/artifacts/pm99_runner/kavanagh_row10_baseline_20260409T231137Z`
- `upstream/pm99-runner/docs/artifacts/pm99_runner/kavanagh_row10_smiley_20260409T231935Z`

Key screenshots (both show `Graham KAVANAGH`, player profile screen):
- Baseline:
  - `.../kavanagh_row10_baseline_20260409T231137Z/screens/35_profile_hold.png`
- Patched:
  - `.../kavanagh_row10_smiley_20260409T231935Z/screens/35_profile_hold.png`

## Comparison Bundle
- Generated bundle:
  - `work/minifoto_smiley_validation/runner_row10_compare_20260409T232732Z`
- Report:
  - `work/minifoto_smiley_validation/runner_row10_compare_20260409T232732Z/comparison_report.json`
- Face crops:
  - `baseline_face_crop.png` (original Graham portrait)
  - `patched_face_crop.png` (yellow smiley visible in top-right mugshot)

## Result
- Validation succeeded:
  - Baseline run and patched run both reached `player_profile_screen` for Graham.
  - Patched run shows the injected yellow smiley on Graham’s portrait.
