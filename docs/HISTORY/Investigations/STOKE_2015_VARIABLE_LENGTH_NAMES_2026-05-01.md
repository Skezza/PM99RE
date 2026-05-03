# Stoke 2015 Variable-Length Names Closeout

Date: 2026-05-01

## Final Result

The role-preserved variable-length-name milestone is game-safe.

The earlier DB-only attempts failed because they shortened the embedded name
length bytes but left the old fixed padding before the role/metadata bytes.
MANAGPRE followed the shortened name cursor, parsed padding as metadata, and
failed when Squad Management was opened.

The passing approach is still DB-only and does not patch `MANAGPRE.EXE`:

- physically compact the compact `dd6360` linked-player name prefix;
- move the role/metadata block immediately after the natural variable-length name;
- append the removed fixed padding at the payload tail;
- preserve the certified 80-byte linked-player payload length; and
- repoint EQ roster rows so every original Stoke slot keeps its coarse role.

This proves true variable-length player names are feasible for the editor when
the writer preserves the native cursor alignment and runtime-safe container
length.

## Delivered Candidate

Game root:

```text
.local/stoke_2015_role_preserved_physical_variable_names_20260501T182402Z
```

Artifact root:

```text
.local/stoke_2015_role_preserved_physical_variable_names_20260501T182402Z/artifacts/role_preserved_physical_variable_names
```

Visual proof page:

```text
.local/stoke_2015_role_preserved_physical_variable_names_20260501T182402Z/artifacts/role_preserved_physical_variable_names/stoke_2015_role_preserved_variable_name_proof.html
```

Runner tag:

```text
stoke_2015_role_preserved_physical_variable_names_20260501T182602Z_profiles20
```

Runtime result:

```text
success=True
profile_capture_ok=True
profile_capture_count=20
profile_capture_expected=20
profile_player_screen_count=20
crash_detected=False
wine_debugger_detected=False
final_screen=squad_management_screen
```

Static result:

```text
validate-database all_valid=True
team-roster-runtime-audit ok=True
team-roster-runtime-audit row_count=20
team-roster-runtime-audit issue_count=0
team-roster-runtime-audit warning_count=0
```

## Role-Preserved Assignment

| Slot | Original slot | Role | 2015 replacement |
|---:|---|---|---|
| 1 | Bryan SMALL | D | Phil BARDSLEY |
| 2 | Peter THORNE | F | Marko ARNAUTOVIC |
| 3 | Larus SIGURDSSON | D | Erik PIETERS |
| 4 | Ray WALLACE | D | Marc MUNIESA |
| 5 | Carl MUGGLETON | G | Jack BUTLAND |
| 6 | Richard FORSYTH | M | Glenn WHELAN |
| 7 | Kevin KEEN | M | Stephen IRELAND |
| 8 | Simon STURRIDGE | F | Joselu MATO |
| 9 | Phillip ROBINSON | M | Ibrahim AFELLAY |
| 10 | David Charles OLDFIELD | M | Marco VAN GINKEL |
| 11 | Kyle LIGHTBOURNE | F | Mame DIOUF |
| 12 | Chris SHORT | D | Glen JOHNSON |
| 13 | Graham KAVANAGH | M | Charlie ADAM |
| 14 | Clive CLARKE | D | Marc WILSON |
| 15 | Stuart FRASER | G | Shay GIVEN |
| 16 | Stephen John WOODS | D | Ryan SHAWCROSS |
| 17 | Neil David McKENZIE | M | Giannelli IMBULA |
| 18 | Dean Anthony CROWE | F | Jonathan WALTERS |
| 19 | Ben PETTY | D | Geoff CAMERON |
| 20 | Robert HEATH | M | Steve SIDWELL |

## Implementation

Builder:

```text
scripts/apply_stoke_2015_role_preserved_physical_variable_names_patch.py
```

Proof HTML builder:

```text
scripts/build_stoke_2015_variable_name_proof_html.py
```

Runner OCR robustness fix:

```text
upstream/pm99-runner/scripts/pm99_runner/screen_cv.py
upstream/pm99-runner/tests/test_pm99_runner_scripts.py
```

The OCR fix does not change the DB/game result. It prevents a valid player
profile screenshot from failing the runner gate when several Tesseract crops
timeout and only noisy profile indicators remain.

## Key Technical Finding

For the compact linked-player proof rows, changing only the name length bytes is
not enough. The native reader expects the role/metadata bytes at the cursor it
derives from the encoded name lengths.

The passing payload shape is:

```text
prefix/header
variable surname/full-name block
role/metadata block
remaining payload data
moved padding at tail
```

Payload length remains 80 bytes for every patched row. The old fixed name end
was 49; the final role-preserved variable rows use shorter per-player name ends
and move 8-18 bytes of padding out of the parse path.

## Commands Run

```bash
python3 -m py_compile scripts/apply_stoke_2015_role_preserved_physical_variable_names_patch.py scripts/apply_stoke_2015_current_order_physical_variable_names_patch.py
python3 scripts/apply_stoke_2015_role_preserved_physical_variable_names_patch.py
./scripts/dev_editor.sh python3 -m app.cli validate-database --players "$OUT/DBDAT/JUG98030.FDI" --teams "$OUT/DBDAT/EQ98030.FDI" --coaches "$OUT/DBDAT/ENT98030.FDI" --json
./scripts/dev_editor.sh python3 -m app.cli team-roster-linked "$OUT/DBDAT/EQ98030.FDI" --player-file "$OUT/DBDAT/JUG98030.FDI" --team Stoke --json
./scripts/dev_editor.sh python3 -m app.cli team-roster-runtime-audit "$OUT/DBDAT/EQ98030.FDI" --player-file "$OUT/DBDAT/JUG98030.FDI" --team Stoke --json
./scripts/run_stoke_profile_capture_with_dbdat_overrides.sh --dbdat-dir "$OUT/DBDAT" --run-tag stoke_2015_role_preserved_physical_variable_names_20260501T182602Z_profiles20 --profile-count 20 --override-ent --skip-setup --skip-build --skip-prepare --cleanup-on-failure
python3 scripts/build_stoke_2015_variable_name_proof_html.py --artifact-dir "$ART" --runner-artifacts-dir "$RUN" --output-html "$ART/stoke_2015_role_preserved_variable_name_proof.html"
python3 -m pytest upstream/pm99-runner/tests/test_pm99_runner_scripts.py -k 'screen_cv_classify_normalized_texts_detects_timeout_truncated_player_profile_screen or screen_cv_classify_normalized_texts_detects_ocr_noisy_player_profile_screen or screen_cv_classify_normalized_texts_detects_player_profile_screen' -q
python3 scripts/check_repo_boundary.py
```

## Sources

- FootballSquads 2015-16 Stoke squad bio data: `https://www.footballsquads.co.uk/eng/2015-2016/faprem/stoke.htm`
- Wikipedia 2015-16 Stoke season squad statistics: `https://en.wikipedia.org/wiki/2015%E2%80%9316_Stoke_City_F.C._season`
- ESPN 2015-16 Stoke Premier League squad statistics: `https://www.espn.com/soccer/team/squad/_/id/336/league/ENG.1/season/2015`
