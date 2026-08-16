# English 80 Modern Replacement Plan

Generated: 2026-05-01

## Goal

Build a modern English 80-club PM99 candidate covering the current Premier League, Championship, League One, and the first 12 League Two clubs needed to fill PM99's 80 English club slots.

## Source Snapshot

- Primary club and squad source: FootballSquads 2025/2026 English league pages.
- Primary player fields: squad number, name, nationality, position, height, weight, date of birth, birthplace, previous club.
- Snapshot date: 2026-05-01.
- PM99 target era: player real birth years are shifted by 27 years for the encoded PM99 DOB field so their in-game age approximates the 2025/26 age inside a 1999-era database. The real DOB remains logged in the source ledger.

## Club Mapping Policy

- Keep existing PM99 club identities whenever the modern club already exists in the English 80 set. Example: Stoke City is relinked through its existing team carrier rather than simulated by renaming another club's players.
- Replace disappeared or out-of-scope PM99 clubs through the modern English pyramid slot assignment already proven by the 80-club selector work.
- Use the current 2025/26 league order:
  - Premier League: 20 clubs.
  - Championship: 24 clubs.
  - League One: 24 clubs.
  - League Two: first 12 FootballSquads-listed clubs, to fit the fixed 80-club PM99 English structure.
- Do not write speculative competition/division bytes until that write surface is release-proven. The game-visible selector mapping and club rosters are the executable contract for this milestone.

## Player Replacement Policy

- For every target club, select the first 20 current-squad players from FootballSquads, ignoring blank squad-number rows and "Players no longer at this club".
- Preserve role shape:
  - G -> goalkeeper.
  - D -> defender.
  - M -> midfielder.
  - F -> forward.
- Use runtime-safe aliases for the visible PM99 name tokens while logging the full source names.
- Patch each allocated runtime-safe player record with:
  - primary position and visible position bytes,
  - visible nationality byte from PM99's country table,
  - DOB day/month and PM99-shifted birth year,
  - height and weight when available,
  - deterministic position/tier/age-based attributes.

## Attribute Policy

The current automated build uses a transparent deterministic attribute model because public squad pages do not provide PM99-equivalent values. The model derives speed, stamina, aggression, quality, heading, dribbling, passing, shooting, and tackling from:

- league tier,
- player position,
- squad number,
- age,
- height,
- weight.

The source ledger records the basis for each row so this can be replaced later by a licensed or explicitly chosen online rating source without changing the write pipeline.

## Execution Checklist

- [x] Scrape and normalize the current English 80 club/squad source data.
- [x] Generate a runtime-safe 80-club slot assignment.
- [x] Build an isolated repointed game candidate from the pristine fixture.
- [x] Patch semantic player fields for all 1,600 allocated player records.
- [x] Cap all target linked rosters to 20 visible rows so legacy surplus carrier rows cannot leak into squad screens.
- [x] Patch mononym aliases so visible names use recognisable aliases instead of `Player` placeholders.
- [x] Validate database parser/readback integrity.
- [x] Capture visual sample screenshots for Liverpool, Stoke City, Manchester United, Arsenal, and Brentford.
- [x] Record artifact paths, validation results, and residual risks.
- [x] Audit all 80 visible clubs against PM99 identity/kit carriers after the Stoke/Wolves kit finding.

## Execution Log

- Build output: `work/pm99/english80_2026_football_squads/english80_2026_football_squads_20260501T072310Z/`
- Isolated game: `work/pm99/english80_2026_football_squads/english80_2026_football_squads_20260501T072310Z/game/`
- Source ledger: `work/pm99/english80_2026_football_squads/english80_2026_football_squads_20260501T072310Z/football_squads_source_ledger.json`
- Slot assignment: `work/pm99/english80_2026_football_squads/english80_2026_football_squads_20260501T072310Z/slot_assignment_english80_2026_football_squads.json`
- World state: `work/pm99/english80_2026_football_squads/english80_2026_football_squads_20260501T072310Z/world_english80_2026_football_squads.json`
- Repoint manifest: `work/pm99/english80_2026_football_squads/english80_2026_football_squads_20260501T072310Z/game/repointed_roster_manifest.json`
- Semantic manifest: `work/pm99/english80_2026_football_squads/english80_2026_football_squads_20260501T072310Z/english80_semantic_manifest.json`
- Roster cap manifest: `work/pm99/english80_2026_football_squads/english80_2026_football_squads_20260501T072310Z/english80_roster_count_cap_manifest.json`
- Mononym alias patch manifest: `work/pm99/english80_2026_football_squads/english80_2026_football_squads_20260501T072310Z/english80_mononym_alias_patch_manifest.json`

