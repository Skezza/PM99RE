# PM99 Game Binary Patch Survey - 2026-04-23

## Scope

This pass inspected the local PM99 binaries and prior PM99RE research artifacts for practical game-level patches:

- `.local/iso/MANAGPRE.EXE`
- `.local/iso/managpre.nocd_patched.exe`
- `.local/premier-manager-ninety-nine/MANAGPRE.EXE`
- `.local/iso/PM99.EXE`
- `.local/iso/DBASEPRE.EXE`

No proprietary binaries or game data were modified.

## Current Binary State

Observed SHA-256 values:

| File | SHA-256 | Notes |
| --- | --- | --- |
| `.local/iso/MANAGPRE.EXE` | `4650897415668de2678753bbe9a92de05a778f0939c44154b5aa1423ab7a3a57` | ISO original; No-CD patcher reports all three source bytes still original. |
| `.local/iso/managpre.nocd_patched.exe` | `650396163ed93918b2b2b66478328f89c8f8062fe9bf424aecc1473f4945e801` | No-CD patcher reports all three target bytes already applied. |
| `.local/premier-manager-ninety-nine/MANAGPRE.EXE` | `43bb6e0ad52e82d22b9cc171743314739c5bbcfca91e03c25a817d21b8ec7e5e` | Installed working binary; No-CD patcher reports target bytes already applied. |
| `.local/premier-manager-ninety-nine/MANAGPRE.original.exe` | `b2fdd927ebfddf80990daa6b60621d46c29d23c9bd9c175de4288b2f306d6735` | Historical local original copy. |
| `.local/iso/pm99.exe` | `effbd35aee3751a02871d253df45db09f85548f3890d4cb26c2d32157480161d` | Launcher executable. |
| `.local/iso/Dbasepre.exe` | `4b21b2051e3583031addd9ae8b87849c9308615120cf3643914038085ff610e9` | Database executable. |

Known patch families already present in PM99RE:

- No-CD: `scripts/patch_pm99_nocd.py`
- Title badge redirect from `F%u.%u` to custom cave string: `scripts/patch_pm99_title_badge.py`
- Valderrama transfer-hover null guard: `scripts/patch_managpre_null_guard_only.py`
- Larger Valderrama source-club/text fallback experiment: `scripts/patch_managpre_valderrama_guard.py`

The installed `MANAGPRE.EXE` is No-CD patched, but the title badge redirection is not present in the checked local installed binary: the push at `0x00467028` still targets `0x00731C2C` (`F%u.%u`), and the cave at `0x0072BA20` is still zero-filled.

## Confirmed Video Architecture

`MANAGPRE.EXE` is a PE32 GUI executable with image base `0x00400000`. Ghidra memory blocks:

- `.text`: `0x00401000..0x006E51FF`
- `.rdata`: `0x006E6000..0x0072BBFF`
- `.data`: `0x0072C000..0x007BDE67`
- `.rsrc`: `0x007BF000..0x007C07FF`

Imports/dynamic loading show a hybrid DirectDraw/GDI/MFC design:

- Imports `ChangeDisplaySettingsA`, `FillRect`, `InvalidateRect`, `GetDeviceCaps`, `StretchDIBits`, `SetSystemPaletteUse`, palette APIs, MFC42.
- Dynamically loads `ddraw.dll`, then resolves `DirectDrawEnumerateA` and `DirectDrawCreate`.
- Dynamically loads `DSOUND.DLL` APIs and imports `DirectInputCreateA`.

Important Ghidra anchors:

| Address | Function | Finding |
| --- | --- | --- |
| `0x00676250` | DirectDraw bootstrap | Loads `ddraw.dll`, resolves `DirectDrawEnumerateA`/`DirectDrawCreate`, enumerates devices, creates primary rendering state. |
| `0x006765F0` | Main window constructor/init | Hardcodes shell surface size: `DAT_00744D98 = 0x280` and `DAT_00744D9C = 0x1E0`, i.e. `640x480`. |
| `0x00676770` | Window startup/render-mode entry | Copies configured fullscreen flag `DAT_0079E69C` to pending mode `DAT_0079E6B8`, validates DirectDraw mode, loads `dat\fader.bmp` and `dat\faderp.bmp`. |
| `0x00676A40` | Mode-selection helper | Updates global width/height and derives active bit depth from device capabilities. |
| `0x00676C00` | Window/fullscreen switch | Calls DirectDraw `SetCooperativeLevel`, then in fullscreen calls DirectDraw `SetDisplayMode(width,height,bpp,0,0)`. Windowed mode avoids `SetDisplayMode` and uses normal window placement. |
| `0x006AACB0` | DirectX/color-depth startup guard | Checks desktop bits-per-pixel via `GetDeviceCaps`; if below 8 bpp it prompts and can call `ChangeDisplaySettingsA` for 8 bpp. |
| `0x004BED90` | GDI/DIB path | Uses `StretchDIBits` with an 8-bit `BITMAPINFO` palette, relevant to print/copy/fallback rendering paths. |

