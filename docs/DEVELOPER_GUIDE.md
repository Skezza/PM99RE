# Developer Guide — Tests, Scripts, CLI

> Snapshot note: canonical product developer guidance lives in `upstream/pm99-skezmod-db-editor/docs/DEVELOPER_GUIDE.md`.

Purpose
Concise engineering playbook for extending, testing, and safely shipping changes to the PM99 database editor and its documentation.

Audience
Engineers contributing code or docs. If you are just using the editor, read [docs/GETTING_STARTED.md](./GETTING_STARTED.md).

Repository layout (operational view)
- CLI and entrypoints
  - Entry: [cli.main()](../app/cli.py:89)
  - Commands: [cli.cmd_list()](../app/cli.py:10), [cli.cmd_search()](../app/cli.py:22), [cli.cmd_rename()](../app/cli.py:38), [cli.cmd_info()](../app/cli.py:74)
- I/O and record scanning
  - Class: [FDIFile](../app/io.py:15)
  - Load: [FDIFile.load()](../app/io.py:31)
  - Directory parse: [FDIFile._parse_directory()](../app/io.py:47)
  - Section scan and decode: [FDIFile._iter_records()](../app/io.py:63)
  - Convenience: [FDIFile.find_by_id()](../app/io.py:211), [FDIFile.find_by_name()](../app/io.py:229), [FDIFile.list_players()](../app/io.py:338)
- Models and serialization
  - Player structure: [PlayerRecord](../app/models.py:13)
  - Parser: [PlayerRecord.from_bytes()](../app/models.py:63)
  - Serializer overlay: [PlayerRecord.to_bytes()](../app/models.py:281)
  - Header & directory: [FDIHeader.from_bytes()](../app/models.py:389), [DirectoryEntry.from_bytes()](../app/models.py:434)
- Writer utilities
  - Backups: [file_writer.create_backup()](../app/file_writer.py:17)
  - Decoded text helper: [file_writer.replace_text_in_decoded()](../app/file_writer.py:32)
  - Safe record write + directory fixups: [file_writer.write_fdi_record()](../app/file_writer.py:102)
  - Post-write reopen check: [editor_actions.validate_database_files()](../app/editor_actions.py)
- GUI application
  - App entry: [main()](../pm99_database_editor.py:1189)

Toolchain and environment
- Python 3.8+ recommended
- OS: Windows 11 primary; POSIX should work for CLI/tests
- Run commands from the repository root
- Sample data: [DBDAT/](../DBDAT/)

Running the CLI locally
Examples:
```
# Inspect header and counts
python -m app info DBDAT/JUG98030.FDI

# List first 20 players
python -m app list DBDAT/JUG98030.FDI --limit 20

# Search by name
python -m app search DBDAT/JUG98030.FDI "Ronaldo"

# Rename by record id (same-length recommended)
python -m app rename DBDAT/JUG98030.FDI --id 123 --name "Cristiano Ronaldo"
```
Internals for reference: [cli.main()](../app/cli.py:89), [FDIFile.load()](../app/io.py:31), [FDIFile._iter_records()](../app/io.py:63).

Test suite
Invoke:
```
pytest -q
```
Key tests to consult when modifying I/O or models:
- Core decoding: [tests/test_core_io_decoding.py](../tests/test_core_io_decoding.py)
- Writer behavior and directory fixups: [tests/test_file_writer.py](../tests/test_file_writer.py)
- Integration/roundtrip: [tests/test_integration_roundtrip.py](../tests/test_integration_roundtrip.py)
- Debug and inspection helpers: [tests/test_debug_inspect.py](../tests/test_debug_inspect.py), [tests/test_hex_dump.py](../tests/test_hex_dump.py)
- Metadata, serialization edge-cases: [tests/test_metadata_edit.py](../tests/test_metadata_edit.py), [tests/test_serialization.py](../tests/test_serialization.py)

Scripts and analysis utilities
The scripts/ directory contains exploratory tools used during reverse engineering. They are useful for investigation but are not the canonical API surface. Prefer using the library API (FDIFile/PlayerRecord/file_writer) in product code and tests.

- Examples (non-exhaustive):
  - Player/coach parsing probes, record mappers, text extraction
  - Validation utilities for positions and attributes
- When using scripts:
  - Cross-check results with library calls (source of truth lives in [FDIFile](../app/io.py:15) and [PlayerRecord](../app/models.py:13))
  - If a script reveals a stable rule, migrate it into the library and document in [docs/DATA_FORMATS.md](./DATA_FORMATS.md)

Safe write path
Preferred approach to persist a modified record:
1) Parse and modify via model overlay
- Parse via library enumeration (e.g., [FDIFile._iter_records()](../app/io.py:63) → [PlayerRecord.from_bytes()](../app/models.py:63))
- Update fields on the model (position, nationality, DOB, attributes)
- Build decoded payload overlay via [PlayerRecord.to_bytes()](../app/models.py:281)
2) Write through file_writer
- Use [file_writer.write_fdi_record()](../app/file_writer.py:102) with the decoded payload and section offset
- This backs up the file and adjusts subsequent directory offsets and header.max_offset
3) Validate with CLI/tests
- Re-load and confirm the change is visible
- Ensure tests pass

