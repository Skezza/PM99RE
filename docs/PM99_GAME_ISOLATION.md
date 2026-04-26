# PM99 Game Isolation

## Purpose

PM99RE now treats the installed game as a derived artifact, not shared working
state. The old `.local/premier-manager-ninety-nine` tree is considered unsafe
because multiple experiments can silently mutate it.

The supported model is:

1. one immutable local pristine fixture extracted from the original ZIP
2. one writable isolated run root per worker/run
3. all game edits applied only inside that isolated run root or a derived output
   folder under `work/`

## Canonical Paths

- Pristine fixture:
  `work/fixtures/premier-manager-ninety-nine-pristine/`
- Fixture manifest:
  `work/fixtures/premier-manager-ninety-nine-pristine.manifest.json`
- Isolated runs:
  `work/pm99/<worker-id>/<run-id>/`

Each isolated run contains:

- `game/`
- `artifacts/`
- `patches/`
- `run_manifest.json`

## Standard Workflow

Create or refresh the fixture, then materialize a writable run:

```bash
./scripts/create_pm99_isolated_run.sh --worker-id "$USER" --run-id stoke_faces
```

Validate an input explicitly:

```bash
python3 ./scripts/assert_pm99_isolated_input.py --fixture-root ./work/fixtures/premier-manager-ninety-nine-pristine
python3 ./scripts/assert_pm99_isolated_input.py --game-root ./work/pm99/$USER/stoke_faces/game --require-writable
python3 ./scripts/assert_pm99_isolated_input.py --dbdat-dir ./work/pm99/$USER/stoke_faces/game/DBDAT
```

Use the isolated run in downstream scripts:

```bash
python3 ./scripts/stoke_2015_apply_metadata.py \
  --game-root ./work/pm99/$USER/stoke_faces/game \
  --output-dir ./work/pm99/$USER/stoke_faces/patches/stoke_metadata

python3 ./scripts/prepare_stoke_2015_face_dbdat.py \
  --game-root ./work/pm99/$USER/stoke_faces/game \
  --output-dir ./work/pm99/$USER/stoke_faces/patches/stoke_faces
```

For remote validation, point the runner wrapper at an isolated game root or a
derived DBDAT directory. Late injection is now debug-only and must be opted into
explicitly.

## Provenance

The fixture manifest records:

- source ZIP path/hash
- MFC42 DLL path/hash
- core file hashes for `MANAGPRE.EXE`, `JUG98030.FDI`, `EQ98030.FDI`,
  `MINIFOTO.PKF`

Each `run_manifest.json` records:

- `run_id`
- `worker_id`
- fixture path + manifest path
- isolated `game/`, `artifacts/`, `patches/` roots
- initial core file hashes

Derived scripts should keep writing their own step manifests under the isolated
run or patch output they control.

## Rules

- Do not read from `.local/premier-manager-ninety-nine`.
- Do not write into the pristine fixture.
- Do not share isolated run roots between workers.
- Use explicit `--game-root` or `--dbdat-dir` inputs for mutating workflows.
