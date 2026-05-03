# Variable Name Semantic Cursor Contract - 2026-05-02

## Current Finding

The failed generic variable-name probes were not just "variable length is bad".
They used a JUG-only physical name rewrite that moved the visible name cursor
without rebuilding every runtime field MANAGPRE reads after that cursor.

Ghidra confirms the linked JUG player loader follows the parsed name cursor and
then consumes role, nationality, position, DOB, physical data, and skills from
cursor-relative offsets in `MANAGPRE.EXE`:

- `0x004b57b0` (`pm99_load_database_sets`) loads indexed JUG before EQ.
- `0x004b6a50` (`pm99_load_jug_indexed`) iterates `dbdat\\jug98%03u.fdi`.
- `0x004afc90` (`pm99_parse_jug_player_candidate`) rejects records when the
  parsed cursor does not stay inside the indexed payload bounds.
- `0x004afd80` (`pm99_parse_jug_player_payload`) parses the two runtime name
  strings, then reads the role/metadata/skills block at the resulting cursor.
- `0x00677e30` (`pm99_parse_xor_len_string`) is the runtime string parser.

This matches the working Stoke proof: the passing patch does not merely edit
the string. It also moves and rewrites semantic fields at the new cursor.

## New Probe Candidates

Two one-record realistic probes were built from:

`/home/joe/pm99-research/work/pm99/codex_2025_roster/pm99_2025_roster_top80_world_ready_20260424T230207Z/game`

Both change only indexed JUG record `33`:

- original: `Guillermo AMOR Martinez` / `Guillermo AMOR Martínez`
- target: `Guillermo Amor`

Candidate A, name-only physical rewrite:

- game root: `/home/joe/pm99-research/.local/20260502T_record33_realname`
- summary: `/home/joe/pm99-research/.local/20260502T_record33_realname/artifacts/record33_realname_patch_summary.json`
- static result: reparses as `Guillermo AMOR`, but the name-end anchor is not
  exact after rewrite.

Candidate B, semantic cursor rewrite:

- game root: `/home/joe/pm99-research/.local/20260502T_record33_realname_semantic`
- summary: `/home/joe/pm99-research/.local/20260502T_record33_realname_semantic/artifacts/record33_semantic_variable_summary.json`
- static result: reparses as `Guillermo AMOR`, keeps payload length `73`, and
  has an exact moved name-end anchor at `33`.

Queued runner tags:

- `varname_record33_realname_nosem_20260502T_iter`
- `varname_record33_realname_semantic_20260502T_iter`

## Product Implication

The editor should continue to fail closed for generic JUG-only variable-name
writes. The next viable DB-only path is a semantic linked-player payload
rebuilder:

1. Parse the runtime name prefix and compute the new cursor.
2. Move the role block to the new cursor.
3. Re-emit nationality, position, DOB, height, weight, and skills at the new
   cursor-relative offsets.
4. Preserve payload length unless a separately proven indexed-entry resize
   contract exists.
5. Prove the rebuilt payload with the PM99 runner before enabling product writes.