Extending the parser (adding or hardening a field)
Follow this checklist:
- Identify anchor/bounds:
  - For decoded “clean” records, locate the name-end anchor `0x61 0x61 0x61 0x61` using [PlayerRecord._find_name_end()](../app/models.py:261)
  - Determine the stable offset window relative to the anchor or the tail window (attributes)
- Update model read/write:
  - Read logic: [PlayerRecord.from_bytes()](../app/models.py:63)
  - Write logic: [PlayerRecord.to_bytes()](../app/models.py:281)
  - Validate ranges and never write outside conservative bounds (e.g., ensure metadata offsets are < attribute start)
- Add tests:
  - Unit test cases in tests/ targeting the new field semantics
  - Integration roundtrip if the change affects writer flow
- Document:
  - Precisely record the byte rules in [docs/DATA_FORMATS.md](./DATA_FORMATS.md)
  - Note any heuristics or edge cases (e.g., “only write if anchor found”)
- Changelog:
  - Add an entry to [docs/CHANGELOG.md](./CHANGELOG.md)

Heuristics guardrails
- Default editor paths should prefer strict/parser-backed record sources; keep heuristic discovery as fallback or investigation-only.
- Do not promote heuristic/reconciled findings (for example Wikipedia-assisted slot interpretation) as parser contract truth.
- If byte semantics are not proven end-to-end (anchor, offsets, decode, write/reopen invariants), mark the lane `FAIL` and document the blocker explicitly.
- Upstream-facing handovers must only contain 100% contract-backed fields; candidate/iffy fields must be isolated as unresolved research output.
- Do not write if you cannot find the name-end anchor (keep original bytes)
- Attributes only within the tail window `len-19 .. len-7`
- Only write values in valid ranges (e.g., position 0..3). Prefer not to coerce silently.
- If a structure differs, preserve unknown bytes by overlaying on [PlayerRecord.raw_data](../app/models.py:59)

Debugging tips
- Print header/directory values via the CLI ([cli.cmd_info()](../app/cli.py:74)) for sanity checks
- When a modified record is not visible:
  - Confirm [PlayerRecord.to_bytes()](../app/models.py:281) actually changed the intended offsets (print diff in a test)
  - Validate [file_writer.write_fdi_record()](../app/file_writer.py:102) adjusted directory offsets as expected
- Use Latin-1 when decoding text bytes for investigation
- Keep a copy of the original file; compare with a hex diff if needed

Documentation policy (canonical vs legacy)
- Canonical: docs/ (concise and maintained)
  - Entrypoints: [docs/CURRENT_ROADMAP.md](./CURRENT_ROADMAP.md), [docs/GETTING_STARTED.md](./GETTING_STARTED.md), [docs/ARCHITECTURE.md](./ARCHITECTURE.md), [docs/DATA_FORMATS.md](./DATA_FORMATS.md), [docs/EDITOR_README.md](./EDITOR_README.md)
  - Narrative summary: [docs/REVERSE_ENGINEERING_REPORT.md](./REVERSE_ENGINEERING_REPORT.md)
- Legacy: docs/archive/ and session logs in docs/ preserved for traceability
  - Useful as references (triangulation, verify snapshots)
  - Do not extend; migrate material into canonical docs as rules solidify

Code style and review checklist
- Tests: `pytest -q` passes locally
- Safety:
  - Writes go through [file_writer.write_fdi_record()](../app/file_writer.py:102) or [FDIFile.save()](../app/io.py:269)
  - Unknown bytes preserved; anchor checks in place
- Docs:
  - Update [docs/DATA_FORMATS.md](./DATA_FORMATS.md) for any new or changed byte rule
  - Update [docs/CHANGELOG.md](./CHANGELOG.md) for user-facing or structural changes
- References:
  - Prefer linking to concrete code anchors: e.g., [FDIFile._iter_records()](../app/io.py:63) instead of broad descriptions

Appendix: common tasks

List a player’s parsed record in a REPL
```
python -q
>>> from app.io import FDIFile
>>> f = FDIFile("DBDAT/JUG98030.FDI"); f.load()
>>> f.records[0]
```
See: [FDIFile](../app/io.py:15), [PlayerRecord](../app/models.py:13)

Prepare and persist a targeted decoded text replacement (advanced)
- Generate a modified decoded payload with [file_writer.replace_text_in_decoded()](../app/file_writer.py:32)
- Persist via [file_writer.write_fdi_record()](../app/file_writer.py:102)

Where to raise questions
- Start with canonical docs in this folder
- Cross-check with docs/archive/ artifacts if you need historical context
- Use code anchors:
  - Scan: [FDIFile._iter_records()](../app/io.py:63)
  - Parse: [PlayerRecord.from_bytes()](../app/models.py:63)
  - Write: [file_writer.write_fdi_record()](../app/file_writer.py:102)
  - CLI: [cli.main()](../app/cli.py:89)
