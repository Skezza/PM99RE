# Player Fields Reference

This is the authoritative player-record field reference for the current codebase.

For container-level rules, use [../DATA_FORMATS.md](../DATA_FORMATS.md). For implementation details, cross-check [../../app/models.py](../../app/models.py), [../../app/io.py](../../app/io.py), and [../../app/file_writer.py](../../app/file_writer.py).

## Scope

This document describes the player data that the project can currently parse or write conservatively from `JUG98030.FDI`.

## Record Anchors

- Player data lives inside `.FDI` entry payloads and is parsed by `PlayerRecord.from_bytes()`.
- `team_id` is stored at bytes `0-1` (little-endian).
- `squad_number` is stored at byte `2`.
- The name region starts after byte `4`.

The current parser supports two complementary ideas:
- It first attempts a structured name read from the payload at offset `5` using two sequential length-prefixed strings (given name, then surname).
- Each structured string is stored as `uint16 length` followed by `length` bytes of `0x61`-XOR'd text.
- When structured parsing is incomplete or suspicious, it falls back to conservative name heuristics.
- Indexed `DMFIv1.0` JUG payloads also carry a second metadata block after the visible name suffix. The parser now uses that block when it validates cleanly.

Reverse-engineering notes and Ghidra validation indicate that the original game reads player records sequentially after the two strings. The `0x61 0x61 0x61 0x61` (`aaaa`) marker is therefore a conservative implementation anchor in the current write path, not a proven format boundary.

## Confirmed Parser-Backed Fields

## Identity

- `team_id`
  - Bytes `0-1`
  - Type: `uint16` little-endian
- `squad_number`
  - Byte `2`
  - Type: `uint8`
- `given_name`, `surname`, `name`
  - Extracted from the name region beginning at byte `5`
  - Backed by the raw payload so unknown surrounding bytes can be preserved

## Metadata (current conservative write anchor)

The current codebase rewrites these fields relative to the `aaaa` anchor when it can be found safely. This is a write-safety rule, not a claim that the underlying format is marker-based:

- `position_primary`
  - `marker + 7`
  - Stored XOR’d (`value ^ 0x61`)
- `nationality`
  - `marker + 8`
  - Stored XOR’d
- `birth_day`
  - `marker + 9`
  - Stored XOR’d
- `birth_month`
  - `marker + 10`
  - Stored XOR’d
- `birth_year`
  - `marker + 11` and `marker + 12`
  - Little-endian, XOR’d bytewise
- `height`
  - `marker + 13`
  - Stored XOR’d

## Metadata (indexed JUG suffix block)

For indexed `DMFIv1.0` JUG entries, the parser can also recover a richer metadata block anchored from the visible name suffix. Existing indexed payloads can now be rewritten conservatively in place through that same suffix block when the anchor validates.

- `nationality`
  - `name_suffix + 8`
  - Stored XOR’d
- `position_primary`
  - `name_suffix + 11`
  - Stored XOR’d
- `birth_day`
  - `name_suffix + 12`
  - Stored XOR’d
- `birth_month`
  - `name_suffix + 13`
  - Stored XOR’d
- `birth_year`
  - `name_suffix + 14` and `name_suffix + 15`
  - Little-endian, XOR’d bytewise
- `height`
  - `name_suffix + 16`
  - Stored XOR’d
- `weight`
  - `name_suffix + 17`
  - Stored XOR’d
  - Current evidence indicates this is kilograms in indexed JUG payloads

## Fine Role Slots (Tactics `ROL.` Dropdown)

This section documents the editable fine-role bytes that drive the black-arrow
`ROL.` dropdown on the in-game `TACTICS` screen.

### What Is Stored vs Computed

- Stored in `JUG98030.FDI`: per-player fine role slots (codes).
- Not stored in `JUG98030.FDI`: the displayed role percentages.
- The game computes percentages from slot-role compatibility at runtime.

### Binary Evidence (Ghidra, `MANAGPRE.EXE`)

- `FUN_004afd80 @ 0x004afd80`
  - Consumes six consecutive role-like bytes from the decoded player stream.
  - Writes them into player struct offsets `+0x1d .. +0x22`.
  - Mirrors slot0 into `+0x23`.