### Corrected Division-Structured Build

- Corrected build output: `work/pm99/english80_2026_division_structured/english80_2026_division_structured_20260501T183853Z/`
- Corrected isolated game: `work/pm99/english80_2026_division_structured/english80_2026_division_structured_20260501T183853Z/game/`
- Corrected world state: `work/pm99/english80_2026_division_structured/english80_2026_division_structured_20260501T183853Z/world_english80_2026_division_structured.json`
- Corrected slot assignment: `work/pm99/english80_2026_division_structured/english80_2026_division_structured_20260501T183853Z/slot_assignment_english80_2026_division_structured.json`
- Linked visible team-name patch manifest: `work/pm99/english80_2026_division_structured/english80_2026_division_structured_20260501T183853Z/division_structured_linked_visible_team_names_manifest.json`
- Stoke City visual selector correction: First Division, selected team coordinate `436,360`.
- HTML evidence page: `artifacts/english80_division_evidence_20260501/index.html`

## Validation Results

- Build manifest: `ok=true`, 80 clubs, 1,600 players.
- Repoint manifest: `ok=true`, 1,600 allocations, 0 failures.
- Semantic readback: `readback_ok=true`, 1,600 rows.
- Roster cap: 64 target carrier rosters capped from more than 20 rows to 20 visible rows.
- Parser validation: `all_valid=true`.
- Game-ready v1 audit: `ok=true`, no issues.
- Boundary check: OK.
- Corrected division-structured build manifest: `ok=true`, 80 clubs, 1,600 players.
- Corrected parser validation: `all_valid=true`.
- Corrected game-ready v1 audit: `ok=true`, no issues.

## Visual Evidence

- Liverpool capped squad: `upstream/pm99-runner/docs/artifacts/pm99_runner/english80_2026_visual5_capped_20260501T072310Z/clubs/liverpool/screens/025_squad_inspect_final.png`
- Stoke City capped squad: `upstream/pm99-runner/docs/artifacts/pm99_runner/english80_2026_visual4_capped_squad_retry_20260501T072310Z/clubs/stoke_city/screens/023_squad_inspect_retry.png`
- Manchester United capped squad: `upstream/pm99-runner/docs/artifacts/pm99_runner/english80_2026_visual4_capped_squad_retry_20260501T072310Z/clubs/manchester_united/screens/023_squad_inspect_retry.png`
- Arsenal capped squad after mononym alias patch: `upstream/pm99-runner/docs/artifacts/pm99_runner/english80_2026_arsenal_mononym_squad_20260501T072310Z/clubs/arsenal/screens/025_squad_inspect_final.png`
- Brentford capped squad: `upstream/pm99-runner/docs/artifacts/pm99_runner/english80_2026_visual4_capped_squad_retry_20260501T072310Z/clubs/brentford/screens/025_squad_inspect_final.png`
- Corrected Stoke First Division selector: `upstream/pm99-runner/docs/artifacts/pm99_runner/english80_stoke_visible_first_division_20260501T183853Z/clubs/stoke_city/screens/008_pick_team.png`
- Corrected Stoke First Division squad: `upstream/pm99-runner/docs/artifacts/pm99_runner/english80_stoke_visible_first_division_20260501T183853Z/clubs/stoke_city/screens/023_squad_inspect_retry.png`
- Wrexham visible selector/squad proof: `upstream/pm99-runner/docs/artifacts/pm99_runner/english80_new_club_visible_evidence_20260501T183853Z/clubs/wrexham/screens/008_pick_team.png`
- Bromley visible selector/squad proof: `upstream/pm99-runner/docs/artifacts/pm99_runner/english80_new_club_visible_evidence_20260501T183853Z/clubs/bromley/screens/008_pick_team.png`
- Crawley visible selector/squad proof: `upstream/pm99-runner/docs/artifacts/pm99_runner/english80_new_club_visible_evidence_20260501T183853Z/clubs/crawley_town/screens/008_pick_team.png`

The runner route classifier returned non-zero for the squad-only proof passes because OCR classification did not accept every final screen, but the screenshot files above were produced and manually checked.

## Identity and Kit Carrier Audit

The Stoke/Wolves kit issue exposed that the division-structured build still used many sequential replacement carriers instead of relinking clubs to their original PM99 EQ identities. PM99 kit art is keyed by `EQ96<eq_record_id>.BMP` records in the kit archives, so a club named Stoke on carrier `EQ0344` inherits Wolverhampton kit art until Stoke is selected through carrier `EQ0341` or the kit archive is patched.

