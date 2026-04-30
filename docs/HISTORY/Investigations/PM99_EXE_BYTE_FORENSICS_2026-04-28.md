# PM99 EXE Byte Forensics (2026-04-28)

## Scope

Fresh executable-only investigation, separate from the DirectDraw/windowed-mode
work. The goal was to look for other transferable fixes or reverse-engineering
leads by treating `MANAGPRE.EXE` as a byte-addressed Windows PE program.

Reference binary:

- `.local/iso/MANAGPRE.original.exe`
- SHA-256: `6e2fccce2a8a8e95537904b5fb76856aad87a8832345461d3cae2ca526eb6eed`
- Size: `3,442,176` bytes
- PE timestamp: `1999-02-22T20:59:56Z`
- Image base: `0x00400000`
- Entry point: `0x006BEFD0`

Repeatable probe:

```bash
python3 scripts/probe_pm99_exe_forensics.py \
  --reference .local/iso/MANAGPRE.original.exe \
  --compare .local/iso/managpre.nocd_patched.exe \
  --compare .local/premier-manager-ninety-nine/MANAGPRE.EXE \
  --compare work/fixtures/premier-manager-ninety-nine-pristine/MANAGPRE.EXE \
  --compact \
  --output .local/pm99_exe_forensics_20260428.json
```

The probe is read-only and writes only metadata. It does not copy or patch game
binaries.

## Plain-English Findings

1. The EXE is boring in the good forensic sense. It is not packed, has no
   appended overlay, and every byte belongs to the PE headers or one of five PE
   sections. There is no secret extra payload after the last section.

2. The local NO-CD patch is still exactly the known eight-byte patch. It changes
   six bytes in `.text` and two bytes in `.data`. It does not contain a bundled
   graphics, DirectDraw, Windows XP, Vista, Windows 7, Wine, or resolution fix.

3. The more interesting non-graphics code is the old install/CD/registry layer.
   PM99 actively reads old Gremlin registry keys, asks for the `Dir` value, scans
   logical drives, checks for CD-ROM drives, checks `DISK.ID`, and uses loader
   event names from the old PCF5/PM99 launcher chain.

4. The game has a real old-style disk-free-space check. It calls
   `GetDiskFreeSpaceA` and contains both the save-game "not enough free space"
   message and the installer-era "200 MB free on C drive" warning. The code does
   not obviously do a simple signed 32-bit multiply; it zero-extends the API
   outputs and uses x87 floating-point multiplication. So this is a real lead,
   but not yet a proven modern bug.

5. The EXE embeds static zlib 1.1.3 inflate/deflate code. It imports no zlib DLL.
   That matters because the SIMULDAT/PKF/resource path probably passes through
   an internal decompressor we can reverse. This is a better research direction
   than more blind resolution patching.

6. `.PKF` archive resolution is active code, not dead text. The `.PKF` suffix is
   referenced in code around `0x00693194`, inside a loader path that tries to
   resolve resources by appending/searching archive names.

7. No obvious hidden command-line switch surfaced from this pass. The binary
   imports `_acmdln` and has generic argument/path parsing code, but the string
   survey did not reveal clear `/window`, `/debug`, `-safe`, or similar user
   switches.

## PE Byte Map

All bytes are mapped.

| Section | VA range | Raw range | Entropy | Notes |
| --- | ---: | ---: | ---: | --- |
| `.text` | `0x00401000..0x006E5200` | `0x000400..0x2E4600` | `6.5494` | Code, execute/read |
| `.rdata` | `0x006E6000..0x0072BC00` | `0x2E4600..0x32A200` | `5.0819` | Imports, constants, static library text |
| `.data` | `0x0072C000..0x007BDE68` | `0x32A200..0x346C00` | `4.8767` | Writable globals and most game strings |
| `.tls` | `0x007BE000..0x007BE200` | `0x346C00..0x346E00` | `0.0941` | Mostly zero |
| `.rsrc` | `0x007BF000..0x007C0800` | `0x346E00..0x348600` | `4.0993` | PE resources |

There are no raw gaps or overlay bytes. Coverage is `100.0%`.

Largest useful slack/cave-like areas found by the probe:

- `.text` zero run at file offset `0x2E4492`, length `366`.
- `.rdata` zero run at file offset `0x32A01E`, length `482`.
- `.data` zero run at file offset `0x32D33A`, length `1534`.

These are useful for research patches, but not by themselves product fixes.

## Variant Diffs

Original vs local NO-CD:

- `8` changed bytes in `3` regions.
- `.text`:
  - `0x00408CF6`: `8A 44 24 10` -> `66 B8 2E 00`
  - `0x00408D19`: `75 12` -> `90 90`