- `FUN_00491980 @ 0x00491980`
  - Builds the `ROL.` dropdown using pointer table `0x00735340`.
  - Iterates role index `1..18`, calls `FUN_004b13f0`, and stores `100 - penalty`
    as the shown percentage.
- `FUN_004b13f0 @ 0x004b13f0`
  - Reads the six fine slots from `[player + 0x1d + i]` (`i=0..5`).
  - Computes the minimum penalty across those slots for the requested role.
  - Penalty constants include `0`, `5`, `0x0f`, `0x18`, `0x28`, `0x46`
    (displayed as `100`, `95`, `85`, `76`, `60`, `30` via `100 - penalty`).
- `0x004901b5` and `0x00490211`
  - `0x004901b5` indexes coarse POS label table (`0x00735400`) using `[player + 0x1c]`.
  - `0x00490211` indexes fine `ROL.` label table (`0x00735340`) using `[player + 0x23]`.

### Fine Role Label Table

The game’s fine-role string table starts at `0x00735340` and contains 18 roles:

1. Goalkeeper
2. Right Back
3. Left Back
4. Sweeper
5. Inside Centre Left
6. Inside Centre Right
7. Right Midfielder
8. Inside Right
9. Centre Forward
10. Central Midfielder
11. Left Midfielder
12. Right Winger
13. Central Striker
14. Left Winger
15. Defensive Midfielder
16. Right Forward
17. Left Forward
18. Inside Left

### Database Decode Rules (Editable Bytes)

The six fine slots are editable in the decoded payload (before re-encoding).

- Marker-shaped rows:
  - Slot window is `name_end - 1 .. name_end + 4` (6 bytes).
  - Decode rule per byte: `xor = byte ^ 0x61`; `code = xor - 1` when `xor > 0`, else `98`.
- Indexed `dd6361` rows:
  - Slot window starts at `indexed_suffix_anchor + 2`.
  - Read up to 6 bytes while `xor = (byte ^ 0x61)` stays in `1..18`.
  - `code = xor - 1`.

`code` range `0..17` maps to fine roles; `98` is unassigned.

### Reproducible Stoke Evidence

- Repro command:

```bash
python3 scripts/probe_role_slot_forensics.py \
  --team-file work/stoke_capture_225942_dbdat/EQ98030.FDI \
  --player-file work/stoke_capture_225942_dbdat/JUG98030.FDI \
  --team-query Stoke \
  --output-dir work \
  --json
```

- Byte/offset artifacts:
  - `work/stoke_city_role_slots_manifest.json`
  - `work/stoke_city_role_slots_table.csv`
  - `work/stoke_city_role_slots_summary.json`
- Example (`Larus SIGURDSSON`, slot 3, `dd6361`):
  - `indexed_anchor = 38`
  - active fine-role bytes at offsets `40` and `41`
  - decoded codes `5;4` => `Inside Centre Right;Inside Centre Left`

## Attributes

- The current parser reads up to 12 skill bytes from the trailing attribute window.
- The effective window is `len(payload) - 19` through `len(payload) - 7`.
- Each byte is XOR’d with `0x61` after outer payload decoding.
- Missing values are padded conservatively in memory for compatibility.
- Confirmed trailing-window mapping:
  - `attributes[3]` = `speed`
  - `attributes[4]` = `stamina`
  - `attributes[5]` = `aggression`
  - `attributes[6]` = `quality`
  - `attributes[7]` = `heading`
  - `attributes[8]` = `dribbling`
  - `attributes[9]` = `passing`
  - `attributes[10]` = `shooting`
  - `attributes[11]` = `tackling`
- `attributes[0]`, `attributes[1]`, and `attributes[2]` remain unresolved.
- The inspection surfaces now expose these three leading tail bytes as a read-only
  `tail_prefix=[a, b, c]` probe in both the CLI (`player-inspect`) and the GUI
  (`Inspect Player Metadata...`) so they can be compared across real records without
  pretending they are normal editable stats.
