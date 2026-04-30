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

1. Place v86 runtime files under `vendor/v86/`.
2. Place BIOS files and a local Windows 98/2000 disk image under `assets/v86/`.
3. Copy `config/v86.sample.json` to `config/v86.local.json`.
4. Adjust disk image URL and size.
5. Launch from the v86 tab.

Record:

- browser load time
- guest boot time
- whether `assets/pm99.iso` appears in the guest
- Windows color depth
- PM99 launch outcome
