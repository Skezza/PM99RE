#!/usr/bin/env python3
"""Build a role-preserved Stoke 2015 candidate by reordering proven JUG records.

The previous compact-variable attempt rewrote each existing roster slot's JUG
payload in place. That is too aggressive: compact linked-player records carry
hidden role/template bytes beyond the visible position fields, and mutating a
goalkeeper template into a defender (or vice versa) can pass static parsing but
crash MANAGPRE when Squad is opened.

This candidate starts from the runner-proven Stoke 2015 compact-clone proof,
keeps each proven 2015 player payload with its compatible template, and edits
only the EQ roster references so every original Stoke slot receives a target
with the same coarse role. Shay Given is added by cloning Jack Butland's proven
goalkeeper compact template into the dropped Odemwingie PID.
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

from app.editor_actions import _IndexedRawStageRecord, edit_team_roster_eq_jug_linked, write_player_staged_records  # noqa: E402
from app.editor_helpers import _player_display_name  # noqa: E402
from app.eq_jug_linked import load_eq_linked_team_rosters  # noqa: E402
from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from app.models import PlayerRecord  # noqa: E402
from assert_pm99_isolated_input import sha256  # noqa: E402
from apply_stoke_2015_role_preserved_compact_variable_patch import (  # noqa: E402
    PRISTINE_SLOT_ROLE_BY_SLOT,
    TARGET_NAMES_BY_ROLE,
    _compact_segments,
    _name_prefix,
    _norm,
    _role_byte,
)
from apply_stoke_2015_semantic_runtime_patch import SKILL_LABELS, _read_clone_fields, _write_decoded_byte  # noqa: E402
from apply_stoke_2015_variable_names_runtime_patch import _extract_nationality_codes, _target_source_rows  # noqa: E402


DROPPED_FORWARD_PID_FOR_SHAY_GIVEN = 10001
BUTLAND_TEMPLATE_NAME = "Jack Butland"
SHAY_GIVEN_NAME = "Shay Given"


def _parse_args() -> argparse.Namespace:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-game",
        default=str(REPO_ROOT / ".local" / "stoke_2015_stats_backfill_20260501T065744Z"),
        help="Runner-proven fixed-order Stoke 2015 compact clone game root.",
    )
    parser.add_argument(
        "--out-game",
        default=str(REPO_ROOT / ".local" / f"stoke_2015_rosterref_variable_names_{stamp}"),
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
                "player_name": str(getattr(row, "player_name", "") or ""),
                "eq_record_id": int(getattr(roster, "eq_record_id", 0) or 0),
                "team_name": str(getattr(roster, "short_name", "") or ""),
                "full_club_name": str(getattr(roster, "full_club_name", "") or ""),
            }
            for row in rows[:20]
        ]
    raise RuntimeError(f"Could not resolve roster for {team_query!r}")


def _role_target_order() -> list[dict[str, Any]]:
    queues = {role: list(names) for role, names in TARGET_NAMES_BY_ROLE.items()}
    out: list[dict[str, Any]] = []
    for slot in range(1, 21):
        role = PRISTINE_SLOT_ROLE_BY_SLOT[slot]
        name = queues[role].pop(0)
        out.append({"slot": slot, "target_role": role, "target_name": name})
    leftovers = {role: names for role, names in queues.items() if names}
    if leftovers:
        raise RuntimeError(f"Unassigned target names remain: {leftovers}")
    return out


def _patch_compact_payload(decoded: bytes, source_row: dict[str, Any], *, template_name: str) -> tuple[bytes, dict[str, Any]]:
    if decoded[2:5] != b"\xdd\x63\x60":
        raise RuntimeError(f"Expected dd6360 compact payload for {source_row['game_name']!r}, got {decoded[2:5].hex()}")
    parsed = PlayerRecord.from_bytes(decoded, 0)
    old_name = " ".join(_player_display_name(parsed).split())
    name_end = PlayerRecord._find_name_end(decoded)
    if name_end is None:
        raise RuntimeError(f"Could not resolve compact name_end for {old_name!r}")
    segments = _compact_segments(decoded)
    if int(segments["name_end"]) != int(name_end):
        raise RuntimeError(f"Segment resolver disagrees with parser for {old_name!r}")

    primary_role = int(list(source_row["fine_role_codes"])[0])
    prefix = _name_prefix(str(source_row["game_name"]))
    role = _role_byte(primary_role)
    role_start = int(name_end) - 3
    prefix_end = int(segments["first_len_offset"]) + len(prefix)
    if prefix_end > role_start:
        raise RuntimeError(f"{source_row['game_name']!r} does not fit compact name window")

    patched = bytearray()
    patched.extend(decoded[: int(segments["first_len_offset"])])
    patched.extend(prefix)
    patched.extend(b" " * (role_start - prefix_end))
    patched.extend(bytes([role, 0x61, role]))
    patched.extend(decoded[int(name_end) :])
    if len(patched) != len(decoded):
        raise RuntimeError(f"Compact payload length changed for {source_row['game_name']!r}: {len(decoded)} -> {len(patched)}")

    _write_decoded_byte(patched, name_end + 5, int(source_row["pm99_nat_code"]))
    _write_decoded_byte(patched, name_end + 7, int(source_row["pm99_position_code"]))
    _write_decoded_byte(patched, name_end + 8, int(source_row["pm99_position_code"]))
    _write_decoded_byte(patched, name_end + 9, int(source_row["birth_day"]))
    _write_decoded_byte(patched, name_end + 10, int(source_row["birth_month"]))
    year_bytes = struct.pack("<H", int(source_row["birth_year"]))
    _write_decoded_byte(patched, name_end + 11, year_bytes[0])
    _write_decoded_byte(patched, name_end + 12, year_bytes[1])
    _write_decoded_byte(patched, name_end + 13, int(source_row["height_cm"]))
    _write_decoded_byte(patched, name_end + 14, int(source_row["weight_kg"]))
    for index, label in enumerate(SKILL_LABELS):
        _write_decoded_byte(patched, name_end + 15 + index, int(source_row["skills"][label]))

    parser_name_end = PlayerRecord._find_name_end(bytes(patched))
    reparsed = PlayerRecord.from_bytes(bytes(patched), 0)
    applied_name = " ".join(_player_display_name(reparsed).split())
    if parser_name_end != name_end or _norm(applied_name) != _norm(str(source_row["game_name"])):
        raise RuntimeError(
            f"Post-patch parser mismatch for {source_row['game_name']!r}: "
            f"name={applied_name!r}, name_end={parser_name_end}, expected={name_end}"
        )
    return bytes(patched), {
        "template_name": template_name,
        "old_name": old_name,
        "applied_name": applied_name,
        "payload_length": len(patched),
        "name_end": int(name_end),
        "natural_name_prefix_length": len(prefix),
        "stable_name_window_padding_bytes": role_start - prefix_end,
        "fields": _read_clone_fields(bytes(patched), int(name_end)),
    }


def main() -> int:
    args = _parse_args()
    base_game = Path(args.base_game).expanduser().resolve()
    out_game = Path(args.out_game).expanduser().resolve()
    if out_game.exists():
        if not args.force:
            raise SystemExit(f"Output exists: {out_game}")
        shutil.rmtree(out_game)
    shutil.copytree(base_game, out_game, symlinks=True)
    artifact_dir = out_game / "artifacts" / "rosterref_variable_names"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    dbdat = out_game / "DBDAT"
    team_file = dbdat / "EQ98030.FDI"
    player_file = dbdat / "JUG98030.FDI"
    coach_file = dbdat / "ENT98030.FDI"
    country_codes = _extract_nationality_codes(dbdat / "TEXTOS.PKF")
    source_by_name = _target_source_rows(country_codes)

    original_rows = _resolve_roster(team_file, player_file, args.team_query)
    pid_by_name = {_norm(row["player_name"]): int(row["pid"]) for row in original_rows}
    if _norm(BUTLAND_TEMPLATE_NAME) not in pid_by_name:
        raise RuntimeError("Butland template PID not found in fixed proof roster")

    target_pid_by_name = {name: pid_by_name[_norm(name)] for names in TARGET_NAMES_BY_ROLE.values() for name in names if name != SHAY_GIVEN_NAME}
    target_pid_by_name[SHAY_GIVEN_NAME] = DROPPED_FORWARD_PID_FOR_SHAY_GIVEN

    file_data = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(file_data)
    entries_by_id = {int(entry.record_id): entry for entry in indexed.entries}
    butland_pid = pid_by_name[_norm(BUTLAND_TEMPLATE_NAME)]
    butland_entry = entries_by_id[butland_pid]
    stages: list[tuple[int, _IndexedRawStageRecord]] = []
    jug_patch_rows: list[dict[str, Any]] = []
    patched_pids: set[int] = set()

    for target_name, target_pid in sorted(target_pid_by_name.items(), key=lambda item: item[1]):
        source_row = source_by_name[target_name]
        if target_name == SHAY_GIVEN_NAME:
            template_entry = butland_entry
            template_name = BUTLAND_TEMPLATE_NAME
        else:
            template_entry = entries_by_id[int(target_pid)]
            template_name = target_name
        decoded = template_entry.decode_payload(file_data)
        patched, meta = _patch_compact_payload(decoded, source_row, template_name=template_name)
        target_entry = entries_by_id[int(target_pid)]
        stages.append(
            (
                int(target_entry.payload_offset),
                _IndexedRawStageRecord(
                    raw_payload=patched,
                    container_offset=int(target_entry.payload_offset),
                    container_length=int(target_entry.payload_length),
                ),
            )
        )
        patched_pids.add(int(target_pid))
        jug_patch_rows.append({"target_name": target_name, "target_pid": int(target_pid), **meta})

    backup_path = write_player_staged_records(str(player_file), stages, create_backup_before_write=True)

    assignment_rows: list[dict[str, Any]] = []
    for row in _role_target_order():
        target_name = str(row["target_name"])
        target_pid = int(target_pid_by_name[target_name])
        result = edit_team_roster_eq_jug_linked(
            team_file=str(team_file),
            player_file=str(player_file),
            team_query=args.team_query,
            slot_number=int(row["slot"]),
            player_record_id=target_pid,
            flag=0,
            write_changes=True,
        )
        assignment_rows.append(
            {
                **row,
                "target_pid": target_pid,
                "changes": [
                    {
                        "slot_number": int(change.slot_number),
                        "old_player_record_id": int(change.old_player_record_id),
                        "new_player_record_id": int(change.new_player_record_id),
                        "old_player_name": str(change.old_player_name),
                        "new_player_name": str(change.new_player_name),
                    }
                    for change in list(getattr(result, "changes", []) or [])
                ],
            }
        )

    final_rows = _resolve_roster(team_file, player_file, args.team_query)
    failures = [
        {"slot": expected["slot"], "expected": expected["target_name"], "actual": actual["player_name"]}
        for expected, actual in zip(_role_target_order(), final_rows, strict=True)
        if _norm(expected["target_name"]) != _norm(actual["player_name"])
    ]

    (artifact_dir / "rosterref_variable_assignments.json").write_text(json.dumps(assignment_rows, indent=2), encoding="utf-8")
    (artifact_dir / "jug_variable_name_patches.json").write_text(json.dumps(jug_patch_rows, indent=2), encoding="utf-8")
    (artifact_dir / "team_roster_final.json").write_text(json.dumps(final_rows, indent=2), encoding="utf-8")
    manifest = {
        "schema": "pm99-stoke-2015-role-preserved-rosterref-variable-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "base_game": str(base_game),
        "out_game": str(out_game),
        "ok": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "contract": (
            "EQ roster references are reordered into original Stoke coarse-role slots; "
            "JUG compact payloads keep stable 80-byte runtime-safe containers with natural "
            "variable-length surname/full-name fields inside the stable name window."
        ),
        "dropped_pid_reused_for_shay_given": DROPPED_FORWARD_PID_FOR_SHAY_GIVEN,
        "butland_template_pid": int(butland_pid),
        "jug_backup_path": str(backup_path) if backup_path else None,
        "assignment_json": str(artifact_dir / "rosterref_variable_assignments.json"),
        "jug_patches_json": str(artifact_dir / "jug_variable_name_patches.json"),
        "final_roster_json": str(artifact_dir / "team_roster_final.json"),
        "hashes": {
            "EQ98030.FDI": sha256(team_file),
            "JUG98030.FDI": sha256(player_file),
            "ENT98030.FDI": sha256(coach_file),
        },
    }
    (artifact_dir / "rosterref_variable_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"ok": manifest["ok"], "out_game": str(out_game), "manifest": str(artifact_dir / "rosterref_variable_manifest.json")}, indent=2))
    return 0 if manifest["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