- The CLI now also exposes `player-tail-prefix-profile`, and the GUI surfaces the same
  data inside the `Tail Prefix` and `Tail Signatures` tabs of `Inspect Indexed Player Byte
  Profiles...`. This keeps the unresolved prefix inspectable with the same parser-backed
  filters already used for `u0/u1/u9/u10`, and it now also supports direct `a0/a1/a2`
  plus the confirmed byte immediately after weight (`post_weight_byte` / `postwt`)
  and the two post-attribute byte filters (`trail` and `sidecar`) so the current
  structural classes can be isolated without ad hoc scripts.
- `DBASEPRE.EXE`'s indexed parser helper (`FUN_0043d170`) now gives a useful negative
  result too: it writes the indexed suffix/physical fields into fixed player-struct
  offsets (`+0x20`, `+0x4C`, `+0x17..+0x1F`, `+0x16`, `+0x50..+0x53`, `+0x4E`, `+0x4F`),
  and it also copies the next encoded byte after weight into `[player + 0x48]`.
  That byte is now surfaced as the read-only `post_weight_byte` probe.
  A later helper (`FUN_0043d960`) tightens the interpretation: it checks
  `[player + 0x1D]` and `[player + 0x48]` against the same lookup value, and its
  known caller in `FUN_004319f0` sits inside the search-options builder where that
  value is resolved through the same `0x4B2E90` nationality table used by the
  player-view nationality label path at `0x00417583`.
  On the current anchored indexed corpus, `post_weight_byte` matches `nationality`
  on roughly 94% of parsed records, so the safest current reading is that it acts
  as a secondary nationality/search key, not a second physical stat.
  The remaining mismatches are also patterned rather than random. The dominant
  divergence is now much narrower than “nearby IDs”: `postwt=30` is the top grouped
  key, and on the current real corpus `57` of its `66` mismatch rows land on the
  four home-nation IDs `31`, `45`, `19`, and `32` (with the leading pairs
  `30 -> 31`, `30 -> 45`, `30 -> 19`, and `30 -> 32`). Combined with the
  `FUN_004319f0` search-options builder loop, this makes the strongest current
  reading a grouped nationality-search umbrella rather than bad physical-stat data:
  selecting the `30` search key likely exposes a broader UK/Ireland-style bucket,
  while the primary `nationality` byte still preserves the specific per-country label.
  The shared profile now also surfaces these grouped cohorts directly, not just the
  raw mismatch pairs, so the non-mirror minority can be inspected without ad hoc scripts.
  The CLI/GUI inspect surfaces now annotate the obvious per-record mirror case as a
  nationality-search mirror, and the non-mirror minority as grouped nationality-search keys.
  but it does not expose the trailing 12-byte attribute window as a comparable set of
  fixed struct-byte writes there. Instead, once it reaches the late opaque region it
  copies a larger trailing block into a player sidecar area in bulk (starting at
  `[player + 0x70]`, after loading two bytes into `[player + 0x6E]` / `[player + 0x6F]`).
  Those two pre-sidecar bytes are now surfaced as separate read-only probes:
  `trail` (the fixed trailer byte after `attributes[3..11]`) and `sidecar`
  (the first byte of the remaining copied sidecar tail).
  Separate UI paths in `DBASEPRE.EXE` also read `[player + 0x6E]` and `[player + 0x6F]`
  individually and render them as standalone one-byte values, which strengthens the
  case that these are real subfields even though their labels are still unknown.
  That is why the tail prefix is currently treated as a structural signature / sidecar
  probe rather than a normal named stat. The same caution applies to
  `post_weight_byte`: it is fixed and parser-backed, and likely nationality-adjacent,
  but still not safe to rename as a normal editable field.
- `handling` is part of the separate `dd6361` visible-skill trailer contract, not this 12-byte player-record tail.
- The GUI now treats `attributes[0..2]` as read-only probe bytes and only exposes `attributes[3..11]`
  as normal editable fields.

## Write Rules and Constraints

