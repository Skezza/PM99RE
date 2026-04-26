# Indexed Name Rebuild Suffix Corruption

Date: 2026-04-11

## Summary

The current upstream editor serializer is corrupting indexed Stoke player records when it performs a name-only `player-batch-edit`.

The corruption is not in the semantic player fields that the editor currently surfaces. It is in the indexed suffix metadata block that sits after the visible name and before the attribute tail. After a rename, that suffix is often flattened to decoded space bytes (`65`) and the parsed face component list becomes empty.

This is a concrete candidate root cause for the no-injection Stoke runtime failure.

## Clean Repro

Standalone PM99RE repro script:

- [scripts/repro_indexed_name_rebuild_bug.py](/home/joe/pm99-research/scripts/repro_indexed_name_rebuild_bug.py)

Validated artifact bundle:

- [summary.json](/home/joe/pm99-research/artifacts/research/indexed_name_rebuild_bug_smoke2_20260411T014100Z/summary.json)
- [player_batch_edit_result.json](/home/joe/pm99-research/artifacts/research/indexed_name_rebuild_bug_smoke2_20260411T014100Z/player_batch_edit_result.json)
- [rename_subset.csv](/home/joe/pm99-research/artifacts/research/indexed_name_rebuild_bug_smoke2_20260411T014100Z/rename_subset.csv)

Repro method:

1. Copy pristine [JUG98030.FDI](/home/joe/pm99-research/work/fixtures/premier-manager-ninety-nine-pristine/DBDAT/JUG98030.FDI).
2. Apply name-only batch edits for Stoke slots `11..15`.
3. Parse the indexed records before and after.
4. Compare indexed suffix metadata and semantic player fields.

Observed result from the clean repro:

- `suffix_changed_count = 5`
- `semantic_changed_count = 0`

That means the serializer changed the indexed suffix block for every tested record while leaving position, nationality, DOB, height, weight, skills, and extended values unchanged.

## Concrete Before/After

From the clean repro bundle:

- Slot `11`
  - before: `u0=12, u1=1, face=[8,11,13], u9=2, u10=3`
  - after: `u0=65, u1=65, face=[], u9=65, u10=65`
- Slot `14`
  - before: `u0=2, u1=0, face=[5,1], u9=1, u10=6`
  - after: `u0=65, u1=65, face=[], u9=65, u10=65`

This was produced by a pure rename operation. No metadata or face edits were requested.

## Existing Stoke Source Comparison

The already-built Stoke source root shows the same family of corruption across slots `2..20`: face components are emptied and the indexed suffix fields are frequently rewritten to `65`.

Representative source root:

- [stoke_bisect_slots2_20_fixed_20260410T211407Z](/home/joe/pm99-research/work/pm99/joe/stoke_bisect_slots2_20_fixed_20260410T211407Z)

The clean repro matches that corruption pattern directly for slots `12`, `13`, and `15`, and is even stronger for `11` and `14` because it also drives `u9/u10` to `65`.

Inference:

- The live Stoke corruption is very likely coming from the name rebuild / serialization path itself.
- Later edit passes may preserve or overwrite some suffix bytes inconsistently, which explains why the source root does not match the clean repro byte-for-byte on every slot.

## Game-Side Evidence

GhidraMCP decompilation shows the game loads indexed player records through `FUN_004afd80` and later consumes fields from the in-memory player struct in automatic tactics/squad generation:

- `FUN_004afd80`
- `FUN_004a18d0`
- `FUN_004a4d30`

Relevant reads in the later game-generation path:

- `+0x23`
- `+0x26`
- `+0xcf..0xd2`
- `+0x114`
- `+0x118..0x11c`

Those consumers do not perform record-length checks in the decompiled paths. They assume the loaded player struct is coherent.

## Important Negative Finding

Slots `14` and `15` are short indexed records in the pristine database too:

- slot `14` payload length: `112`
- slot `15` payload length: `117`

So the issue is not “Stoke created illegal short records”. The short layout is native. The problem is the suffix metadata being clobbered during serialization.

## Likely Upstream Fault Site

Most likely serializer fault site:

- [models.py](/home/joe/pm99-research/upstream/pm99-skezmod-db-editor/app/models.py)

Most suspicious function:

- [_rebuild_name_region()](/home/joe/pm99-research/upstream/pm99-skezmod-db-editor/app/models.py#L2636)

Why:

- It has a fallback path that rebuilds a plain printable name run.
- That fallback preserves a coarse “metadata block” based on heuristic boundaries.
- For indexed records, that heuristic can consume or overwrite the indexed suffix metadata next to the visible name.
- The resulting decoded bytes come back as spaces (`65`) and empty face lists, which is exactly what the repro shows.

## Fix Direction

Do not patch blindly. The likely correct direction is:

1. Detect indexed player records before name rebuild.
2. Preserve the indexed suffix metadata block exactly.
3. Rebuild only the visible name portion.
4. Add regression tests that rename indexed records and assert these fields are unchanged:
   - `indexed_unknown_0`
   - `indexed_unknown_1`
   - `indexed_face_components`
   - `indexed_unknown_9`
   - `indexed_unknown_10`
5. Re-run the no-injection Stoke runtime probe after the serializer fix lands.

## Current Constraint

The likely fix file is currently dirty in the upstream editor workspace and should not be edited until the other worker is clear:

- [models.py](/home/joe/pm99-research/upstream/pm99-skezmod-db-editor/app/models.py)

This note exists so the next worker can patch that file surgically instead of rediscovering the failure.
