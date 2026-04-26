# Valderrama Signing Notice Formatter Fix - 2026-04-21

## Goal
Close the remaining Valderrama signing-message bug where the game rendered:

`You have signed Valderrama of .`

The target output is:

`You have signed Valderrama of Stars.`

## Key Finding
The first suspected producer was `FUN_004b2fc0` around `0x004B31A8`, which constructs event `0x453` and pushes a null `{S3}` argument. A proof-only overlay forced that producer's `{S3}` to `Stars`, but the live rendered message still remained `of .`.

That proved `0x004B31A8` was not sufficient for the observed UI output.

The initial effective fix was formatter-local in `FUN_00499d00`, at the `{S3}` token branch, but the first implementation was too narrow because it guarded only on Valderrama's indexed player record id `20864` (`0x5180`).

The scalable fix now keeps the same patch site, `0x00499DA1`, but changes the fallback rule:

- if the supplied `{S3}` pointer is non-null, preserve original formatting behavior
- if `{S3}` is null, resolve `[ebp+0x0c]` through the central team lookup `FUN_004B5C20`
- use `[team_record+0x04]` from that lookup as the formatter argument
- therefore `team_id 4705 -> Stars` and `team_id 4706 -> Free players` are covered by the shared fallback table, without player-id hardcoding

This keeps the fallback narrow: it does not globally rewrite all `{S3}` tokens, but it does scale to all events whose null club suffix still carries a fallback-covered team id.

## Runner Validation
Validation run:

- `valderrama_formatter_s3_validate_20260421T073000Z`

Local artifact root:

- `artifacts/valderrama_offer_probe/valderrama_formatter_s3_validate_20260421T073000Z/`

Proof HTML:

- `upstream/pm99-runner/docs/artifacts/pm99_runner/valderrama_formatter_s3_proof.html`

Live process memory evidence showed multiple decoded strings containing:

`You have signed Valderrama of Stars.`

Representative addresses:

- `0x040ee7c0`
- `0x040ee800`
- `0x04119804`

The runner also read back patched process bytes:

- formatter site `0x00499DA1`: `e9aba42400909090909090e9b1000000`
- formatter stage `0x006E4251`: `8b451885c07479e9055cdbffcccccc8b`

## Commits
- `pm99-research`: `34489be Fix Valderrama signing notice Stars fallback`
- `pm99-runner`: `548f053 Add native memory probe steps`

## Local Manual Test
A local patched copy was created at:

- `work/pm99/local-test/valderrama_formatter_s3_20260421/`

The game launched locally from that copy using the default Wine prefix. The dedicated test Wine prefix was not suitable because it lacked `MFC42.DLL`.

## Search Hover/Status Strip Closure
The remaining search-by-name gap was the hover/status strip above `Cancel`, not the visible result-row columns. A rejected experiment rendered club text by replacing a result-row cell; that was reverted because it changed the row layout and fonts.

Correct target:

- `FUN_00474B20` stores the hovered row player pointer at container `+0x2734` and invalidates the status widget at `container+0x26e0`.
- status widget vtable `0x006EA428`, draw entry `0x006EA534 -> 0x00405F30`.
- `FUN_00405F30` draws the bottom hover/status strip. For normal players it calls `FUN_004B5C20` and draws `[team_record+0x04]`. For Valderrama it hits a special `0x26AC` branch at `0x00406116` and uses `[player+0x10]`, which is blank, bypassing the central fallback.

Patch added in `pm99-skezmod-patcher`:

- site: `0x00406116` in `FUN_00405F30`
- cave: `0x006E5145` inside the existing fallback bundle gap
- behavior: preserve non-empty special-club text; for blank/null `0x26AC` text, use existing `Stars` string at `0x006E519A`; normal players continue through the original lookup path.

Runner validation:

- broken clean control: `artifacts/valderrama_offer_probe/valderrama_hover_rightmsg_20260422T200650Z/screens/46_hover_result_row.png` shows `Carlos VALDERRAMA` with blank club cell.
- fixed Valderrama proof: `artifacts/valderrama_offer_probe/valderrama_hover_fix_20260422T201330Z/screens/46_hover_result_row.png` shows `Carlos VALDERRAMA` and `Stars`.
- Beckham regression control: `artifacts/valderrama_offer_probe/beckham_hover_fix_control_20260422T201616Z/screens/43_hover_result_row.png` still shows `David Robert BECKHAM` and `Manchester Utd.`.


## Lalas / All-Stars Scale Follow-up - 2026-04-22

Alexi Lalas proved that two more surfaces were still independent of the central lookup:

- Search hover/status strip: `FUN_00405F30` at `0x00406116` branches on special marker `0x26AC` and uses `[player+0x10]` directly. Patch cave `0x006E5145` preserves non-empty text and backfills blank/null text with `Stars`.
- Player-record renderer: the profile path around `0x0043F1EF` has the same `0x26AC` special branch and uses `[player+0x10]` at `0x0043F20F`. Patch cave `0x006E51E1` preserves non-empty text and backfills blank/null text with `Stars`.

Validation evidence:

- Search hover Valderrama proof: `artifacts/valderrama_offer_probe/valderrama_hover_fix_20260422T201330Z/screens/46_hover_result_row.png` shows `Carlos VALDERRAMA` / `Stars`.
- Search hover Beckham control: `artifacts/valderrama_offer_probe/beckham_hover_fix_control_20260422T201616Z/screens/43_hover_result_row.png` preserves `David Robert BECKHAM` / `Manchester Utd.`.
- Lalas player-record proof: `artifacts/valderrama_offer_probe/lalas_profile_special_patch_20260422T231639Z/screens/48_inspect_lalas_profile.png` shows Alexi Lalas with `Stars` in the player record.