- Preserve `raw_data` whenever possible; unknown bytes should survive unchanged.
- Do not assume arbitrary player-name expansion is safe.
- Metadata writes must not happen if the `aaaa` anchor cannot be located.
- Indexed JUG metadata writes must not happen if the suffix anchor cannot be located safely.
- Attribute writes must remain within the trailing attribute window.
- If a write would change record size, directory offsets and header state must be updated through the existing safe writers.

## Known / Partial / Unknown

## Known

- `team_id`
- `squad_number`
- name region handling
- `position_primary`
- `nationality`
- `birth_day`
- `birth_month`
- `birth_year`
- `height`
- `weight` (indexed JUG payloads, plus legacy records with a dedicated marker-backed slot)
- trailing attribute window

## Partial

- The exact internal name encoding varies across records; the parser handles multiple shapes conservatively.
- `weight` is now parser-backed for indexed `DMFIv1.0` JUG payloads and for non-indexed / legacy records only when the conservative marker anchor exposes a real extra byte at `name_end + 14` before the trailing attribute window. In those legacy cases the same in-place slot is writable too. Canonical synthesized records still do not emit this extra byte, so they remain weightless unless a real slot already exists in `raw_data`.
- `DBASEPRE.EXE` player-view code also treats the in-memory physical stat bytes as adjacent values: it reads `[player + 0x4E]` as a centimetre height value (then converts it to feet/inches for display) and `[player + 0x4F]` as a raw weight-like value after drawing the `HEIGHT` / `WEIGHT` labels. That strongly corroborates the indexed JUG `height`/`weight` mapping.
- `DBASEPRE.EXE`'s indexed player parser helper (`FUN_0043d170`) also places the first two bytes of the indexed suffix block into struct offsets `[player + 0x20]` and `[player + 0x4C]`. These bytes are now surfaced as raw `indexed_unknown_0` / `indexed_unknown_1` probe values.
- `DBASEPRE.EXE` portrait rendering also confirms that indexed suffix bytes `name_suffix + 2 .. + 7` are the variable-length face-component sequence used to build the player head graphic.
- Separate from those per-record face-component bytes, the mirrored game corpus
  now also exposes a distinct player mini-photo asset archive:
  `FDI-PKF/DBDAT/MINIFOTO.PKF`. That archive currently yields `1354`
  `J96#####.BMP` player-photo records, and it should be treated as a separate
  asset contract rather than as an inline `JUG98030.FDI` field family.
- The current best colour render path for `MINIFOTO` uses an embedded RIFF
  palette from `DAT.PKF` (`ba71c6264fdd9ad0`, with identical observed output to
  `2d2bceb5304c1937` for `MINIFOTO`). Loose `SIMULPCF6.PAL` is a usable
  fallback for discovery, but it is visibly mis-paletted for portraits.
