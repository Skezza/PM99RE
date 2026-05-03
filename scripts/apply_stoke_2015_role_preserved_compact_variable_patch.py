#!/usr/bin/env python3
"""Role-preserved Stoke 2015 variable-name patch for runtime-safe compact clones.

This is the runtime-oriented fallback after direct variable-length rewrites of
the original pristine Stoke ``dd6361`` records proved static-valid but tripped
MANAGPRE's startup gate. It starts from the previously runner-proven compact
clone candidate, keeps Stoke roster slots in place, and rewrites each slot's
compact ``dd6360`` clone payload with an exact variable-length name segment for
the 2015 player that matches the original pristine slot role.
"""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
EDITOR_ROOT = REPO_ROOT / "upstream" / "pm99-skezmod-db-editor"
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.editor_actions import (  # noqa: E402
    _IndexedRawStageRecord,
    _cp1252_bytes,
    _split_display_name_for_linked_payload,
    write_player_staged_records,
)
from app.editor_helpers import _player_display_name  # noqa: E402
from app.eq_jug_linked import load_eq_linked_team_rosters  # noqa: E402
from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from app.models import PlayerRecord  # noqa: E402
from assert_pm99_isolated_input import sha256  # noqa: E402
from apply_stoke_2015_semantic_runtime_patch import (  # noqa: E402
    POSITION_LABEL,
    SKILL_LABELS,
    _read_clone_fields,
)
from apply_stoke_2015_variable_names_runtime_patch import (  # noqa: E402
    ROLE_ORDER,
    TARGET_NAMES_BY_ROLE,
    _encode_byte,
    _extract_nationality_codes,
    _norm,
    _target_source_rows,
    _write_decoded_byte,
)


PRISTINE_SLOT_ROLE_BY_SLOT = {
    1: "D",
    2: "F",
    3: "D",
    4: "D",
    5: "G",
    6: "M",
    7: "M",
    8: "F",
    9: "M",
    10: "M",
    11: "F",
    12: "D",
    13: "M",
    14: "D",
    15: "G",
    16: "D",
    17: "M",
    18: "F",
    19: "D",
    20: "M",
}


def _parse_args() -> argparse.Namespace:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-game",
        default=str(REPO_ROOT / ".local" / "stoke_2015_stats_backfill_20260501T065744Z"),
        help="Runner-proven compact clone game root.",
    )
    parser.add_argument(
        "--out-game",
        default=str(REPO_ROOT / ".local" / f"stoke_2015_compact_variable_names_{stamp}"),
        help="Output game root to create.",
    )
    parser.add_argument("--team-query", default="Stoke")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _resolve_roster(team_file: Path, player_file: Path, team_query: str) -> list[dict[str, Any]]:
    needle = team_query.casefold()
    for roster in load_eq_linked_team_rosters(team_file=str(team_file), player_file=str(player_file)):
        names = [
            str(getattr(roster, "short_name", "") or "").casefold(),
            str(getattr(roster, "full_club_name", "") or "").casefold(),
        ]
        if not any(needle in item for item in names):
            continue
        rows = sorted(list(getattr(roster, "rows", []) or []), key=lambda row: int(getattr(row, "slot_index", 0)))
        return [
            {
                "slot": int(getattr(row, "slot_index", 0)) + 1,
                "pid": int(getattr(row, "player_record_id", 0) or 0),
                "linked_player_name": str(getattr(row, "player_name", "") or ""),
                "eq_record_id": int(getattr(roster, "eq_record_id", 0) or 0),
                "team_name": str(getattr(roster, "short_name", "") or ""),
                "full_club_name": str(getattr(roster, "full_club_name", "") or ""),
            }
            for row in rows[:20]
        ]
    raise RuntimeError(f"Could not resolve roster for {team_query!r}")


def _compact_segments(payload: bytes) -> dict[str, int]:
    name_end = PlayerRecord._find_name_end(payload)
    if name_end is None:
        raise RuntimeError("Compact clone payload has no name_end marker")
    for first_len_offset in range(5, min(len(payload), 24)):
        surname_width = int(payload[first_len_offset] ^ 0x61)
        surname_start = first_len_offset + 2
        surname_end = surname_start + surname_width
        if not (1 <= surname_width <= 32):
            continue
        if first_len_offset + 1 >= len(payload) or payload[first_len_offset + 1] != 0x61:
            continue
        full_len_offset = surname_end
        if full_len_offset + 1 >= len(payload) or payload[full_len_offset + 1] != 0x61:
            continue
        full_width = int(payload[full_len_offset] ^ 0x61)
        full_start = full_len_offset + 2
        full_end = full_start + full_width
        if not (1 <= full_width <= 96 and full_end <= len(payload)):
            continue
        if int(full_end) + 3 == int(name_end):
            return {
                "first_len_offset": first_len_offset,
                "surname_start": surname_start,
                "surname_end": surname_end,
                "surname_width": surname_width,
                "full_len_offset": full_len_offset,
                "full_name_start": full_start,
                "full_name_end": full_end,
                "full_name_width": full_width,
                "name_end": int(name_end),
            }
    raise RuntimeError("Could not resolve compact clone name segments")


