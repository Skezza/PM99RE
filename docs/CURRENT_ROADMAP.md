# Current Editor Roadmap

> Snapshot note: canonical product roadmap lives in `upstream/pm99-skezmod-db-editor/docs/CURRENT_ROADMAP.md`.

This is the active roadmap for the PM99 editor.

The historical plans under `docs/HISTORY/enhancement_plans/` are retained for
provenance, but they are not the current execution plan.

## Product Direction

The editor should be built from parser-backed, writable contracts first.

- Default product flows should prefer strict record boundaries and confirmed
  field contracts.
- Heuristic scanners and probes remain useful, but they are fallback or
  investigation tools, not the primary source of truth.
- Unknown regions should be preserved until their layout is confirmed.

## Current Product Shell

The active desktop product path is now the refreshed club-first Tk shell exposed
through `app.gui` and implemented in `app/gui_refresh.py`.

- The GUI resolves a full PM99 database set (`JUG*.FDI`, `EQ*.FDI`, `ENT*.FDI`)
  from any one selected file.
- Startup now prioritizes editor readiness:
  clubs and coaches load first, then the player catalog is deferred.
- The player catalog still uses the full parser + fallback recovery path, but it
  now loads on demand and can warm in the background after the shell becomes
  usable.
- Team editor roster tools now include a structured `Batch Import CSV` flow in
  the refreshed shell (shared backend with CLI), replacing the previous
  placeholder path.
- Team roster batch import now supports a row-level preview/diff contract
  (`plan_preview`) shared by GUI and CLI JSON output before staging/apply.
- Team loading now promotes strong competition-signal probes into a read-only
  `competition_probe_contract` league assignment source, while preserving
  initial fallback provenance for audit (`league_source_initial` and
  `league_probe_matches_original_assigned`).
- The Leagues workspace now surfaces assignment provenance directly (`source`,
  `confidence`, `status`) with bucket filters so promoted vs fallback clubs are
  inspectable without leaving the main shell.
- Roster tools in the refreshed shell are now staged-first and commit through
  `Save All` (slot edits, promotions, batch CSV), keeping write semantics
  aligned with the core editor model.
- `Save All` now includes rollback attempts when a multi-file write fails
  mid-transaction, so open/save/edit workflows are safer during ongoing parser
  expansion.
- `Save All` now also runs a preflight save-plan gate (structured plan preview
  plus safety checks) before any write begins, reducing avoidable mid-save
  failures from malformed staged payloads.
- Reverse-engineering tools stay available in `Tools -> Advanced Workspace`
  instead of driving the main editor workflow.
- Bitmap/asset discovery now uses a shared read-only contract in both GUI
  (`Inspect Bitmap References`) and CLI (`bitmap-reference-probe`) so the
  discovery payload is scriptable and consistent.
- The asset lane has now moved beyond string references in local research: player
  mini-photos have been traced to `FDI-PKF/DBDAT/MINIFOTO.PKF`, with a working
  read-only extraction/render path and a reproducible full-gallery build through
  PM99RE (`scripts/build_player_bitmap_review.sh`). The correct current colour
  path uses an embedded RIFF palette from `DAT.PKF`, not the loose
  `SIMULPCF6.PAL` fallback.
- Player-name capacity preflight is now also a shared read-only contract in GUI
  Advanced and CLI (`player-name-capacity`) so future API/batch imports can
  validate name-length constraints before writes.
- Indexed staged player writes now support variable-length payload rewrites
  (directory offset/length repointing), and GUI `Save All` now uses the same
  shared staged-player write path as CLI contracts.
- Linked roster promotions now use that same player staged-writer path,
  replacing the old fixed-width alias patch behavior for promoted player names.
- Full-squad linked operations now have explicit reusable contracts: template
  export (`team-roster-export-template`), slot-for-slot clone
  (`team-roster-clone-linked`), and one-name bulk promotion
  (`team-roster-promote-bulk-name`).
- The right-hand editor remains the canonical staged-edit surface; saves are
  still validated through the shared reopen validation path.

## Near-Term Product Milestones

1. Finish roster parity.
   - Complete the unresolved legacy inline roster family so more clubs resolve
     through confirmed roster mappings instead of falling back to “unavailable”.
   - Keep the club editor, CLI, and Advanced workspace aligned on the same
     authoritative roster contracts.

