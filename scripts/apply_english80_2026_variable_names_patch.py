#!/usr/bin/env python3
"""Apply full variable-length source names to the English 80 current-squad build.

The 2026 FootballSquads build intentionally used runtime-safe shortened names
for broad game stability. This proof layer rewrites the 1,600 allocated linked
JUG records with full source-backed names and lets the indexed FDI writer grow
payloads where the compact name region needs more room.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import struct
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
EDITOR_ROOT = REPO_ROOT / "upstream" / "pm99-skezmod-db-editor"
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.editor_actions import _IndexedRawStageRecord, write_player_staged_records  # noqa: E402
from app.editor_helpers import _player_display_name  # noqa: E402
from app.eq_jug_linked import load_eq_linked_team_rosters  # noqa: E402
from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from app.models import PlayerRecord  # noqa: E402
from assert_pm99_isolated_input import sha256  # noqa: E402
from apply_stoke_2015_current_order_physical_variable_names_patch import _read_clone_fields  # noqa: E402
from apply_stoke_2015_role_preserved_compact_variable_patch import (  # noqa: E402
    _compact_segments,
    _name_prefix,
    _role_byte,
)
from apply_stoke_2015_semantic_runtime_patch import SKILL_LABELS  # noqa: E402
from build_english80_2026_football_squads import (  # noqa: E402
    SOURCE_MONONYM_ALIASES,
    _ascii,
    _json_dump,
)


DEFAULT_INPUT_BUILD = (
    REPO_ROOT
    / "work"
    / "pm99"
    / "english80_2026_division_structured"
    / "english80_2026_division_structured_20260501T212554Z"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "work" / "pm99" / "english80_2026_variable_names"


def _norm(value: str) -> str:
    return "".join(ch for ch in _ascii(str(value or "")).casefold() if ch.isalnum())


def _source_game_name(source_name: str) -> str:
    ascii_name = _ascii(source_name)
    expanded = SOURCE_MONONYM_ALIASES.get(ascii_name, ascii_name)
    return " ".join(expanded.split())


def _encode_byte(value: int) -> int:
    if not 0 <= int(value) <= 255:
        raise ValueError(f"Byte value out of range: {value}")
    return int(value) ^ 0x61


def _write_decoded_byte(payload: bytearray, offset: int, value: int) -> None:
    if offset < 0 or offset >= len(payload):
        raise RuntimeError(f"Offset {offset} outside payload length {len(payload)}")
    payload[offset] = _encode_byte(value)


def _expected_clone_fields(source_row: dict[str, Any]) -> dict[str, Any]:
    year_bytes = struct.pack("<H", int(source_row["birth_year"]))
    primary_role = int(list(source_row["fine_role_codes"])[0])
    return {
        "ui_primary_role_code": primary_role,
        "visible_nationality_code": int(source_row["pm99_nat_code"]),
        "parser_position_code": int(source_row["pm99_position_code"]),
        "visible_position_code": int(source_row["pm99_position_code"]),
        "birth_day": int(source_row["birth_day"]),
        "birth_month": int(source_row["birth_month"]),
        "birth_year": year_bytes[0] | (year_bytes[1] << 8),
        "height_cm": int(source_row["height_cm"]),
        "weight_kg": int(source_row["weight_kg"]),
        "skills": dict(source_row["skills"]),
    }


def _assert_expected_fields(actual: dict[str, Any], expected: dict[str, Any], player_name: str) -> None:
    comparable = {key: actual[key] for key in expected}
    if comparable != expected:
        raise RuntimeError(
            f"Metadata readback mismatch for {player_name!r}: expected {expected!r}, got {comparable!r}"
        )


def _patch_physical_variable_payload(decoded: bytes, source_row: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    if decoded[2:5] != b"\xdd\x63\x60":
        raise RuntimeError(f"Expected dd6360 compact payload, got {decoded[2:5].hex()}")

    parsed_before = PlayerRecord.from_bytes(decoded, 0)
    old_display_name = " ".join(_player_display_name(parsed_before).split())
    segments = _compact_segments(decoded)
    old_name_end = int(segments["name_end"])
    old_role_start = old_name_end - 3
    old_tail_start = old_role_start + 8
    old_payload_length = len(decoded)
    if old_tail_start > old_payload_length:
        raise RuntimeError(f"Compact role/metadata block overruns payload for {old_display_name!r}")

    target_name = _source_game_name(str(source_row["source_name"]))
    prefix = _name_prefix(target_name)
    first_len_offset = int(segments["first_len_offset"])
    new_role_start = first_len_offset + len(prefix)
    new_name_end = new_role_start + 3
    fixed_padding_removed = old_role_start - new_role_start

    primary_role = int(list(source_row["fine_role_codes"])[0])
    primary_role_byte = _role_byte(primary_role)
    role_block = bytearray(
        [
            primary_role_byte,
            0x61,
            primary_role_byte,
            0x61,
            0x61,
            0x61,
            0x61,
            0x61,
        ]
    )
    tail = decoded[old_tail_start:]

    patched = bytearray()
    patched.extend(decoded[:first_len_offset])
    patched.extend(prefix)
    patched.extend(role_block)
    patched.extend(tail)

    natural_payload_length = len(patched)
    tail_padding_bytes = max(0, old_payload_length - natural_payload_length)
    if tail_padding_bytes:
        patched.extend(b"\x61" * tail_padding_bytes)
    if len(patched) < old_payload_length:
        raise RuntimeError(f"Payload shrank unexpectedly for {target_name!r}")

    _write_decoded_byte(patched, new_name_end + 5, int(source_row["pm99_nat_code"]))
    _write_decoded_byte(patched, new_name_end + 7, int(source_row["pm99_position_code"]))
    _write_decoded_byte(patched, new_name_end + 8, int(source_row["pm99_position_code"]))
    _write_decoded_byte(patched, new_name_end + 9, int(source_row["birth_day"]))
    _write_decoded_byte(patched, new_name_end + 10, int(source_row["birth_month"]))
    year_bytes = struct.pack("<H", int(source_row["birth_year"]))
    _write_decoded_byte(patched, new_name_end + 11, year_bytes[0])
    _write_decoded_byte(patched, new_name_end + 12, year_bytes[1])
    _write_decoded_byte(patched, new_name_end + 13, int(source_row["height_cm"]))
    _write_decoded_byte(patched, new_name_end + 14, int(source_row["weight_kg"]))
    for index, label in enumerate(SKILL_LABELS):
        _write_decoded_byte(patched, new_name_end + 15 + index, int(source_row["skills"][label]))

    parsed_after = PlayerRecord.from_bytes(bytes(patched), 0)
    applied_name = " ".join(_player_display_name(parsed_after).split())
    parser_name_end = PlayerRecord._find_name_end(bytes(patched))
    if parser_name_end != new_name_end:
        raise RuntimeError(
            f"Parser name_end mismatch for {target_name!r}: expected {new_name_end}, got {parser_name_end}"
        )
    if _norm(applied_name) != _norm(target_name):
        raise RuntimeError(f"Patched payload reparsed as {applied_name!r}, expected {target_name!r}")

    fields = _read_clone_fields(bytes(patched), new_name_end)
    expected = _expected_clone_fields(source_row)
    _assert_expected_fields(fields, expected, target_name)

    return bytes(patched), {
        "old_name": old_display_name,
        "source_name": str(source_row["source_name"]),
        "target_name": target_name,
        "applied_name": applied_name,
        "old_payload_length": old_payload_length,
        "new_payload_length": len(patched),
        "payload_length_delta": len(patched) - old_payload_length,
        "natural_payload_length": natural_payload_length,
        "tail_padding_bytes": tail_padding_bytes,
        "old_name_end": old_name_end,
        "new_name_end": new_name_end,
        "name_end_delta": new_name_end - old_name_end,
        "first_len_offset": first_len_offset,
        "old_role_start": old_role_start,
        "new_role_start": new_role_start,
        "fixed_padding_removed": fixed_padding_removed,
        "prefix_length": len(prefix),
        "fields": fields,
    }


def _load_sources(path: Path) -> dict[tuple[str, int], dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: dict[tuple[str, int], dict[str, Any]] = {}
    for club in payload.get("clubs", []):
        club_key = str(club["club_key"])
        for player in club.get("players", []):
            slot = int(player["slot"])
            rows[(club_key, slot)] = {**player, "club_key": club_key, "club_name": str(club["display_name"])}
    if len(rows) != 1600:
        raise RuntimeError(f"Expected 1,600 source rows, got {len(rows)}")
    return rows


def _updated_assignment(base_assignment: dict[str, Any], source_rows: dict[tuple[str, int], dict[str, Any]]) -> dict[str, Any]:
    output = json.loads(json.dumps(base_assignment))
    output["schema"] = "pm99-english80-variable-names-slot-assignment-v1"
    output["variable_name_policy"] = {
        "source": "FootballSquads source_name, ASCII-normalized, mononym-expanded where needed",
        "writer": "dd6360 compact physical variable name with indexed FDI payload growth",
    }
    for assignment in output.get("assignments", []):
        club_key = str(assignment.get("target_club_key") or assignment.get("club_key") or "")
        for row in assignment.get("roster", []):
            slot = int(row.get("slot") or 0)
            source = source_rows[(club_key, slot)]
            full_name = _source_game_name(str(source["source_name"]))
            row["target_name"] = full_name
            row["applied_name"] = full_name
            row["source_target_name"] = source["source_name"]
            row["variable_name_source"] = "football_squads_source_name"
    return output


def _updated_world(base_world: dict[str, Any], source_rows: dict[tuple[str, int], dict[str, Any]]) -> dict[str, Any]:
    output = json.loads(json.dumps(base_world))
    output["schema"] = "pm99-english80-variable-names-world-v1"
    scope = dict(output.get("scope") or {})
    scope["name_policy"] = "full source-backed variable-length player names"
    output["scope"] = scope
    for player in output.get("players", []):
        club_key = str(player.get("club_key") or "")
        slot = int(player.get("slot") or 0)
        source = source_rows.get((club_key, slot))
        if not source:
            continue
        player["set_name"] = _source_game_name(str(source["source_name"]))
        player["source_name"] = source["source_name"]
        player["variable_name_source"] = "football_squads_source_name"
    return output


def _write_readback_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "club_key",
        "club_name",
        "slot",
        "pid",
        "source_name",
        "target_name",
        "applied_name",
        "old_name",
        "old_payload_length",
        "new_payload_length",
        "payload_length_delta",
        "old_name_end",
        "new_name_end",
        "name_end_delta",
        "source_url",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _resolve_base_build(path: str) -> Path:
    base = Path(path).expanduser().resolve()
    if not base.is_dir():
        raise FileNotFoundError(base)
    return base


def build(args: argparse.Namespace) -> dict[str, Any]:
    base_build = _resolve_base_build(args.input_build)
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else Path(args.output_root).expanduser().resolve()
        / f"english80_2026_variable_names_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    )
    if output_dir.exists():
        if not args.force:
            raise FileExistsError(output_dir)
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    base_game = base_build / "game"
    out_game = output_dir / "game"
    shutil.copytree(base_game, out_game, symlinks=True)

    source_ledger_path = base_build / "football_squads_source_ledger.json"
    assignment_path = base_build / "slot_assignment_english80_2026_division_structured.json"
    world_path = base_build / "world_english80_2026_division_structured.json"
    repointed_manifest_path = out_game / "repointed_roster_manifest.json"
    for path in (source_ledger_path, assignment_path, world_path, repointed_manifest_path):
        if not path.is_file():
            raise RuntimeError(f"Missing required input: {path}")

    source_rows = _load_sources(source_ledger_path)
    assignment = _updated_assignment(json.loads(assignment_path.read_text(encoding="utf-8")), source_rows)
    world = _updated_world(json.loads(world_path.read_text(encoding="utf-8")), source_rows)
    output_assignment_path = output_dir / "slot_assignment_english80_2026_variable_names.json"
    output_world_path = output_dir / "world_english80_2026_variable_names.json"
    output_source_path = output_dir / "football_squads_source_ledger.json"
    _json_dump(output_assignment_path, assignment)
    _json_dump(output_world_path, world)
    shutil.copy2(source_ledger_path, output_source_path)

    player_file = out_game / "DBDAT" / "JUG98030.FDI"
    team_file = out_game / "DBDAT" / "EQ98030.FDI"
    coach_file = out_game / "DBDAT" / "ENT98030.FDI"
    file_data = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(file_data)
    entries_by_id = {int(entry.record_id): entry for entry in indexed.entries}
    repointed = json.loads(repointed_manifest_path.read_text(encoding="utf-8"))

    stages: list[tuple[int, _IndexedRawStageRecord]] = []
    readback_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for allocation in repointed.get("allocations", []):
        club_key = str(allocation["club_key"])
        slot = int(allocation["slot"])
        pid = int(allocation["new_record_id"])
        source = source_rows[(club_key, slot)]
        entry = entries_by_id.get(pid)
        if entry is None:
            failures.append({**allocation, "failure": "missing_jug_entry"})
            continue
        decoded = entry.decode_payload(file_data)
        try:
            patched, meta = _patch_physical_variable_payload(decoded, source)
        except Exception as exc:
            failures.append({**allocation, "source_name": source.get("source_name"), "failure": str(exc)})
            continue
        stages.append(
            (
                int(entry.payload_offset),
                _IndexedRawStageRecord(
                    raw_payload=patched,
                    container_offset=int(entry.payload_offset),
                    container_length=int(entry.payload_length),
                ),
            )
        )
        readback_rows.append(
            {
                "club_key": club_key,
                "club_name": source["club_name"],
                "slot": slot,
                "pid": pid,
                "source_url": source["source_url"],
                **meta,
            }
        )

    if failures:
        _json_dump(output_dir / "variable_name_failures.json", failures)
        raise RuntimeError(f"Failed to patch {len(failures)} rows; see {output_dir / 'variable_name_failures.json'}")

    backup_path = write_player_staged_records(str(player_file), stages, create_backup_before_write=True)

    post_data = player_file.read_bytes()
    post_index = IndexedFDIFile.from_bytes(post_data)
    post_by_id = {int(entry.record_id): entry for entry in post_index.entries}
    post_failures: list[dict[str, Any]] = []
    for row in readback_rows:
        entry = post_by_id.get(int(row["pid"]))
        if entry is None:
            post_failures.append({**row, "failure": "post_missing_jug_entry"})
            continue
        decoded = entry.decode_payload(post_data)
        parsed = PlayerRecord.from_bytes(decoded, int(entry.payload_offset))
        applied_name = " ".join(_player_display_name(parsed).split())
        parser_name_end = PlayerRecord._find_name_end(decoded)
        actual_length = int(entry.payload_length)
        if (
            _norm(applied_name) != _norm(str(row["target_name"]))
            or int(parser_name_end or -1) != int(row["new_name_end"])
            or actual_length != int(row["new_payload_length"])
        ):
            post_failures.append(
                {
                    **row,
                    "failure": "post_readback_mismatch",
                    "post_applied_name": applied_name,
                    "post_name_end": parser_name_end,
                    "post_payload_length": actual_length,
                }
            )

    rosters = list(load_eq_linked_team_rosters(team_file=str(team_file), player_file=str(player_file)))
    visible_by_eq_slot: dict[tuple[int, int], str] = {}
    for roster in rosters:
        eq_id = int(getattr(roster, "eq_record_id", 0) or 0)
        for linked_row in list(getattr(roster, "rows", []) or []):
            visible_by_eq_slot[(eq_id, int(getattr(linked_row, "slot_index", 0) or 0) + 1)] = " ".join(
                str(getattr(linked_row, "player_name", "") or "").split()
            )
    for allocation in repointed.get("allocations", []):
        source = source_rows[(str(allocation["club_key"]), int(allocation["slot"]))]
        expected = _source_game_name(str(source["source_name"]))
        actual = visible_by_eq_slot.get((int(allocation["carrier_eq_record_id"]), int(allocation["slot"])), "")
        if _norm(actual) != _norm(expected):
            post_failures.append(
                {
                    "club_key": allocation["club_key"],
                    "slot": int(allocation["slot"]),
                    "pid": int(allocation["new_record_id"]),
                    "failure": "linked_roster_visible_name_mismatch",
                    "expected": expected,
                    "actual": actual,
                }
            )

    readback_json = output_dir / "variable_name_readback.json"
    readback_csv = output_dir / "variable_name_readback.csv"
    _json_dump(readback_json, readback_rows)
    _write_readback_csv(readback_csv, readback_rows)
    if post_failures:
        _json_dump(output_dir / "variable_name_post_failures.json", post_failures)

    payload_deltas = Counter(int(row["payload_length_delta"]) for row in readback_rows)
    name_end_deltas = Counter(int(row["name_end_delta"]) for row in readback_rows)
    source_payload = json.loads(source_ledger_path.read_text(encoding="utf-8"))
    source_urls = sorted({str(club.get("source_url") or "") for club in source_payload.get("clubs", []) if club.get("source_url")})
    manifest = {
        "schema": "pm99-english80-2026-variable-player-names-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "ok": not post_failures,
        "input_build": str(base_build),
        "output_dir": str(output_dir),
        "game_root": str(out_game),
        "assignment": str(output_assignment_path),
        "world_state": str(output_world_path),
        "source_ledger": str(output_source_path),
        "readback_json": str(readback_json),
        "readback_csv": str(readback_csv),
        "backup_path": str(backup_path) if backup_path else None,
        "club_count": 80,
        "player_count": len(readback_rows),
        "failure_count": len(post_failures),
        "failures": post_failures[:100],
        "payload_length_delta_counts": dict(sorted(payload_deltas.items())),
        "payload_grew_count": sum(1 for row in readback_rows if int(row["payload_length_delta"]) > 0),
        "payload_same_count": sum(1 for row in readback_rows if int(row["payload_length_delta"]) == 0),
        "payload_shrank_count": sum(1 for row in readback_rows if int(row["payload_length_delta"]) < 0),
        "max_payload_length_delta": max(int(row["payload_length_delta"]) for row in readback_rows),
        "name_end_delta_counts": dict(sorted(name_end_deltas.items())),
        "variable_name_end_count": sum(1 for row in readback_rows if int(row["name_end_delta"]) != 0),
        "source_url_count": len(source_urls),
        "source_urls": source_urls,
        "hashes": {
            "EQ98030.FDI": sha256(team_file),
            "JUG98030.FDI": sha256(player_file),
            "ENT98030.FDI": sha256(coach_file),
        },
    }
    _json_dump(output_dir / "variable_name_build_manifest.json", manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-build", default=str(DEFAULT_INPUT_BUILD))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    manifest = build(parse_args())
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if manifest["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
