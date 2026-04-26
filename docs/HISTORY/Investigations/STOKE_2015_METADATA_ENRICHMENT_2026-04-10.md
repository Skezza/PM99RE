# Stoke 2015 Metadata Enrichment (2026-04-10)

## Scope

Goal: apply and verify Stoke 2015 player metadata updates for:

- birth date (calibrated for in-game year handling)
- nationality
- height
- weight

for all 20 Stoke first-team slots in the active local game DB.

## Reproducible Apply Path

Script:

- `scripts/stoke_2015_apply_metadata.py`

Run:

```bash
python3 scripts/stoke_2015_apply_metadata.py \
  --game-dir .local/premier-manager-ninety-nine \
  --output-dir artifacts/stoke_2015_metadata_20260410/apply_metadata_live_v2
```

## Data Sources and Contracts

- Wikidata API (`wbgetentities`) for `P569` (DOB), `P2048` (height), `P2067` (weight).
- Archived Premier League profile for Steve Sidwell weight fallback.
- Nationality code mapping extracted parser-backed from XOR-decoded `TEXTOS.PKF`
  country table (not a handwritten map).

Notes:

- Height parsing is unit-aware (`cm` vs `m`) and validated to a sane player range.
- Birth year is calibrated by `real_birth_year - 17` (script default).

## Verified Outputs

Apply evidence bundle:

- `artifacts/stoke_2015_metadata_20260410/apply_metadata_live_v2/stoke_2015_metadata_manifest.json`
- `artifacts/stoke_2015_metadata_20260410/apply_metadata_live_v2/stoke_2015_metadata_batch.csv`
- `artifacts/stoke_2015_metadata_20260410/apply_metadata_live_v2/stoke_2015_metadata_apply_result.json`
- `artifacts/stoke_2015_metadata_20260410/apply_metadata_live_v2/stoke_2015_metadata_verification.json`

Key result facts:

- `player-batch-edit`: `matched_row_count=20`, `changes_count=20`, `applied_to_disk=true`, `warnings_count=0`
- parser post-check: `verification_ok=true` with `20/20` row matches
- `validate-database`: `all_valid=true` for players/teams/coaches

## Runner Verification Status

Attempted automated in-game validation using:

- `upstream/pm99-runner/scripts/pm99_runner/stoke_vanilla_profile_capture_driver.py`

under local isolated `Xvfb` + `fluxbox` execution.

Result:

- The run consistently stalls at the preseason configuration continuation point.
- Manual intervention at that stage surfaces an in-game modal:
  `MANAGPRE - Application cannot continue.`

Evidence:

- `artifacts/stoke_2015_metadata_20260410/runner_verify_xvfb_v4/manual_error_application_cannot_continue.png`

## Runner Changes During Investigation

To make local runner probing more robust in this environment, retry logic was
extended in:

- `upstream/pm99-runner/scripts/pm99_runner/stoke_vanilla_profile_capture_driver.py`

The preseason retry cycle now includes additional click/key fallbacks to avoid
hotspot-only deadlocks. Despite that, the runtime modal above remains reproducible.

## Upstream Next Step

Before shipping these metadata writes upstream, isolate the runtime-unsafe field
combination with a deterministic bisect over the same 20 Stoke players:

1. apply only nationality, test continue
2. apply only DOB, test continue
3. apply only height/weight, test continue
4. narrow to per-player subset if needed

The enrichment script and artifacts above are already structured for this bisect
workflow.