def _role_byte(role_code: int) -> int:
    if int(role_code) == 98:
        decoded = 0
    elif 0 <= int(role_code) <= 17:
        decoded = int(role_code) + 1
    else:
        raise ValueError(f"Fine role out of range: {role_code}")
    return _encode_byte(decoded)


def _name_prefix(name: str) -> bytes:
    given, surname = _split_display_name_for_linked_payload(name)
    given = " ".join(str(given or "").split())
    surname = " ".join(str(surname or "").split())
    if not given or not surname:
        raise ValueError(f"Name must include given and surname: {name!r}")
    # Native linked-player payloads carry a title-case alias surname followed by
    # a display name with the surname uppercased. Mixed-case display surnames
    # cause the fallback parser to concatenate the alias and display segments.
    full = f"{given} {surname.upper()}".strip()
    surname_bytes = _cp1252_bytes(surname)
    full_bytes = _cp1252_bytes(full)
    return (
        bytes([len(surname_bytes) ^ 0x61, 0x61])
        + surname_bytes
        + bytes([len(full_bytes) ^ 0x61, 0x61])
        + full_bytes
    )


def _patch_clone_payload(decoded: bytes, source_row: dict[str, Any], *, min_payload_length: int) -> tuple[bytes, dict[str, Any]]:
    if decoded[2:5] != b"\xdd\x63\x60":
        raise RuntimeError(f"Expected dd6360 compact clone payload, got {decoded[2:5].hex()}")
    parsed = PlayerRecord.from_bytes(decoded, 0)
    old_name = " ".join(_player_display_name(parsed).split())
    segments = _compact_segments(decoded)
    old_name_end = int(segments["name_end"])
    before = _read_clone_fields(decoded, old_name_end)
    primary_role = int(list(source_row["fine_role_codes"])[0])
    prefix = _name_prefix(str(source_row["game_name"]))
    role = _role_byte(primary_role)
    role_start = old_name_end - 3
    prefix_end = int(segments["first_len_offset"]) + len(prefix)
    if prefix_end > role_start:
        raise RuntimeError(
            f"Variable compact name for {source_row['game_name']!r} does not fit the "
            f"stable compact name window: prefix_end={prefix_end}, role_start={role_start}"
        )
    patched = bytearray()
    patched.extend(decoded[: int(segments["first_len_offset"])])
    patched.extend(prefix)
    patched.extend(b" " * (role_start - prefix_end))
    patched.extend(bytes([role, 0x61, role]))
    patched.extend(decoded[old_name_end:])
    new_name_end = old_name_end

    target_length = max(min_payload_length, len(decoded))
    if len(patched) > target_length:
        raise RuntimeError(
            f"Variable compact payload for {source_row['game_name']!r} grew beyond "
            f"the certified compact length: {len(patched)} > {target_length}"
        )
    if len(patched) < target_length:
        patched.extend(b"\x61" * (target_length - len(patched)))

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

    reparsed = PlayerRecord.from_bytes(bytes(patched), 0)
    applied_name = " ".join(_player_display_name(reparsed).split())
    if _norm(applied_name) != _norm(str(source_row["game_name"])):
        raise RuntimeError(f"Patched compact clone reparsed as {applied_name!r}")
    parser_name_end = PlayerRecord._find_name_end(bytes(patched))
    if parser_name_end != new_name_end:
        raise RuntimeError(
            f"Parser name_end mismatch for {source_row['game_name']!r}: "
            f"expected {new_name_end}, got {parser_name_end}"
        )
    after = _read_clone_fields(bytes(patched), parser_name_end)
    expected = {
        "visible_nationality_code": int(source_row["pm99_nat_code"]),
        "parser_position_code": int(source_row["pm99_position_code"]),
        "visible_position_code": int(source_row["pm99_position_code"]),
        "birth_day": int(source_row["birth_day"]),
        "birth_month": int(source_row["birth_month"]),
        "birth_year": int(source_row["birth_year"]),
        "height_cm": int(source_row["height_cm"]),
        "weight_kg": int(source_row["weight_kg"]),
        "skills": dict(source_row["skills"]),
    }
    actual = {key: after[key] for key in expected}
    if actual != expected:
        raise RuntimeError(f"Compact clone semantic readback mismatch for {source_row['game_name']!r}")
    return bytes(patched), {
        "old_name": old_name,
        "applied_name": applied_name,
        "old_payload_length": len(decoded),
        "new_payload_length": len(patched),
        "payload_length_delta": len(patched) - len(decoded),
        "old_name_end": old_name_end,
        "new_name_end": new_name_end,
        "old_segments": segments,
        "new_prefix_hex": prefix.hex(),
        "new_prefix_text": prefix.decode("cp1252", errors="replace"),
        "stable_name_window_padding_bytes": role_start - prefix_end,
        "before": before,
        "after": after,
    }


