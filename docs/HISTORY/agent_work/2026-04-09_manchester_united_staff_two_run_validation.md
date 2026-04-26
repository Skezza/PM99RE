# 2026-04-09 Manchester United Staff Two-Run Validation

## Why this was run

Previous package-level probes showed deterministic decoded staff-name rows in
`ENT98030.FDI`, including names like `Trevor Francis` for Stoke. We needed to
validate whether start-of-season **in-game** club personnel is deterministic for
a fixed club when starting new games repeatedly.

This note documents the corrected experiment for:

- club: `Manchester Utd.` (Premier League)
- two fresh new-manager games
- direct comparison of first staff screen names

## Commands run

From `upstream/pm99-runner/`:

```bash
./scripts/pm99_runner/run_stoke_staff_extract.sh \
  --run-tag manutd_prem_staff_clean_run1 \
  --skip-setup --skip-build --skip-prepare --reset-wine-prefix \
  --division-x 80 --division-y 302 \
  --team-x 201 --team-y 353

./scripts/pm99_runner/run_stoke_staff_extract.sh \
  --run-tag manutd_prem_staff_clean_run2 \
  --skip-setup --skip-build --skip-prepare --reset-wine-prefix \
  --division-x 80 --division-y 302 \
  --team-x 201 --team-y 353

python3 scripts/pm99_runner/compare_staff_extract_runs.py \
  --summary-a docs/artifacts/pm99_runner/manutd_prem_staff_clean_run1/summary.json \
  --summary-b docs/artifacts/pm99_runner/manutd_prem_staff_clean_run2/summary.json \
  --output docs/artifacts/pm99_runner/manutd_prem_staff_clean_run1_vs_run2_compare.json
```

## Artifacts

- Run 1 summary:
  `upstream/pm99-runner/docs/artifacts/pm99_runner/manutd_prem_staff_clean_run1/summary.json`
- Run 2 summary:
  `upstream/pm99-runner/docs/artifacts/pm99_runner/manutd_prem_staff_clean_run2/summary.json`
- Team selection proof (run 1):
  `upstream/pm99-runner/docs/artifacts/pm99_runner/manutd_prem_staff_clean_run1/screens/16_pick_stoke.png`
- Team selection proof (run 2):
  `upstream/pm99-runner/docs/artifacts/pm99_runner/manutd_prem_staff_clean_run2/screens/16_pick_stoke.png`
- Staff screen (run 1):
  `upstream/pm99-runner/docs/artifacts/pm99_runner/manutd_prem_staff_clean_run1/screens/28_dashboard_enter_staff_1.png`
- Staff screen (run 2):
  `upstream/pm99-runner/docs/artifacts/pm99_runner/manutd_prem_staff_clean_run2/screens/28_dashboard_enter_staff_1.png`
- Side-by-side visual proof:
  `upstream/pm99-runner/docs/artifacts/pm99_runner/manutd_prem_staff_run1_vs_run2_staff.png`
- Machine compare output:
  `upstream/pm99-runner/docs/artifacts/pm99_runner/manutd_prem_staff_clean_run1_vs_run2_compare.json`

## Visual staff names captured

Run 1:

- C. Prudhoe
- G. Newman
- A. Peake
- D. Owen
- S. Kirkham
- T. Powell
- K. Davis
- K. Ward
- W. Goodliffe
- G. Bass
- P. Roget
- P. Victor
- B. Neville

Run 2:

- M. Ireland
- G. Farrell
- D. Barber
- A. Wrack
- P. Dunford
- N. Roland
- S. Youngs
- A. Donovan
- J. Stallard
- M. Seabury
- J. Clark
- S. Essex
- M. Allen

## Result

Not deterministic for this lane. The same club (`Manchester Utd.`) produced a
different staff list across two fresh game starts.

`compare_staff_extract_runs.py` reports:

- `entry_count_a=13`
- `entry_count_b=13`
- `exact_match=false`
- `mismatch_count=7` (OCR-slot compare; visual read confirms broad name changes)

## Upstream editor implications

For editor implementation planning, this is the key correction:

- Package-level deterministic linkage (`team slot -> decoded ENT row`) is **not**
  sufficient evidence that in-game start-of-season staff UI names are fixed per
  club.
- Do not model "new game club staff" as a deterministic static table without
  first solving the runtime generation/routing mechanism.
- Safe near-term product framing:
  - expose package coach records as package data, and
  - keep runtime staff behavior explicitly marked as unresolved/randomized.

