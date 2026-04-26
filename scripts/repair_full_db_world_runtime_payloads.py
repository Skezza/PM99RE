#!/usr/bin/env python3
"""Repair short JUG player payloads used by a compiled full-DB world-state.

This is a research orchestration helper around the editor's targeted linked
payload repair primitive. It preserves the world-state's roster links and player
names, but replaces short player payload families with compatible long runtime
templates so MANAGPRE's Current Squad filter can certify them.
"""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
EDITOR_ROOT = REPO_ROOT / "upstream" / "pm99-skezmod-db-editor"
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))

from app.editor_actions import (  # noqa: E402
    _IndexedRawStageRecord,
    _LINKED_RUNTIME_MIN_CERTIFIABLE_PLAYER_PAYLOAD_LENGTH,
    _build_indexed_player_runtime_metadata_index,
    _build_linked_roster_template_clone_payload,
    _build_parser_fixed_name_candidate,
    _mutate_indexed_player_name_fixed_safe,
    _cp1252_bytes,
    _split_display_name_for_linked_payload,
    write_player_staged_records,
)
from app.eq_jug_linked import load_eq_linked_team_rosters  # noqa: E402
from app.eq_jug_linked import (  # noqa: E402
    _EXTERNAL_LINK_JUMP,
    _advance_legacy_mode_zero_cursor,
    _read_xor_u16_string,
)
from app.editor_helpers import _player_display_name  # noqa: E402
from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from app.file_writer import replace_player_name_preserving_layout  # noqa: E402
from app.models import PlayerRecord  # noqa: E402


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(type(value).__name__)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _target_token_width(name: str) -> int:
    _given, surname = _split_display_name_for_linked_payload(name)
    normalized = " ".join(str(name or "").split())
    return len(_cp1252_bytes(f"fa{surname}qa{normalized}"))