def _assign_targets(roster_rows: list[dict[str, Any]], source_by_name: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    queues = {role: [dict(source_by_name[name]) for name in names] for role, names in TARGET_NAMES_BY_ROLE.items()}
    out: list[dict[str, Any]] = []
    for row in roster_rows:
        slot = int(row["slot"])
        role = PRISTINE_SLOT_ROLE_BY_SLOT[slot]
        source = queues[role].pop(0)
        source.update(row)
        source["old_pristine_position_abbr"] = role
        source["old_pristine_position_label"] = POSITION_LABEL[{"G": 0, "D": 1, "M": 2, "F": 3}[role]]
        out.append(source)
    leftovers = {role: [row["game_name"] for row in rows] for role, rows in queues.items() if rows}
    if leftovers:
        raise RuntimeError(f"Unassigned target rows remain: {leftovers}")
    return out


def main() -> int:
    args = _parse_args()
    base_game = Path(args.base_game).expanduser().resolve()
    out_game = Path(args.out_game).expanduser().resolve()
    if out_game.exists():
        if not args.force:
            raise SystemExit(f"Output exists: {out_game}")
        shutil.rmtree(out_game)
    shutil.copytree(base_game, out_game, symlinks=True)
    artifact_dir = out_game / "artifacts" / "compact_variable_names"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    dbdat = out_game / "DBDAT"
    team_file = dbdat / "EQ98030.FDI"
    player_file = dbdat / "JUG98030.FDI"
    coach_file = dbdat / "ENT98030.FDI"
    textos_pkf = dbdat / "TEXTOS.PKF"
    country_codes = _extract_nationality_codes(textos_pkf)
    source_by_name = _target_source_rows(country_codes)
    roster_rows = _resolve_roster(team_file, player_file, args.team_query)
    if len(roster_rows) != 20:
        raise RuntimeError(f"Expected 20 Stoke rows, got {len(roster_rows)}")
    assigned = _assign_targets(roster_rows, source_by_name)

    file_data = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(file_data)
    entries_by_id = {int(entry.record_id): entry for entry in indexed.entries}
    stages: list[tuple[int, _IndexedRawStageRecord]] = []
    rows: list[dict[str, Any]] = []
    for row in assigned:
        entry = entries_by_id[int(row["pid"])]
        decoded = entry.decode_payload(file_data)
        patched, meta = _patch_clone_payload(decoded, row, min_payload_length=80)
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
        rows.append({**row, "compact_variable_patch": meta})

    backup_path = write_player_staged_records(str(player_file), stages, create_backup_before_write=True)
    post_data = player_file.read_bytes()
    post_index = IndexedFDIFile.from_bytes(post_data)
    post_by_id = {int(entry.record_id): entry for entry in post_index.entries}
    failures: list[dict[str, Any]] = []
    for row in rows:
        entry = post_by_id[int(row["pid"])]
        decoded = entry.decode_payload(post_data)
        parsed = PlayerRecord.from_bytes(decoded, int(entry.payload_offset))
        applied_name = " ".join(_player_display_name(parsed).split())
        parser_name_end = PlayerRecord._find_name_end(decoded)
        expected_name_end = int(row["compact_variable_patch"]["new_name_end"])
        if _norm(applied_name) != _norm(str(row["game_name"])) or parser_name_end != expected_name_end:
            failures.append(
                {
                    **row,
                    "post_applied_name": applied_name,
                    "post_parser_name_end": parser_name_end,
                    "expected_name_end": expected_name_end,
                }
            )

    (artifact_dir / "compact_variable_assignments.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    manifest = {
        "schema": "pm99-stoke-2015-role-preserved-compact-variable-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "base_game": str(base_game),
        "out_game": str(out_game),
        "dbdat": str(dbdat),
        "team_file": str(team_file),
        "player_file": str(player_file),
        "coach_file": str(coach_file),
        "backup_path": str(backup_path) if backup_path else None,
        "ok": not failures,
        "row_count": len(rows),
        "failure_count": len(failures),
        "failures": failures,
        "role_target_names": TARGET_NAMES_BY_ROLE,
        "assignments_json": str(artifact_dir / "compact_variable_assignments.json"),
        "hashes": {
            "EQ98030.FDI": sha256(team_file),
            "JUG98030.FDI": sha256(player_file),
            "ENT98030.FDI": sha256(coach_file),
        },
    }
    (artifact_dir / "compact_variable_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"ok": manifest["ok"], "out_game": str(out_game), "manifest": str(artifact_dir / "compact_variable_manifest.json")}, indent=2))
    return 0 if manifest["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
