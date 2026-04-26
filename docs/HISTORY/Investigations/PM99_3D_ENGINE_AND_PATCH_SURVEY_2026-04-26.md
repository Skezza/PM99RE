# PM99 3D Engine And Patch Survey (2026-04-26)

## Scope

This is a forensic pass over the local PM99 game/ISO copy and the already
imported `MANAGPRE.EXE` Ghidra database. No proprietary binaries or assets were
copied into git. All binary/asset reads came from `.local/`.

Reference binary unless stated otherwise:

- `.local/iso/MANAGPRE.EXE`
- SHA-1 prefix: `33f38b3c5867`
- PE32 GUI i386, image base `0x00400000`
- Sections: `.text`, `.rdata`, `.data`, `.tls`, `.rsrc`

Repeatable probe added:

```bash
python3 scripts/probe_pm99_3d_assets.py --game-root .local/iso
```

The probe is read-only. It scans the executable and SIMULDAT tree for renderer
strings, embedded bitmap/palette chunks, file counts, hashes, and dimensions.

## Plain-English Conclusions

1. PM99 has a real match-view 3D subsystem. It is not just static match
   screens. The executable names a `3D ENGINE`, loads `.p3d` model files,
   references stadium models and palettes, and exposes graphics options for
   gouraud shading, textures, bilinear filtering, shadows, grass, players,
   stadium quality, fog, cameras, and match duration.

2. The visible graphics API is DirectDraw, not Direct3D. The executable imports
   DirectInput normally, dynamically loads `ddraw.dll`, resolves
   `DirectDrawCreate` and `DirectDrawEnumerateA`, and contains no `Direct3D`,
   `d3d`, OpenGL, or Glide strings. That means the match renderer is very
   likely a custom/software 3D pipeline presented through DirectDraw surfaces,
   possibly with hardware-ish DirectDraw surface paths, not a normal Direct3D
   renderer we can cheaply upscale.

3. The main shell resolution is hardcoded to `640x480`, not `800x600`.
   `FUN_006765f0`/code around `0x0067666f` writes `0x280`, and
   `0x00676679` writes `0x1e0`, into global width/height state. The UI asset
   coordinates and the shell DIB/palette path are built around that.

4. The black-framebuffer/XP-era fullscreen problem is probably in the exclusive
   DirectDraw/palette/display-mode path. The safe mitigation is to force
   windowed mode. True native high resolution is a much bigger job because it
   touches coordinates, surfaces, presentation, and likely match-engine camera
   assumptions.

5. SIMULDAT is more promising than display scaling. The game assets are real,
   large, and partly uncompressed inside PKF blobs. We can likely extract and
   replace textures/models/stadium resources once the SIMULDAT PKF layout is
   decoded.

6. The installed game's stadium PKFs differ heavily from the ISO stadium PKFs:
   89 of 96 common stadium archives differ, and many installed stadium files are
   normalized to `1053956` bytes. That is a concrete experiment: the install may
   have lower-detail stadium assets than the ISO, or the installer may have
   copied a reduced set. Testing ISO stadium overlays is higher value than
   another fullscreen-scaling wrapper attempt.

## Executable Renderer Evidence

Ghidra/local PE scan confirms:

- `DirectDrawCreate` at `0x00744fc4`, referenced at `0x006762a6`.
- `DirectDrawEnumerateA` at `0x00744fd8`, referenced at `0x0067628f`.
- `ddraw.dll` at `0x00744ff0`, referenced at `0x00676264`.
- No `Direct3D`, `d3d`, OpenGL, or Glide strings in the executable.
- Imported graphics/display functions include `StretchDIBits`,
  `CreatePalette`, `SetSystemPaletteUse`, `GetDeviceCaps`, and
  `ChangeDisplaySettingsA`.

The shell/window setup writes fixed dimensions:

- `0x0067666f`: stores `0x280` / `640`.
- `0x00676679`: stores `0x1e0` / `480`.
- Global width/height are `0x00744d98` and `0x00744d9c`.

DirectDraw startup and mode-switch code:

- `0x00676250`: dynamic DirectDraw bootstrap.
- `0x00676a40`: updates global width/height and color-depth state.
- `0x00676c00`: fullscreen/windowed switch. The fullscreen path uses DirectDraw
  vtable calls equivalent to cooperative-level/display-mode work. The windowed
  path avoids the risky display-mode switch.

Config read/write:

- `manager.ini` literal at `0x0072c9f4`.
- `FULL SCREEN` key at `0x006f7730`.
- `SCREEN POSITION` key at `0x006f7740`.
- `MUSIC`, `SOUND`, `TRANSITIONS`, and `PIS LEVEL` are parsed nearby.
- Parser function starts around `0x0040b5a0`; writer starts around
  `0x0040b9e0`.
- If `manager.ini` is missing, the binary defaults `FULL SCREEN` to `ON`
  around `0x0040b894`.

Patch implication:

- A compatibility patch can force or default `FULL SCREEN: OFF`.
- A stronger binary patch can ignore the parsed fullscreen value and always
  clear `0x0079e69c`/`0x0079e6b8`.
- This is a realistic bug fix. It avoids the fragile DirectDraw fullscreen
  path instead of trying to make old exclusive 8-bit/16-bit palette behavior
  work everywhere.

## 3D Engine Evidence

The string `3D ENGINE` exists at `0x0072dc54`. More importantly, the match
options and asset strings prove a 3D subsystem:

- `GOURAUD SHADING` at `0x0073a16c`
- `TEXTURES` at `0x0073a17c`
- `BILINEAR FILTER` at `0x0073a188`
- `HARDWARE OPTIONS` at `0x0073a198`
- `DURATION OF MATCH` at `0x0073a2a4`
- `CAMERAS` at `0x0073a388`
- `RESOLUTION` at `0x0073a4cc`
- `GRAPHICS QUALITY` at `0x0073a410`
- `PLAYERS`, `BACK NUMBERS`, `ANIMATIONS`, `SHADOWS`, `GRASS`
- Runtime/localized states for `FOG: ON/OFF`, `STADIUM: LOW/HIGH`,
  `SHADOWS: LOW/HIGH`, `PLAYERS: LOW/HIGH`, `GRASS: ON/OFF`

UI/control references:

- `HARDWARE OPTIONS`: `0x005a4b1f`, `0x005a63c8`
- `BILINEAR FILTER`: `0x005a4b6e`
- `TEXTURES`: `0x005a4b9f`
- `GOURAUD SHADING`: `0x005a4bf2`
- `RESOLUTION`: `0x005a5f7a`
- `GRAPHICS QUALITY`: `0x005a6120`
- `PLAYERS`: `0x005a618e`
- `BACK NUMBERS`: `0x005a61ed`
- `ANIMATIONS`: `0x005a624c`
- `SHADOWS`: `0x005a630a`
- `GRASS`: `0x005a6369`
- `CAMERAS`: `0x005a67f1`
- `DURATION OF MATCH`: `0x005a75a6`

The option handlers around `0x005a8200..0x005a8e20` update internal option
fields and flip labels between `ON`, `OFF`, `LOW`, and `HIGH`. These are real
stateful toggles, not dead strings.

## SIMULDAT Asset Evidence

`.local/iso/Simuldat` contains:

- `118` files
- `293,722,338` bytes
- `117` `.pkf` archives
- `1` `.pal` palette

Key paths and sizes:

- `Modelos.pkf`: `55,794,624` bytes
- `Camaras.pkf`: `649,934` bytes
- `Cespedes.pkf`: `4,184,943` bytes
- `Texturas/OTROS.pkf`: `1,664,355` bytes
- `Texturas/CARAS.pkf`: `563,913` bytes
- `SIMULPCF6.PAL`: `1,048` bytes, RIFF `PAL `
- `Estadios/*.pkf`: many day/night stadium blobs

The executable references these asset names directly:

- `simuldat\modelos\somball.p3d`
- `simuldat\modelos\balon`
- `simuldat\modelos\redhw.bmp`, `redhw3.bmp`, `redhw4.bmp`, `redhw5.bmp`
- `simuldat\modelos\flechajugador.p3d`
- `simuldat\modelos\medium.p3d`, `large.p3d`, `flag.p3d`, `card.p3d`
- `simuldat\modelos\medium-h.p3d`, `large-h.p3d`, `flag-h.p3d`, `card-h.p3d`
- `simuldat\modelos\states.tbl`
- `simuldat\modelos\banderin.p3d`
- `simuldat\estadios\g0\paleta.pal`
- `estadio.p3d`
- `simuldat\texturas\otros\...`
- `simuldat\texturas\caras\cara...`
- `simuldat\camaras\...`

The PKF blobs are not just opaque compressed noise. They contain plausible
embedded BMP and RIFF resources:

- `Modelos.pkf`: first plausible BMP at offset `0x5b2`, `256x256`, 8 bpp.
- `Cespedes.pkf`: first plausible BMP at offset `0x7812`, `256x256`, 8 bpp;
  also contains RIFF `PAL ` chunks.
- `Texturas/OTROS.pkf`: first plausible BMP at offset `0x5b2`, `256x256`,
  8 bpp.
- `Texturas/CARAS.pkf`: first plausible BMP at offset `0x5b2`, `64x64`,
  8 bpp.
- `SIMULPCF6.PAL`: RIFF `PAL ` at offset `0`.

The current upstream `PKFFile` parser is conservative and falls back to raw
mode for these files. It does not yet understand the SIMULDAT archive layout.
That is now a clear engineering target: write a SIMULDAT PKF indexer/extractor
instead of guessing at one-off byte edits.

## Match/Tactics Files

The game also has simple match/tactics inputs:

