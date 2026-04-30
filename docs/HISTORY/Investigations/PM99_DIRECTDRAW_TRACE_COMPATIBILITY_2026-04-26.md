# PM99 DirectDraw Trace Compatibility Pass - 2026-04-26

## Summary

The DirectDraw trace proxy is now implemented as PM99RE research tooling. It is
log-only: it forwards PM99's DirectDraw calls to Wine/the system DirectDraw and
records the call parameters plus HRESULTs.

The first useful result is that the larger-desktop failure is not a simple
DirectDraw HRESULT failure. In the tested paths, DirectDraw calls return
success, then PM99 shows its own `Application cannot start` modal.

## Tooling Added

- `scripts/pm99_ddraw_trace_proxy.c`: 32-bit `ddraw.dll` proxy source.
- `scripts/pm99_ddraw_trace_proxy.def`: undecorated DirectDraw exports.
- `scripts/build_pm99_ddraw_trace_overlay.sh`: builds the DLL with the existing
  `pm99-runner:latest` image on `tiny-m73`; it does not rebuild the image.
- `scripts/run_pm99_ddraw_trace_probe.sh`: runs the static PM99/Stoke flow with
  `WINEDLLOVERRIDES=ddraw=n,b` and routes `PM99_DDRAW_TRACE_LOG` into runner
  artifacts.
- `scripts/summarize_pm99_ddraw_trace.py`: summarizes trace logs, runner JSON,
  OCR modal text, first failed HRESULT, and suspicious surface dimensions.

The proxy wraps:

- `DirectDrawEnumerateA`
- `DirectDrawCreate`
- `DirectDrawCreateEx`
- `DirectDrawEnumerateExA`
- `IDirectDraw`
- `IDirectDraw4`

PM99 immediately queries `IDirectDraw4`, so wrapping `IDirectDraw` alone is not
enough.

The proxy now also has opt-in compatibility experiments:

- `PM99_DDRAW_NORMALIZE_DISPLAY_MODE=1`: report `640x480x16` from
  `GetDisplayMode`.
- `PM99_DDRAW_FILTER_ENUM_MODES_640=1`: hide non-`640x480x16`
  `EnumDisplayModes` callbacks from PM99.
- `PM99_DDRAW_INJECT_ENUM_MODE_640=1`: if no `640x480x16` enum mode reached
  PM99, synthesize one callback.
- `PM99_DDRAW_FORCE_SET_DISPLAY_MODE_OK=1`: if the real
  `SetDisplayMode(640,480,16)` fails, return `DD_OK` to PM99.

Those switches are off by default in the research proxy.

## Runner Evidence

### 640x480 Shim Safety Run

```text
run tag: pm99_ddraw_trace_safety_640_20260426_impl2
result:  container exit 0
flow:    title screen to squad management screen
window:  640x480
trace:   4864 DirectDraw events
modal:   none
```

Important DirectDraw calls all succeeded:

- `SetCooperativeLevel(hwnd=NULL, flags=0x8)`
- `GetDisplayMode -> 640x480x16`
- `SetCooperativeLevel(hwnd=<game>, flags=0x53)`
- `SetDisplayMode(640, 480, 16, 0, 0)`
- primary/backbuffer surface creation
- palette creation
- many 8 bpp offscreen surface creations

Conclusion: the trace proxy is safe enough for PM99's normal runner path.

### 1024x768 Windowed Path Failure

Overlay:

- trace `ddraw.dll`
- `manager.ini` with `FULL SCREEN: OFF`

```text
run tag: pm99_ddraw_trace_windowed_1024_20260426_impl
result:  container exit 1
phase:   blocked_modal
modal:   Application cannot start.
window:  640x480 at x=44, y=66 on a 1024x768 screen
```

There was no failed DirectDraw HRESULT. The suspicious trace event is earlier:

```text
IDirectDraw4::GetDisplayMode -> 1024x768x16
IDirectDraw4::CreateSurface input width=4294967252 height=4294967252
IDirectDraw4::CreateSurface hr=0x00000000 ok
```

`4294967252` is `-44` wrapped as an unsigned 32-bit value. That is not a real
surface size. It strongly suggests PM99's windowed-path geometry calculation is
using the configured screen/window offset (`44`) in a way that underflows on
the larger desktop path.

### 1024x768 Fullscreen/Default Failure

Overlay:

- trace `ddraw.dll`
- no windowed `manager.ini` override

```text
run tag: pm99_ddraw_trace_fullscreen_1024_20260426_impl
result:  container exit 1
phase:   blocked_modal
modal:   Application cannot start.
window:  640x480
```

Again there was no failed DirectDraw HRESULT. This path did not reach
`SetDisplayMode` or primary surface creation. The trace stopped after:

```text
IDirectDraw4::SetCooperativeLevel(hwnd=NULL, flags=0x8) -> ok
IDirectDraw4::GetDisplayMode -> 1024x768x16
IDirectDraw4::GetAvailableVidMem -> ok
```

