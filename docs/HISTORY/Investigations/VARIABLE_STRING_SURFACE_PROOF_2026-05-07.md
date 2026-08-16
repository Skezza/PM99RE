# Variable String Surface Proof

Date: 2026-05-07

## Result

The DB-only variable string writer is now visually proven for a foreign-club
team name through the in-game transfer/search/profile flow.

The current proof does not require an EXE patch. It uses the editor to rebuild
indexed FDI payloads and offsets, then uses `pm99-runner` to launch the edited
game and capture screenshots.

## Evidence Page

Browser evidence:

```text
docs/artifacts/variable_string_surfaces_20260507/index.html
```

Copied source screenshots:

```text
docs/artifacts/variable_string_surfaces_20260507/screens/transfer_market.png
docs/artifacts/variable_string_surfaces_20260507/screens/barcelona_guardiola_search.png
docs/artifacts/variable_string_surfaces_20260507/screens/barcelona_guardiola_profile_offer.png
docs/artifacts/variable_string_surfaces_20260507/screens/barcelona_guardiola_profile_inspect.png
```

Raw runner artifacts:

```text
work/pm99/joe/variable_surfaces_runtime_proof_20260506T221714Z/artifacts/transfer_dashboard_corrected_probe/transfer_dashboard_corrected_probe_20260507T070529Z
work/pm99/joe/variable_surfaces_runtime_proof_20260506T221714Z/artifacts/barcelona_guardiola_transfer_profile/barcelona_guardiola_transfer_profile_20260507T071907Z
```

## What Is Screenshot-Proven

The corrected transfer route reaches the actual `TRANSFER MARKET` screen:

```text
success=True
phase_reached=transfer_market_inspect
final_screen=transfer_market_screen
crash_detected=False
wine_debugger_detected=False
```

The transfer market itself does not show club names. The proof therefore drives
the existing Offers/Search flow:

1. Open Transfers from the Stoke dashboard.
2. Open Offers.
3. Open Search Player By Name.
4. Search `GUARDIOLA`.
5. Open the matched `Josep GUARDIOLA Sala` profile/offer screen.

The final screenshots visibly show:

```text
Josep GUARDIOLA Sala
Barcelona Runtime Club
```

This proves that the edited foreign-club team string is consumed by real in-game
UI, not only by the editor parser.

## DB Reopen Proof

The editor reopens the modified team records with the expected variable strings:

```text
Barcelona Runtime Club
Barcelona Variable Nou
Barcelona Runtime Football Club

Manchester Runtime United
Manchester Variable Park
Manchester Runtime Football Club

Norwich Runtime City
Norwich Variable Road
Norwich Runtime Football Club

Stoke Runtime FC
Stoke Variable Ground
Stoke Runtime Football Club

Torquay Runtime United
Torquay Variable Plainmoor
Torquay Runtime Football Club
```

JSON evidence:

```text
work/pm99/joe/variable_surfaces_runtime_proof_20260506T221714Z/artifacts/variable_string_runtime_edits/runtime_team_search_reopen.json
work/pm99/joe/variable_surfaces_runtime_proof_20260506T221714Z/artifacts/variable_string_runtime_edits/barcelona_team_search_reopen.json
```

Barcelona linked roster extraction resolves the player used in the screenshot
proof:

```text
team_name=Barcelona Runtime Club
full_club_name=Barcelona Runtime Football Club
stadium_name=Barcelona Variable Nou
player=Josep GUARDIOLA Sala
```

JSON evidence:

```text
work/pm99/joe/variable_surfaces_runtime_proof_20260506T221714Z/artifacts/variable_string_runtime_edits/barcelona_runtime_roster_linked.json
```

## Arsenal Manager / Coach Scope

The earlier `Arsene Septicemia` screenshot attempt targeted the wrong coach
record. The corrected Arsenal-linked coach record is:

```text
team=Arsenal
team_offset=101239
coach_record_id=619
coach_offset=8012
resolved_name=Arsene Septicemia
```

The team-to-coach linkage audit is clean:

```text
team_count=536
decoded_link_count=536
unresolved_count=0
inconsistent_count=0
coverage_ratio=1.0
```

JSON evidence:

```text
work/pm99/joe/variable_surfaces_runtime_proof_20260506T221714Z/artifacts/variable_string_runtime_edits/arsenal_manager_rename_offset8012.json
work/pm99/joe/variable_surfaces_runtime_proof_20260506T221714Z/artifacts/variable_string_runtime_edits/arsenal_manager_linkage_after_offset8012_rename.json
work/pm99/joe/variable_surfaces_runtime_proof_20260506T221714Z/artifacts/variable_string_runtime_edits/arsene_septicemia_coach_search_reopen.json
```

This is DB/linkage-proven, not screenshot-proven. A runner route that visually
surfaces the team-linked manager/coach name distinct from the staff/personnel
screen has not been found yet.

## Technical Interpretation

- Team/stadium/full-club variable strings are structured inline EQ strings.
- The writer rebuilds the indexed record payload and lets the FDI index offsets
  move.
- The game accepts the rebuilt payload at runtime.
- Foreign clubs such as Barcelona can be surfaced through player profile/offer
  screens even though they are not playable in the English club selector.
- Manager/coach names are a separate ENT contract. The DB writer and
  team-link audit are clean, but the UI surface for the linked manager name
  still needs route discovery.

## Commands Run

```bash
bash -n scripts/run_stoke_runtime_probe_direct.sh
python3 scripts/check_repo_boundary.py

./scripts/dev_editor.sh python3 -m app.cli team-search "$GAME_ROOT/DBDAT/EQ98030.FDI" Barcelona --json
./scripts/dev_editor.sh python3 -m app.cli team-search "$GAME_ROOT/DBDAT/EQ98030.FDI" Runtime --json
./scripts/dev_editor.sh python3 -m app.cli coach-search "$GAME_ROOT/DBDAT/ENT98030.FDI" Septicemia --include-uncertain --json
./scripts/dev_editor.sh python3 -m app.cli team-roster-linked "$GAME_ROOT/DBDAT/EQ98030.FDI" --player-file "$GAME_ROOT/DBDAT/JUG98030.FDI" --team "Barcelona Runtime Club" --row-limit 30 --json

bash scripts/run_stoke_runtime_probe_direct.sh \
  --run-tag transfer_dashboard_corrected_probe_20260507T070529Z \
  --local-game-dir "$GAME_ROOT" \
  --local-artifact-dir "$RUN_ROOT/artifacts/transfer_dashboard_corrected_probe" \
  --docker-timeout 900 \
  --no-default-steps \
  --step ...

bash scripts/run_stars_player_offer_probe_direct.sh \
  --run-tag barcelona_guardiola_transfer_profile_20260507T071907Z \
  --local-game-dir "$GAME_ROOT" \
  --local-artifact-dir "$RUN_ROOT/artifacts/barcelona_guardiola_transfer_profile" \
  --team-slot 1 \
  --player-search GUARDIOLA \
  --player-label Barcelona_Guardiola \
  --player-row-click 120,166,1 \
  --profile-only
```
