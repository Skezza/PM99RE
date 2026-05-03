# Variable Length Player Name Contracts - 2026-05-01

## Scope

Research pass for PM99 player-name storage contracts across the indexed player
database, with runner evidence for all 80 playable English clubs and the
transfer/player-market surface.

Primary artifact directory:

`/home/joe/pm99-research/.local/variable_name_contract_research_20260501T201643Z`

## Closure Evidence

- Static contract report:
  `/home/joe/pm99-research/.local/variable_name_contract_research_20260501T201643Z/contracts/variable_player_name_contracts.html`
- Static contract JSON:
  `/home/joe/pm99-research/.local/variable_name_contract_research_20260501T201643Z/contracts/variable_player_name_contracts.json`
- Consolidated runner evidence HTML:
  `/home/joe/pm99-research/.local/variable_name_contract_research_20260501T201643Z/evidence/variable_name_contract_research_evidence.html`
- Consolidated runner evidence JSON:
  `/home/joe/pm99-research/.local/variable_name_contract_research_20260501T201643Z/evidence/variable_name_contract_research_evidence.json`

## Static Coverage

- Total indexed entries: 11,479
- Parsed player payloads: 11,457
- Opaque/preserve-only payloads: 22
- Playable-80 linked player records: 1,865
- Foreign/non-playable linked player records: 9,597
- Unlinked indexed player records: 0
- Playable world-club selector match: 80/80

## Contract Families

| Family | Records | Playable-80 records | Foreign/non-playable records | Editor implication |
| --- | ---: | ---: | ---: | --- |
| `dd6360_compact_linked_gap3_physical_cursor` | 6,419 | 1 | 6,419 | Compact linked layout with surname/full-name length segments and a 3-byte pre-marker gap. Requires a contract-aware writer and runtime write certification before broad edits. |
| `dd6360_compact_linked_gap4_physical_cursor` | 2,912 | 1 | 2,912 | Sibling compact linked layout with 4-byte pre-marker gap. Same writer class as gap3, but must remain a separate certified contract. |
| `dd6361_indexed_suffix_biography` | 2,126 | 1,863 | 266 | Dominant playable-club layout. Visible name starts at byte 5 and ends before a suffix/biography anchor that must be preserved. |
| `opaque_or_non_player_payload` | 22 | 0 | 22 | Preserve-only until explicitly reverse engineered. |

## Runtime Evidence

The runner proof is consolidated from these matrix roots:

- Full 80-club fast-valid matrix:
  `/home/joe/pm99-research/.local/variable_name_contract_research_20260501T201643Z/runner_80club_fastvalid_matrix_varname_contract_80clubs_fastvalid_20260501T223940Z`
- Targeted fast-valid rerun after route activation fixes:
  `/home/joe/pm99-research/.local/variable_name_contract_research_20260501T201643Z/runner_80club_fastvalid_rerun2_matrix_varname_contract_80clubs_fastvalid_rerun2_20260501T234722Z`
- Coventry classification-enabled recovery after fixing squad return coordinates:
  `/home/joe/pm99-research/.local/variable_name_contract_research_20260501T201643Z/runner_80club_classvalid_rerun_matrix_varname_contract_coventry_classvalid2_20260502T000659Z`

The consolidated report produced:

- Playable clubs targeted: 80
- Playable clubs matched: 80
- Squad screenshot evidence: 80
- Transfer/player-market screenshot evidence: 80
- Failed clubs after recovery: 0
- Missing clubs after recovery: 0

The transfer route is the available runner proof surface for foreign/non-club
player visibility. The DB-side foreign/non-playable coverage is static and
complete; deeper runtime proof of every individual foreign indexed record would
need a separate selector/search automation pass.

Runtime notes:

- Coventry needed OCR/classification enabled because it stops on `START OF
  SEASON` during setup; skip-classification routing incorrectly treated that
  state as dashboard-ready.
- Squad route activation must be a single click. Double-clicking can over-shoot
  from squad selection into a player profile.
- Squad return must use the bottom dashboard-style `RETURN` button coordinate
  (`y=436`). The profile-depth return coordinate (`y=459`) opens match options
  from squad and breaks the following transfer route.

## Editor Build Implications

- Do not implement a single generic string overwrite. The editor needs family
  dispatch by `head_hex` and resolved anchors.
- For `dd6361`, preserve the suffix/biography tail exactly and only replace the
  visible prefix between byte 5 and the resolved suffix anchor.
- For `dd6360`, preserve the compact segment grammar, including length bytes,
  surname/full-name duplication, role bytes, pre-marker gap, and tail cursor.
- For all contracts, the indexed FDI directory must remain coherent when payload
  lengths change. If the replacement name grows beyond the current container,
  the writer must rebuild/update indexed payload offsets and lengths rather
  than relying on in-place padding.
- The 22 opaque payloads should fail closed in an editor until a separate
  contract is proven.

## Commands Used

```bash
python3 scripts/research_variable_player_name_contracts.py --output-dir "$OUT/contracts"
python3 scripts/build_variable_name_contract_research_evidence.py
bash -n scripts/run_2025_roster_visual_sample.sh
python3 -m py_compile scripts/research_variable_player_name_contracts.py scripts/build_variable_name_contract_research_evidence.py upstream/pm99-runner/scripts/pm99_runner/stoke_season_driver.py upstream/pm99-runner/scripts/pm99_runner/season_navigation.py
python3 scripts/check_repo_boundary.py
```

Runner proof used `scripts/run_2025_roster_visual_sample.sh` against the
runner-ready isolated game root recorded at:

`/home/joe/pm99-research/.local/variable_name_contract_research_20260501T201643Z/runnerready_isolated_game_root.txt`