- Audit report: `artifacts/english80_kit_research_20260501/index.html`
- Matrix JSON: `artifacts/english80_kit_research_20260501/english80_identity_kit_matrix.json`
- Matrix CSV: `artifacts/english80_kit_research_20260501/english80_identity_kit_matrix.csv`
- Base kit preview sheet: `artifacts/english80_kit_research_20260501/base_miniesc_review/team_kits_all_labeled_datpal_mask0.png`
- Repro script: `scripts/build_english80_kit_research.py`

Audit result: 80 clubs reviewed, 71 direct PM99 identities, 1 heritage successor host (`AFC Wimbledon` on `Wimbledon`), and 8 synthetic new-club hosts. The current division-structured build has 63 carrier mismatches. Existing clubs should be relinked to their original PM99 EQ ids rather than papered over with copied kit art; only the heritage/synthetic clubs should receive newly synthesized modern kit records.

### Kit-Corrected Division-Structured Build

- Kit-corrected build output: `work/pm99/english80_2026_division_structured/english80_2026_division_structured_20260501T212554Z/`
- Kit-corrected isolated game: `work/pm99/english80_2026_division_structured/english80_2026_division_structured_20260501T212554Z/game/`
- Kit patch manifest: `work/pm99/english80_2026_division_structured/english80_2026_division_structured_20260501T212554Z/kit_patch/english80_division_kit_patch_summary.json`
- Kit contact sheet: `work/pm99/english80_2026_division_structured/english80_2026_division_structured_20260501T212554Z/kit_patch/english80_division_kit_contact_sheet.png`
- Rich evidence page: `artifacts/english80_kit_corrected_20260501/index.html`
- Dense selector sweep: `upstream/pm99-runner/docs/artifacts/pm99_runner/english80_kit_corrected_selector_dense_20260506/`
- Original focused visual proofs: `upstream/pm99-runner/docs/artifacts/pm99_runner/english80_kit_corrected_visual_proofs_20260501T212554Z/`
- Corrected lower-division focused visual proofs: `upstream/pm99-runner/docs/artifacts/pm99_runner/english80_kit_corrected_lower_coord_proofs_20260506/`
- Corrected lower-division selector world: `artifacts/english80_kit_corrected_20260501/english80_corrected_selector_world_dense_20260506.json`

Kit patch result: `ok=true`. The patcher reviewed all 80 researched identities and rewrote the kit archives for the visible carrier slots:

- 85 kit records kept because the carrier already matched the original PM99 identity.
- 213 kit records copied from the correct source identity.
- 42 kit records resampled from a source identity where source and target bitmap geometry differed.
- 43 kit records synthesized for heritage/new clubs.
- 8 kit records synthesized from fallback club colours because a source bitmap was absent in one archive.
- 9 target records were absent from specific archives and therefore had no writable bitmap record to patch.

Stoke City now remains in the modern First Division selector slot, while the visible carrier `EQ0344` receives Stoke's source kit art from `EQ0341` across the writable kit archives. Liverpool and Arsenal keep their original kit records; Manchester United is copied from its original `EQ0303` identity; AFC Wimbledon and Bromley receive synthesized modern kits.

Validation after this build:

- Build manifest: `ok=true`, 80 clubs, 1,600 players.
- Kit patch manifest: `kit_patch_ok=true`.
- Semantic readback: `readback_ok=true`, 1,600 rows.
- Parser validation: `all_valid=true`.
- Game-ready v1 audit: `ok=true`, no issues.
- Boundary check: OK.
- Dense runner selector sweep: `success=true`, 4 divisions, 296 observations.
- Focused visual runs: 8/8 trusted route captures are represented in the HTML. Arsenal, Liverpool, Manchester United, and Stoke City are retained from the original focused proof assets; Wrexham, AFC Wimbledon, Bromley, and Crawley Town are refreshed from the corrected lower-division coordinate proof run.

## Residual Risks

- Division/competition-byte writes remain deliberately out of scope until the competition surface is release-proven. The executable mapping is the selector/roster mapping.
- Attributes are deterministic derived PM99 attributes, not imported one-for-one from a third-party ratings database.
- FootballSquads mononyms require explicit aliases for best visible names; the current build patches 16 observed mononyms.
- Lower-division focused selector drift from the first proof run is superseded by the 2026-05-06 dense sweep and corrected four-club proof run.