def _normalized_display_name(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _build_variable_original_name_payload(
    *,
    decoded_payload: bytes,
    payload_offset: int,
    target_name: str,
) -> tuple[bytes, str] | None:
    """Rewrite the native name region while preserving the original record tail."""

    try:
        parsed = PlayerRecord.from_bytes(decoded_payload, int(payload_offset))
        parsed.set_name(target_name)
        patched = parsed.to_bytes()
        if not isinstance(patched, (bytes, bytearray)):
            return None
        reparsed = PlayerRecord.from_bytes(bytes(patched), int(payload_offset))
    except Exception:
        return None

    applied_name = " ".join(_player_display_name(reparsed).split())
    if _normalized_display_name(applied_name) != _normalized_display_name(target_name):
        return None
    return bytes(patched), applied_name


def _assignment_rows(path: Path, *, game_root: Path, include_assigned: bool = True) -> list[dict[str, Any]]:
    payload = _load_json(path)
    rows: list[dict[str, Any]] = []
    rosters_by_eq = {
        int(roster.eq_record_id): roster
        for roster in load_eq_linked_team_rosters(
            team_file=str(game_root / "DBDAT" / "EQ98030.FDI"),
            player_file=str(game_root / "DBDAT" / "JUG98030.FDI"),
        )
    }
    for assignment in list(payload.get("assignments") or []):
        if not isinstance(assignment, dict):
            continue
        club_key = str(assignment.get("target_club_key") or assignment.get("club_key") or "").strip()
        display_name = str(assignment.get("target_display_name") or club_key).strip()
        assigned_slots: set[int] = set()
        for row in list(assignment.get("roster") or []):
            if not isinstance(row, dict):
                continue
            record_id = int(row.get("record_id") or 0)
            target_name = str(row.get("applied_name") or row.get("target_name") or "").strip()
            slot = int(row.get("slot") or 0)
            if record_id <= 0 or not target_name or slot <= 0:
                continue
            assigned_slots.add(slot)
            if include_assigned:
                rows.append(
                    {
                        "club_key": club_key,
                        "club_display_name": display_name,
                        "carrier_eq_record_id": int(assignment.get("carrier_eq_record_id") or 0),
                        "requested_player_count": int(assignment.get("requested_player_count") or assignment.get("carrier_active_rows") or 20),
                        "slot": slot,
                        "record_id": record_id,
                        "target_name": target_name,
                        "source": "assigned_world_row",
                        "force_rewrite": False,
                    }
                )
        skipped_names = [str(name or "").strip() for name in list(assignment.get("skipped_target_names") or []) if str(name or "").strip()]
        if not skipped_names:
            continue
        roster = rosters_by_eq.get(int(assignment.get("carrier_eq_record_id") or 0))
        if roster is None:
            for name in skipped_names:
                rows.append(
                    {
                        "club_key": club_key,
                        "club_display_name": display_name,
                        "carrier_eq_record_id": int(assignment.get("carrier_eq_record_id") or 0),
                        "requested_player_count": int(assignment.get("requested_player_count") or assignment.get("carrier_active_rows") or 20),
                        "slot": 0,
                        "record_id": 0,
                        "target_name": name,
                        "source": "skipped_target_fill",
                        "force_rewrite": True,
                        "pre_blocked_reason": "linked_roster_missing_for_skipped_target",
                    }
                )
            continue
        requested = int(assignment.get("requested_player_count") or assignment.get("carrier_active_rows") or 20)
        available_rows = [
            row
            for row in list(getattr(roster, "rows", []) or [])
            if int(getattr(row, "player_record_id", 0) or 0) > 0
            and int(getattr(row, "slot_index", 0) or 0) + 1 not in assigned_slots
            and int(getattr(row, "slot_index", 0) or 0) + 1 <= requested
        ]
        for name, linked_row in zip(skipped_names, available_rows):
            rows.append(
                {
                        "club_key": club_key,
                        "club_display_name": display_name,
                        "carrier_eq_record_id": int(assignment.get("carrier_eq_record_id") or 0),
                        "requested_player_count": requested,
                        "slot": int(getattr(linked_row, "slot_index", 0) or 0) + 1,
                    "record_id": int(getattr(linked_row, "player_record_id", 0) or 0),
                    "target_name": name,
                    "source": "skipped_target_fill",
                    "force_rewrite": True,
                }
            )
        if len(available_rows) < len(skipped_names):
            for name in skipped_names[len(available_rows) :]:
                rows.append(
                    {
                        "club_key": club_key,
                        "club_display_name": display_name,
                        "carrier_eq_record_id": int(assignment.get("carrier_eq_record_id") or 0),
                        "requested_player_count": requested,
                        "slot": 0,
                        "record_id": 0,
                        "target_name": name,
                        "source": "skipped_target_fill",
                        "force_rewrite": True,
                        "pre_blocked_reason": "no_unused_linked_roster_slot_for_skipped_target",
                    }
                )
    return rows


def _read_xor_u16_string_span(raw_payload: bytes, cursor: int, label: str) -> tuple[dict[str, Any], int]:
    start = cursor
    text, end = _read_xor_u16_string(raw_payload, cursor)
    size = int.from_bytes(raw_payload[start : start + 2], "little")
    return (
        {
            "label": label,
            "length_offset": start,
            "data_start": start + 2,
            "data_end": end,
            "size": size,
            "text": text,
        },
        end,
    )


def _linked_roster_layout(raw_payload: bytes) -> dict[str, Any] | None:
    if len(raw_payload) < 0x2A:
        return None
    record_size = int.from_bytes(raw_payload[0x26:0x28], "little")
    mode_byte = int(raw_payload[0x29])
    cursor = 0x2A
    string_spans: list[dict[str, Any]] = []
    try:
        span, cursor = _read_xor_u16_string_span(raw_payload, cursor, "short_name")
        string_spans.append(span)
        span, cursor = _read_xor_u16_string_span(raw_payload, cursor, "stadium_name")
        string_spans.append(span)
        cursor += 1
        if record_size > 0x20C:
            cursor += 1
        span, cursor = _read_xor_u16_string_span(raw_payload, cursor, "full_club_name")
        string_spans.append(span)
    except Exception:
        return None
    cursor += 4
    if record_size >= 0x1FE:
        cursor += 4
    cursor += 2 + 2 + 2
    link_base = cursor
    if mode_byte == 0:
        try:
            if record_size > 0x207:
                cursor += 2
            cursor += 4
            span, cursor = _read_xor_u16_string_span(raw_payload, cursor, "legacy_staff_name")
            string_spans.append(span)
            cursor += 4
            cursor += 4
            span, cursor = _read_xor_u16_string_span(raw_payload, cursor, "legacy_sponsor_name")
            string_spans.append(span)
            span, cursor = _read_xor_u16_string_span(raw_payload, cursor, "legacy_aux_name")
            string_spans.append(span)
            cursor += 3
            cursor += 20 if record_size >= 0x1F9 else 10
            cursor += 15
            cursor += 46 if record_size >= 0x1F9 else 42
            if record_size < 700:
                if record_size < 0x1F9:
                    pair_count = 7
                elif record_size < 0x203:
                    pair_count = 17
                else:
                    pair_count = 21
                cursor += pair_count * 2
            else:
                if cursor >= len(raw_payload):
                    return None
                sparse_count = raw_payload[cursor]
                cursor += 1 + sparse_count * 3
            if cursor > len(raw_payload):
                return None
            link_base = cursor
        except Exception:
            return None
    ent_cursor = link_base + _EXTERNAL_LINK_JUMP
    if ent_cursor >= len(raw_payload):
        return None
    ent_count = int(raw_payload[ent_cursor])
    player_count_offset = ent_cursor + 1 + ent_count * 4
    if player_count_offset >= len(raw_payload):
        return None
    player_count = int(raw_payload[player_count_offset])
    rows_start = player_count_offset + 1
    if rows_start + player_count * 5 > len(raw_payload):
        return None
    return {
        "player_count_offset": player_count_offset,
        "player_count": player_count,
        "rows_start": rows_start,
        "string_spans": string_spans,
    }


def _make_room_for_linked_roster_row(raw_payload: bytearray) -> tuple[int, list[dict[str, Any]], str | None]:
    """Trim non-selector EQ text to make one same-size linked roster row slot.

    The previously tested payload-growth strategy validated statically but
    produced a MANAGPRE modal. This path keeps the raw indexed payload length
    exactly constant by removing five bytes from variable-length stadium/full
    club text before inserting the five-byte linked JUG row.
    """
    layout = _linked_roster_layout(bytes(raw_payload))
    if layout is None:
        return 0, [], "linked_roster_layout_unresolved"
    player_count = int(layout["player_count"])
    if player_count >= 20:
        return 0, [], "linked_roster_already_at_20"

    needed = 5
    trim_events: list[dict[str, Any]] = []
    # Keep the selector-facing short name untouched. Prefer lower-visibility
    # legacy metadata first, then stadium, and only then full club name.
    trim_preferences = (
        ("legacy_sponsor_name", 4),
        ("legacy_staff_name", 4),
        ("stadium_name", 4),
        ("full_club_name", 12),
        ("full_club_name", 4),
    )
    while needed > 0:
        current_layout = _linked_roster_layout(bytes(raw_payload))
        if current_layout is None:
            return 0, trim_events, "linked_roster_layout_unresolved_during_trim"
        spans_by_label = {str(span["label"]): dict(span) for span in list(current_layout.get("string_spans") or [])}
        selected: tuple[str, int, dict[str, Any], int] | None = None
        for label, min_keep in trim_preferences:
            span = spans_by_label.get(label)
            if not span:
                continue
            old_size = int(span["size"])
            available = max(0, old_size - min_keep)
            if available <= 0:
                continue
            selected = (label, min_keep, span, min(available, needed))
            break
        if selected is None:
            break
        label, _min_keep, span, trim_bytes = selected
        old_size = int(span["size"])
        delete_start = int(span["data_end"]) - trim_bytes
        delete_end = int(span["data_end"])
        if delete_start < int(span["data_start"]) or delete_end > len(raw_payload):
            return 0, trim_events, "linked_roster_string_trim_bounds_failed"
        del raw_payload[delete_start:delete_end]
        new_size = old_size - trim_bytes
        raw_payload[int(span["length_offset"]) : int(span["length_offset"]) + 2] = new_size.to_bytes(2, "little")
        trim_events.append(
            {
                "label": label,
                "trim_bytes": trim_bytes,
                "old_size": old_size,
                "new_size": new_size,
                "old_text": str(span.get("text") or ""),
            }
        )
        needed -= trim_bytes

    if needed > 0:
        return 0, trim_events, "insufficient_same_size_eq_text_slack"

    trimmed_layout = _linked_roster_layout(bytes(raw_payload))
    if trimmed_layout is None:
        return 0, trim_events, "linked_roster_layout_unresolved_after_trim"
    if int(trimmed_layout["player_count"]) != player_count:
        return 0, trim_events, "linked_roster_player_count_changed_during_trim"
    return player_count, trim_events, None


def _write_raw_indexed_payloads(
    file_path: Path,
    raw_payload_by_offset: dict[int, bytes],
    *,
    create_backup: bool,
) -> str | None:
    if not raw_payload_by_offset:
        return None
    file_data = file_path.read_bytes()
    indexed = IndexedFDIFile.from_bytes(file_data)
    entries_by_offset = {int(entry.payload_offset): entry for entry in indexed.entries}
    missing = sorted(set(raw_payload_by_offset) - set(entries_by_offset))
    if missing:
        raise RuntimeError(f"Raw indexed offsets not present in {file_path}: {missing[:5]}")

    ordered_entries = sorted(indexed.entries, key=lambda item: int(item.payload_offset))
    first_payload_offset = int(ordered_entries[0].payload_offset)
    rebuilt = bytearray(file_data[:first_payload_offset])
    new_offsets_by_old_offset: dict[int, int] = {}
    new_lengths_by_offset: dict[int, int] = {}
    for idx, entry in enumerate(ordered_entries):
        old_offset = int(entry.payload_offset)
        old_length = int(entry.payload_length)
        old_end = old_offset + old_length
        if old_offset < 0 or old_end > len(file_data):
            raise RuntimeError(f"Indexed payload 0x{old_offset:x}+0x{old_length:x} is outside file bounds")
        payload = bytes(raw_payload_by_offset.get(old_offset, file_data[old_offset:old_end]))
        new_offsets_by_old_offset[old_offset] = len(rebuilt)
        new_lengths_by_offset[old_offset] = len(payload)
        rebuilt.extend(payload)
        if idx + 1 < len(ordered_entries):
            next_offset = int(ordered_entries[idx + 1].payload_offset)
            if next_offset < old_end:
                raise RuntimeError(f"Indexed payload overlap detected between 0x{old_offset:x} and 0x{next_offset:x}")
            rebuilt.extend(file_data[old_end:next_offset])
        else:
            rebuilt.extend(file_data[old_end:])

    for entry in indexed.entries:
        index_offset = int(entry.index_offset)
        key_length = int(rebuilt[index_offset + 4])
        payload_offset_pos = index_offset + 5 + key_length
        payload_length_pos = payload_offset_pos + 4
        if payload_length_pos + 4 > first_payload_offset:
            raise RuntimeError(f"Indexed directory entry at 0x{index_offset:x} has an invalid key length")
        old_payload_offset = int(entry.payload_offset)
        struct.pack_into("<I", rebuilt, payload_offset_pos, int(new_offsets_by_old_offset[old_payload_offset]))
        struct.pack_into("<I", rebuilt, payload_length_pos, int(new_lengths_by_offset[old_payload_offset]))

    IndexedFDIFile.from_bytes(bytes(rebuilt))
    backup_path = None
    if create_backup:
        backup_path = str(file_path.with_suffix(file_path.suffix + ".backup"))
        counter = 1
        while Path(backup_path).exists():
            backup_path = str(file_path.with_suffix(f"{file_path.suffix}.backup{counter}"))
            counter += 1
        shutil.copy2(file_path, backup_path)
    file_path.write_bytes(bytes(rebuilt))
    return backup_path


def _allocate_no_slot_rows(
    *,
    target_rows: list[dict[str, Any]],
    game_root: Path,
    templates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[int, bytes]]:
    team_file = game_root / "DBDAT" / "EQ98030.FDI"
    team_data = team_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(team_data)
    entries_by_id = {int(entry.record_id): entry for entry in indexed.entries}

    linked_ids: set[int] = set()
    for roster in load_eq_linked_team_rosters(
        team_file=str(team_file),
        player_file=str(game_root / "DBDAT" / "JUG98030.FDI"),
    ):
        for row in getattr(roster, "rows", []) or []:
            player_id = int(getattr(row, "player_record_id", 0) or 0)
            if player_id > 0:
                linked_ids.add(player_id)
    linked_ids.update(int(row.get("record_id") or 0) for row in target_rows if int(row.get("record_id") or 0) > 0)
    spare_ids = [
        int(template["record_id"])
        for template in templates
        if int(template["record_id"]) > 0 and int(template["record_id"]) not in linked_ids
    ]

    updated_rows: list[dict[str, Any]] = []
    insertions: list[dict[str, Any]] = []
    repoints: list[dict[str, Any]] = []
    raw_payload_by_offset: dict[int, bytes] = {}
    spare_index = 0

    for row in target_rows:
        if str(row.get("pre_blocked_reason") or "") != "no_unused_linked_roster_slot_for_skipped_target":
            updated_rows.append(row)
            continue
        eq_record_id = int(row.get("carrier_eq_record_id") or 0)
        entry = entries_by_id.get(eq_record_id)
        if entry is None:
            updated_rows.append(row)
            continue
        original_payload_length = int(entry.payload_length)
        raw_payload = bytearray(raw_payload_by_offset.get(int(entry.payload_offset), team_data[int(entry.payload_offset) : int(entry.payload_offset) + original_payload_length]))
        layout = _linked_roster_layout(bytes(raw_payload))
        if layout is None or int(layout["player_count"]) >= 20:
            updated_rows.append(row)
            continue
        if spare_index >= len(spare_ids):
            updated_rows.append(row)
            continue
        spare_record_id = spare_ids[spare_index]
        before_length = len(raw_payload)
        old_count, trim_events, trim_error = _make_room_for_linked_roster_row(raw_payload)
        if trim_error:
            updated_rows.append(
                {
                    **row,
                    "pre_blocked_reason": trim_error,
                    "same_size_trim_events": trim_events,
                }
            )
            continue
        layout_after_trim = _linked_roster_layout(bytes(raw_payload))
        if layout_after_trim is None:
            updated_rows.append({**row, "pre_blocked_reason": "linked_roster_layout_unresolved_after_trim"})
            continue
        insert_at = int(layout_after_trim["rows_start"]) + old_count * 5
        raw_payload[insert_at:insert_at] = bytes([0]) + int(spare_record_id).to_bytes(4, "little")
        raw_payload[int(layout_after_trim["player_count_offset"])] = old_count + 1
        if len(raw_payload) != before_length or len(raw_payload) != original_payload_length:
            updated_rows.append(
                {
                    **row,
                    "pre_blocked_reason": "same_size_eq_payload_length_guard_failed",
                    "old_payload_length": original_payload_length,
                    "new_payload_length": len(raw_payload),
                }
            )
            continue
        verify_layout = _linked_roster_layout(bytes(raw_payload))
        if verify_layout is None or int(verify_layout["player_count"]) != old_count + 1:
            updated_rows.append({**row, "pre_blocked_reason": "linked_roster_layout_unresolved_after_insert"})
            continue
        spare_index += 1
        raw_payload_by_offset[int(entry.payload_offset)] = bytes(raw_payload)
        allocated = {
            **row,
            "slot": old_count + 1,
            "record_id": spare_record_id,
            "source": "skipped_target_inserted",
            "allocated_spare_record_id": spare_record_id,
        }
        allocated.pop("pre_blocked_reason", None)
        updated_rows.append(allocated)
        insertions.append(
            {
                "club_key": row.get("club_key"),
                "club_display_name": row.get("club_display_name"),
                "carrier_eq_record_id": eq_record_id,
                "slot": old_count + 1,
                "record_id": spare_record_id,
                "target_name": row.get("target_name"),
                "old_player_count": old_count,
                "new_player_count": old_count + 1,
                "payload_length": original_payload_length,
                "same_size_trim_events": trim_events,
            }
        )

    final_rows: list[dict[str, Any]] = []
    target_name_by_record_id: dict[int, str] = {}
    for row in updated_rows:
        record_id = int(row.get("record_id") or 0)
        normalized_target = " ".join(str(row.get("target_name") or "").casefold().split())
        if record_id <= 0 or not normalized_target:
            final_rows.append(row)
            continue
        previous_target = target_name_by_record_id.get(record_id)
        if previous_target is None or previous_target == normalized_target:
            target_name_by_record_id[record_id] = normalized_target
            final_rows.append(row)
            continue

        eq_record_id = int(row.get("carrier_eq_record_id") or 0)
        slot = int(row.get("slot") or 0)
        entry = entries_by_id.get(eq_record_id)
        if entry is None or slot <= 0 or spare_index >= len(spare_ids):
            final_rows.append(row)
            continue
        original_payload_length = int(entry.payload_length)
        raw_payload = bytearray(raw_payload_by_offset.get(int(entry.payload_offset), team_data[int(entry.payload_offset) : int(entry.payload_offset) + original_payload_length]))
        layout = _linked_roster_layout(bytes(raw_payload))
        if layout is None or slot > int(layout["player_count"]):
            final_rows.append(row)
            continue
        row_offset = int(layout["rows_start"]) + (slot - 1) * 5
        if row_offset + 5 > len(raw_payload):
            final_rows.append(row)
            continue
        existing_record_id = int.from_bytes(raw_payload[row_offset + 1 : row_offset + 5], "little")
        if existing_record_id != record_id:
            final_rows.append(row)
            continue
        spare_record_id = spare_ids[spare_index]
        spare_index += 1
        raw_payload[row_offset + 1 : row_offset + 5] = int(spare_record_id).to_bytes(4, "little")
        if len(raw_payload) != original_payload_length:
            final_rows.append(row)
            continue
        raw_payload_by_offset[int(entry.payload_offset)] = bytes(raw_payload)
        allocated = {
            **row,
            "record_id": spare_record_id,
            "source": "duplicate_target_repointed",
            "allocated_spare_record_id": spare_record_id,
            "previous_conflicting_record_id": record_id,
            "previous_target_name": previous_target,
        }
        final_rows.append(allocated)
        target_name_by_record_id[spare_record_id] = normalized_target
        repoints.append(
            {
                "club_key": row.get("club_key"),
                "club_display_name": row.get("club_display_name"),
                "carrier_eq_record_id": eq_record_id,
                "slot": slot,
                "old_record_id": record_id,
                "new_record_id": spare_record_id,
                "target_name": row.get("target_name"),
                "previous_target_name": previous_target,
                "payload_length": original_payload_length,
            }
        )

    return final_rows, insertions, repoints, raw_payload_by_offset


def _template_candidates(player_file: Path) -> list[dict[str, Any]]:
    file_data = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(file_data)
    candidates: list[dict[str, Any]] = []
    for entry in indexed.entries:
        record_id = int(entry.record_id)
        payload_length = int(entry.payload_length)
        if record_id <= 0 or payload_length < _LINKED_RUNTIME_MIN_CERTIFIABLE_PLAYER_PAYLOAD_LENGTH:
            continue
        try:
            payload = entry.decode_payload(file_data)
            record = PlayerRecord.from_bytes(payload, int(entry.payload_offset))
        except Exception:
            continue
        name = " ".join(_player_display_name(record).split())
        if not name or name in {"Unknown Player", "Parse Error"}:
            continue
        try:
            width = _target_token_width(name)
        except Exception:
            continue
        candidates.append(
            {
                "record_id": record_id,
                "payload_offset": int(entry.payload_offset),
                "payload_length": payload_length,
                "payload": bytes(payload),
                "name": name,
                "token_width": width,
            }
        )
    return sorted(candidates, key=lambda item: (int(item["token_width"]), int(item["payload_length"]), int(item["record_id"])))


def _clone_template_payload(
    *,
    template: dict[str, Any],
    target_name: str,
    team_id: int | None,
    parse_offset: int,
    allow_parser_fixed_clone: bool,
) -> tuple[bytes, dict[str, Any]] | None:
    template_payload = bytes(template["payload"])
    template_name = str(template["name"])
    try:
        patched, replacement_offset, old_text, new_text = _build_linked_roster_template_clone_payload(
            template_payload=template_payload,
            template_player_name=template_name,
            target_player_name=target_name,
            team_id=team_id,
        )
        try:
            reparsed = PlayerRecord.from_bytes(bytes(patched), int(parse_offset))
        except Exception:
            reparsed = None
        if reparsed is not None and " ".join(_player_display_name(reparsed).casefold().split()) == " ".join(str(target_name).casefold().split()):
            return bytes(patched), {
                "method": "linked_text_token_clone",
                "replacement_offset": int(replacement_offset),
                "old_template_text": str(old_text),
                "new_template_text": str(new_text),
            }
    except Exception:
        pass

    try:
        patched, ok = replace_player_name_preserving_layout(template_payload, template_name, target_name)
    except Exception:
        patched, ok = template_payload, False
    if ok and len(patched) == len(template_payload):
        patched_bytes = bytearray(patched)
        if team_id is not None:
            patched_bytes[0:2] = int(team_id).to_bytes(2, "little")
        try:
            reparsed = PlayerRecord.from_bytes(bytes(patched_bytes), int(parse_offset))
        except Exception:
            reparsed = None
        if reparsed is not None and " ".join(_player_display_name(reparsed).casefold().split()) == " ".join(str(target_name).casefold().split()):
            return bytes(patched_bytes), {
                "method": "name_preserving_template_clone",
                "replacement_offset": None,
                "old_template_text": template_name,
                "new_template_text": target_name,
            }

    if not allow_parser_fixed_clone:
        return None

    try:
        patched = _build_parser_fixed_name_candidate(
            decoded_payload=template_payload,
            payload_offset=int(template["payload_offset"]),
            new_name=target_name,
        )
    except Exception:
        return None
    patched_bytes = bytearray(patched)
    if team_id is not None:
        patched_bytes[0:2] = int(team_id).to_bytes(2, "little")
    try:
        reparsed = PlayerRecord.from_bytes(bytes(patched_bytes), int(parse_offset))
    except Exception:
        return None
    if " ".join(_player_display_name(reparsed).casefold().split()) != " ".join(str(target_name).casefold().split()):
        return None
    return bytes(patched_bytes), {
        "method": "parser_fixed_name_template_clone",
        "replacement_offset": None,
        "old_template_text": template_name,
        "new_template_text": target_name,
    }


def repair_world_payloads(
    *,
    game_root: Path,
    assignment_path: Path,
    dry_run: bool,
    create_backup: bool,
    skipped_only: bool = False,
    allow_roster_insert: bool = False,
    allow_parser_fixed_clone: bool = False,
    original_payload_mode: str = "fixed-first",
) -> dict[str, Any]:
    player_file = game_root / "DBDAT" / "JUG98030.FDI"
    if not player_file.is_file():
        raise FileNotFoundError(f"Missing player file: {player_file}")
    if not assignment_path.is_file():
        raise FileNotFoundError(f"Missing assignment file: {assignment_path}")

    metadata = _build_indexed_player_runtime_metadata_index(str(player_file))
    file_data = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(file_data)
    entries_by_id = {int(entry.record_id): entry for entry in indexed.entries}
    templates = _template_candidates(player_file)
    target_rows = _assignment_rows(assignment_path, game_root=game_root, include_assigned=not skipped_only)
    if allow_roster_insert:
        target_rows, roster_insertions, roster_repoints, team_raw_payload_by_offset = _allocate_no_slot_rows(
            target_rows=target_rows,
            game_root=game_root,
            templates=templates,
        )
    else:
        roster_insertions = []
        roster_repoints = []
        team_raw_payload_by_offset = {}

    stages: list[tuple[int, _IndexedRawStageRecord]] = []
    repaired: list[dict[str, Any]] = []
    already_certified: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    used_template_counts: dict[int, int] = {}
    target_name_by_record_id: dict[int, str] = {}

    for row in target_rows:
        record_id = int(row["record_id"])
        target_name = str(row["target_name"])
        pre_blocked_reason = str(row.get("pre_blocked_reason") or "")
        if pre_blocked_reason:
            blockers.append({**row, "reason": pre_blocked_reason})
            continue
        entry = entries_by_id.get(record_id)
        current_meta = metadata.get(record_id)
        if entry is None or current_meta is None:
            blockers.append({**row, "reason": "player_record_missing"})
            continue
        previous_target = target_name_by_record_id.get(record_id)
        normalized_target = " ".join(target_name.casefold().split())
        if previous_target is not None and previous_target != normalized_target:
            blockers.append(
                {
                    **row,
                    "reason": "record_id_already_targets_different_player",
                    "previous_target_name": previous_target,
                }
            )
            continue
        target_name_by_record_id[record_id] = normalized_target
        current_name = " ".join(str(getattr(current_meta, "parsed_player_name", "") or "").casefold().split())
        expected_name = normalized_target
        force_rewrite = bool(row.get("force_rewrite"))
        if (
            int(current_meta.payload_length) >= _LINKED_RUNTIME_MIN_CERTIFIABLE_PLAYER_PAYLOAD_LENGTH
            and current_name == expected_name
            and not force_rewrite
        ):
            already_certified.append(row)
            continue
        try:
            target_payload = entry.decode_payload(file_data)
            target_record = PlayerRecord.from_bytes(target_payload, int(entry.payload_offset))
            team_id = int(getattr(target_record, "team_id", 0) or 0) or None
            required_width = _target_token_width(target_name)
        except Exception as exc:
            blockers.append({**row, "reason": "target_payload_parse_failed", "error": str(exc)})
            continue

        chosen: dict[str, Any] | None = None
        patched_payload: bytes | None = None
        repair_meta: dict[str, Any] | None = None
        if (
            original_payload_mode == "variable-first"
            and int(entry.payload_length) >= _LINKED_RUNTIME_MIN_CERTIFIABLE_PLAYER_PAYLOAD_LENGTH
        ):
            variable = _build_variable_original_name_payload(
                decoded_payload=bytes(target_payload),
                payload_offset=int(entry.payload_offset),
                target_name=target_name,
            )
            if variable is not None:
                variable_payload, applied_name = variable
                if len(variable_payload) >= _LINKED_RUNTIME_MIN_CERTIFIABLE_PLAYER_PAYLOAD_LENGTH:
                    patched_payload = bytes(variable_payload)
                    chosen = {
                        "record_id": record_id,
                        "payload_length": int(entry.payload_length),
                        "name": str(current_meta.parsed_player_name),
                    }
                    repair_meta = {
                        "method": "variable_name_original_payload",
                        "mutation_family": "native_length_prefixed_name_region",
                        "replacement_offset": None,
                        "old_template_text": str(current_meta.parsed_player_name),
                        "new_template_text": str(applied_name),
                    }

        if (
            patched_payload is None
            and original_payload_mode == "fixed-first"
            and int(entry.payload_length) >= _LINKED_RUNTIME_MIN_CERTIFIABLE_PLAYER_PAYLOAD_LENGTH
        ):
            try:
                fixed_payload, applied_name, mutation_family = _mutate_indexed_player_name_fixed_safe(
                    decoded_payload=bytes(target_payload),
                    payload_offset=int(entry.payload_offset),
                    new_name=target_name,
                )
            except Exception:
                fixed_payload = b""
                applied_name = ""
                mutation_family = ""
            if (
                fixed_payload
                and len(fixed_payload) == int(entry.payload_length)
                and " ".join(str(applied_name).casefold().split()) == expected_name
            ):
                patched_payload = bytes(fixed_payload)
                chosen = {
                    "record_id": record_id,
                    "payload_length": int(entry.payload_length),
                    "name": str(current_meta.parsed_player_name),
                }
                repair_meta = {
                    "method": "fixed_name_original_payload",
                    "mutation_family": str(mutation_family),
                    "replacement_offset": None,
                    "old_template_text": str(current_meta.parsed_player_name),
                    "new_template_text": target_name,
                }

        if patched_payload is None:
            for template in templates:
                if int(template["record_id"]) == record_id:
                    continue
                if int(template["token_width"]) < required_width or int(template["payload_length"]) < _LINKED_RUNTIME_MIN_CERTIFIABLE_PLAYER_PAYLOAD_LENGTH:
                    continue
                cloned = _clone_template_payload(
                    template=template,
                    target_name=target_name,
                    team_id=team_id,
                    parse_offset=int(entry.payload_offset),
                    allow_parser_fixed_clone=allow_parser_fixed_clone,
                )
                if cloned is None:
                    continue
                patched, meta = cloned
                chosen = template
                patched_payload = bytes(patched)
                repair_meta = dict(meta)
                break

        if chosen is None or patched_payload is None or repair_meta is None:
            blockers.append({**row, "reason": "no_compatible_runtime_template", "required_token_width": required_width})
            continue

        stages.append(
            (
                int(entry.payload_offset),
                _IndexedRawStageRecord(
                    raw_payload=patched_payload,
                    container_offset=int(entry.payload_offset),
                    container_length=int(entry.payload_length),
                ),
            )
        )
        used_template_counts[int(chosen["record_id"])] = used_template_counts.get(int(chosen["record_id"]), 0) + 1
        repaired.append(
            {
                **row,
                "old_payload_length": int(entry.payload_length),
                "new_payload_length": len(patched_payload),
                "template_record_id": int(chosen["record_id"]),
                "template_name": str(chosen["name"]),
                "team_id_written": team_id,
                **repair_meta,
            }
        )

    backup_path = None
    team_backup_path = None
    applied_to_disk = False
    if stages and not dry_run:
        backup_path = write_player_staged_records(
            str(player_file),
            stages,
            create_backup_before_write=create_backup,
        )
        applied_to_disk = True
    if team_raw_payload_by_offset and not dry_run:
        team_backup_path = _write_raw_indexed_payloads(
            game_root / "DBDAT" / "EQ98030.FDI",
            team_raw_payload_by_offset,
            create_backup=create_backup,
        )

    post = None
    if not dry_run:
        post_meta = _build_indexed_player_runtime_metadata_index(str(player_file))
        unresolved = []
        for row in target_rows:
            meta = post_meta.get(int(row["record_id"]))
            expected_name = " ".join(str(row.get("target_name") or "").casefold().split())
            actual_name = " ".join(str(getattr(meta, "parsed_player_name", "") if meta else "").casefold().split())
            if (
                meta is None
                or int(meta.payload_length) < _LINKED_RUNTIME_MIN_CERTIFIABLE_PLAYER_PAYLOAD_LENGTH
                or actual_name != expected_name
            ):
                unresolved.append(
                    {
                        **row,
                        "actual_name": str(getattr(meta, "parsed_player_name", "") if meta else ""),
                        "actual_payload_length": int(getattr(meta, "payload_length", 0) or 0) if meta else None,
                    }
                )
        post = {
            "target_rows": len(target_rows),
            "runtime_certified": len(target_rows) - len(unresolved),
            "unresolved_rows": len(unresolved),
            "unresolved_examples": unresolved[:25],
        }

    return {
        "schema": "pm99-world-runtime-payload-repair-v1",
        "game_root": str(game_root),
        "player_file": str(player_file),
        "assignment_path": str(assignment_path),
        "dry_run": bool(dry_run),
        "skipped_only": bool(skipped_only),
        "allow_roster_insert": bool(allow_roster_insert),
        "allow_parser_fixed_clone": bool(allow_parser_fixed_clone),
        "original_payload_mode": str(original_payload_mode),
        "applied_to_disk": applied_to_disk,
        "backup_path": backup_path,
        "team_backup_path": team_backup_path,
        "ok": not blockers and (post is None or post["unresolved_rows"] == 0),
        "counts": {
            "target_rows": len(target_rows),
            "already_certified": len(already_certified),
            "repaired": len(repaired),
            "blockers": len(blockers),
            "roster_insertions": len(roster_insertions),
            "roster_repoints": len(roster_repoints),
            "templates_available": len(templates),
            "templates_used": len(used_template_counts),
        },
        "post_apply": post,
        "blockers": blockers,
        "repaired": repaired,
        "roster_insertions": roster_insertions,
        "roster_repoints": roster_repoints,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", required=True)
    parser.add_argument("--assignment", required=True, help="slot_assignment_2025_top80.json path")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    parser.add_argument("--skipped-only", action="store_true", help="Repair only skipped target names while still using assigned slots for roster placement")
    parser.add_argument("--allow-roster-insert", action="store_true", help="Allow experimental same-size EQ linked-roster activation for skipped names with no active slot")
    parser.add_argument("--allow-parser-fixed-clone", action="store_true", help="Allow experimental parser-rebuilt template clones; disabled by default because runner testing found modal risk")
    parser.add_argument(
        "--original-payload-mode",
        choices=("fixed-first", "variable-first", "clone-only"),
        default="fixed-first",
        help=(
            "How to handle already-long original JUG payloads before template fallback. "
            "fixed-first preserves historical same-size behavior; variable-first rewrites "
            "the original native name region and lets the indexed writer update lengths; "
            "clone-only skips original-payload mutation."
        ),
    )
    args = parser.parse_args(argv)

    result = repair_world_payloads(
        game_root=Path(args.game_root).expanduser().resolve(),
        assignment_path=Path(args.assignment).expanduser().resolve(),
        dry_run=bool(args.dry_run),
        create_backup=not bool(args.no_backup),
        skipped_only=bool(args.skipped_only),
        allow_roster_insert=bool(args.allow_roster_insert),
        allow_parser_fixed_clone=bool(args.allow_parser_fixed_clone),
        original_payload_mode=str(args.original_payload_mode),
    )
    output_path = Path(args.output_json).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("ok", "counts", "post_apply")}, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
