#!/usr/bin/env python3
"""Repair PM99 linked-player runtime table aliases in a full-world game copy.

The full-world editor pass can make parser-visible names correct while leaving
MANAGPRE's early linked-player table tokens stale. This helper keeps the
authoritative EQ roster rows and original assigned JUG records in place, then
patches or same-club-clones the early runtime name segments used by Squad
Management tables.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
EDITOR_ROOT = REPO_ROOT / "upstream" / "pm99-skezmod-db-editor"
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.editor_actions import _IndexedRawStageRecord, _cp1252_bytes, _split_display_name_for_linked_payload  # noqa: E402
from app.editor_actions import write_player_staged_records  # noqa: E402
from app.editor_helpers import _player_display_name  # noqa: E402
from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from app.models import PlayerRecord  # noqa: E402
from scripts.repair_full_db_world_runtime_payloads import _assignment_rows  # noqa: E402


def _norm(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _split_runtime_name(name: str) -> tuple[str, str]:
    try:
        given, surname = _split_display_name_for_linked_payload(name)
    except Exception:
        parts = " ".join(str(name or "").split()).split()
        if len(parts) < 2:
            raise ValueError(f"Name must include given and surname: {name!r}")
        given, surname = parts[0], parts[-1]
    given = " ".join(str(given or "").split()).strip()
    surname = " ".join(str(surname or "").split()).strip()
    if not given or not surname:
        raise ValueError(f"Name must include given and surname: {name!r}")
    return given, surname


def _runtime_name_segments(payload: bytes) -> dict[str, int] | None:
    """Find adjacent surname/display-name segments used by PM99 squad tables."""

    for first_len_offset in range(5, min(len(payload), 24)):
        surname_width = int(payload[first_len_offset] ^ 0x61)
        surname_start = first_len_offset + 2
        surname_end = surname_start + surname_width
        if not (1 <= surname_width <= 32):
            continue
        if first_len_offset + 1 >= len(payload) or payload[first_len_offset + 1] != 0x61:
            continue
        if surname_end >= len(payload):
            continue

        name_len_offset = surname_end
        if name_len_offset + 1 >= len(payload):
            continue
        name_width = int(payload[name_len_offset] ^ 0x61)
        name_start = name_len_offset + 2
        name_end = name_start + name_width
        if not (1 <= name_width <= 96):
            continue
        if payload[name_len_offset + 1] != 0x61 or name_end > len(payload):
            continue
        return {
            "surname_start": surname_start,
            "surname_end": surname_end,
            "surname_width": surname_width,
            "name_start": name_start,
            "name_end": name_end,
            "name_width": name_width,
        }
    return None


def _segment_text(payload: bytes, segments: dict[str, int], key: str) -> str:
    start = int(segments[f"{key}_start"])
    end = int(segments[f"{key}_end"])
    return payload[start:end].decode("cp1252", errors="replace").strip()


def _patch_runtime_segments(
    *,
    payload: bytes,
    payload_offset: int,
    target_name: str,
) -> tuple[bytes, str, dict[str, Any]] | None:
    segments = _runtime_name_segments(payload)
    if segments is None:
        return None

    _given, surname = _split_runtime_name(target_name)
    surname_bytes = _cp1252_bytes(surname)
    name_bytes = _cp1252_bytes(target_name)
    if len(surname_bytes) > int(segments["surname_width"]):
        return None
    if len(name_bytes) > int(segments["name_width"]):
        return None

    patched = bytearray(payload)
    patched[int(segments["surname_start"]) : int(segments["surname_end"])] = (
        surname_bytes + (b" " * (int(segments["surname_width"]) - len(surname_bytes)))
    )
    patched[int(segments["name_start"]) : int(segments["name_end"])] = (
        name_bytes + (b" " * (int(segments["name_width"]) - len(name_bytes)))
    )

    try:
        reparsed = PlayerRecord.from_bytes(bytes(patched), int(payload_offset))
        applied_name = " ".join(_player_display_name(reparsed).split())
    except Exception:
        return None
    if _norm(applied_name) != _norm(target_name):
        return None

    return (
        bytes(patched),
        applied_name,
        {
            "surname_width": int(segments["surname_width"]),
            "name_width": int(segments["name_width"]),
            "runtime_surname": surname,
            "runtime_name": target_name,
        },
    )


def _player_rows_by_id(player_file: Path) -> tuple[dict[int, Any], bytes]:
    file_data = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(file_data)
    return {int(entry.record_id): entry for entry in indexed.entries}, file_data


def _build_template_pool(
    *,
    target_rows: list[dict[str, Any]],
    entries_by_id: dict[int, Any],
    file_data: bytes,
) -> list[dict[str, Any]]:
    pool: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in target_rows:
        record_id = int(row.get("record_id") or 0)
        if record_id <= 0 or record_id in seen:
            continue
        entry = entries_by_id.get(record_id)
        if entry is None:
            continue
        try:
            payload = entry.decode_payload(file_data)
            record = PlayerRecord.from_bytes(payload, int(entry.payload_offset))
        except Exception:
            continue
        segments = _runtime_name_segments(payload)
        if segments is None:
            continue
        seen.add(record_id)
        pool.append(
            {
                "record_id": record_id,
                "club_key": str(row.get("club_key") or ""),
                "slot": int(row.get("slot") or 0),
                "payload_offset": int(entry.payload_offset),
                "payload_length": int(entry.payload_length),
                "payload": bytes(payload),
                "parsed_name": " ".join(_player_display_name(record).split()),
                "surname_width": int(segments["surname_width"]),
                "name_width": int(segments["name_width"]),
            }
        )
    return sorted(
        pool,
        key=lambda item: (
            str(item["club_key"]),
            -int(item["surname_width"]),
            -int(item["name_width"]),
            int(item["slot"]),
            int(item["record_id"]),
        ),
    )


def repair_runtime_alias_segments(
    *,
    game_root: Path,
    assignment_path: Path,
    dry_run: bool,
    create_backup: bool,
    allow_payload_length_change: bool,
) -> dict[str, Any]:
    player_file = game_root / "DBDAT" / "JUG98030.FDI"
    if not player_file.is_file():
        raise FileNotFoundError(f"Missing player file: {player_file}")
    if not assignment_path.is_file():
        raise FileNotFoundError(f"Missing assignment file: {assignment_path}")

    target_rows = _assignment_rows(assignment_path, game_root=game_root, include_assigned=True)
    entries_by_id, file_data = _player_rows_by_id(player_file)
    templates = _build_template_pool(target_rows=target_rows, entries_by_id=entries_by_id, file_data=file_data)

    stages: list[tuple[int, _IndexedRawStageRecord]] = []
    stage_by_record_id: dict[int, bytes] = {}
    repaired: list[dict[str, Any]] = []
    unchanged: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    methods: Counter[str] = Counter()
    target_by_record_id: dict[int, str] = {}

    for row in target_rows:
        record_id = int(row.get("record_id") or 0)
        target_name = str(row.get("target_name") or "").strip()
        if record_id <= 0 or not target_name:
            blockers.append({**row, "reason": "missing_record_or_target_name"})
            continue
        normalized = _norm(target_name)
        previous = target_by_record_id.get(record_id)
        if previous is not None and previous != normalized:
            blockers.append({**row, "reason": "record_id_already_targets_different_player", "previous_target_name": previous})
            continue
        target_by_record_id[record_id] = normalized

        entry = entries_by_id.get(record_id)
        if entry is None:
            blockers.append({**row, "reason": "player_record_missing"})
            continue

        try:
            payload = bytes(stage_by_record_id.get(record_id) or entry.decode_payload(file_data))
            record = PlayerRecord.from_bytes(payload, int(entry.payload_offset))
            parsed_name = " ".join(_player_display_name(record).split())
        except Exception as exc:
            blockers.append({**row, "reason": "player_payload_parse_failed", "error": str(exc)})
            continue

        segments = _runtime_name_segments(payload)
        if segments is None:
            if _norm(parsed_name) == normalized:
                unchanged.append({**row, "reason": "no_runtime_segments", "parsed_name": parsed_name})
                methods["unchanged_no_runtime_segments"] += 1
                continue
            blockers.append({**row, "reason": "no_runtime_segments_name_mismatch", "parsed_name": parsed_name})
            continue

        _given, target_surname = _split_runtime_name(target_name)
        current_surname = _segment_text(payload, segments, "surname")
        current_runtime_name = _segment_text(payload, segments, "name")
        if _norm(parsed_name) == normalized and _norm(current_surname) == _norm(target_surname) and _norm(current_runtime_name) == normalized:
            unchanged.append(
                {
                    **row,
                    "reason": "runtime_segments_already_match",
                    "parsed_name": parsed_name,
                    "runtime_surname": current_surname,
                    "runtime_name": current_runtime_name,
                }
            )
            methods["unchanged_runtime_segments_match"] += 1
            continue

        patched = _patch_runtime_segments(payload=payload, payload_offset=int(entry.payload_offset), target_name=target_name)
        method = "runtime_segment_in_place"
        template_meta: dict[str, Any] = {}

        if patched is None:
            same_club = [
                item
                for item in templates
                if str(item["club_key"]) == str(row.get("club_key") or "")
                and int(item["record_id"]) != record_id
                and (
                    allow_payload_length_change
                    or int(item["payload_length"]) == int(entry.payload_length)
                )
            ]
            global_pool = [
                item
                for item in templates
                if int(item["record_id"]) != record_id
                and (
                    allow_payload_length_change
                    or int(item["payload_length"]) == int(entry.payload_length)
                )
            ]
            for template in [*same_club, *global_pool]:
                patched = _patch_runtime_segments(
                    payload=bytes(template["payload"]),
                    payload_offset=int(entry.payload_offset),
                    target_name=target_name,
                )
                if patched is None:
                    continue
                method = "same_club_runtime_segment_template_clone" if template in same_club else "global_runtime_segment_template_clone"
                template_meta = {
                    "template_record_id": int(template["record_id"]),
                    "template_club_key": str(template["club_key"]),
                    "template_slot": int(template["slot"]),
                    "template_name": str(template["parsed_name"]),
                    "template_payload_length": int(template["payload_length"]),
                    "payload_length_change_allowed": bool(allow_payload_length_change),
                    "template_surname_width": int(template["surname_width"]),
                    "template_name_width": int(template["name_width"]),
                }
                break

        if patched is None:
            blockers.append(
                {
                    **row,
                    "reason": "no_runtime_segment_capacity",
                    "parsed_name": parsed_name,
                    "runtime_surname": current_surname,
                    "runtime_name": current_runtime_name,
                    "surname_width": int(segments["surname_width"]),
                    "name_width": int(segments["name_width"]),
                }
            )
            continue

        patched_payload, applied_name, patch_meta = patched
        stage_by_record_id[record_id] = bytes(patched_payload)
        stages.append(
            (
                int(entry.payload_offset),
                _IndexedRawStageRecord(
                    raw_payload=bytes(patched_payload),
                    container_offset=int(entry.payload_offset),
                    container_length=int(entry.payload_length),
                ),
            )
        )
        repaired.append(
            {
                **row,
                "method": method,
                "old_payload_length": int(entry.payload_length),
                "new_payload_length": len(patched_payload),
                "parsed_name_before": parsed_name,
                "applied_name": applied_name,
                "runtime_surname_before": current_surname,
                "runtime_name_before": current_runtime_name,
                **patch_meta,
                **template_meta,
            }
        )
        methods[method] += 1

    backup_path = None
    applied_to_disk = False
    if stages and not dry_run:
        # Keep only the final staged payload for each offset if a duplicate target
        # record appears in the assignment.
        deduped: dict[int, _IndexedRawStageRecord] = {offset: staged for offset, staged in stages}
        backup_path = write_player_staged_records(
            str(player_file),
            sorted(deduped.items()),
            create_backup_before_write=create_backup,
        )
        applied_to_disk = True

    post_unresolved: list[dict[str, Any]] = []
    if not dry_run:
        post_entries_by_id, post_file_data = _player_rows_by_id(player_file)
        for row in target_rows:
            record_id = int(row.get("record_id") or 0)
            target_name = str(row.get("target_name") or "").strip()
            entry = post_entries_by_id.get(record_id)
            if entry is None:
                post_unresolved.append({**row, "reason": "post_player_record_missing"})
                continue
            payload = entry.decode_payload(post_file_data)
            try:
                record = PlayerRecord.from_bytes(payload, int(entry.payload_offset))
                parsed_name = " ".join(_player_display_name(record).split())
            except Exception as exc:
                post_unresolved.append({**row, "reason": "post_parse_failed", "error": str(exc)})
                continue
            if _norm(parsed_name) != _norm(target_name):
                post_unresolved.append({**row, "reason": "post_name_mismatch", "parsed_name": parsed_name})

    return {
        "schema": "pm99-full-world-runtime-alias-segment-repair-v1",
        "game_root": str(game_root),
        "player_file": str(player_file),
        "assignment_path": str(assignment_path),
        "dry_run": bool(dry_run),
        "allow_payload_length_change": bool(allow_payload_length_change),
        "applied_to_disk": applied_to_disk,
        "backup_path": backup_path,
        "ok": not blockers and not post_unresolved,
        "counts": {
            "target_rows": len(target_rows),
            "templates_available": len(templates),
            "repaired": len(repaired),
            "unchanged": len(unchanged),
            "blockers": len(blockers),
            "post_unresolved": len(post_unresolved),
        },
        "method_counts": dict(sorted(methods.items())),
        "blockers": blockers[:100],
        "post_unresolved": post_unresolved[:100],
        "repaired": repaired,
        "unchanged_examples": unchanged[:50],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", required=True)
    parser.add_argument("--assignment", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    parser.add_argument(
        "--allow-payload-length-change",
        action="store_true",
        help=(
            "Allow template clones that change an indexed JUG record payload length. "
            "Default is safer for game-ready DBs: clone only same-length payload families."
        ),
    )
    args = parser.parse_args()

    result = repair_runtime_alias_segments(
        game_root=Path(args.game_root).expanduser().resolve(),
        assignment_path=Path(args.assignment).expanduser().resolve(),
        dry_run=bool(args.dry_run),
        create_backup=not bool(args.no_backup),
        allow_payload_length_change=bool(args.allow_payload_length_change),
    )
    output_path = Path(args.output_json).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("ok", "counts", "method_counts")}, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
