# 2026-04-08 Plaintext Staff Extraction Proof

## Scope Clarification (2026-04-09)

This note proves deterministic **package-level** decoded staff rows, not
deterministic in-game staff UI output after starting a new game.

For runtime UI validation evidence (Manchester Utd. two fresh starts producing
different staff names), see:

- [`2026-04-09_manchester_united_staff_two_run_validation.md`](2026-04-09_manchester_united_staff_two_run_validation.md)

## Scope

Produce deterministic plaintext output artifacts for:

- Stoke City start-of-season staff
- all 20 Premier League clubs from the manager-listing reference lane

Write scope stayed inside `scripts/` and `docs/`.

## Commands Run

```bash
python3 scripts/check_repo_boundary.py
python3 -m py_compile \
  scripts/probe_start_season_staff.py \
  scripts/export_start_of_season_staff_plaintext.py
python3 scripts/export_start_of_season_staff_plaintext.py
python3 scripts/check_repo_boundary.py
```

## Output Artifacts

- [`docs/artifacts/staff_extraction/start_of_season_staff_proof_20260408.json`](/home/joe/pm99-research/docs/artifacts/staff_extraction/start_of_season_staff_proof_20260408.json)
- [`docs/artifacts/staff_extraction/premier_league_start_of_season_staff_20260408.csv`](/home/joe/pm99-research/docs/artifacts/staff_extraction/premier_league_start_of_season_staff_20260408.csv)
- [`docs/artifacts/staff_extraction/stoke_city_start_of_season_staff_20260408.txt`](/home/joe/pm99-research/docs/artifacts/staff_extraction/stoke_city_start_of_season_staff_20260408.txt)
- [`docs/artifacts/staff_extraction/premier_league_start_of_season_staff_20260408.txt`](/home/joe/pm99-research/docs/artifacts/staff_extraction/premier_league_start_of_season_staff_20260408.txt)

## Validation Counts

From the export summary:

- `decoded_link_count=534`
- `team_count=534`
- `focus_club_count=1`
- `focus_staff_entry_count=1`
- `premier_league_club_count=20`
- `premier_league_staff_entry_count=20`
- `premier_league_mapped_count=19`
- `premier_league_league_mismatch_count=1`
- `premier_league_missing_map_count=0`
- `premier_league_placeholder_name_count=0`

## Key Proof Snippets

Stoke City plaintext row:

```text
full_club_name=Stoke City | team_name=Stoke C. | league=First Division | slot_index=80 | coach_record_id=700 | coach_offset=61497 | staff_name=Trevor Francis | name_source=decoded_payload
```

Premier League plaintext header:

```text
club_count=20
staff_entry_count=20
mapped_count=19
league_mismatch_count=1
missing_map_count=0
```

Representative Premier League rows:

```text
canonical_team=Charlton Athletic | manager_listing=Curbishley | mapping_status=league_mismatch | mapped_team=Charlton Ath. | local_league=First Division | slot_index=72 | coach_record_id=687 | staff_name=Ruud Gullit | name_source=decoded_payload
canonical_team=Manchester United | manager_listing=Ferguson | mapping_status=mapped | mapped_team=Manchester Utd. | local_league=Premier League | slot_index=40 | coach_record_id=604 | staff_name=Fatih Terim | name_source=decoded_payload
canonical_team=Blackburn Rovers | manager_listing=Kidd | mapping_status=mapped | mapped_team=Blackburn R. | local_league=Premier League | slot_index=38 | coach_record_id=594 | staff_name=Smuda | name_source=decoded_payload
```

## Notes

- The deterministic linkage proof remains anchored to the existing reproducibility hash:
  `6359b05965008c91c1785be585eb54d27769dc5be644010d6dab4101c6d0f94e`.
- The Premier League export keeps Charlton Athletic in the 20-club output instead of
  dropping the row. It is flagged as `league_mismatch` because the local team record is
  currently tagged `First Division`.