A long Lalas signing ticker run (`lalas_profile_patch_ticker_20260422T232036Z`) advanced through many dashboard cycles but did not produce an OCR match for `lalas` and `stars` before timeout. Treat that as inconclusive route/signing evidence, not as a formatter-patch failure.

## All-Stars Formatter Scale Follow-up - 2026-04-25

The earlier formatter fallback was too narrow when described as Valderrama-specific. The scalable condition observed in the signing formatter is not the player name; it is the null `{S3}` suffix paired with a zero event-team argument on the special Stars signing feed.

Updated patch shape in `upstream/pm99-skezmod-patcher/skezmod.py`:

- site remains `0x00499DA1` in `FUN_00499D00` for `{S3}` formatting.
- non-null `{S3}` still jumps back to the original formatter push path.
- null `{S3}` with nonzero `[ebp+0x0c]` now resolves through `FUN_004B5C20` in support caves at `0x006E4DF2` and `0x006E4E22`.
- null `{S3}` with zero `[ebp+0x0c]` now resolves to the shared `Stars` string at `0x006E519A`.
- the failed player-lookup cave experiment at `0x006E4B01` was rejected because that address is occupied in the known-good combinedfix binary (`52 ff 36 68 53 04 00 00 8b cd e9 ad e6 dc ff`) and overwriting it caused the runner to route into `PREDEFINED CONFIGURATIONS`.

Runner evidence and cave-safety findings:

- `valderrama_zero_team_s3_20260425T121051Z`: clean full-game validation reached `PREDEFINED CONFIGURATIONS`; invalid validation source, not accepted as proof.
- `valderrama_zero_team_combinedfix_20260425T122105Z`: failed at launch because a compact overlay was incorrectly supplied as a full game dir; invalid run.
- `valderrama_zero_team_overlay_20260425T122542Z`: correct compact-overlay launch reached the real dashboard and preserved player-record `Stars`, but the low default offer terms did not reproduce the signing message surface.
- `valderrama_zero_team_terms_20260425T124438Z`: restored the old accepted-offer terms (`9` offer increments, `14` wage increments), but the default final-inspection branch collided with the PM Shield modal and advanced past the Sunday message surface.
- `valderrama_zero_team_nofinal_20260425T125702Z`: removed final-inspection detour and reached the real dashboard; selected left-rail message was a different item (`Vieira`/TV rights), so it is route evidence but not signing-message proof.
- `valderrama_zero_team_allicons_20260425T130753Z`: probed ten visible left-rail icon positions after the accepted-offer route; no selected message showed the signing item, so the runner route still needs a better deterministic signing-message capture point.
- `valderrama_zero_team_cont1_auto1_lowdisk_20260425T204247Z`: accepted terms (`9` offer increments, `14` wage increments), avoided the bad hard-coded prefinal line-up click path, used one fixed advance to enter the match, then used auto-continue to complete half-time/full-time/championship/start-season gates. This reproduced the same Sunday PM Shield left-rail signing ticker surface that previously rendered `...rama of Unknown club.` and now shows `...ama of Stars.` in `screens/130_leftrail_02_inspect_07.png`.

Current conclusion:

- The patcher implementation is lean again and no longer writes into the occupied `0x006E4B01` cave.
- Static formatter logic now scales to all zero-team Stars signing notices instead of checking Valderrama's id.
- Runtime proof for player record/search hover remains valid from earlier runs.
- Runtime proof for the exact left-rail signing-message surface is now closed by `valderrama_zero_team_cont1_auto1_lowdisk_20260425T204247Z/screens/130_leftrail_02_inspect_07.png`.

## All 10 Stars Signing Validation - 2026-04-26

The scalable formatter fallback was validated against all ten parser-backed Stars players by signing each player individually to Manchester Utd through the PM99 runner.

Proof page:

- `artifacts/stars_sign_all_to_manutd/index.html`

Run artifacts:

- `stars_sign_vazquez_manutd_20260426T113806Z`
- `stars_sign_rafa_paz_manutd_20260426T113806Z`
- `stars_sign_marcio_santos_manutd_20260426T114510Z`
- `stars_sign_luis_hernandez_manutd_20260426T114510Z`
- `stars_sign_carlos_munoz_cobos_manutd_20260426T115327Z`
- `stars_sign_leonel_alvarez_manutd_20260426T115327Z`
- `stars_sign_valderrama_manutd_20260426T120054Z`
- `stars_sign_etcheverry_manutd_20260426T120054Z`
- `stars_sign_sonora_manutd_20260426T120821Z`
- `stars_sign_lalas_manutd_20260426T120821Z`

All ten wrapper runs returned `run_status=0`, `sync_status=0`, and `cleanup_status=0`.

Selection note:

- Carlos Muñoz Cobos is not reliably reached through broad `CARLOS` search. The deterministic route is `COBOS`, second row.

Soñora note:

- Diego Soñora submitted and advanced successfully, then stopped on the expected "initial line-up is not correct" dashboard warning loop after the squad changed. The wrapper still returned `run_status=0`, and the run includes the profile and post-submit proof screenshots.
