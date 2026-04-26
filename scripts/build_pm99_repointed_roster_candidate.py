#!/usr/bin/env python3
"""Build a PM99 roster candidate by repointing carrier squad slots.

This avoids mutating the original assigned carrier player records. Every target
slot is linked to a unique long JUG record outside the assignment's original
record-id set, then that record's native name region is rewritten.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
EDITOR_ROOT = REPO_ROOT / "upstream" / "pm99-skezmod-db-editor"
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.editor_actions import _IndexedRawStageRecord, write_player_staged_records  # noqa: E402
from app.editor_actions import _cp1252_bytes, _split_display_name_for_linked_payload  # noqa: E402
from app.editor_helpers import _player_display_name  # noqa: E402
from app.eq_jug_linked import load_eq_linked_team_rosters  # noqa: E402
from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from app.file_writer import replace_player_name_preserving_layout  # noqa: E402
from app.models import PlayerRecord  # noqa: E402
from scripts.repair_full_db_world_runtime_payloads import (  # noqa: E402
    _build_variable_original_name_payload,
    _linked_roster_layout,
    _make_room_for_linked_roster_row,
    _target_token_width,
    _write_raw_indexed_payloads,
)


def _norm(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _assignment_target_rows(assignment_path: Path) -> tuple[list[dict[str, Any]], set[int]]:
    payload = _load_json(assignment_path)
    rows: list[dict[str, Any]] = []
    original_assigned_ids: set[int] = set()
    for assignment in list(payload.get("assignments") or []):
        if not isinstance(assignment, dict):
            continue
        club_key = str(assignment.get("target_club_key") or assignment.get("club_key") or "").strip()
        club_display_name = str(assignment.get("target_display_name") or club_key).strip()
        eq_record_id = int(assignment.get("carrier_eq_record_id") or 0)
        by_slot: dict[int, dict[str, Any]] = {}
        for row in list(assignment.get("roster") or []):
            if not isinstance(row, dict):
                continue
            slot = int(row.get("slot") or 0)
            record_id = int(row.get("record_id") or 0)
            target_name = str(row.get("applied_name") or row.get("target_name") or "").strip()
            if record_id > 0:
                original_assigned_ids.add(record_id)
            if 1 <= slot <= 20 and target_name:
                by_slot[slot] = {
                    "club_key": club_key,
                    "club_display_name": club_display_name,
                    "carrier_eq_record_id": eq_record_id,
                    "slot": slot,
                    "target_name": target_name,
                    "source_target_name": str(row.get("source_target_name") or target_name),
                    "original_record_id": record_id,
                    "source": "assigned",
                }
        skipped = [str(name or "").strip() for name in list(assignment.get("skipped_target_names") or []) if str(name or "").strip()]
        source_skipped = [
            str(name or "").strip()
            for name in list(assignment.get("source_skipped_target_names") or [])
            if str(name or "").strip()
        ]
        free_slots = [slot for slot in range(1, 21) if slot not in by_slot]
        for index, (slot, target_name) in enumerate(zip(free_slots, skipped)):
            by_slot[slot] = {
                "club_key": club_key,
                "club_display_name": club_display_name,
                "carrier_eq_record_id": eq_record_id,
                "slot": slot,
                "target_name": target_name,
                "source_target_name": source_skipped[index] if index < len(source_skipped) else target_name,
                "original_record_id": 0,
                "source": "skipped",
            }
        missing = sorted(set(range(1, 21)) - set(by_slot))
        if missing:
            raise RuntimeError(f"{club_key} has no target names for slots {missing}")
        rows.extend(by_slot[slot] for slot in range(1, 21))
    return rows, original_assigned_ids


def _candidate_player_rows(player_file: Path, *, excluded_record_ids: set[int]) -> list[dict[str, Any]]:
    file_data = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(file_data)
    candidates: list[dict[str, Any]] = []
    for entry in indexed.entries:
        record_id = int(entry.record_id)
        if record_id <= 0 or record_id in excluded_record_ids or int(entry.payload_length) < 80:
            continue
        try:
            payload = entry.decode_payload(file_data)
            record = PlayerRecord.from_bytes(payload, int(entry.payload_offset))
            name = " ".join(_player_display_name(record).split())
        except Exception:
            continue
        if not name or name in {"Unknown Player", "Parse Error"}:
            continue
        try:
            token_width = _target_token_width(name)
        except Exception:
            token_width = len(name.encode("cp1252", errors="replace"))
        candidates.append(
            {
                "record_id": record_id,
                "payload_offset": int(entry.payload_offset),
                "payload_length": int(entry.payload_length),
                "payload": bytes(payload),
                "name": name,
                "token_width": token_width,
            }
        )
    return sorted(candidates, key=lambda row: (int(row["payload_length"]), int(row["record_id"])))


def _globally_linked_player_ids(*, team_file: Path, player_file: Path) -> set[int]:
    """Return every JUG record ID currently referenced by any linked EQ roster."""

    linked_ids: set[int] = set()
    for roster in load_eq_linked_team_rosters(team_file=str(team_file), player_file=str(player_file)):
        for row in list(getattr(roster, "rows", []) or []):
            record_id = int(getattr(row, "player_record_id", 0) or 0)
            if record_id > 0:
                linked_ids.add(record_id)
    return linked_ids


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
    """Find the two early PM99 runtime name segments used by squad tables."""

    # Linked JUG payloads normally encode the table surname and display name as:
    #   (width ^ 0x61), 0x61, text[width]
    # for two adjacent text segments. The cursor is not completely fixed across
    # families, so scan the small prefix window instead of hard-coding byte 8.
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


def _build_runtime_segment_clone_payload(
    *,
    target_name: str,
    template_payload: bytes,
    template_payload_offset: int,
) -> tuple[bytes, str] | None:
    segments = _runtime_name_segments(template_payload)
    if segments is None:
        return None
    _given, surname = _split_runtime_name(target_name)
    surname_bytes = _cp1252_bytes(surname)
    name_bytes = _cp1252_bytes(target_name)
    if len(surname_bytes) > int(segments["surname_width"]):
        return None
    if len(name_bytes) > int(segments["name_width"]):
        return None

    patched = bytearray(template_payload)
    patched[int(segments["surname_start"]) : int(segments["surname_end"])] = (
        surname_bytes + (b" " * (int(segments["surname_width"]) - len(surname_bytes)))
    )
    patched[int(segments["name_start"]) : int(segments["name_end"])] = (
        name_bytes + (b" " * (int(segments["name_width"]) - len(name_bytes)))
    )

    try:
        reparsed = PlayerRecord.from_bytes(bytes(patched), int(template_payload_offset))
        applied_name = " ".join(_player_display_name(reparsed).split())
    except Exception:
        return None
    if _norm(applied_name) != _norm(target_name):
        return None
    return bytes(patched), applied_name


def _build_non_assigned_payload(
    *,
    target: dict[str, Any],
    candidate: dict[str, Any],
    donor_templates: list[dict[str, Any]],
) -> tuple[bytes, str, str, dict[str, Any]]:
    target_name = str(target["target_name"])

    for donor in donor_templates:
        segment_clone = _build_runtime_segment_clone_payload(
            target_name=target_name,
            template_payload=bytes(donor["payload"]),
            template_payload_offset=int(candidate["payload_offset"]),
        )
        if segment_clone is None:
            continue
        patched_payload, applied_name = segment_clone
        return (
            bytes(patched_payload),
            str(applied_name),
            "runtime_segment_template_clone",
            {
                "template_record_id": int(donor["record_id"]),
                "template_name": str(donor["name"]),
            },
        )

    required_width = _target_token_width(target_name)
    for donor in donor_templates:
        if int(donor["token_width"]) < required_width:
            continue
        try:
            patched, ok = replace_player_name_preserving_layout(
                bytes(donor["payload"]),
                str(donor["name"]),
                target_name,
            )
        except Exception:
            continue
        if not ok:
            continue
        try:
            reparsed = PlayerRecord.from_bytes(bytes(patched), int(candidate["payload_offset"]))
            applied_name = " ".join(_player_display_name(reparsed).split())
        except Exception:
            continue
        if _norm(applied_name) != _norm(target_name):
            continue
        return (
            bytes(patched),
            str(applied_name),
            "name_preserving_non_assigned_template_clone",
            {
                "template_record_id": int(donor["record_id"]),
                "template_name": str(donor["name"]),
            },
        )

    variable = _build_variable_original_name_payload(
        decoded_payload=bytes(candidate["payload"]),
        payload_offset=int(candidate["payload_offset"]),
        target_name=target_name,
    )
    if variable is not None:
        patched_payload, applied_name = variable
        if _norm(applied_name) == _norm(target_name):
            return (
                bytes(patched_payload),
                str(applied_name),
                "variable_name_non_assigned_payload",
                {
                    "template_record_id": int(candidate["record_id"]),
                    "template_name": str(candidate["name"]),
                },
            )

    raise RuntimeError(
        f"Could not build non-assigned payload for {target['club_key']} "
        f"slot {target['slot']} {target_name!r} using candidate {candidate['record_id']}"
    )


def build_repointed_candidate(*, base_game: Path, assignment_path: Path, out_game: Path, force: bool) -> dict[str, Any]:
    if out_game.exists():
        if not force:
            raise FileExistsError(f"Output game already exists: {out_game}")
        shutil.rmtree(out_game)
    shutil.copytree(base_game, out_game, symlinks=True)

    target_rows, original_assigned_ids = _assignment_target_rows(assignment_path)
    player_file = out_game / "DBDAT" / "JUG98030.FDI"
    team_file = out_game / "DBDAT" / "EQ98030.FDI"
    globally_linked_ids = _globally_linked_player_ids(team_file=team_file, player_file=player_file)
    candidate_exclusions = set(original_assigned_ids)
    candidates = sorted(
        _candidate_player_rows(player_file, excluded_record_ids=candidate_exclusions),
        key=lambda row: (
            int(row["record_id"]) in globally_linked_ids,
            int(row["payload_length"]),
            int(row["record_id"]),
        ),
    )
    if len(candidates) < len(target_rows):
        raise RuntimeError(f"Need {len(target_rows)} candidate JUG rows, only found {len(candidates)}")
    donor_templates = _candidate_player_rows(player_file, excluded_record_ids=set())

    player_stages: list[tuple[int, _IndexedRawStageRecord]] = []
    allocations: list[dict[str, Any]] = []
    allocation_order = sorted(
        target_rows,
        key=lambda row: (
            -len(str(row["target_name"]).encode("cp1252", errors="replace")),
            str(row["club_key"]),
            int(row["slot"]),
        ),
    )
    for target, candidate in zip(allocation_order, candidates):
        patched_payload, applied_name, method, donor_meta = _build_non_assigned_payload(
            target=target,
            candidate=candidate,
            donor_templates=donor_templates,
        )
        player_stages.append(
            (
                int(candidate["payload_offset"]),
                _IndexedRawStageRecord(
                    raw_payload=bytes(patched_payload),
                    container_offset=int(candidate["payload_offset"]),
                    container_length=int(candidate["payload_length"]),
                ),
            )
        )
        allocations.append(
            {
                **target,
                "new_record_id": int(candidate["record_id"]),
                "candidate_old_name": str(candidate["name"]),
                "old_payload_length": int(candidate["payload_length"]),
                "new_payload_length": len(patched_payload),
                "applied_name": applied_name,
                "method": method,
                **donor_meta,
            }
        )

    write_player_staged_records(str(player_file), player_stages, create_backup_before_write=False)

    team_data = team_file.read_bytes()
    indexed_teams = IndexedFDIFile.from_bytes(team_data)
    team_entries_by_id = {int(entry.record_id): entry for entry in indexed_teams.entries}
    by_eq: dict[int, list[dict[str, Any]]] = {}
    for row in allocations:
        by_eq.setdefault(int(row["carrier_eq_record_id"]), []).append(row)

    raw_payload_by_offset: dict[int, bytes] = {}
    roster_patch_events: list[dict[str, Any]] = []
    for eq_record_id, rows in by_eq.items():
        entry = team_entries_by_id.get(eq_record_id)
        if entry is None:
            raise RuntimeError(f"Missing carrier EQ record {eq_record_id}")
        raw_payload = bytearray(
            raw_payload_by_offset.get(
                int(entry.payload_offset),
                team_data[int(entry.payload_offset) : int(entry.payload_offset) + int(entry.payload_length)],
            )
        )
        layout = _linked_roster_layout(bytes(raw_payload))
        if layout is None:
            raise RuntimeError(f"Could not parse linked roster layout for EQ {eq_record_id}")
        while int(layout["player_count"]) < 20:
            old_count = int(layout["player_count"])
            before_len = len(raw_payload)
            _new_count, trim_events, trim_error = _make_room_for_linked_roster_row(raw_payload)
            if trim_error:
                raise RuntimeError(f"Could not make room in EQ {eq_record_id}: {trim_error}")
            layout = _linked_roster_layout(bytes(raw_payload))
            if layout is None:
                raise RuntimeError(f"Could not reparse linked roster layout for EQ {eq_record_id}")
            insert_at = int(layout["rows_start"]) + old_count * 5
            raw_payload[insert_at:insert_at] = b"\x00\x00\x00\x00\x00"
            raw_payload[int(layout["player_count_offset"])] = old_count + 1
            if len(raw_payload) != before_len:
                raise RuntimeError(f"EQ {eq_record_id} payload size changed while inserting roster row")
            layout = _linked_roster_layout(bytes(raw_payload))
            roster_patch_events.append(
                {
                    "carrier_eq_record_id": eq_record_id,
                    "event": "insert_blank_roster_row",
                    "old_player_count": old_count,
                    "new_player_count": old_count + 1,
                    "same_size_trim_events": trim_events,
                }
            )
        if int(layout["player_count"]) < 20:
            raise RuntimeError(f"EQ {eq_record_id} still has fewer than 20 player rows")
        for row in rows:
            slot = int(row["slot"])
            row_offset = int(layout["rows_start"]) + (slot - 1) * 5
            if row_offset + 5 > len(raw_payload):
                raise RuntimeError(f"EQ {eq_record_id} slot {slot} is outside payload")
            old_record_id = int.from_bytes(raw_payload[row_offset + 1 : row_offset + 5], "little")
            raw_payload[row_offset + 1 : row_offset + 5] = int(row["new_record_id"]).to_bytes(4, "little")
            row["old_record_id_in_slot"] = old_record_id
        raw_payload_by_offset[int(entry.payload_offset)] = bytes(raw_payload)

    _write_raw_indexed_payloads(team_file, raw_payload_by_offset, create_backup=False)

    rosters = {
        int(roster.eq_record_id): roster
        for roster in load_eq_linked_team_rosters(team_file=str(team_file), player_file=str(player_file))
    }
    post_meta_file = player_file.read_bytes()
    post_indexed = IndexedFDIFile.from_bytes(post_meta_file)
    post_entry_by_id = {int(entry.record_id): entry for entry in post_indexed.entries}
    failures: list[dict[str, Any]] = []
    for row in allocations:
        roster = rosters.get(int(row["carrier_eq_record_id"]))
        actual_record_id = 0
        if roster is not None and int(row["slot"]) - 1 < len(getattr(roster, "rows", []) or []):
            actual_record_id = int(getattr(list(roster.rows)[int(row["slot"]) - 1], "player_record_id", 0) or 0)
        actual_name = ""
        entry = post_entry_by_id.get(actual_record_id)
        if entry is not None:
            try:
                record = PlayerRecord.from_bytes(entry.decode_payload(post_meta_file), int(entry.payload_offset))
                actual_name = " ".join(_player_display_name(record).split())
            except Exception:
                actual_name = ""
        if actual_record_id != int(row["new_record_id"]) or _norm(actual_name) != _norm(str(row["target_name"])):
            failures.append({**row, "actual_record_id": actual_record_id, "actual_name": actual_name})

    manifest = {
        "schema": "pm99-repointed-roster-candidate-v1",
        "base_game": str(base_game),
        "assignment_path": str(assignment_path),
        "out_game": str(out_game),
        "ok": not failures,
        "target_rows": len(target_rows),
        "candidate_count": len(candidates),
        "consumed_candidate_count": len(allocations),
        "original_assigned_id_count": len(original_assigned_ids),
        "globally_linked_id_count": len(globally_linked_ids),
        "candidate_exclusion_count": len(candidate_exclusions),
        "globally_unlinked_candidate_count": sum(
            1 for row in candidates if int(row["record_id"]) not in globally_linked_ids
        ),
        "allocation_count": len(allocations),
        "roster_patch_events": roster_patch_events,
        "failure_count": len(failures),
        "failures": failures[:100],
        "allocations": allocations,
    }
    (out_game / "repointed_roster_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-game", required=True)
    parser.add_argument("--assignment", required=True)
    parser.add_argument("--out-game", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    manifest = build_repointed_candidate(
        base_game=Path(args.base_game).expanduser().resolve(),
        assignment_path=Path(args.assignment).expanduser().resolve(),
        out_game=Path(args.out_game).expanduser().resolve(),
        force=bool(args.force),
    )
    print(
        json.dumps(
            {
                "ok": manifest["ok"],
                "target_rows": manifest["target_rows"],
                "allocation_count": manifest["allocation_count"],
                "failure_count": manifest["failure_count"],
                "out_game": manifest["out_game"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if manifest["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
