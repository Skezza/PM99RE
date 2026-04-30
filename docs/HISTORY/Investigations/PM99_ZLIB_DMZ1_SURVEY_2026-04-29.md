# PM99 Zlib And DMZ1 Survey (2026-04-29)

## Scope

This is a targeted follow-up to the executable byte-forensics finding that
`MANAGPRE.EXE` embeds zlib 1.1.3 inflate/deflate code.

The practical question was:

- Does this reveal a hidden compression layer for players, teams, staff, photos,
  text, or other database content?
- If not, what does the embedded zlib code actually give us?

No proprietary binary or asset payloads were copied into git. The scanner added
in this pass records only offsets, sizes, hashes, type guesses, and counts.

Repeatable probe:

```bash
python3 scripts/probe_pm99_zlib_streams.py <roots> --output .local/<report>.json
```

## Plain-English Conclusion

The zlib discovery does not make player or team discovery easier.

PM99 does contain real inflate/deflate code, but the shipped DBDAT and SIMULDAT
trees we have do not contain normal zlib streams and do not contain PM99's custom
`DMZ1` compressed blocks. The player/team database path remains the already
solved FDI path: archive directory plus XOR `0x61` payload decoding, with the
known record/section structure. Zlib is not the missing roster decoder.

What zlib gives us instead is knowledge of a dormant/general-purpose compressed
file abstraction in the executable. The game can read and write a custom format:

```text
DMZ1
uint32 little-endian decompressed_size
raw deflate payload
```

That is useful if we later find `.DMZ` files, Gremlin editor/exporter artifacts,
or a loader path that accepts compressed replacement assets. It is not currently
useful for extracting players, teams, or the common PM99 data files we already
care about.

## Executable Evidence

Ghidra confirms static zlib strings in `MANAGPRE.EXE`:

- `inflate 1.1.3` at `0x0070d5f9`
- `deflate 1.1.3` at `0x0070c151`
- zlib error strings such as `incorrect data check`

The EXE imports no external `zlib.dll`; the code is statically linked.

The important part is not plain zlib. The PM99 wrapper uses a custom header:

- Around `0x00678052`, the loader compares the first four bytes of a buffer with
  little-endian `0x315a4d44`, i.e. ASCII `DMZ1`.
- Around `0x0067806d`, it reads the next DWORD as the decompressed length.
- Around `0x00678075`, it allocates that decompressed length.
- Around `0x006780aa..0x006780bd`, it calls the inflate wrapper with the source
  pointer advanced past the eight-byte `DMZ1` header.
- The final wrapper argument selects raw deflate (`wbits=-15`), not normal
  RFC1950 zlib framing.

There is also a write/compress path:

- Around `0x006784b9`, the game calls its deflate wrapper.
- Around `0x006784d3`, it writes the `DMZ1` magic.
- It then writes the original uncompressed length and the compressed payload.

So this is real code. It is not just unused copyright text left by a linked
library.

## Data Scan Results

The scanner checks both:

- normal zlib-wrapped streams, including common headers like `78 01`, `78 5e`,
  `78 9c`, and `78 da`;
- PM99 `DMZ1` blocks containing raw deflate.

Strict combined ISO data scan:

```bash
python3 scripts/probe_pm99_zlib_streams.py \
  .local/iso/DbDat .local/iso/Simuldat \
  --output .local/pm99_zlib_dmz1_iso_data_20260429.json
```

Result:

- Files scanned: `224`
- Bytes scanned: `338,494,093`
- Candidate zlib headers: `13,052`
- Valid zlib streams: `0`
- Candidate `DMZ1` headers: `0`
- Valid `DMZ1` streams: `0`

Strict combined pristine fixture scan:

```bash
python3 scripts/probe_pm99_zlib_streams.py \
  work/fixtures/premier-manager-ninety-nine-pristine/DBDAT \
  work/fixtures/premier-manager-ninety-nine-pristine/SIMULDAT \
  --output .local/pm99_zlib_dmz1_pristine_data_20260429.json
```

Result:

- Files scanned: `132`
- Bytes scanned: `242,506,692`
- Candidate zlib headers: `8,522`
- Valid zlib streams: `0`
- Candidate `DMZ1` headers: `0`
- Valid `DMZ1` streams: `0`

Broader legal-header scan on DBDAT, to avoid missing unusual RFC1950 zlib
headers:

```bash
python3 scripts/probe_pm99_zlib_streams.py \
  .local/iso/DbDat \
  --header-mode valid \
  --max-input-size 65536 \
  --output .local/pm99_zlib_streams_iso_dbdat_validhdr_20260429.json
```

Result:

- Files scanned: `106`
- Bytes scanned: `44,771,755`
- Legal zlib-looking candidates: `5,417`
- Valid zlib streams: `0`

The same broader DBDAT scan on the pristine fixture found `1,673` legal
zlib-looking candidates and again `0` valid streams.

EXE scan:

```bash
python3 scripts/probe_pm99_zlib_streams.py \
  .local/iso/MANAGPRE.EXE .local/iso/Dbasepre.exe \
  --all-files \
  --output .local/pm99_zlib_dmz1_iso_exes_20260429.json
```

Result:

- Files scanned: `2`
- Bytes scanned: `4,144,128`
- Candidate zlib headers: `290`
- Valid zlib streams: `0`
- Candidate `DMZ1` headers: `4`
- Valid `DMZ1` streams: `0`

The four EXE `DMZ1` hits are code immediates/string writes for the wrapper
itself, not compressed embedded payloads.

## Follow-up: Does Any Loader Actually Decompress A Shipped File?

Static caller review says no shipped file in the current trees is proven to hit
the decompressor.

