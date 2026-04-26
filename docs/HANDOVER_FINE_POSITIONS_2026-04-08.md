# Handover: Fine-Grained Player Positions (2026-04-08)

Purpose: give an upstream worker a direct, evidence-backed implementation brief
for surfacing PM99 fine-grained player positions (for example, `Inside Right`,
`Centre Forward`, `Striker`) from `JUG98030.FDI`.

## Status Snapshot

- Investigation lane status: `PASS`
- Corpus coverage: `11,479 / 11,479` players assigned (`100%`)
- Unresolved/unknown rows: `0`
- Primary evidence bundle:
  - `work/parallel_recheck/fine_positions/fine_positions_summary.json`
  - `work/parallel_recheck/fine_positions/fine_position_codebook.json`
  - `work/parallel_recheck/fine_positions/player_fine_positions_manifest.json`

## Position Catalog (Code -> Label -> Count)

From `work/parallel_recheck/fine_positions/fine_position_codebook.json`:

| Code | Label | Count |
| --- | --- | ---: |
| 0 | Keeper | 1203 |
| 1 | Right Back | 776 |
| 2 | Left Back | 673 |
| 3 | Sweeper | 460 |
| 4 | Inside Centre Left | 806 |
| 5 | Inside Centre Right | 872 |
| 6 | Mid. Right | 590 |
| 7 | Inside Right | 590 |
| 8 | Centre Forward | 1433 |
| 9 | Central Mid. | 740 |
| 10 | Mid. Left | 491 |
| 11 | Right Winger | 499 |
| 12 | Striker | 558 |
| 13 | Left Winger | 420 |
| 14 | Defensive Midfielder | 435 |
| 15 | Right Forward | 258 |
| 16 | Left Forward | 257 |
| 17 | Inside Left | 414 |
| 98 | Unassigned | 4 |

Requested examples confirmed present:
- `Inside Centre Right`: 872
- `Inside Right`: 590
- `Centre Forward`: 1433
- `Striker`: 558

## Decode Contract (Parser-Side)

Two-source contract (as proven by artifacts):

1. Marker-backed rows (`source_counts.name_end_minus2_slot1 = 10910`)
- Find `name_end` with `PlayerRecord._find_name_end_in_data(raw)`.
- Read 6 encoded bytes from `name_end-1 .. name_end+4`.
- Decode each slot with: `slot_code = ((byte ^ 0x61) - 1)` when xor value > 0, else `98`.
- Primary surfaced fine position = decoded slot 0.

2. Indexed markerless fallback rows (`source_counts.indexed_face_component0 = 569`)
- Resolve indexed anchor with `PlayerRecord._find_indexed_suffix_anchor(raw, parsed_name)`.
- Decode face components from `anchor+2 .. anchor+7` while `(byte ^ 0x61)` is in `[1,18]`.
- Component code = `(byte ^ 0x61) - 1`.
- Primary surfaced fine position = first decoded component.

Notes:
- Existing lane naming uses `name_end_minus2_slot1`; keep it for compatibility
  with current evidence files, but apply the exact byte window above.
- `98` is an explicit unassigned sentinel and is observed in real rows.

## Binary Evidence Anchors (Ghidra MCP)

From `work/parallel_recheck/fine_positions/fine_positions_summary.json`:

- `MANAGPRE.EXE` `FUN_004afd80 @ 0x004afd80`
  - Consumes six fine-position bytes, decrements non-zero values by 1, stores
    them in player-struct slot fields.
- `DBASEPRE.EXE` `FUN_004012e0 @ 0x004012e0` (table `0x004a7060`)
  - Maps codes `0..17` to labels (`KEEPER`, `RIGHT BACK`, ...).
- `DBASEPRE.EXE` `FUN_004012f0 @ 0x004012f0`
  - Uses six fine-position slots in filter/match logic.

## Reproducible Method

Use the PM99RE script added for this handover:

```bash
python3 scripts/probe_player_fine_positions.py --json
```

Default output directory:
- `work/fine_positions_decode_repro/player_fine_positions_manifest.json`
- `work/fine_positions_decode_repro/fine_position_codebook.json`
- `work/fine_positions_decode_repro/fine_positions_summary.json`

Inputs:
- auto-detected `JUG98030.FDI` (prefers `FDI-PKF/DBDAT/JUG98030.FDI`)

Important:
- If your local `JUG98030.FDI` has changed after the 2026-04-08 evidence run,
  counts can differ while the decode contract remains unchanged.

## Upstream Integration Checklist

1. Data model
- Add parser-backed fine-position fields to player DTOs/models:
  - primary fine-position code + label
  - optional six-slot array (read-only initially)
  - source provenance (`marker` vs `indexed fallback`)

2. API surface
- Return fine-position code/label alongside existing coarse `position_primary`.
- Keep coarse position unchanged for backward compatibility.

3. CLI/UI
- Surface fine position in inspect and roster views.
- Keep write-path gated unless/until a full write contract is accepted.

4. Tests (must-pass)
- Deterministic codebook map test (`0..17`, `98`).
- Corpus extraction test proving no unresolved rows on baseline corpus.
- Regression test for requested labels (`Inside Right`, `Centre Forward`, `Striker`, `Inside Centre Right`).

5. Promotion gate
- Do not promote to writable UI flow until byte-preservation + reopen validation
  tests are in place for all touched player record shapes.

