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

## Interpretation

This changes the compatibility target. The immediate problem is not Wine
returning a bad DirectDraw HRESULT. PM99 is seeing a larger current display
mode, doing its own validation/geometry work, and deciding startup is invalid.

The two 1024x768 failures differ:

- Default/fullscreen fails before `SetDisplayMode`, probably during PM99's
  mode-table or display-state validation.
- Windowed mode gets further and creates bogus `-44 x -44` wrapped surfaces,
  then fails with the same PM99 modal.

That explains why blind branch bypasses and forced-success patches produced
black/invalid renderer state: the underlying PM99 state is already wrong.

## Next High-Value Work

The next patch should not spoof success blindly. The useful next targets are:

- Instrument PM99's own validation returns around `0x00676250`, `0x00676770`,
  `0x00676C00`, and helper calls near the mode-table/device validation path.
- Test whether a shim can safely normalize the startup `GetDisplayMode` result
  to PM99's expected `640x480x16` before PM99's validation runs.
- Investigate the `SCREEN POSITION: 44, 44` interaction with the wrapped
  `4294967252 x 4294967252` surface request in windowed mode.
- Only after that, try a targeted fix: either clamp/normalize the bad geometry
  or patch the exact PM99 validation branch that rejects a harmless larger
  desktop.

Do not revive the rejected forced-windowed patch as-is.
