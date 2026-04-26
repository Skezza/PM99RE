#!/usr/bin/env python3
"""Repair repointed roster slots that reuse player IDs linked elsewhere.

The repointed 2025 roster strategy writes target player payloads into donor JUG
records and then points EQ roster slots at those donors. If a donor record is
still referenced by another linked roster, MANAGPRE can resolve the player
under the other club and omit the new row from Squad Management.

This helper keeps the already-booting repointed DB and either:
- reassigns duplicate-linked slots for one club to globally unused JUG records;
- reassigns all manifest target duplicates when enough unused records exist; or
- detaches stale non-target EQ references so all manifest target rows stay
  uniquely linked.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
EDITOR_ROOT = REPO_ROOT / "upstream" / "pm99-skezmod-db-editor"
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.editor_actions import _IndexedRawStageRecord, write_player_staged_records  # noqa: E402
from app.editor_helpers import team_query_matches  # noqa: E402
from app.eq_jug_linked import load_eq_linked_team_rosters  # noqa: E402
from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from scripts.build_pm99_repointed_roster_candidate import (  # noqa: E402
    _build_non_assigned_payload,
    _candidate_player_rows,
    _globally_linked_player_ids,
    _linked_roster_layout,
    _write_raw_indexed_payloads,
)


def _resolve_roster(*, team_file: Path, player_file: Path, team_query: str) -> Any:
    matches = [
        roster
        for roster in load_eq_linked_team_rosters(team_file=str(team_file), player_file=str(player_file))
        if team_query_matches(
            team_query,
            team_name=str(getattr(roster, "short_name", "") or ""),
            full_club_name=str(getattr(roster, "full_club_name", "") or ""),
        )
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one roster for {team_query!r}, found {len(matches)}")
    return matches[0]


def _linked_refs_by_player_id(rosters: list[Any]) -> dict[int, list[dict[str, Any]]]:
    refs_by_player_id: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for roster in rosters:
        for row in list(getattr(roster, "rows", []) or []):
            record_id = int(getattr(row, "player_record_id", 0) or 0)
            if record_id <= 0:
                continue
            refs_by_player_id[record_id].append(
                {
                    "eq_record_id": int(getattr(roster, "eq_record_id", 0) or 0),
                    "team_name": str(getattr(roster, "short_name", "") or ""),
                    "full_club_name": str(getattr(roster, "full_club_name", "") or ""),
                    "slot": int(getattr(row, "slot_index", 0) or 0) + 1,
                    "flag": int(getattr(row, "flag", 0) or 0),
                    "player_name": str(getattr(row, "player_name", "") or ""),
                }
            )
    return refs_by_player_id


def _repair_rows(
    *,
    game_root: Path,
    duplicate_rows: list[dict[str, Any]],
    dry_run: bool,
) -> tuple[list[dict[str, Any]], int]:
    team_file = game_root / "DBDAT" / "EQ98030.FDI"
    player_file = game_root / "DBDAT" / "JUG98030.FDI"
    linked_ids = _globally_linked_player_ids(team_file=team_file, player_file=player_file)
    candidates = _candidate_player_rows(player_file, excluded_record_ids=linked_ids)
    if len(candidates) < len(duplicate_rows):
        raise RuntimeError(f"Need {len(duplicate_rows)} unused donor rows, found {len(candidates)}")
    donor_templates = _candidate_player_rows(player_file, excluded_record_ids=set())

    player_stages: list[tuple[int, _IndexedRawStageRecord]] = []
    repairs: list[dict[str, Any]] = []
    for target, candidate in zip(duplicate_rows, candidates):
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
        repairs.append(
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

    team_data = team_file.read_bytes()
    indexed_teams = IndexedFDIFile.from_bytes(team_data)
    team_entries_by_id = {int(entry.record_id): entry for entry in indexed_teams.entries}
    raw_payload_by_offset: dict[int, bytes] = {}
    for repair in repairs:
        eq_record_id = int(repair["carrier_eq_record_id"])
        team_entry = team_entries_by_id.get(eq_record_id)
        if team_entry is None:
            raise RuntimeError(f"Missing EQ record {eq_record_id}")
        payload_offset = int(team_entry.payload_offset)
        raw_payload = bytearray(
            raw_payload_by_offset.get(
                payload_offset,
                team_data[payload_offset : payload_offset + int(team_entry.payload_length)],
            )
        )
        layout = _linked_roster_layout(bytes(raw_payload))
        if layout is None:
            raise RuntimeError(f"Could not parse linked roster layout for EQ {eq_record_id}")
        slot = int(repair["slot"])
        row_offset = int(layout["rows_start"]) + (slot - 1) * 5
        if row_offset + 5 > len(raw_payload):
            raise RuntimeError(f"Slot {slot} is outside EQ {eq_record_id} payload")
        found = int.from_bytes(raw_payload[row_offset + 1 : row_offset + 5], "little")
        if found != int(repair["old_record_id"]):
            raise RuntimeError(f"EQ {eq_record_id} slot {slot} expected {repair['old_record_id']}, found {found}")
        raw_payload[row_offset + 1 : row_offset + 5] = int(repair["new_record_id"]).to_bytes(4, "little")
        raw_payload_by_offset[payload_offset] = bytes(raw_payload)

    if not dry_run and repairs:
        write_player_staged_records(str(player_file), player_stages, create_backup_before_write=False)
        _write_raw_indexed_payloads(team_file, raw_payload_by_offset, create_backup=False)

    return repairs, len(candidates)


def repair_duplicate_links(
    *,
    game_root: Path,
    team_query: str,
    dry_run: bool,
) -> dict[str, Any]:
    team_file = game_root / "DBDAT" / "EQ98030.FDI"
    player_file = game_root / "DBDAT" / "JUG98030.FDI"
    if not team_file.is_file():
        raise FileNotFoundError(f"Missing team file: {team_file}")
    if not player_file.is_file():
        raise FileNotFoundError(f"Missing player file: {player_file}")

    rosters = load_eq_linked_team_rosters(team_file=str(team_file), player_file=str(player_file))
    refs_by_player_id = _linked_refs_by_player_id(rosters)

    roster = _resolve_roster(team_file=team_file, player_file=player_file, team_query=team_query)
    target_eq_id = int(getattr(roster, "eq_record_id", 0) or 0)
    duplicate_rows: list[dict[str, Any]] = []
    for row in list(getattr(roster, "rows", []) or []):
        record_id = int(getattr(row, "player_record_id", 0) or 0)
        refs = refs_by_player_id.get(record_id, [])
        other_refs = [ref for ref in refs if int(ref["eq_record_id"]) != target_eq_id]
        if not other_refs:
            continue
        duplicate_rows.append(
            {
                "club_key": team_query.lower().replace(" ", "_").replace(".", ""),
                "club_display_name": str(getattr(roster, "full_club_name", "") or getattr(roster, "short_name", "") or team_query),
                "carrier_eq_record_id": target_eq_id,
                "slot": int(getattr(row, "slot_index", 0) or 0) + 1,
                "target_name": str(getattr(row, "player_name", "") or "").strip(),
                "old_record_id": record_id,
                "other_refs": other_refs,
            }
        )

    repairs, available_unused_donors = _repair_rows(game_root=game_root, duplicate_rows=duplicate_rows, dry_run=dry_run)

    return {
        "schema": "pm99-repointed-roster-duplicate-link-repair-v1",
        "game_root": str(game_root),
        "team_query": team_query,
        "dry_run": bool(dry_run),
        "ok": True,
        "duplicate_row_count": len(duplicate_rows),
        "available_unused_donors": available_unused_donors,
        "repairs": repairs,
    }


def repair_manifest_duplicate_links(
    *,
    game_root: Path,
    manifest_path: Path,
    dry_run: bool,
) -> dict[str, Any]:
    team_file = game_root / "DBDAT" / "EQ98030.FDI"
    player_file = game_root / "DBDAT" / "JUG98030.FDI"
    if not team_file.is_file():
        raise FileNotFoundError(f"Missing team file: {team_file}")
    if not player_file.is_file():
        raise FileNotFoundError(f"Missing player file: {player_file}")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Missing manifest file: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rosters = load_eq_linked_team_rosters(team_file=str(team_file), player_file=str(player_file))
    refs_by_player_id = _linked_refs_by_player_id(rosters)

    duplicate_rows: list[dict[str, Any]] = []
    for allocation in list(manifest.get("allocations") or []):
        if not isinstance(allocation, dict):
            continue
        eq_record_id = int(allocation.get("carrier_eq_record_id") or 0)
        slot = int(allocation.get("slot") or 0)
        record_id = int(allocation.get("new_record_id") or 0)
        target_name = str(allocation.get("target_name") or allocation.get("applied_name") or "").strip()
        if eq_record_id <= 0 or slot <= 0 or record_id <= 0 or not target_name:
            continue
        other_refs = [ref for ref in refs_by_player_id.get(record_id, []) if int(ref["eq_record_id"]) != eq_record_id]
        if not other_refs:
            continue
        duplicate_rows.append(
            {
                "club_key": str(allocation.get("club_key") or ""),
                "club_display_name": str(allocation.get("club_display_name") or allocation.get("club_key") or ""),
                "carrier_eq_record_id": eq_record_id,
                "slot": slot,
                "target_name": target_name,
                "old_record_id": record_id,
                "other_refs": other_refs[:10],
            }
        )

    repairs, available_unused_donors = _repair_rows(game_root=game_root, duplicate_rows=duplicate_rows, dry_run=dry_run)
    return {
        "schema": "pm99-repointed-roster-manifest-duplicate-link-repair-v1",
        "game_root": str(game_root),
        "manifest_path": str(manifest_path),
        "dry_run": bool(dry_run),
        "ok": True,
        "allocation_count": len(list(manifest.get("allocations") or [])),
        "duplicate_row_count": len(duplicate_rows),
        "available_unused_donors": available_unused_donors,
        "repairs": repairs,
    }


def detach_manifest_external_duplicate_refs(
    *,
    game_root: Path,
    manifest_path: Path,
    dry_run: bool,
) -> dict[str, Any]:
    """Clear non-target roster references that collide with manifest target rows."""

    team_file = game_root / "DBDAT" / "EQ98030.FDI"
    player_file = game_root / "DBDAT" / "JUG98030.FDI"
    if not team_file.is_file():
        raise FileNotFoundError(f"Missing team file: {team_file}")
    if not player_file.is_file():
        raise FileNotFoundError(f"Missing player file: {player_file}")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Missing manifest file: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    allocations = [row for row in list(manifest.get("allocations") or []) if isinstance(row, dict)]
    target_slot_keys = {
        (int(row.get("carrier_eq_record_id") or 0), int(row.get("slot") or 0))
        for row in allocations
        if int(row.get("carrier_eq_record_id") or 0) > 0 and int(row.get("slot") or 0) > 0
    }
    target_ids = {
        int(row.get("new_record_id") or 0)
        for row in allocations
        if int(row.get("new_record_id") or 0) > 0
    }

    rosters = load_eq_linked_team_rosters(team_file=str(team_file), player_file=str(player_file))
    refs_by_player_id = _linked_refs_by_player_id(rosters)
    detach_events: list[dict[str, Any]] = []
    for record_id in sorted(target_ids):
        for ref in refs_by_player_id.get(record_id, []):
            ref_key = (int(ref["eq_record_id"]), int(ref["slot"]))
            if ref_key in target_slot_keys:
                continue
            detach_events.append({"record_id": record_id, **ref})

    team_data = team_file.read_bytes()
    indexed_teams = IndexedFDIFile.from_bytes(team_data)
    team_entries_by_id = {int(entry.record_id): entry for entry in indexed_teams.entries}
    raw_payload_by_offset: dict[int, bytes] = {}
    for event in detach_events:
        eq_record_id = int(event["eq_record_id"])
        team_entry = team_entries_by_id.get(eq_record_id)
        if team_entry is None:
            raise RuntimeError(f"Missing EQ record {eq_record_id}")
        payload_offset = int(team_entry.payload_offset)
        raw_payload = bytearray(
            raw_payload_by_offset.get(
                payload_offset,
                team_data[payload_offset : payload_offset + int(team_entry.payload_length)],
            )
        )
        layout = _linked_roster_layout(bytes(raw_payload))
        if layout is None:
            raise RuntimeError(f"Could not parse linked roster layout for EQ {eq_record_id}")
        slot = int(event["slot"])
        row_offset = int(layout["rows_start"]) + (slot - 1) * 5
        if row_offset + 5 > len(raw_payload):
            raise RuntimeError(f"Slot {slot} is outside EQ {eq_record_id} payload")
        found = int.from_bytes(raw_payload[row_offset + 1 : row_offset + 5], "little")
        if found != int(event["record_id"]):
            raise RuntimeError(f"EQ {eq_record_id} slot {slot} expected {event['record_id']}, found {found}")
        raw_payload[row_offset + 1 : row_offset + 5] = (0).to_bytes(4, "little")
        raw_payload_by_offset[payload_offset] = bytes(raw_payload)

    if not dry_run and detach_events:
        _write_raw_indexed_payloads(team_file, raw_payload_by_offset, create_backup=False)

    return {
        "schema": "pm99-repointed-roster-manifest-external-ref-detach-v1",
        "game_root": str(game_root),
        "manifest_path": str(manifest_path),
        "dry_run": bool(dry_run),
        "ok": True,
        "allocation_count": len(allocations),
        "target_id_count": len(target_ids),
        "detached_ref_count": len(detach_events),
        "touched_eq_count": len({int(event["eq_record_id"]) for event in detach_events}),
        "detach_events": detach_events,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", required=True)
    parser.add_argument("--team")
    parser.add_argument("--manifest")
    parser.add_argument("--all-manifest-targets", action="store_true")
    parser.add_argument("--detach-external-refs", action="store_true")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if bool(args.detach_external_refs):
        if not args.manifest:
            raise SystemExit("--detach-external-refs requires --manifest")
        result = detach_manifest_external_duplicate_refs(
            game_root=Path(args.game_root).expanduser().resolve(),
            manifest_path=Path(args.manifest).expanduser().resolve(),
            dry_run=bool(args.dry_run),
        )
    elif bool(args.all_manifest_targets):
        if not args.manifest:
            raise SystemExit("--all-manifest-targets requires --manifest")
        result = repair_manifest_duplicate_links(
            game_root=Path(args.game_root).expanduser().resolve(),
            manifest_path=Path(args.manifest).expanduser().resolve(),
            dry_run=bool(args.dry_run),
        )
    else:
        if not args.team:
            raise SystemExit("--team is required unless --all-manifest-targets is used")
        result = repair_duplicate_links(
            game_root=Path(args.game_root).expanduser().resolve(),
            team_query=str(args.team),
            dry_run=bool(args.dry_run),
        )
    output_path = Path(args.output_json).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_keys = (
        "ok",
        "duplicate_row_count",
        "available_unused_donors",
        "detached_ref_count",
        "touched_eq_count",
        "allocation_count",
    )
    print(json.dumps({k: result[k] for k in summary_keys if k in result}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
