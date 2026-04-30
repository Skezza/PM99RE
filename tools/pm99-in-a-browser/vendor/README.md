# Local Vendor Runtimes

Ignored emulator builds go here.

Suggested layout:

- `vendor/v86/`
  - `libv86.js`
  - `v86.wasm` or whatever matching build assets your v86 build requires
- `vendor/boxedwine/`
  - `boxedwine.js`
  - `boxedwine.wasm`
  - `boxedwine.data` if produced by the build
  - Wine filesystem ZIPs used by your BoxedWine build

Keep licenses with downloaded vendor payloads locally. Do not commit the vendor
payloads from this research workspace.
