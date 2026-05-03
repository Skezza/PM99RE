# Variable Name Generic JUG-Only Failure - 2026-05-02

## Outcome

Generic JUG-only variable-length player-name rewrites are not runtime-safe.

The Stoke 2015 role-preserved proof remains valid, but it is a narrower contract:
it rewrites controlled roster/player records and preserves the runtime roster
surface. It must not be generalized to arbitrary `JUG98030.FDI` player rows.

## Evidence

- Working narrow proof:
  `/home/joe/pm99-research/work/pm99/in_game_variable_name_proof/20260502T_ui_varnames/working_stoke_variable_ui_proof/in_game_ui_proof.html`
- Generic failure summary:
  `/home/joe/pm99-research/work/pm99/in_game_variable_name_proof/20260502T_ui_varnames/generic_jug_only_failure_summary.json`
- Generic failure HTML:
  `/home/joe/pm99-research/work/pm99/in_game_variable_name_proof/20260502T_ui_varnames/generic_jug_only_failure_evidence.html`

Runner probes that hit the MANAGPRE `Application cannot continue` modal at
`021_squad_inspect.png`:

- `clean_gap3_1_73byte`
- `min80_1_83byte`
- `fixed49_1_80byte_cursor49`
- `fixed49_25`
- `fixed49_full_81`

This rules out the simple filters that looked plausible from static parsing:

- `dd6360_gap3` alone is insufficient.
- payload length `>= 80` is insufficient.
- payload length `80` plus original cursor/name-end `49` is insufficient.

## Product Decision

The editor now fails closed for generic JUG-only variable-name writes. The
planner still diagnoses short payloads, `gap4`, and `dd6361` contracts, but
otherwise refuses generic `dd6360_gap3` writes before attempting any name-length
growth/shrink decision. Static parser shape is no longer treated as a sufficient
write contract until the game-side validation contract is mapped.

Updated code:

- `/home/joe/pm99-research/upstream/pm99-skezmod-db-editor/app/editor_actions.py`
- `/home/joe/pm99-research/upstream/pm99-skezmod-db-editor/tests/test_player_variable_names.py`

Validation:

- `./scripts/dev_editor.sh pytest tests/test_player_variable_names.py -q`
- `./scripts/dev_editor.sh pytest -m deterministic -q`

## Next Research Path

The next milestone is not another static JUG filter and not another raw
string-only writer. The missing contract is the game-side runtime cursor
contract: after MANAGPRE parses the two variable-length linked-player name
strings, it reads role, nationality, position, DOB, physical data, and skills
from cursor-relative offsets. A DB-only variable-name writer must therefore
rebuild that semantic block at the moved cursor, then prove the candidate with
the runner.

Follow-up investigation:

- `/home/joe/pm99-research/docs/HISTORY/Investigations/VARIABLE_NAME_SEMANTIC_CURSOR_CONTRACT_2026-05-02.md`