- `Tactics/partido.dat`: `80` bytes
- `Tactics/predef.001..010`: `1848` bytes each
- Installed runtime has `TACTIC.000..00A`, around `1777..1788` bytes each

`partido.dat` is small enough for controlled byte-level experimentation. The
first word differs between ISO and installed/runtime state:

- ISO: starts `04 00 00 00 ...`
- Installed runtime: starts `04 01 00 00 ...`

This is a lower-risk patch surface for default tactics/match setup than editing
the renderer.

## Patch Candidates

High value:

- Instrument DirectDraw startup/mode switching before adding more compatibility
  byte patches. The failed larger-desktop windowed experiment showed that blind
  branch bypasses leave invalid renderer state.
- Build a clean patch chain from a known-good binary: No-CD, title badge, and
  known null-guard fixes. The installed binary has research-tainted caves and
  should not be treated as the canonical patch base.
- Decode SIMULDAT PKF layout and extract/reinsert BMP/PAL/P3D resources. This
  unlocks actual football visuals: faces, pitch textures, player textures,
  ball/net graphics, stadium assets, and possibly camera presets.
- Test ISO-vs-installed stadium overlays on the runner. The huge stadium-PKF
  differences are a concrete lead and may affect visual quality without engine
  surgery.
- Default match graphics options to safe/high values where supported:
  graphics quality, players, back numbers, animations, shadows, grass, cameras,
  duration, bilinear filtering, textures, and gouraud shading.

Medium value:

- Patch match-option defaults in the option object or initial UI state.
- Patch match duration defaults or expose them in a launcher/profile overlay.
- Patch camera defaults or zoom/camera mode defaults.
- Add a launcher-managed `manager.ini` overlay so every runner/local test uses
  known-safe music/sound/fullscreen/window-position values.
- Investigate portable install hardening: prefer local game root and `DISK.ID`
  before registry/CD assumptions.
- Patch the legacy `ChangeDisplaySettingsA` colour-mode mutation only if a real
  target system still hits that path.

Low value or high risk:

- Native 1080p by changing the `640x480` constants. That only changes part of
  the problem; the UI coordinates, DIBs, DirectDraw surfaces, and match camera
  all still need work.
- Wrapper scaling as the primary route. The cnc-ddraw 1080p attempt failed at
  startup with the game modal. It may be fixable, but it is a compatibility
  chase rather than reverse-engineering progress.
- Forced binary windowed mode. The patch points were real, but 1024x768 Wine
  runner validation failed in PM99's original windowed DirectDraw path. Do not
  upstream it without a new instrumentation-backed fix.
- Rewriting the renderer or faking a Direct3D path. The binary does not expose
  a normal Direct3D interface to hook.

## Bugs Or Weak Spots Found

- Fullscreen default is unsafe for modern/Wine/runner contexts. Missing
  `manager.ini` defaults to fullscreen ON.
- The render path is old DirectDraw/palette/DIB code; fullscreen exclusive mode
  is the likely black-framebuffer trigger.
- The installed binary is not a clean patch base. Use the ISO binary plus
  explicit patch manifests.
- The title-badge patch is not present in both checked reference binaries from
  this pass.
- SIMULDAT PKF support in the editor is incomplete. It can search raw bytes but
  cannot yet list/rewrite the embedded resources safely.
- Installed stadium assets differ heavily from ISO assets. That could be a real
  quality/configuration issue or an installer/profile artifact; it needs a
  controlled runner test.

## Recommended Next Work

1. Instrument DirectDraw startup/mode switching around `0x00676250`,
   `0x00676770`, and `0x00676C00`, then capture the failing stage/HRESULT on
   tiny-M73.

2. Implement a SIMULDAT PKF resource mapper that records embedded BMP/PAL/P3D
   candidates with offsets, sizes, dimensions, and surrounding header bytes.

3. Run a no-GUI extraction proof locally: map resources only, no asset export
   committed. If a local export is needed, keep it under `.local/`.

4. Build a runner overlay that swaps only installed stadium PKFs with ISO
   stadium PKFs, then compare match-view screenshots on tiny-M73.

5. Build a clean `MANAGPRE.EXE` patch manifest from the ISO binary:
   No-CD, title badge, and known bug guards.

6. Add a runner lane for match-option/profile overlays: known `manager.ini`,
   known `partido.dat`, known match options, then screenshot evidence.

7. Only revisit 1080p after asset/option work. If 1080p is still required,
   treat it as external presentation scaling first, native resolution second.

## Commands/Evidence

```bash
python3 scripts/probe_pm99_3d_assets.py --game-root .local/iso
python3 -m py_compile scripts/probe_pm99_3d_assets.py
objdump -p .local/iso/MANAGPRE.EXE
objdump -D -Mintel --start-address=0x00676230 --stop-address=0x00676d80 .local/iso/MANAGPRE.EXE
objdump -D -Mintel --start-address=0x005a4b00 --stop-address=0x005a8e20 .local/iso/MANAGPRE.EXE
```
