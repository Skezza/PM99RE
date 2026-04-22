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

## Search-by-name Row Follow-up
The remaining search-row surface was closed separately after tracing the row subclass painter.

Key finding:

- `FUN_00474870` already includes team names in the search key, but it only stores player pointers into result rows.
- The concrete row painter is `FUN_0044F590`, reached from the search-row vtable. It reads `row + 0x54` as the player pointer and paints name, stars, numeric attributes, value/wage, and two small numeric cells.
- The original row painter never calls `FUN_004B5C20` or reads player `+0x18`, so the club name was not rendered even when the lookup fallback was correct.

Patch added in `pm99-skezmod-patcher`:

- patch site: `0x0044FA54` inside `FUN_0044F590`
- behavior: replace the wage/trailing numeric cells with one club-name cell
- lookup: read player team id from `[player + 0x18]`, call `FUN_004B5C20`, then draw `[team + 0x04]`
- fallback coverage: hidden Valderrama team id `4705` resolves to `Stars` through the existing fallback record

Runner validation:

- `valderrama_search_teamcell_v2_20260422T065304Z`: search row shows `Stars`
- `beckham_search_teamcell_v2_20260422T065601Z`: search row shows `Manchester Utd.`
- proof HTML: `artifacts/valderrama_offer_probe/search_teamcell_v2_proof.html`