- Indexed suffix bytes `name_suffix + 9` and `+10` are now surfaced as raw `indexed_unknown_9` / `indexed_unknown_10` values. They behave like low-cardinality categorical flags, but their gameplay meaning is still unresolved.
- The `player-inspect` CLI path exposes the indexed suffix anchor and these raw probe bytes directly for real-record comparisons.
- The GUI now exposes the same confirmed indexed snapshot through `Inspect Player Metadata...`, using the same parser-backed backend contract as `player-inspect` in a structured dialog.
- In the full GUI, these confirmed player inspection surfaces now render into the persistent `Analysis` tab workspace instead of living only in transient popups.
- When a matching local reference still exists under `.local/PlayerStills/*.png`, that dialog now also surfaces it as an optional visual cross-check. This is a GUI aid only, not part of the binary contract.
- The `player-leading-profile` CLI path aggregates the unresolved leading byte pair (`indexed_unknown_0` / `indexed_unknown_1`) across the indexed JUG dataset for the same kind of cohort analysis, and it can now be filtered by `u0` / `u1` as well as `u9` / `u10`.
- Current evidence suggests the leading pair behaves differently from `u9/u10`: `indexed_unknown_0` is much higher-cardinality (dozens of values in the anchored dataset), while `indexed_unknown_1` is often `0` but does take non-zero values.
- `DBASEPRE.EXE` also has a direct player-list UI consumer for `[player + 0x4C]`: it reads the byte and maps it into row colors. In the indexed subset, the observed values currently collapse to `0`, `1`, `2`, and `4`, with `4` normalized into the same display bucket as `1`. That makes `indexed_unknown_1` look like a compact display/status class, even though the underlying gameplay meaning is still not named.
- A position cross-check on the anchored indexed subset rules out the simplest alternative explanation: `indexed_unknown_1` spans all main position codes (`0`..`3`) rather than collapsing to a single coarse position group. It may still be used for presentation, but it is not just a hidden position-color byte.
- `DBASEPRE.EXE`'s player-list builders (`FUN_0042a430` and `FUN_0042e330`) also use the leading pair as guard bytes before adding players to sortable UI lists. They reject records when `[player + 0x4C] == 3`, and they branch on `[player + 0x20]` against `0x62` / `0x63`. In the current anchored indexed JUG subset, those guard values do not appear (`u0` currently tops out at `31`, and `u1` is only `0`, `1`, `2`, or `4`), so these look like reserved or non-listable sentinel states rather than normal live values.
- `indexed_unknown_0` remains the more likely fine-grained variant selector within that class.
- The `player-suffix-profile` CLI path aggregates these unresolved byte pairs across the indexed JUG dataset, with optional nationality/position filters for hypothesis testing.
- The GUI now also exposes the same confirmed read-side profile data through `Inspect Indexed Player Byte Profiles...`, combining the current `player-suffix-profile` and `player-leading-profile` views into one structured stateful dialog.
- That same GUI profile view now also includes the unresolved `tail_prefix` buckets, using
  the same filters and backed by the same indexed parser path as the CLI
  `player-tail-prefix-profile` command.
- In the full GUI, that profile view also renders in the persistent `Analysis` tab so the latest parser-backed inspection data stays visible while editing.
- That profile dialog also records when the sampled example names have matching local still assets, so the current byte-bucket hypotheses can be cross-checked against the local screenshot set without affecting the underlying parser contract.
- Current working hypothesis only: `indexed_unknown_9` behaves like an appearance tone bucket, and `indexed_unknown_10` behaves like a hair/palette bucket. This is investigation guidance, not a safe write contract.
- Current tail-prefix evidence is stronger for a structural signature than for user-facing
  stats. For example, on the current `JUG98030.FDI` corpus filtered to `u1=1`, the top
  buckets are `[77, 81, 107]` (`132` records), `[1, 0, 25]` (`96`), and
  `[77, 80, 107]` (`56`). That clustering is real and useful for reverse engineering, but
  it still does not map cleanly to named visible fields like `fitness` or `morale`.
- The new per-byte histogram view strengthens that same conclusion:
  - `Attr 0` is highly skewed toward `77`, with a smaller secondary family at `1`
  - `Attr 1` has several real buckets (`81`, `0`, `80`, `83`, `76`, ...)
  - `Attr 2` is almost binary on the anchored indexed corpus (`107` vs `25`)
  This makes `Attr 2` look more like a class marker than a normal user-facing stat, but
  it is still not safe to name until a real binary consumer is identified.
  The direct `a2` filter makes that split even stronger:
  - `a2=25` currently collapses to the single dominant family `[1, 0, 25]` (`308` records)
  - `a2=107` covers the remaining larger family set (`1646` records), where `Attr 0` and
    `Attr 1` still vary materially
  Adding the fixed trailer byte refines that further:
  - `a2=25` with `trail=19` isolates the dominant combined signature
    `[1, 0, 25 | trail=19]` (`182` records)
  - the remaining `a2=25` records retain the same `tail_prefix` but split across other
    trailer-byte values, which makes the trailer byte a useful secondary discriminator
    even though it is still unresolved.
  Adding the second pre-sidecar byte refines that dominant branch again:
  - `[1, 0, 25 | trail=19 sidecar=0]` currently contains `161` records
  - `[1, 0, 25 | trail=19 sidecar=1]` currently contains `21` records
  So `sidecar` is now a parser-backed tertiary discriminator on top of the current
  `Attr 2` and `trail` split, even though it remains unnamed.
  The newly surfaced `post_weight_byte` is also a useful cohort discriminator:
  on the current corpus, the dominant `a2=25` + `trail=19` branch is still mostly
  `postwt=30`, which makes it a stable read-only filter even before it has a
  semantic label.
  Across the broader anchored indexed set, `post_weight_byte` matches `nationality`
  on about `94%` of rows, which is why the current tooling now treats it as a
  secondary nationality/search byte rather than part of the physical-stat contract.
  The CLI and GUI inspect surfaces now also annotate the obvious per-record case where
  `post_weight_byte == nationality`, so that mirror relationship is visible without
  having to run a separate profile command.
  The shared profile surface now also reports the top mismatch pairs and the top
  divergent `postwt` keys directly, so the non-mirror minority can be tracked
  without ad hoc scripts.
