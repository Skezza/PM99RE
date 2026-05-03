# Test Plan

## Baseline Asset Check

```bash
cd tools/pm99-in-a-browser
./scripts/prepare_pm99_assets.sh --source ../../work/fixtures/premier-manager-ninety-nine-pristine
python3 scripts/validate_assets.py --pm99-root assets/pm99
./scripts/serve.sh
```

Open `http://127.0.0.1:8099/` and confirm the asset panel shows:

- PM99 manifest present
- required PM99 files present
- sample configs present

## BoxedWine Gate

1. Place a local BoxedWine Emscripten build under `vendor/boxedwine/`.
2. Copy `config/boxedwine.sample.json` to `config/boxedwine.local.json`.
3. Adjust `moduleScriptUrl`, filesystem ZIP names, and arguments for that build.
4. Launch from the BoxedWine tab.

Record the first failure stage:

- module load
- filesystem preload
- Wine boot
- drive mount
- `MANAGPRE.EXE` process start
- DirectDraw/display mode
- title screen reached

## v86 Gate

1. Run `npm run payloads:open` to stage the redistributable v86 runtime and BIOS
   files.
2. Prepare a local Windows 98 disk with `scripts/prepare_win98_disk.sh`; see
   `docs/WIN98_DISK.md`.
3. Inject PM99 into the installed FAT partition with
   `scripts/inject_pm99_into_win98_disk.py`.
4. Launch the `Windows 98 + PM99` profile from the v86 tab.

Record:

- browser load time
- guest boot time
- whether `assets/pm99.iso` appears in the guest
- Windows color depth
- PM99 launch outcome