2. Expand editor parity cautiously.
   - Improve coach linkage resolution so club cards can route into meaningful
     linked coach edits.
   - Continue promoting only parser-backed fields into the normal edit surface.
   - Keep the new file-order league fallback honest: it now covers the full
     known EQ team stream for browsing/routing, but it still needs to be
     replaced with stronger parser-backed competition contracts as they are
     decoded.
   - Use the Advanced Workspace competition-candidate probe to drive that next
     decode step instead of extending the fallback blindly.
   - Compare candidate offsets across leagues with the competition-signature
     profiler so the next promoted field is backed by cross-league evidence.
   - Current first-pass signal: byte `+0x00` after the known-text anchor is the
     strongest non-filler discriminator across the profiled competitions, with
     `+0x08` / `+0x0A` as secondary candidates.
   - Treat that `+0x00` byte as the current strongest read-only candidate field
     and keep the profiler focused on its code clusters before promoting any
     parser-backed semantic label.
   - Use the new derived cluster metadata (`competition-like` /
     `country-like` / `shared-family`) to decide whether `+0x00` should be
     promoted as a direct competition field or treated as a broader family code.
   - Current corpus signal: the dominant `0x7F` cluster is now inferred as
     `country-like` and is overwhelmingly England-heavy, which suggests `+0x00`
     may be a country/family discriminator rather than a clean league code.
   - The new secondary read-only signature (`+0x08` + `+0x0A`) is now worth
     tracking alongside `+0x00`: on the current real corpus it classifies `48`
     of `102` primary-code clusters as `competition-splitting`, which means it
     often separates the smaller shared families into cleaner competition-like
     groups.
   - That secondary signature is not enough yet for the largest family. The
     dominant `0x7F` cluster still only profiles as `weak` at about `50.6%`
     average within-competition purity, so it remains supporting evidence, not
     a replacement for a true decoded dedicated competition field.
   - A first third-byte refinement pass is now in place. The current best
     tested extra byte is `+0x01`, but on the real corpus it is still `no-gain`
     for the dominant `0x7F` family and does not materially improve the
     `+0x08/+0x0A` split. Treat it as evidence about what does *not* help yet,
     not as a promoted field.
   - The next better read-only lead is now the family-specific non-text byte
     scan. Once text-like spill bytes are excluded, the dominant `0x7F` family
     currently points to `+0x16` as its best non-text candidate (`exploratory`,
     about `64.2%` average within-competition purity). That is still not a
     decoded field, but it is a better target than the earlier text-heavy bytes.
   - The new `Inspect Primary-Code Family` view should now be the default way
     to pursue that lead from the GUI: it narrows the analysis to one selected
     club's primary-code family and shows the local probe window around the
     current best non-text candidate so text spill and structural bytes are
     easier to distinguish.
   - The next follow-on within the dominant `0x7F` family is now a
     dominant-country subgroup scan. For the England-heavy bucket, the current
     best subgroup candidate is `+0x19` (`tentative`, about `42.9%` average
     within-league purity, `3` dominant values). That is still read-only, but
     it is a more focused lead for splitting the English tiers than the broader
     family-wide `+0x16` byte.
   - This subgroup phase is now promoted into the Advanced workspace through
     `Profile Country Subgroups`, which should be the default report when
     validating country-like families before attempting any parser-backed field
     promotion.
   - Keep those same probes available in CLI form (`team-competition-profile`,
     `team-primary-family`, `team-country-subgroup-profile`) so investigation
     remains scriptable and consistent with the GUI.
   - Keep league placement explicitly auditable through shared probe metadata
     and `team-league-audit`, so sequence-fallback placements can be reviewed
     without silently rewriting clubs into different competitions.

3. Add an asset/bitmap discovery track.
   - Treat bitmap / image assets as part of the product plan, even if they are
     not yet first-class in the editor UI.
   - Identify where `BMP` / related references are stored in the PM99 data and
     formalize a read-only contract first.
   - The first shared contract is now in place (`inspect_bitmap_references`),
     exposed in GUI Advanced (`Inspect Bitmap References`) and CLI
     (`bitmap-reference-probe`) with aligned payloads.
   - That initial reference probe has now led to a stronger player-photo result:
     `MINIFOTO.PKF` is the current confirmed player portrait archive, and the
     current mirrored corpus yields `1354` `J96#####.BMP` player-photo records.
   - The current best read-only render path depends on an embedded `DAT.PKF`
     RIFF palette, so palette selection is now part of the discovery contract.
   - Use the PM99RE wrapper `scripts/build_player_bitmap_review.sh` as the
     reproducible research entry point for full-corpus local review, then
     promote richer asset tooling only after the ownership / write model is
     stable.
   - Build a future asset browser/editor surface only after the file references,
     ownership model, and write safety are understood.

## Immediate Baseline

1. Make the default editor load path strict-first.
   - Prefer real FDI entry boundaries and parser-backed records.
   - Use the embedded scanner only to fill gaps.

2. Stabilize the player contract before expanding writes.
   - Keep `PlayerRecord` as the canonical player model.
   - Finish unresolved fields such as `weight`.
   - Lock down the user-facing meaning of the trailing attribute bytes.