- The indexed tail layout itself is now partially formalized:
  - on the current anchored indexed corpus, the conservative layout walker verifies the
    same split on `1921` records, with `33` remaining mismatches / unparsed layouts
  - `attributes[0..2]` are the last three bytes of the final variable-length block payload
  - `attributes[3..11]` are the following nine bytes in the fixed trailer
  - the parser then skips one additional trailer byte, leaving the final six bytes as
    trailing padding / post-trailer data
  This is a structural mapping, not a semantic one, but it explains why the front of the
  attribute window behaves differently from the named stats.
- The `player-edit` CLI path now supports in-place indexed renames as well as the confirmed `DMFIv1.0` metadata fields. On non-indexed player files it also supports the conservative marker-backed fields (`position_primary`, `nationality`, `birth_*`, `height`) and now `weight` too, but only when the selected record already exposes a real parser-backed legacy weight slot. `player-batch-edit` applies the same contract from a CSV plan.
- `player-inspect` now also works on non-indexed player files. On those legacy shapes it exposes the
  same conservative marker-backed fields through the shared inspection path, leaves indexed-only
  suffix fields empty, and now also surfaces `weight` when the record has a real marker-backed slot.
- `player-legacy-weight-profile` now uses the indexed suffix-weight field as a control set to test
  old marker-relative candidate offsets. On the current indexed corpus, `marker + 14` is the only
  serious candidate: it exactly matches the trusted indexed `weight` in `742 / 1464` control records
  (`50.68%`), while `marker + 15 .. + 18` are effectively noise. Across that same control set,
  `marker + 13` still remains the only viable height baseline (`50.20%` exact). That makes
  the legacy `marker + 14` promotion a structural consequence of the already-accepted marker-backed
  height slot, not just a loose statistical guess.
- `player-legacy-weight-profile` now also reports a second validation pass over the real name-only
  parser path (`gather_player_records`) for the same file, counting how many valid parsed records
  expose the legacy slot and how often those parser-backed weights agree with uniquely matched
  indexed records. On the current `JUG98030.FDI` corpus, that name-only cross-check is much
  stronger than the pure control set: `2470` valid parsed records expose the slot, `492` map
  uniquely to indexed records, and `447 / 492` of those (`90.85%`) agree exactly. The GUI
  exposes the same summary and candidate table inside
  `Inspect Indexed Player Byte Profiles...`.
- Indexed JUG metadata is now writable in place for existing records, but canonical synthesized records still do not emit this suffix block.
- The trailing 12-byte attribute window is now partially stabilized: slots `3 .. 11` are strongly
  corroborated against the `dd6361` visible-skill index, while slots `0 .. 2` are still unresolved.

## Unknown or Not Yet Safe

- Contract-related fields
- Any unknown metadata bytes outside the confirmed offsets
- Structural rewrites that rely on undocumented player-record variants

## Safety Notes

- Historical investigations showed that player-name storage is structurally sensitive. Incorrect assumptions about string layout can corrupt the file.
- The original game appears to read the record sequentially, so name edits and metadata edits should be treated as whole-record structural work, not arbitrary byte pokes around a presumed delimiter.
- Current write paths should therefore be treated as conservative overlays, not as permission to freely synthesize or reflow record internals.