The long-standing runner assumption is correct: PM99 starts in an exclusive `640x480x16`-compatible mode. Existing runner docs and artifacts also show `640x480`, not `800x600`.

## Runtime Runner Evidence

Fresh runner probes were executed for this survey.

Baseline fullscreen-configured smoke:

- Command: `upstream/pm99-runner/scripts/pm99_runner/run_stoke_smoke.sh --run-tag pm99_binary_survey_baseline_20260423 --skip-setup --skip-build --skip-prepare --reset-wine-prefix --full-trace`
- Result: `apply_status=0`, `smoke_status=0`.
- Artifact root: `upstream/pm99-runner/docs/artifacts/pm99_runner/pm99_binary_survey_baseline_20260423/smoke/`
- Runtime result: title screen classified with `confidence=0.99`, `crash_detected=false`, `blocking_error_modal_detected=false`.
- Window state: one `PREMIER MANAGER 99` window at `640x480+0+0`.
- Screenshot: `screens/00_smoke.png` is `640 x 480`, 8-bit/color RGB.

Windowed `manager.ini` overlay path:

- Overlay: `.local/runner-overlays/windowed-manager/manager.ini` with `FULL SCREEN: OFF`.
- Command: `bash scripts/run_stoke_runtime_probe_direct.sh --run-tag pm99_binary_survey_windowed_20260423 --local-overlay-dir .local/runner-overlays/windowed-manager --docker-timeout 900`
- Result: `run_status=0`.
- Artifact root: `artifacts/stoke_remote_profile_probe/pm99_binary_survey_windowed_20260423/`
- Runtime result: reached `squad_management_screen` with `confidence=0.99`, `crash_detected=false`, `blocking_error_modal_detected=false`.
- Window state: one `PREMIER MANAGER 99` window at `640x480+0+0` across all captured steps.
- Screenshots: all captured PNGs are `640 x 480`, 8-bit/color RGB.

Conclusion: `FULL SCREEN: OFF` is runtime-safe through at least a title-to-squad flow and is the first compatibility mitigation to ship/test for black-framebuffer reports. It does not increase internal resolution; it keeps the fixed 640x480 shell while avoiding the fullscreen `SetDisplayMode` path.

## DirectDraw Wrapper Evidence

Off-the-shelf `ddraw.dll` replacement wrappers were tested on the tiny M73 runner, not on the local laptop display. They all failed before the title screen with PM99's own startup modal:

```text
DirectX couldn't be started.
Application cannot start.
Please try again or reinstall.
```

Tested wrapper families:

| Wrapper | Runner tag | Result |
| --- | --- | --- |
| `cnc-ddraw` 7.1.0.0, OpenGL/1080p config | `pm99_cnc_ddraw_1080p_tiny_m73_r2_20260424` | Failed before title with PM99 DirectX startup modal. |
| `cnc-ddraw` 7.1.0.0, native 640x480/GDI config | `pm99_cnc_ddraw_gdi_native_tiny_m73_r2_20260424` | Failed before title with same modal. |
| `dxwrapper` 1.6.8300.25, `dx7.games` config | `pm99_dxwrapper_dx7_native_tiny_m73_20260424` | Failed before title with same modal. |
| `dgVoodoo2` 2.87.1 | `pm99_dgvoodoo2_native_tiny_m73_20260424` | Failed before title with same modal. |

Export inspection showed those wrappers do export both `DirectDrawEnumerateA` and `DirectDrawCreate`, so the failure is not a trivial missing-symbol problem. The likely failure point is inside PM99's bootstrap at `0x00676250`, after wrapper enumeration/creation begins. PM99 enumerates DirectDraw devices, builds a private device/mode table, filters by pixel format/bit depth, calls `SetCooperativeLevel`, and validates display mode state. Generic wrappers appear to fail PM99's expectations in that path, while Wine's built-in DirectDraw passes.

Conclusion: "drop in a modern `ddraw.dll`" is currently not viable. A PM99-specific proxy could still work, but it would need to preserve PM99's exact enumeration/caps behavior and then add scaling later. That is a real compatibility-wrapper project, not a config tweak.

## Native Resolution Patch Probe

The constructor constants at `0x006765F0` were patched in throwaway runner overlays:

| Global | Original write | Meaning |
| --- | --- | --- |
| `DAT_00744D98` | `640` at immediate VA `0x00676675` | Requested DirectDraw/client width. |
| `DAT_00744D9C` | `480` at immediate VA `0x0067667F` | Requested DirectDraw/client height. |

