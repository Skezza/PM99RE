# PM99 SIMULDAT PKF Layout Survey (2026-04-30)

## Scope

This follows the zlib/DMZ1 investigation. Zlib did not explain shipped PM99 data,
so the next useful target was SIMULDAT `.PKF`: stadiums, 3D models, grass,
menus, icons, face textures, and miscellaneous match textures.

No payloads were extracted into git. The probe records offsets, sizes, hashes,
type guesses, image dimensions, table locations, and coverage only.

Repeatable probe:

```bash
python3 scripts/probe_simuldat_pkf_layout.py <SIMULDAT root> \
  --output .local/<report>.json
```

## Plain-English Conclusion

This is a real reverse-engineering milestone.

SIMULDAT PKFs are not opaque compressed blobs and they are not zlib. They are
mostly table-indexed asset containers. We can now enumerate most contained
payloads without guessing: BMP textures, GIF textures, RIFF palette files, and
P3D-like binary model/camera/stadium chunks.

This does not reveal players or teams. It gives us the simulation/3D/UI asset
layer: grass, stadium textures, ad boards, menus, icons, 3D face textures, model
data, camera/model chunks, palettes, and similar assets.

## PKF Table Shape

The first record field in every scanned SIMULDAT PKF starts at file offset
`0x107`. Record fields then repeat every `0x26` bytes.

Each record field is:

```text
offset +0: uint32 little-endian payload_offset
offset +4: uint32 little-endian payload_length
offset +8: uint32 little-endian flag, normally 1
offset +12..+37: 26 bytes of descriptor/encoded metadata before the next field
```

Most tables contain up to 32 records. Larger PKFs chain additional tables later
in the file. The probe auto-discovers those continuation tables by looking for
monotonic `payload_offset`, `payload_length`, `flag == 1` records at the same
`0x26` stride.

The 26-byte descriptor area is not decoded yet. It looks like encoded asset
identity/name metadata. It is not needed for read-only enumeration because the
offset and length fields are enough to locate the payloads.

## Scan Results

ISO SIMULDAT scan:

- PKF files scanned: `117`
- Bytes scanned: `293,721,290`
- Tables found: `246`
- Indexed payloads found: `6,335`
- Indexed byte coverage: `99.2343%`
- Payload kinds: `2,499` BMP, `3,538` GIF, `190` P3D-like binary, `107`
  RIFF/PAL, `1` other binary
- Loose asset starts: `6,144` were indexed payload starts, `17` were outside
  selected table coverage
- Orphan single-record asset candidates: `14`

Pristine fixture SIMULDAT scan:

- PKF files scanned: `117`
- Bytes scanned: `226,923,909`
- Tables found: `230`
- Indexed payloads found: `5,408`
- Indexed byte coverage: `99.7930%`
- Payload kinds: `1,572` BMP, `3,538` GIF, `190` P3D-like binary, `107`
  RIFF/PAL, `1` other binary
- Loose asset starts: `5,217` were indexed payload starts, `8` were outside
  selected table coverage
- Orphan single-record asset candidates: `5`

The ISO has `927` more indexed BMP payloads than the pristine fixture. That
difference is almost entirely stadium content.

## Key Files

`Modelos.pkf`:

- Size: `55,794,624` bytes
- Tables: `2`
- Indexed payloads: `64`
- Coverage: `99.8736%`
- Kinds: `14` BMP, `49` P3D-like binary, `1` other binary
- Extra finding: one orphan BMP record candidate at field `0x35252dd`, pointing
  to payload `0x3525788`, length `0x10438`

`Cespedes.pkf`:

- Tables: `3`
- Indexed payloads: `90`
- Kinds: `55` BMP grass textures, `11` RIFF/PAL palettes, `24` P3D-like binary
  chunks
- All indexed BMPs are `256x256x8`

`Texturas/OTROS.pkf`:

- Tables: `2`
- Indexed payloads: `46`
- Kinds: all BMP
- Dimensions include `256x256x8`, `128x64x8`, `128x128x8`, `64x64x8`, and one
  `90x82x8`

`Texturas/CARAS.pkf`:

- Tables: `4`
- Indexed payloads: `108`
- Kinds: all BMP
- All indexed BMPs are `64x64x8`

`Texturas/Varios/A.pkf` and `Texturas/Varios/B.pkf`:

- Tables: `26` each
- Indexed payloads: `804` each
- Kinds: all GIF

`menus.pkf`:

- Tables: `2`
- Indexed payloads: `52`
- Kinds: `45` BMP, `7` GIF

`Iconos.pkf`:

- Tables: `1`
- Indexed payloads: `8`
- Kinds: all BMP

`Estadios/G0.pkf`:

- Tables: `1`
- Indexed payloads: `7`
- Kinds: `5` BMP, `1` P3D-like binary, `1` RIFF/PAL

## Stadium Difference

The stadium PKFs are the largest practical difference between the ISO and the
pristine fixture.

ISO stadium PKFs:

- Files: `96`
- Total bytes: `157,899,953`
- Files exactly `1,053,956` bytes: `2`
- Files exactly `349,814` bytes: `2`
- Entry counts vary from `7` to `45`

Pristine fixture stadium PKFs:

- Files: `96`
- Total bytes: `91,102,572`
- Files exactly `1,053,956` bytes: `79`
- Files exactly `349,814` bytes: `14`
- Entry counts are mostly `17` or `7`

This explains the earlier "many stadium files are exactly 1053956 bytes" smell:
the reduced-looking tree has many repeated-size stadium containers with fewer
indexed BMP payloads. The ISO has much more stadium texture content.

This is not an exciting "fix" by itself. It is still useful evidence because it
proves the PKF parser can quantify exactly what is present or missing.

## What This Provides

This gives us a practical SIMULDAT asset indexer:

- enumerate 3D/UI/stadium assets by file, table, slot, offset, length, hash, and
  type;
- identify BMP/GIF dimensions and bit depth without extracting payloads;
- compare full ISO assets against reduced/min-install assets;
- target exact records for future same-size replacement experiments;
- prepare a real extractor/repacker design that preserves unknown descriptors.

This is also the first concrete route into the 3D engine asset layer. It does
not alter render resolution, but it tells us where the engine's texture/model/
palette inputs live.

## Remaining Work

The next useful steps are:

- decode the 26-byte descriptor/name metadata so extracted assets can receive
  original or near-original names;
- build a safe extractor that writes payloads outside git into `.local` or
  `artifacts/research`;
- build a no-op repacker test that parses and rewrites PKF tables byte-identical;
- test same-size texture replacement first, before attempting changed-length
  repacks;
- map P3D-like binary chunks to model/camera/stadium semantics.

## Commands Run

```bash
python3 -m py_compile scripts/probe_simuldat_pkf_layout.py
python3 scripts/probe_simuldat_pkf_layout.py \
  .local/iso/Simuldat \
  --output .local/pm99_simuldat_pkf_layout_iso_20260430.json
python3 scripts/probe_simuldat_pkf_layout.py \
  work/fixtures/premier-manager-ninety-nine-pristine/SIMULDAT \
  --output .local/pm99_simuldat_pkf_layout_pristine_20260430.json
```
