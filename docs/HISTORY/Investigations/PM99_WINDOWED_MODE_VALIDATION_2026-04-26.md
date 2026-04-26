# PM99 Windowed Mode Validation - 2026-04-26

## Summary

The separate SkezMod Windowed Mode Patch is not yet proven as a playable
larger-desktop windowed-mode fix.

What is proven:

- The patch changes the three intended fullscreen-control paths in
  `MANAGPRE.EXE`.
- A hostile `manager.ini` with `FULL SCREEN: ON` no longer forces exclusive
  fullscreen in the patched EXE.
- On the 640x480 runner, the patched No-CD EXE completes the existing
  title-to-squad flow.

What is not proven:

- It does not make PM99 playable as a 640x480 framed window on a larger Wine
  desktop.
- It does not upscale PM99.
- It does not fix the deeper Wine/DirectDraw startup failure in PM99's original
  windowed path.

## Evidence

Successful 640x480 patched run:

```text
run tag: pm99_windowed_mode_patch_runner_20260426_retry2
result:  container exit 0
window:  PREMIER MANAGER 99, 640x480
flow:    title screen to squad management screen
modal:   no blocking error modal detected
```

Failed 1024x768 patched run:

```text
run tag: pm99_windowed_mode_patch_runner_20260426_bigscreen
result:  container exit 1
window:  normal framed 640x480 window
modal:   Application cannot start. Please try again or reinstall.
```

Failed 1024x768 config-only control:

```text
run tag: pm99_windowed_config_only_bigscreen_20260426
result:  container exit 1
scope:   no binary patch, only manager.ini FULL SCREEN: OFF
window:  normal framed 640x480 window
modal:   Application cannot start. Please try again or reinstall.
```

The control matters. It shows the new binary patch is not what creates the
1024x768 failure; PM99's own windowed DirectDraw startup path already fails on
that Wine/X11 larger-desktop setup.

## Static Findings

Relevant code paths:

- `0x0040B806`: parsed `FULL SCREEN` value stored to `DAT_0079E69C`.
- `0x0040B89F`: missing-`manager.ini` fullscreen default.
- `0x00677A49`: Alt+Enter fullscreen toggle.
- `0x00676770`: render startup entry. It copies `DAT_0079E69C` to
  `DAT_0079E6B8`, validates graphics state, then loads `dat\fader.bmp` and
  `dat\faderp.bmp`.
- `0x00676839`: branch after `0x68AD30` rejects the startup if the requested
  640x480 mode is not accepted by PM99's DirectDraw mode table.
- `0x00676C00`: core window/fullscreen mode switch. It calls DirectDraw
  cooperative-level/display or window setup and uses `AdjustWindowRectEx`,
  `GetMenu`, GDI palette calls, and DirectDraw vtable calls.

The user-visible startup modal text has two relevant variants:

- `Application cannot start. Please try again or reinstall.`
- `Application cannot continue.`

## Diagnostic Patches Tried

Diagnostic patch 1:

- Patch: `0x00676839`, `74 04 -> 90 90`
- Meaning: ignore one mode-table rejection and continue into the mode switch.
- Result: still failed on 1024x768. The PM99 window became a 1024x768
  fullscreen-style black surface and showed `Application cannot start`.

Diagnostic patch 2:

- Patch: diagnostic 1 plus `0x00677356`, `8A 44 24 0B -> B0 01 90 90`
- Meaning: force `FUN_00676C00` to return success.
- Result: still failed on 1024x768. The modal changed to
  `Application cannot continue`.

These are not shipping patches. They prove the larger-desktop failure is deeper
than the first mode-table check and that blindly forcing success leaves invalid
renderer state.

## Current Conclusion

Do not present the current Windowed Mode Patch as a proven real windowed-mode
fix. It is a separate, reversible fullscreen-avoidance patch with a valid 640x480
runner pass and a known larger-desktop Wine failure.

The more promising next line is to instrument `0x00676C00` or run the same path
with Wine DirectDraw debug enabled, then identify the exact failing DirectDraw
vtable call/HRESULT. Guessing more branch bypasses is low value.

## Future Improvement Candidates

These remain worth revisiting, but they are separate from the failed upstream
Windowed Mode Patch experiment:

- DirectDraw failure instrumentation. Add logging around `0x00676250`,
  `0x00676C00`, and the DirectDraw vtable calls so startup failures name the
  failing stage and HRESULT.
- PM99-specific DirectDraw shim. Generic wrappers failed because PM99 validates
  enumeration/caps/mode state. A custom shim would need to preserve PM99's
  expected DirectDraw behaviour first, then add diagnostics or scaling later.
- Fullscreen hardening. Once instrumentation identifies the failing fullscreen
  or palette call, patch that exact path rather than forcing windowed mode.
- SIMULDAT/3D asset tooling. Decode PKF archives for BMP/PAL/P3D resources so
  match visuals can be modified without renderer surgery.
- Match graphics/profile defaults. Find where options such as textures,
  bilinear filtering, gouraud shading, stadium quality, grass, shadows, cameras,
  and duration persist, then expose a safe/high preset.
- Portable install hardening. Prefer the local game root and local `DISK.ID`
  before old registry/CD assumptions, with useful errors for incomplete copies.
- Desktop colour-mode mutation guard. Patch or launcher-block the legacy
  `ChangeDisplaySettingsA` path if real systems still hit it.

Do not upstream a windowed-mode patch until the larger-desktop DirectDraw
failure is understood and a runner proof shows the game is actually playable.