3. Strengthen the team contract around proven roster linkage.
   - Treat `EQ -> JUG` linked roster extraction as the authoritative roster path.
   - Continue reverse engineering the unresolved legacy inline roster mode.
   - Keep heuristic team metadata parsing clearly labeled as partial.

4. Expand write support only after read support is proven.
   - Do not add synthetic writes into unresolved regions.
   - Preserve unknown bytes by default.
   - Allow broader structural rewrites only when parser-backed read/write rules
     are documented and tested.

5. Clean the codebase by separating product and investigation paths.
   - Product modules should expose stable APIs.
   - Scripts and heuristic probes should stay available, but clearly outside the
     core editor path.
   - Delete obsolete code only after a strict replacement exists.

## Current Priorities

- Replace remaining heuristic-first editor paths with strict-first behavior.
- Extend team-side authoritative editing beyond read-only linked rosters, while keeping writes inside proven fixed-size overlays.
- Continue promoting same-entry authoritative roster families from read-only analysis into explicit fixed-size overlay contracts.
- Keep the proven team roster edit surfaces aligned across the shared action layer, CLI, and GUI.
- Add a read-only asset discovery path for bitmap-backed content once the
  reference contract is stable, then promote it into the editor shell only when
  the ownership / write story is clear.
- Keep the current player-photo findings explicit in research: `MINIFOTO.PKF`
  is now the proven player bitmap archive, but it is still a read-only asset
  lane until archive ownership and write safety are decoded.
- Keep confirmed parser-backed inspection/reporting contracts visible in the GUI as well as the CLI, while leaving unstable heuristic investigation flows in tools-first surfaces until their contracts settle.
- Prefer persistent in-app workspaces (for example, the `Analysis` tab) over transient dialogs when a confirmed inspection surface becomes part of the normal editor workflow.
- Treat “save succeeded” and “database is healthy” as separate checks:
  the main GUI save path should keep running a parser-backed reopen validation after write,
  and equivalent CLI validation should stay available through the shared action layer.
- Keep row-shape confidence and mapping confidence separate for same-entry fallbacks:
  the current preferred fallback families now share the confirmed `xor_pid + 0x61 0x61 0x61`
  row shape, but only the strongest mappings should be promoted into write-safe overlays.
- Finish the unresolved team roster families beyond the currently supported same-entry overlay set
  (`same_entry_authoritative` plus the strongest proven fallback) before attempting broader
  team structural writes.
- Use the staged promotion skip diagnostics (CLI + GUI Save plan) as the primary RE queue for
  unsafe linked-name payload families, and only promote additional fixed-name write contracts after
  those slot families are decoded and validated in-game.
- Keep the skip-diagnostics triage scriptable and in-app: use CLI `team-roster-promotion-safety`
  and Advanced `Profile Roster Promotion Safety` to rank `fixed_name_unsafe` families before promoting
  any broader linked-name write contracts.
- The promoted fixed-name text-spill families are now `parser_text_spill_salvage`,
  `parser_text_spill_no_alias_sync`, and `parser_text_spill_prefix_clip`: when
  direct text-replace output is garbled and length-prefixed parsing fails with
  given/surname slot-bound errors, parser-derived writes are allowed only under
  strict local-window guardrails (`first >= 5`, `last <= 128`, `diff <= 128`).
- `parser_text_spill_salvage` keeps alias-sync only when post-sync windows stay
  local under the same bounds; `parser_text_spill_no_alias_sync` is allowed only
  when parser windows pass but alias-sync is the sole widening failure.
- `parser_text_spill_prefix_clip` is allowed only when parser windows fail for the
  full parser candidate, but clipping parser bytes to offsets `5..128` still
  parses cleanly and yields a reasonable target name.
- Keep unresolved members of these families conservative: if parser windows fail,
  clip validation fails, or any additional guardrail fails, the slot stays
  `fixed_name_unsafe` and is never written.
- Use `scripts/profile_roster_promotion_unsafe_families.py` to rank exact
  `fixed_name_unsafe` subfamilies, cluster parser-window shapes (exact + bucketed),
  and emit before/after JSON deltas between runs.
- Use the now-broader `player-inspect` read path on non-indexed files to drive the remaining
  legacy player parity work, especially non-indexed `weight` and the trailing attribute contract.
- The legacy `marker + 14` weight candidate is now promoted for records that expose a real
  dedicated slot before the trailing attribute window. The remaining weight work is now about
  corpus validation across more legacy shapes, not whether the slot exists at all.
- Keep the legacy weight validation visible in the same confirmed inspection surfaces: the CLI
  profiler and the GUI `Inspect Indexed Player Byte Profiles...` view should continue to report
  both the indexed control-set evidence and the real name-only parser-path cross-check.
- Keep the unresolved tail-prefix bytes on the same footing: they are now a confirmed read-side
  probe exposed by `player-inspect`, `player-tail-prefix-profile`, and the GUI analysis view,
  but they still stay out of the normal edit contract until the binary-side consumer is found.
