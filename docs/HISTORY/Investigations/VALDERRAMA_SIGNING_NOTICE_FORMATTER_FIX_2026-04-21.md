# Valderrama Signing Notice Formatter Fix - 2026-04-21

## Goal
Close the remaining Valderrama signing-message bug where the game rendered:

`You have signed Valderrama of .`

The target output is:

`You have signed Valderrama of Stars.`

## Key Finding
The first suspected producer was `FUN_004b2fc0` around `0x004B31A8`, which constructs event `0x453` and pushes a null `{S3}` argument. A proof-only overlay forced that producer's `{S3}` to `Stars`, but the live rendered message still remained `of .`.

That proved `0x004B31A8` was not sufficient for the observed UI output.

The effective fix is formatter-local in `FUN_00499d00`, at the `{S3}` token branch:

- patch site: `0x00499DA1`
- condition: event `{S3}` pointer is null
- guard: event player id at `[event + 0x08]` equals Valderrama's indexed player record id `20864` (`0x5180`)
- replacement: use the existing cave string pointer for `Stars` at `0x006E519A`

This keeps the fallback narrow: it does not globally rewrite all `{S3}` tokens or all signing messages.

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