Conclusion: PM99 rejects the larger current desktop/mode before its real
fullscreen mode switch.

### Failed Single-Factor Shim Attempts

These were tested and should not be promoted as fixes:

- `pm99_ddraw_norm_fullscreen_1024_20260426`: normalizing only
  `GetDisplayMode` to `640x480x16` still failed with `Application cannot start`.
- `pm99_ddraw_norm_windowed_1024_20260426`: normalizing only
  `GetDisplayMode` still produced the bogus wrapped `-44 x -44` surface sizes.
- `pm99_ddraw_clamp_windowed_1024_20260426`: clamping those impossible
  surfaces to `640x480` still failed with the startup modal.

Those failures matter because they prove the fix has to address the earlier
mode enumeration table, not just one later value or one bad surface request.

### EnumDisplayModes Finding

The callback trace changed the diagnosis.

At `640x480x16`, Wine enumerates only the current `640x480` modes:

```text
run tag: pm99_ddraw_enumtrace_safety_640_20260426
result:  container exit 0
modes:   640x480x32, 640x480x16, 640x480x8
```

At `1024x768x16`, Wine enumerates only the current `1024x768` modes:

```text
run tag: pm99_ddraw_enumtrace_fullscreen_1024_20260426
result:  container exit 1
modal:   Application cannot start.
modes:   1024x768x32, 1024x768x16, 1024x768x8
```

So PM99 is not being offered its expected `640x480x16` startup mode on larger
desktops. A simple "filter to 640" is therefore insufficient because it passes
zero modes. The shim has to synthesize a `640x480x16` mode as well.

### Synthetic 640 Mode Without Forced SetDisplayMode

This run hid the real `1024x768` enum modes, injected one synthetic
`640x480x16` mode, and normalized `GetDisplayMode` to `640x480x16`.

```text
run tag: pm99_ddraw_synth640_fullscreen_1024_20260426
result:  container exit 1
modal:   Application cannot start.
```

That got PM99 further than the original failure. It reached the normal
fullscreen transition and called:

```text
IDirectDraw4::SetDisplayMode width=640 height=480 bpp=16
hr=0x80004001 fail
```

`0x80004001` is `E_NOTIMPL`. On the 1024 runner desktop, Wine did not actually
support switching that DirectDraw display mode, even though PM99 had now chosen
the right internal mode.

### Successful Larger-Desktop Compatibility Shim

This run used the full compatibility set:

- hide real non-640 enum modes
- inject `640x480x16`
- normalize `GetDisplayMode`
- return success to PM99 for failed `SetDisplayMode(640,480,16)`

```text
run tag: pm99_ddraw_synth640_forceset_fullscreen_1024_20260426
result:  container exit 0
modal:   none
flow:    30 scripted steps, through squad/dashboard screens
window:  640x480 on a 1024x768 desktop
trace:   23423 DirectDraw events
```

The same shim also passed on a 1080p desktop:

```text
run tag: pm99_ddraw_synth640_forceset_fullscreen_1080p_20260426
screen:  1920x1080x16
result:  container exit 0
modal:   none
flow:    30 scripted steps
window:  640x480 on a 1920x1080 desktop
trace:   18931 DirectDraw events
```

Important caveat: this is not a higher-resolution renderer. PM99 still creates
and uses a `640x480` game window. The fix is that the game now starts and plays
on a larger host desktop instead of rejecting startup.

## Interpretation

This changes the compatibility target. The immediate problem is not a random
DirectDraw failure. PM99 is seeing only the host desktop's larger modes during
startup, not its expected `640x480x16` mode. If the shim makes PM99 see the
same `640x480x16` startup facts it sees on the passing 640 runner, PM99 gets
far enough to attempt the normal mode switch. On larger Wine/Xvfb desktops,
that real mode switch returns `E_NOTIMPL`, so the shim also has to treat that
specific failed mode switch as non-fatal.

The two 1024x768 failures differ:

- Default/fullscreen fails before `SetDisplayMode`, probably during PM99's
  mode-table or display-state validation.
- Windowed mode gets further and creates bogus `-44 x -44` wrapped surfaces,
  then fails with the same PM99 modal.

That explains why the earlier blind branch bypasses and forced-success patches
produced black/invalid renderer state: the underlying PM99 mode table was
already wrong. The working path fixes the mode table first, then bypasses only
the final unsupported host mode switch.

## Next High-Value Work

The next patch should be a packaged compatibility shim, not a binary branch
bypass:

- Build a release-style `ddraw.dll` where the four successful compatibility
  behaviors can be enabled by an INI file or a clearly named build profile.
- Keep the default trace-only behavior for research builds.
- Test on real Windows 10/11 and Wine outside Xvfb. The runner proves the
  startup logic and scripted flow, but it does not prove every real GPU/driver
  combination.
- If visual scaling is still desired, add it outside this fix. This shim makes
  PM99 work on a larger desktop; it does not upscale or re-render the game at
  1080p.

Do not revive the rejected forced-windowed patch as-is.