- The latest binary evidence narrows that search: `DBASEPRE.EXE`'s indexed parser helper
  materializes the confirmed suffix/physical fields into fixed struct offsets, but it still
  does not reveal comparable fixed-offset stores for the trailing attribute window. Instead,
  it bulk-copies the late opaque region into a sidecar area after `[player + 0x6E]` /
  `[player + 0x6F]`. Treat the tail prefix as a structural signature / sidecar contract
  unless a later consumer proves otherwise.
- Keep using the new tail-prefix histograms to drive the next RE step: the current indexed
  corpus strongly suggests `Attr 2` is a low-cardinality class marker (`107` vs `25`) rather
  than a normal stat, so the next binary target should be consumers that branch on that class.
- Use the now-formalized tail-layout split in future work:
  `attributes[0..2]` sit in the final variable-length block payload, while `attributes[3..11]`
  sit in the fixed trailer. That means the remaining open question is the meaning of the front
  block bytes, not the placement of the already-named trailer stats.
- The byte immediately after indexed `weight` is now also surfaced as a read-only probe
  (`post_weight_byte` / `postwt`). `FUN_0043d170` copies it into `[player + 0x48]` before
  it advances into the three variable-length string blocks, so it is now part of the
  stable parser-backed analysis surface even though the label is still unknown.
  The current evidence is stronger than “unknown byte”, though: `FUN_0043d960` tests
  `[player + 0x1D]` and `[player + 0x48]` against the same lookup value, and the
  known caller sits inside the search-options builder where that value is resolved
  through the same nationality table used by the player-view nationality label.
  The anchored indexed corpus currently shows about a `94%` exact match between
  `post_weight_byte` and `nationality`. Treat it as a secondary nationality/search
  key until a cleaner semantic label is proven.
  The remaining mismatch cases are now explicitly surfaced in the shared profile view;
  the current dominant divergence is `postwt=30 -> nat=31`, followed by `30 -> 45`,
  and `30` is also the dominant grouped `postwt` key in that non-mirror subset.
  More importantly, that dominant group is no longer just “nearby IDs”: on the
  current real corpus, `57` of the `66` `postwt=30` mismatches collapse to the
  home-nation IDs `31`, `45`, `19`, and `32`, which makes a grouped UK/Ireland-style
  search umbrella the strongest current hypothesis.
  That makes the next RE target sharper: explain the grouped/non-mirror nationality
  buckets instead of re-proving the mirror cases.
- Use the new direct `a0/a1/a2` tail-prefix filters to isolate the two current `Attr 2`
  classes and hunt for a consumer that branches on that split.
- The current `Attr 2` split is now sharper than before:
  `a2=25` collapses to the single `[1, 0, 25]` family, while `a2=107` contains the rest
  of the variation. The next binary trace should specifically target code that distinguishes
  those two classes.
- The fixed trailer byte is now exposed alongside that tail prefix in the same shared
  profile surface. Treat it as a secondary structural discriminator:
  for example, `a2=25` plus `trail=19` currently isolates the dominant combined signature
  `[1, 0, 25 | trail=19]`, but it is still not safe to name until the consuming code is found.
- The next byte after that fixed trailer is now also exposed (`sidecar`), because the
  binary consumes `[player + 0x6E]` and `[player + 0x6F]` separately before the later
  sidecar block. That makes `sidecar` a tertiary discriminator:
  the current `a2=25` + `trail=19` branch splits into `[... sidecar=0]` and
  `[... sidecar=1]`. The next binary trace should target the later consumer of the copied
  `[player + 0x70]` sidecar region, not the loader itself.
- This is no longer just a loader-side fact: at least one `DBASEPRE.EXE` UI path also reads
  `[player + 0x6E]` and `[player + 0x6F]` individually and renders them as separate one-byte
  values. That strengthens the contract boundary (two discrete subfields plus a copied sidecar),
  but the semantic labels are still unknown.
- The next binary trace should stay focused on the actual late consumer of the indexed
  variable blocks / copied sidecar region. The loader boundary is now materially clearer:
  the open questions are the exact semantic role of the nationality-like `post_weight_byte`,
  the front tail-prefix bytes, and the later sidecar consumer, not whether those bytes exist.
- Complete the remaining player field map, especially legacy/non-indexed parity and the trailing attribute contract.
- Finish the front of the trailing 12-byte player attribute window:
  slots `3 .. 11` are now strongly corroborated, but slots `0 .. 2` still need naming.
- Keep `attributes[0 .. 2]` out of the normal edit surface until they are named; treat them as
  read-only probe bytes rather than user-facing stats.
- Add tests whenever a formerly heuristic rule becomes parser-backed.
