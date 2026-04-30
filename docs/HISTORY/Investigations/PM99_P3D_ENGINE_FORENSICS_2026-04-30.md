# PM99 P3D Engine Forensics - 2026-04-30

## Scope

This pass investigated the P3D-like binary records discovered in SIMULDAT PKF
files and tied them back to concrete `MANAGPRE.EXE` loader/writer code.

## Corpus Findings

- 190 P3D-like records were found across 99 PKFs in `.local/iso/Simuldat`.
- They appear only in `Modelos.pkf`, `Camaras.pkf`, `Cespedes.pkf`, and
  `Estadios/*.pkf`.
- Observed families after loader-aware decoding:
  - `fe...records@4`: 63 records.
  - `fd...00-records@8`: 115 records.
  - `fd...01-records@32`: 12 records.
- `fd...00` dominates stadium records; `fd...01` carries an optional six-dword
  header before the first disk record; `fe...` carries record data immediately
  after the marker.
- Common extracted labels include `1-CUPULA01`, `1A-FONDO01`, `Box01`,
  `Box02`, `A-CESPED01`, `Bandera`, and `BANDERA`.
- The first inner body marker after the first `0x80` object header is mostly
  `-6` for `fe...` records and `-8` for `fd...` records.

## EXE Evidence

Ghidra and local disassembly identify these relevant routines:

- `0x0069E520` / `pm99_p3d_resource_reset_and_load`: clears existing runtime
  entries, frees old storage, and loads a path.
- `0x0069E590` / `pm99_p3d_parse_loaded_buffer`: parses an already-loaded
  buffer. It has a special `-7` branch that copies fixed `0x80` byte records
  into a stack buffer.
- `0x0069E700` / `pm99_p3d_load_file_then_parse`: loads a P3D path and parses
  marker/header fields. It computes `(-first_dword) & 0x7fffff`, so
  `0xff7ffffe` decodes to 2 and `0xff7ffffd` decodes to 3.
- `0x0069ECE0` / `FUN_69ece0_sigfd_candidate`: writer-side evidence. It writes
  marker `0xff7ffffd`, writes a 4-byte optional flag, conditionally writes two
  12-byte blocks, then writes one `0x80` byte disk record per runtime object
  while stepping runtime memory by `0x1e0`.
- `0x0069ECB0`: fuller writer entry. It opens the output with `fopen(...,
  "wb")`, uses `fwrite` for the marker/header/records, and closes with
  `fclose`.
- `0x0069ED80` / `pm99_p3d_parse_chunk_and_insert`: consumes a single `0x80`
  disk chunk, creates/resets a temporary runtime object, binary-searches the
  existing runtime list by name, inserts if missing, and returns the `0x1e0`
  runtime entry address.
- `0x00697890` / `pm99_p3d_object_reset_from_buffer`: initializes a runtime
  entry and copies/uppercases the chunk-leading string.
- `0x006A0750` / `pm99_p3d_runtime_entry_copy_ctor`: copies a full `0x1e0`
  runtime entry, including three 0x80 string regions and several dynamic
  subarrays.

Concrete path/callsite strings include `simuldat\modelos\medium.p3d`,
`flag.p3d`, `card.p3d`, `large.p3d`, `flechajugador.p3d`, `camara.p3d`,
`target.p3d`, `estadio.p3d`, and `states.tbl`.

## Practical Meaning

This is not player/team database data. It is the match visual asset layer:
stadium shells, grass/terrain, cameras, flags, cards, ball/props, and player
marker-style models.

The immediate value is tooling and asset inspection:

- The PKF viewer can now distinguish P3D families instead of showing one vague
  `P3D-like binary` label.
- It can show loader-derived fields: decoded marker count, optional header flag,
  optional dwords, record-stream offset, `0x80` chunk estimates, duplicate
  payload count, first inner body marker, detected chunk-name samples, ASCII
  labels, and float-density clues.
- `scripts/probe_pm99_p3d_assets.py` reproduces the corpus summary as JSON.

## Remaining Unknowns

- The exact field layout inside each `0x80` disk record is not fully decoded.
- The relationship between `0x80` disk records and `0x1e0` runtime entries is
  now proven by writer/copy code, but individual dynamic-array members need
  deeper decompilation.
- Some PKF record lengths have trailing bytes after the loader-derived
  `0x80` chunk floor. Those may be secondary sections, parser padding, or a
  limitation of the current PKF table slicing.

## Next High-Value Experiments

- Decode one `0x80` record family field-by-field using `0x0069ED80` and
  `0x00697C70`.
- Decode inner marker bodies for `-5`, `-6`, `-8`, `-9`, and `-10`, preserving
  the writer's odd-count 2-byte padding behavior.
- Build a non-rendering structural view that lists each inferred `0x80` record
  as a row with label, first floats, first integers, and probable transform
  fields.
- Compare duplicate stadium payloads to find reusable templates.
- Only after record fields are understood, consider a WebGL previewer.