The test overlays were based on `.local/iso/MANAGPRE.EXE`, then No-CD patched with `scripts/patch_pm99_nocd.py`. They were local-only runner overlays under `.local/runner-overlays/native-res-*`.

Runner results:

| Patch | Screen geometry | Runner tag | Result |
| --- | --- | --- | --- |
| `800x600` | `800x600x16` | `pm99_native_res_800x600_nocd_tiny_m73_20260424` | Boots, window is `800x600`, no blocking modal. Game drawing remains mostly `640x480`; extra area is unused/black. |
| `1024x768` | `1024x768x16` | `pm99_native_res_1024x768_nocd_tiny_m73_20260424` | Boots, window is `1024x768`, no blocking modal. Game drawing remains `640x480` in the top-left. |
| `1440x1080` | `1440x1080x16` | `pm99_native_res_1440x1080_nocd_tiny_m73_20260424` | Boots, window is `1440x1080`, no blocking modal. Game drawing remains `640x480` in the top-left. |

This proves the DirectDraw mode request can be increased, including a 4:3 1080p target (`1440x1080`), but it does not modernize the visible game. PM99's actual scene/UI renderer is still hardwired around a 640x480 coordinate space and surfaces. The result is a larger DirectDraw canvas with the old game painted into the top-left corner.

Generated comparison previews:

- `artifacts/display_scaling_previews/pm99_640_to_1440x1080_nearest.png`
- `artifacts/display_scaling_previews/pm99_640_to_1440x1080_lanczos.png`
- `artifacts/display_scaling_previews/pm99_640_to_1280x960_nearest.png`
- `artifacts/display_scaling_previews/pm99_640_to_1280x960_lanczos.png`

Those previews are artifact-only crops/resizes of captured runner output. They show what an external scaler can look like; they are not an interactive game scaler.

## Configuration Surface

`manager.ini` is genuinely read/written by `FUN_0040B5A0` / `FUN_0040B9E0`:

```text
MUSIC: ON
MUSIC VOLUME: 100
SOUND: ON
SOUND VOLUME: 100
TRANSITIONS: ON
FULL SCREEN: ON
SCREEN POSITION: 0, 0
```

`sip.ini` supports:

```text
PIS LEVEL: 3
```

The game also contains strings for match-side options:

- `RESOLUTION`
- `BILINEAR FILTER`
- `BACK NUMBERS`
- `SOUND`
- `FX SOUNDS`
- `Fixed 4`

Those appear tied to the match/simulation option screen rather than the main 640x480 shell. They may be persisted in a non-obvious binary/options file, not `manager.ini`.

## Patch Opportunities

### 1. Low-risk: force windowed mode to avoid fullscreen/black-framebuffer issues

The safest compatibility patch is not a code patch: ship or generate `manager.ini` with:

```text
FULL SCREEN: OFF
SCREEN POSITION: 0, 0
```

Reasoning:

- Fullscreen path in `0x00676C00` calls `SetDisplayMode` and then creates/attaches primary/palette state.
- Windowed path avoids `SetDisplayMode`, clamps position to desktop bounds, restores overlapped-window styles, and uses `SetWindowPos`.
- Existing runner evidence already shows stable `640x480` windows.

Binary variant if config is not trusted:

- Patch `FUN_0040B5A0` so parsed `FULL SCREEN` always stores `0` in `DAT_0079E69C`.
- Patch default fallback so missing `manager.ini` defaults to windowed instead of fullscreen.
- Patch the fullscreen toggle path around `0x00677A3F..0x00677A5C` to refuse toggling into fullscreen.

This is the most practical "XP black framebuffer" mitigation to test first.

### 2. Medium-risk: DirectDraw fullscreen hardening

Candidate patch points in `FUN_00676C00`:

- `0x00676E10`: DirectDraw `SetCooperativeLevel(hwnd, flags)`.
- `0x006770AD`: DirectDraw `SetDisplayMode(DAT_00744D98, DAT_00744D9C, DAT_00744DA4, 0, 0)`.
- `0x00677272`: `SetSystemPaletteUse(hdc, 2)`.
- `0x00677298..0x006772BA`: attaches palette/surface after mode switch.

Potential experiments:

- Force `DAT_00744DA4` to `16` before `SetDisplayMode`.
- Force `FUN_0064D080` mode class from `2` to `1` for 8-bit `640x480`.
- Add a repaint/restore sequence after `SetDisplayMode`: `InvalidateRect`, palette realize, surface restore, and fader reload.

Risk:

- Palette and surface code is tightly coupled to 8-bit assets and DirectDraw primary/backbuffer semantics.
- A bad patch can create a successful startup with invisible UI, not an obvious crash.

### 3. High-risk: increase main-shell resolution

The main shell resolution is not a single safe constant. `0x006765F0` seeds:

- `DAT_00744D98 = 640`
- `DAT_00744D9C = 480`
- initial client rect/position fields at object offsets `0x78..0x84`, `0x398`, `0x39C`

However, there are hundreds of hardcoded `640`, `480`, coordinate, clipping, asset, and layout references across `.text`. The shell UI uses fixed bitmap resources and fixed screen-coordinate interaction regions. Replacing only the constructor constants now has direct evidence: `800x600`, `1024x768`, and `1440x1080` all boot, but the game still draws a `640x480` scene with black unused space around it.

Recommended path:

- Do not ship the constructor-only native resolution patch as "high resolution"; it is only a larger canvas.
- Use a scaler approach first: keep the game renderer at `640x480`, then scale output to `1280x960`, `1440x1080`, or fullscreen pillarboxed `1920x1080`.
- If native high-res is required, build a patch map screen by screen, starting with title/menu and one dashboard screen, and expect a larger renderer/layout project.

## Practical Scaling Options

What can realistically be achieved:

| Target | What it means | Status |
| --- | --- | --- |
| `640x480` windowed | Original renderer, compatibility-focused. | Proven stable through runner flow. Best black-framebuffer mitigation. |
| `1280x960` external scale | Exact 2x integer scale of the original 4:3 frame. | Best quality/lowest risk if the host display can fit it. |
| `1440x1080` external scale | 2.25x scale to fill a 1080-high 4:3 area. On a 1920x1080 monitor this leaves 240px black bars left/right. | Best 1080p target; preview artifacts generated. |
| `1920x1080` stretched | Non-4:3 horizontal stretch. | Technically easy for an external scaler, visually wrong. Not recommended. |
| Native `800x600+` by binary patch | Larger DirectDraw mode with unchanged 640x480 game drawing. | Proven, but not useful alone. |
| True native high-res UI | Re-layout/render game screens at higher coordinates. | Possible only as a substantial renderer patch/rewrite. |

Best next engineering route: build or integrate a PM99-specific external scaler that launches the game windowed at `640x480`, presents a scaled `1440x1080` or `1280x960` host window, and maps mouse input back by the inverse scale. Existing generic DirectDraw wrappers failed PM99's startup validation, so the safer first scaler should sit outside PM99's DirectDraw path rather than replacing `ddraw.dll`.

### 4. Existing stable binary patches to productize

Already viable:

- No-CD patch: three known file offsets in `scripts/patch_pm99_nocd.py`.
- Title badge patch: redirect `0x00467028` push from `0x00731C2C` to a cave string at `0x0072BA20`.
- Minimal Valderrama null guard: trampoline at `0x0066F1FB`, cave at `0x006E51C0`, NULL path to `0x0066F243`.

Needs cleanup before release:

- The installed binary currently has cave bytes that the minimal/null-guard and larger Valderrama patchers do not recognize as clean/already-patched. Treat that local binary as research-tainted until a clean source plus patch manifest is rebuilt.

### 5. Data/resource mods with lower binary risk

Already supported or partially researched:

- Player/team database edits through `upstream/pm99-skezmod-db-editor`.
- No-CD and title badge through `upstream/pm99-skezmod-patcher`/scripts.
- Player stills/minifoto archives.
- Stadium metadata.
- Staff/plaintext start-of-season extraction.
- Font assets in `WINFONTS`.
- Simulation textures/models under `simuldat`.
- Tactical seed data under `TACTICS/partido.dat`.

These are safer than invasive renderer changes because they do not alter DirectDraw startup.

## Recommended Next Experiments

1. Productize a compatibility preset that writes or preserves `FULL SCREEN: OFF` before launch.
2. Repeat with `FULL SCREEN: ON` on the target XP or XP-like environment to reproduce the black framebuffer and capture screenshots/window messages.
3. If black occurs only in fullscreen, keep the default compatibility preset windowed and make fullscreen opt-in.
4. If black occurs in windowed mode too, instrument `0x00676C00` return paths and surface/palette calls, especially `SetDisplayMode`, `SetSystemPaletteUse`, and DirectDraw palette attachment.
5. For resolution, implement external scaling first. Native `800x600` should be considered a separate renderer/layout project, not a byte tweak.

## Commands/Evidence Used

- `file` on PM99 executables.
- `sha256sum` on target binaries.
- `objdump -p` for imports.
- `objdump -d -Mintel` around video functions.
- `strings -a -td` for DirectDraw/resolution/config strings.
- GhidraMCP memory block reads, string searches, and decompilation for the functions listed above.
- Fresh runner probes `pm99_binary_survey_baseline_20260423` and `pm99_binary_survey_windowed_20260423`.
- Existing runner docs/artifacts showing `640x480x16` and `640x480` xwininfo captures.
