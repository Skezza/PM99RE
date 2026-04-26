# PM99 Transferable Fix Candidates (2026-04-26)

## Scope

This note deliberately ignores the local ripped/min-install stadium finding.
Those files may explain one bad install, but they are not a useful product fix.
The goal here is patches or tooling that transfer to a clean full install and
to other PM99 users.

Reference binary:

- `.local/iso/MANAGPRE.EXE`
- SHA-256: `4650897415668de2678753bbe9a92de05a778f0939c44154b5aa1423ab7a3a57`
- PE32 i386, image base `0x00400000`

## Highest-Value Fixes

### 1. DirectDraw failure instrumentation and targeted hardening

The failed windowed-mode experiment changed the priority order. The next
transferable compatibility fix should identify the exact DirectDraw failure
instead of adding more blind branch patches.

Instrumentation targets:

- `0x00676250`: DirectDraw bootstrap, dynamic `ddraw.dll` load, enumeration,
  `DirectDrawCreate`, and private device/mode table setup.
- `0x00676770`: render startup entry and post-mode validation.
- `0x00676C00`: core window/fullscreen mode switch.
- `0x00676E10`: DirectDraw cooperative-level call.
- `0x006770AD`: fullscreen `SetDisplayMode(width, height, bpp, 0, 0)` call.
- Palette/surface setup after the mode switch.

Desired output:

- A runner artifact that names the failing stage.
- The failing HRESULT or boolean gate.
- A small targeted patch only after the failure is known.

This is now higher value than another attempted windowed/high-resolution patch.

### 2. PM99-specific DirectDraw shim

Generic `ddraw.dll` wrappers failed because PM99 is not just importing
DirectDraw; it validates enumeration, caps, mode tables, cooperative level, and
surface/palette state. A custom PM99 shim could preserve the behaviour PM99
expects while adding diagnostics, compatibility fixes, or scaling later.

This is harder than a byte patch, but it is the credible route if the goal is a
real black-framebuffer/fullscreen compatibility fix.

### 3. SIMULDAT PKF tooling

SIMULDAT PKFs contain real BMP/PAL/P3D resources. The editor currently does not
understand that archive family. A SIMULDAT mapper/extractor would transfer
across installs and unlock real modding of pitch textures, model textures,
faces, ball/net graphics, stadium resources, palettes, and camera assets.

This is not a bug fix by itself, but it is high-leverage modding
infrastructure.

### 4. Match-engine option defaults

The match view has real stateful 3D options, not dead strings:

- `GOURAUD SHADING`
- `TEXTURES`
- `BILINEAR FILTER`
- `HARDWARE OPTIONS`
- `GRAPHICS QUALITY`
- `PLAYERS`
- `BACK NUMBERS`
- `ANIMATIONS`
- `SHADOWS`
- `GRASS`
- `CAMERAS`
- `DURATION OF MATCH`
- `RESOLUTION`

The handlers around `0x005A8200..0x005A8E20` change backing state and UI labels.
The practical transferable fix is a profile/launcher default: start new games
with safe/high graphics settings and known camera/duration defaults.

This is better than native-resolution byte poking because it uses options the
engine already understands.

### 5. Make installs portable instead of registry/CD fragile

The startup code still contains old Gremlin product registry and `DISK.ID`
lookup logic:

- Product registry keys include `Software\Gremlin\Premier Manager 99` and
  related PC Futbol products.
- The value read is `Dir`.
- Startup builds/checks `DISK.ID` paths and validates tokens such as `PCP6 00`.
- The existing No-CD patch reroutes the path enough to use local `DISK.ID`, but
  the broader install-path behavior is still brittle.

The transferable fix is a launcher/patcher contract:

- Prefer the executable/current game root.
- Validate local `DISK.ID`.
- Only fall back to registry lookup if local files are absent.
- Surface a useful error if the game root is incomplete.

This is more useful than a one-off No-CD byte patch because it makes clean,
isolated, copied, runner, and user installs behave the same way.

### 6. Stop mutating the user's desktop color mode

The code at `0x006AACB0` checks desktop color depth. If it thinks the desktop is
below 8 bpp, it can ask to switch to 256 colors and then calls
`ChangeDisplaySettingsA` at `0x006AAD86`.