- `.data`:
  - file `0x32A97D` / VA `0x0072C77D`: `3A 5C` -> `5C 00`

Original vs fixture `work/fixtures/premier-manager-ninety-nine-pristine`:

- `24` changed bytes in `11` regions.
- The executable-body changes are the same NO-CD eight-byte patch.
- The remaining differences are PE-header/resource-table bookkeeping bytes.

Original vs installed `.local/premier-manager-ninety-nine/MANAGPRE.EXE`:

- `428` changed bytes in `60` regions.
- This is not a mysterious third-party compatibility patch. Besides the NO-CD
  bytes, it contains previous local research patch code and cave payloads,
  including the known SkezMod/Valderrama/Stars-era work.

## Active Legacy Install/CD Code

The binary imports and actively references:

- `RegOpenKeyExA`, `RegQueryValueExA`, `RegCloseKey`
- `GetLogicalDriveStringsA`, `GetDriveTypeA`
- `CreateFileA`, `FindFirstFileA`, `FindNextFileA`
- `GetDiskFreeSpaceA`
- `OpenEventA`, `CreateProcessA`, `SetCurrentDirectoryA`

Registry function around `0x00408E80`:

- Selects old Gremlin registry keys.
- Opens under `HKEY_LOCAL_MACHINE` (`0x80000002`).
- Queries value name `Dir`.
- Registry key strings include:
  - `Software\Gremlin\PC Francia`
  - `Software\Gremlin\PC F...`
  - `Software\Gremlin\PC Calcio 6.0`
  - `Software\Gremlin\Premier Manager 99`

CD-drive scan around `0x00408CD0`:

- Calls `GetLogicalDriveStringsA` at `0x00408CEC`.
- Calls `GetDriveTypeA`.
- Compares the result with `5`, i.e. `DRIVE_CDROM`.
- Calls a `DISK.ID`-related check when a CD-ROM drive is found.
- The NO-CD patch at `0x00408D19` bypasses this branch.

Launcher/event setup around `0x00409200`:

- Opens `PCF5_Loader_Event1`.
- Opens `PCF5_Loader_Event2`.
- This is old launcher handshaking, not graphics code.

Patch implication:

- A "portable install" patch is plausible if we ever see a machine where PM99
  fails because registry `Dir`, old launcher events, or drive enumeration are
  absent/wrong.
- The normal NO-CD patch already handles the most obvious CD-ROM branch.

## Disk-Free-Space Code

`GetDiskFreeSpaceA` is called at `0x004C2951`.

The function passes a null root path, so it checks the current drive. On success,
it multiplies:

- sectors per cluster
- bytes per sector
- free clusters

The implementation zero-extends each 32-bit value into a 64-bit stack slot and
uses x87 `fild`/`fmulp`, so the obvious "signed 32-bit multiply overflow" bug is
not present at that exact site.

Patch implication:

- If a modern system ever shows a false "not enough free space" save/install
  warning, this is the site to instrument or patch.
- Today it is only a lead, not a proven bug.

## Archive/Compression Lead

The string survey found static zlib 1.1.3 text:

- `deflate 1.1.3 Copyright 1995-1998 Jean-loup Gailly`
- `inflate 1.1.3 Copyright 1995-1998 Mark Adler`
- `incorrect data check`
- `incompatible version`
- `buffer error`
- `stream error`

There is no zlib DLL import, so this is statically linked code.

The `.PKF` suffix at `0x00746448` is referenced by active code around
`0x00693194`. That path appends/searches `.PKF` names while resolving assets.

Patch/research implication:

- The best next non-graphics investigation is the PKF/archive loader and its
  zlib call chain.
- If we understand this path, we can build a proper SIMULDAT PKF extractor or
  replacement workflow instead of treating stadium/model/texture archives as
  opaque blobs.

## Not Found

This pass did not find:

- an appended hidden payload,
- a packed/encrypted EXE body,
- a bundled compatibility wrapper,
- an obvious hidden window/resolution command-line flag,
- evidence that the NO-CD EXE itself patched DirectDraw or Windows compatibility.

## Commands Run

```bash
python3 -m py_compile scripts/probe_pm99_exe_forensics.py
python3 scripts/probe_pm99_exe_forensics.py \
  --reference .local/iso/MANAGPRE.original.exe \
  --compare .local/iso/managpre.nocd_patched.exe \
  --compare .local/premier-manager-ninety-nine/MANAGPRE.EXE \
  --compare work/fixtures/premier-manager-ninety-nine-pristine/MANAGPRE.EXE \
  --compact \
  --output .local/pm99_exe_forensics_20260428.json
python3 scripts/check_repo_boundary.py
```