The important file-open wrapper is at `0x00677f90`. It reads the whole requested
file into memory, then only attempts decompression in two cases:

- the requested path has a `.DMZ` extension;
- the caller passes flag `0x1000`.

Even then, the loaded buffer still has to start with `DMZ1`. If the magic is not
present, it does not inflate anything.

Direct callers of `0x00677f90` were checked. The ordinary database/config/data
callers use flag `0x10` or nearby non-compress flags for paths such as
`manager.ini`, `sip.ini`, `tactics\partido.dat`, `tactics\predef.%.3u`,
`%s\main.dat`, and dynamic `DMFI`/`DMLT` payload paths. Those do not force
decompression.

The only direct forced-decompression caller found is around `0x0064aa9a`, which
passes `0x1000`. Its call chain sits in match/3D runtime-state territory, near
simulation asset references such as `simuldat\simulpcf6.pal` and
`simuldat\Modelos\PENALTY_GOL.BMP`. That makes it a possible runtime-state or
tooling hook, not a roster/database decoder. Since no `.DMZ` files and no valid
`DMZ1` buffers were found under the shipped DBDAT/SIMULDAT/EXE scans, there is
currently no concrete local file that this path decompresses.

## What This Does Not Provide

It does not decode `JUG98030.FDI`, `EQ98030.FDI`, `ENT98030.FDI`,
`MINIFOTO.PKF`, `TEXTOS.PKF`, or the SIMULDAT PKFs.

It does not reveal hidden player, team, staff, nationality, formation, or photo
records.

It does not explain the FDI record boundaries. Those are already explained by
the FDI directory/section structure, XOR `0x61`, and known player/team record
heuristics.

It does not prove that shipped PM99 assets are compressed with zlib. The data
scan says the opposite for the local ISO and pristine fixture trees.

## What This Does Provide

It gives us a precise format to support if we encounter compressed PM99-era
artifacts:

```text
offset +0:  "DMZ1"
offset +4:  decompressed byte count, little-endian uint32
offset +8:  raw deflate payload
```

It gives us a possible future packaging route. If a specific loader path accepts
`DMZ1` buffers, we could generate game-native compressed replacements instead of
inventing our own wrapper. That still needs a loader-specific proof; the current
DBDAT/SIMULDAT evidence does not show it being used for shipped data.

It explains why naive zlib scans were negative. PM99's real wrapper is not normal
zlib framing; it is raw deflate behind a `DMZ1` header. Once that wrapper was
scanned explicitly, the shipped data still came back empty.

It gives another lead for `DBASEPRE.EXE` or old Gremlin tooling. The write path
means some internal tool or editor/exporter may have produced `.DMZ` resources.
No `.DMZ` files were found under the local ISO, installed game tree, or pristine
fixture:

```bash
find .local/iso .local/premier-manager-ninety-nine \
  work/fixtures/premier-manager-ninety-nine-pristine \
  -type f \( -iname '*.dmz' -o -iname '*.DMZ' \) -printf '%p %s\n'
```

That command produced no matching files.

## Value For SkezMod

Low value for roster work. It does not shorten the path to players, teams,
staff, or photos.

Medium-low value as reverse-engineering infrastructure. We now know one more
native PM99 container/compression format and have a read-only scanner that can
prove whether future candidate files use it.

Higher-value work remains elsewhere:

- SIMULDAT PKF layout/index reconstruction.
- 3D model, texture, palette, and stadium extraction/repacking.
- Continued FDI parser/editor hardening for roster and metadata work.
- Runtime probes only where they answer a specific loader question.

## Commands Run

```bash
python3 -m py_compile scripts/probe_pm99_zlib_streams.py
python3 scripts/probe_pm99_zlib_streams.py \
  work/fixtures/premier-manager-ninety-nine-pristine/DBDAT \
  --output .local/pm99_zlib_streams_pristine_dbdat_20260429.json
python3 scripts/probe_pm99_zlib_streams.py \
  work/fixtures/premier-manager-ninety-nine-pristine/SIMULDAT \
  --output .local/pm99_zlib_streams_pristine_simuldat_20260429.json
python3 scripts/probe_pm99_zlib_streams.py \
  .local/iso/DbDat \
  --output .local/pm99_zlib_streams_iso_dbdat_20260429.json
python3 scripts/probe_pm99_zlib_streams.py \
  .local/iso/Simuldat \
  --output .local/pm99_zlib_streams_iso_simuldat_20260429.json
python3 scripts/probe_pm99_zlib_streams.py \
  .local/iso/DbDat \
  --header-mode valid \
  --max-input-size 65536 \
  --output .local/pm99_zlib_streams_iso_dbdat_validhdr_20260429.json
python3 scripts/probe_pm99_zlib_streams.py \
  work/fixtures/premier-manager-ninety-nine-pristine/DBDAT \
  --header-mode valid \
  --max-input-size 65536 \
  --output .local/pm99_zlib_streams_pristine_dbdat_validhdr_20260429.json
python3 scripts/probe_pm99_zlib_streams.py \
  .local/iso/DbDat .local/iso/Simuldat \
  --output .local/pm99_zlib_dmz1_iso_data_20260429.json
python3 scripts/probe_pm99_zlib_streams.py \
  work/fixtures/premier-manager-ninety-nine-pristine/DBDAT \
  work/fixtures/premier-manager-ninety-nine-pristine/SIMULDAT \
  --output .local/pm99_zlib_dmz1_pristine_data_20260429.json
python3 scripts/probe_pm99_zlib_streams.py \
  .local/iso/MANAGPRE.EXE .local/iso/Dbasepre.exe \
  --all-files \
  --output .local/pm99_zlib_dmz1_iso_exes_20260429.json
python3 scripts/check_repo_boundary.py
```