That is hostile on modern Windows/Wine. It is also the wrong layer for a 2026
compatibility build: the launcher should decide compatibility policy, not the
game changing the desktop mode.

An opt-in patch can replace the `ChangeDisplaySettingsA` call with
`xor eax,eax` plus NOPs, so the game thinks the call succeeded without changing
the desktop. Keep this out of the default patch set unless real systems still
hit this path.

### Rejected: binary-level forced windowed patch

This is more than writing `FULL SCREEN: OFF` into `manager.ini`. The binary
defaults to fullscreen when `manager.ini` is missing, trusts a parsed fullscreen
setting if the file exists, and lets Alt+Enter enter exclusive fullscreen again.

Confirmed patch points:

- `0x0040B806`: force parsed `FULL SCREEN` result to zero before storing
  `DAT_0079E69C`.
- `0x0040B89F`: change the missing-`manager.ini` default from fullscreen ON to
  fullscreen OFF.
- `0x00677A49`: change the Alt+Enter toggle so it never requests fullscreen.

PoC added:

```bash
python3 scripts/patch_pm99_transferable_compat.py .local/iso/MANAGPRE.EXE --dry-run
python3 scripts/patch_pm99_transferable_compat.py .local/iso/MANAGPRE.EXE \
  --output .local/pm99-transferable-compat/MANAGPRE.windowed_compat.EXE
```

Local patched-copy SHA-256:

- `defa7e86c27bf42dcb20a4426382467eb552d96822ea5ddacd681e32c2127ac8`

Later validation changed the risk rating. The patch points are real, but the
patch is not yet a proven playable larger-desktop windowed-mode fix.

Runner evidence:

- `pm99_windowed_mode_patch_runner_20260426_retry2`: patched No-CD EXE passed
  the title-to-squad flow at 640x480, even with hostile `FULL SCREEN: ON`.
- `pm99_windowed_mode_patch_runner_20260426_bigscreen`: patched EXE failed on a
  1024x768 Wine runner with PM99's `Application cannot start` modal.
- `pm99_windowed_config_only_bigscreen_20260426`: config-only control with no
  EXE patch failed the same way on 1024x768.

Conclusion: the fullscreen-control patch is still transferable as a reversible
fullscreen-avoidance experiment, but it failed the intended upstream goal: it is
not a proven playable larger-desktop windowed-mode fix. Do not upstream it.

## Existing Proven Fixes To Preserve

### Preserve the already-proven null-pointer/formatter crash fixes

The Valderrama/Stars work is a genuine transferable game bug fix, not local data
repair. Existing patchers already cover the important class:

- `scripts/patch_managpre_null_guard_only.py`
- `scripts/patch_managpre_valderrama_guard.py`

The relevant pattern is worth keeping: small, named byte patches with exact
source-byte checks, not open-ended binary surgery.

## Low-Value Or De-Prioritized

- Replacing installed stadium PKFs from the ISO: probably explains a ripped
  install, but it is not an interesting transferable fix.
- Native `800x600+`/`1080p` by changing the `640x480` constants: proven to make
  the DirectDraw canvas bigger while the game still draws a 640x480 scene.
- Generic external scaling as the main research route: useful for presentation
  eventually, but it does not fix the engine and has already produced black
  screens/crashes locally.

## Verification Run

```bash
python3 -m py_compile scripts/patch_pm99_transferable_compat.py
python3 scripts/patch_pm99_transferable_compat.py .local/iso/MANAGPRE.EXE --dry-run
python3 scripts/patch_pm99_transferable_compat.py .local/iso/MANAGPRE.EXE --patch-set all --dry-run
python3 scripts/patch_pm99_transferable_compat.py .local/iso/MANAGPRE.EXE \
  --output .local/pm99-transferable-compat/MANAGPRE.windowed_compat.EXE
python3 scripts/patch_pm99_transferable_compat.py \
  .local/pm99-transferable-compat/MANAGPRE.windowed_compat.EXE --revert --dry-run
```

The revert dry-run returns the original ISO SHA-256, so the patch set is
round-trip clean.
