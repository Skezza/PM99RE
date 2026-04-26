#!/usr/bin/env python3
"""Extract Stoke roster fine-position slots with strict parser-backed contracts.

This probe is fail-closed:
- Marker-backed rows use the exact six-byte window consumed by MANAGPRE parser
  (`name_end-1 .. name_end+4` in decoded payload space).
- Indexed rows use the existing indexed-face component extraction contract.
- No external reconciliation data is used for slot interpretation.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
EDITOR_ROOT = REPO_ROOT / "upstream" / "pm99-skezmod-db-editor"
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from assert_pm99_isolated_input import choose_preferred_game_root, ensure_not_legacy_path
from app.editor_sources import gather_player_records
from app.eq_jug_linked import EQLinkedTeamRoster, load_eq_linked_team_rosters
from app.models import PlayerRecord

from probe_player_fine_positions import FINE_CODE_TO_LABEL, _decode_indexed_face_component0, _extract_name

KNOWN_POSITION_CODES = {code for code in FINE_CODE_TO_LABEL if 0 <= int(code) <= 17}
COARSE_CODE_TO_LABEL = {
    0: "Goalkeeper",
    1: "Defender",
    2: "Midfielder",
    3: "Forward",
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_team_file() -> Path:
    root = choose_preferred_game_root()
    return root / "DBDAT" / "EQ98030.FDI"


def _default_player_file() -> Path:
    root = choose_preferred_game_root()
    return root / "DBDAT" / "JUG98030.FDI"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _normalize_team_text(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum() or ch.isspace()).strip()


def _resolve_team_roster(
    *,
    team_file: Path,
    player_file: Path,
    team_query: str,
) -> EQLinkedTeamRoster:
    rosters = load_eq_linked_team_rosters(team_file=str(team_file), player_file=str(player_file))
    if not rosters:
        raise RuntimeError("No EQ->JUG linked rosters were parsed")

    normalized_query = _normalize_team_text(team_query)
    matches: list[EQLinkedTeamRoster] = []
    for roster in rosters:
        haystack = " ".join(
            [
                str(getattr(roster, "short_name", "") or ""),
                str(getattr(roster, "full_club_name", "") or ""),
                str(getattr(roster, "stadium_name", "") or ""),
            ]
        )
        if normalized_query in _normalize_team_text(haystack):
            matches.append(roster)

    if not matches:
        raise ValueError(f"No linked roster matched team_query={team_query!r}")
    if len(matches) == 1:
        return matches[0]

    exact: list[EQLinkedTeamRoster] = []
    for roster in matches:
        short_name = _normalize_team_text(str(getattr(roster, "short_name", "") or ""))
        full_name = _normalize_team_text(str(getattr(roster, "full_club_name", "") or ""))
        if normalized_query in {short_name, full_name}:
            exact.append(roster)
    if len(exact) == 1:
        return exact[0]
    raise ValueError(
        f"Ambiguous team query {team_query!r}; matched {[getattr(r, 'short_name', '') for r in matches]}"
    )


def _build_player_record_map(player_file: Path) -> tuple[dict[int, Any], dict[str, int]]:
    valid, uncertain = gather_player_records(str(player_file))
    by_id: dict[int, Any] = {}
    for row in [*valid, *uncertain]:
        record_id = int(getattr(row.record, "record_id", 0) or 0)
        if record_id > 0 and record_id not in by_id:
            by_id[record_id] = row
    return by_id, {"valid_rows": len(valid), "uncertain_rows": len(uncertain)}


def _decode_marker_slot_window(raw: bytes, record: PlayerRecord) -> dict[str, Any] | None:
    """Decode the six parser-consumed marker slots from decoded payload bytes.

    Contract anchor:
    - marker name_end is found by PlayerRecord._find_name_end_in_data(raw)
    - six slot bytes are read at name_end-1 .. name_end+4
    - slot decode: ((byte ^ 0x61) - 1) if xor>0 else 98

    Additional checks confirm marker-aligned DOB/height/weight bytes continue to
    match parser fields at name_end+9..+14 for this row.
    """
    name_end = PlayerRecord._find_name_end_in_data(raw)
    if name_end is None:
        return None

    start = int(name_end) - 1
    if start < 0 or (start + 6) > len(raw):
        return None

    slots: list[int] = []
    for i in range(6):
        xor_value = int(raw[start + i]) ^ 0x61
        slots.append(int(xor_value - 1) if xor_value > 0 else 98)

    def _decoded_byte(idx: int) -> int | None:
        if 0 <= idx < len(raw):
            return int(raw[idx] ^ 0x61)
        return None

    day_raw = _decoded_byte(int(name_end) + 9)
    month_raw = _decoded_byte(int(name_end) + 10)
    year_lo = _decoded_byte(int(name_end) + 11)
    year_hi = _decoded_byte(int(name_end) + 12)
    year_raw = None
    if year_lo is not None and year_hi is not None:
        year_raw = int(year_lo | (year_hi << 8))
    height_raw = _decoded_byte(int(name_end) + 13)
    weight_raw = _decoded_byte(int(name_end) + 14)

    day_match = (day_raw is not None) and (int(day_raw) == int(getattr(record, "birth_day", 0) or 0))
    month_match = (month_raw is not None) and (int(month_raw) == int(getattr(record, "birth_month", 0) or 0))
    year_match = (year_raw is not None) and (int(year_raw) == int(getattr(record, "birth_year", 0) or 0))
    height_match = (height_raw is not None) and (int(height_raw) == int(getattr(record, "height", 0) or 0))

    weight_slot_valid = bool(weight_raw is not None and 40 <= int(weight_raw) <= 140)
    parsed_weight = getattr(record, "weight", None)
    if weight_slot_valid and parsed_weight is not None:
        weight_match = bool(int(weight_raw) == int(parsed_weight))
    else:
        # Marker +14 is only a weight slot when it validates in range.
        # Out-of-range bytes are treated as non-weight marker-adjacent data.
        weight_match = None

    alignment = {
        "day_match": bool(day_match),
        "month_match": bool(month_match),
        "year_match": bool(year_match),
        "height_match": bool(height_match),
        "weight_slot_valid": bool(weight_slot_valid),
        "weight_match": weight_match,
        "overall_pass": bool(day_match and month_match and year_match and height_match),
        "decoded_day": day_raw,
        "decoded_month": month_raw,
        "decoded_year": year_raw,
        "decoded_height": height_raw,
        "decoded_weight": weight_raw,
    }

    return {
        "decode_status": "ok",
        "decode_source": "marker_window_name_end_minus1",
        "fine_position_slots": slots,
        "marker_anchor": int(name_end),
        "marker_slot_window_start": int(start),
        "marker_slot_window_end_exclusive": int(start + 6),
        "marker_alignment": alignment,
    }


def _decode_row_slots(player_row: Any) -> dict[str, Any]:
    record = player_row.record
    raw = bytes(getattr(record, "raw_data", b"") or b"")

    marker_decoded = _decode_marker_slot_window(raw, record)
    if marker_decoded is not None:
        return marker_decoded

    parsed_name = _extract_name(player_row)
    decoded = _decode_indexed_face_component0(raw, parsed_name)
    if decoded is not None:
        return {
            "decode_status": "ok",
            "decode_source": "indexed_face_component0",
            "fine_position_slots": [int(value) for value in decoded["fine_position_slots"]],
            "marker_anchor": None,
            "marker_slot_window_start": None,
            "marker_slot_window_end_exclusive": None,
            "marker_alignment": None,
        }

    return {
        "decode_status": "unresolved",
        "decode_source": "unresolved",
        "fine_position_slots": [],
        "marker_anchor": None,
        "marker_slot_window_start": None,
        "marker_slot_window_end_exclusive": None,
        "marker_alignment": None,
    }


def _labels_for_slots(slots: list[int]) -> list[str]:
    return [FINE_CODE_TO_LABEL.get(code, f"Unknown ({code})") for code in slots]


def _secondary_positions_from_marker_slots(slots: list[int], primary_code: int) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    # slot5 is treated as non-position tail because it frequently carries
    # non-code values (for example nationality-adjacent mirrors) in marker rows.
    for code in slots[1:5]:
        code = int(code)
        if code == 98:
            continue
        if code not in KNOWN_POSITION_CODES:
            continue
        if code == primary_code:
            continue
        if code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def _secondary_positions_from_indexed_slots(slots: list[int], primary_code: int) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for code in slots[1:6]:
        code = int(code)
        if code == 98:
            continue
        if code not in KNOWN_POSITION_CODES:
            continue
        if code == primary_code:
            continue
        if code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def run(
    *,
    team_file: Path,
    player_file: Path,
    team_query: str,
    output_dir: Path,
) -> dict[str, Any]:
    roster = _resolve_team_roster(team_file=team_file, player_file=player_file, team_query=team_query)
    player_map, player_load_stats = _build_player_record_map(player_file)

    rows: list[dict[str, Any]] = []
    missing_player_rows = 0
    unresolved_decode_rows = 0
    marker_rows = 0
    indexed_rows = 0
    marker_alignment_pass_rows = 0
    marker_alignment_fail_rows = 0

    for linked_row in sorted(list(getattr(roster, "rows", [])), key=lambda item: int(getattr(item, "slot_index", 0))):
        slot_index = int(getattr(linked_row, "slot_index", 0) or 0)
        pid = int(getattr(linked_row, "player_record_id", 0) or 0)
        linked_name = str(getattr(linked_row, "player_name", "") or "").strip()
        player_row = player_map.get(pid)
        if player_row is None:
            missing_player_rows += 1
            rows.append(
                {
                    "slot_index": slot_index,
                    "slot_number": slot_index + 1,
                    "player_record_id": pid,
                    "linked_player_name": linked_name,
                    "parsed_player_name": "",
                    "decode_status": "missing_player_record",
                    "decode_source": "missing_player_record",
                    "fine_position_slots": [],
                    "fine_position_slot_labels": [],
                    "primary_position_code": 98,
                    "primary_position_label": FINE_CODE_TO_LABEL[98],
                    "secondary_position_codes": [],
                    "secondary_position_labels": [],
                    "single_role_confirmed": False,
                    "non_position_tail_code": None,
                    "non_position_tail_label": None,
                    "marker_alignment": None,
                }
            )
            continue

        record = player_row.record
        parsed_name = _extract_name(player_row)
        decoded = _decode_row_slots(player_row)
        slots = [int(value) for value in decoded["fine_position_slots"]]
        if decoded["decode_status"] != "ok":
            unresolved_decode_rows += 1

        source = str(decoded["decode_source"])
        marker_alignment = decoded.get("marker_alignment")
        if source == "marker_window_name_end_minus1":
            marker_rows += 1
            if bool((marker_alignment or {}).get("overall_pass", False)):
                marker_alignment_pass_rows += 1
            else:
                marker_alignment_fail_rows += 1
            primary_code = int(slots[0]) if slots else 98
            if primary_code not in KNOWN_POSITION_CODES:
                primary_code = 98
            secondary_codes = _secondary_positions_from_marker_slots(slots, primary_code)
            tail_code = int(slots[5]) if len(slots) > 5 else 98
            if tail_code in KNOWN_POSITION_CODES or tail_code == 98:
                non_position_tail_code = None
                non_position_tail_label = None
            else:
                non_position_tail_code = int(tail_code)
                non_position_tail_label = f"Non-position ({int(tail_code)})"
            single_role_confirmed = (
                len(secondary_codes) == 0
                and len(slots) > 0
                and all(int(code) in {98, primary_code} for code in slots[1:5])
            )
        elif source == "indexed_face_component0":
            indexed_rows += 1
            primary_code = int(slots[0]) if slots else 98
            secondary_codes = _secondary_positions_from_indexed_slots(slots, primary_code)
            non_position_tail_code = None
            non_position_tail_label = None
            single_role_confirmed = (
                len(secondary_codes) == 0
                and len(slots) > 0
                and all(int(code) in {98, primary_code} for code in slots[1:6])
            )
        else:
            primary_code = 98
            secondary_codes = []
            non_position_tail_code = None
            non_position_tail_label = None
            single_role_confirmed = False

        rows.append(
            {
                "slot_index": slot_index,
                "slot_number": slot_index + 1,
                "player_record_id": pid,
                "linked_player_name": linked_name,
                "parsed_player_name": parsed_name,
                "decode_status": str(decoded["decode_status"]),
                "decode_source": source,
                "marker_anchor": decoded.get("marker_anchor"),
                "marker_slot_window_start": decoded.get("marker_slot_window_start"),
                "marker_slot_window_end_exclusive": decoded.get("marker_slot_window_end_exclusive"),
                "parser_coarse_code": int(getattr(record, "position_primary", 0) or 0),
                "parser_coarse_label": COARSE_CODE_TO_LABEL.get(
                    int(getattr(record, "position_primary", 0) or 0),
                    f"Unknown ({int(getattr(record, 'position_primary', 0) or 0)})",
                ),
                "fine_position_slots": slots,
                "fine_position_slot_labels": _labels_for_slots(slots),
                "primary_position_code": primary_code,
                "primary_position_label": FINE_CODE_TO_LABEL.get(primary_code, f"Unknown ({primary_code})"),
                "secondary_position_codes": secondary_codes,
                "secondary_position_labels": [
                    FINE_CODE_TO_LABEL.get(code, f"Unknown ({code})") for code in secondary_codes
                ],
                "single_role_confirmed": bool(single_role_confirmed),
                "non_position_tail_code": non_position_tail_code,
                "non_position_tail_label": non_position_tail_label,
                "marker_alignment": marker_alignment,
            }
        )

    total_rows = len(rows)
    resolved_rows = total_rows - missing_player_rows
    players_with_secondary = sum(1 for row in rows if len(row["secondary_position_codes"]) > 0)
    players_without_secondary = sum(1 for row in rows if len(row["secondary_position_codes"]) == 0)
    players_confirmed_single_role = sum(1 for row in rows if bool(row.get("single_role_confirmed")))
    rows_with_non_position_tail = sum(1 for row in rows if row.get("non_position_tail_code") is not None)

    larus_rows = [row for row in rows if "SIGURDSSON" in row["parsed_player_name"].upper()]

    criteria = {
        "all_roster_rows_resolved": missing_player_rows == 0,
        "all_rows_decoded": unresolved_decode_rows == 0,
        "larus_sigurdsson_present": len(larus_rows) > 0,
        "marker_alignment_pass_for_all_marker_rows": marker_alignment_fail_rows == 0,
    }
    status = "PASS" if all(criteria.values()) else "FAIL"

    summary = {
        "task": "stoke_secondary_positions_probe",
        "generated_at": _iso_now(),
        "status": status,
        "inputs": {
            "team_file": str(team_file),
            "player_file": str(player_file),
            "team_query": team_query,
            "player_load_stats": player_load_stats,
        },
        "team": {
            "eq_record_id": int(getattr(roster, "eq_record_id", 0) or 0),
            "short_name": str(getattr(roster, "short_name", "") or ""),
            "full_club_name": str(getattr(roster, "full_club_name", "") or ""),
            "stadium_name": str(getattr(roster, "stadium_name", "") or ""),
            "row_count": total_rows,
        },
        "metrics": {
            "total_roster_rows": total_rows,
            "resolved_rows": resolved_rows,
            "missing_player_rows": missing_player_rows,
            "unresolved_decode_rows": unresolved_decode_rows,
            "marker_rows": marker_rows,
            "indexed_rows": indexed_rows,
            "marker_alignment_pass_rows": marker_alignment_pass_rows,
            "marker_alignment_fail_rows": marker_alignment_fail_rows,
            "players_with_secondary_positions": players_with_secondary,
            "players_without_secondary_positions": players_without_secondary,
            "players_confirmed_single_role": players_confirmed_single_role,
            "rows_with_non_position_tail": rows_with_non_position_tail,
        },
        "criteria": criteria,
        "notes": [
            "Marker rows use strict parser slot window: name_end-1..name_end+4 (decoded payload bytes).",
            "For marker rows, slot0 is primary; slot1..4 are secondary candidates; slot5 is treated as non-position tail.",
            "Indexed rows use indexed_face_component0 decode with slot0 primary and slot1.. secondary candidates.",
            "No external reconciliation inputs are used in this contract probe.",
            "This probe is read-only and does not mutate DB files.",
        ],
        "larus_sigurdsson_rows": larus_rows,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "stoke_secondary_positions_manifest.json", {"rows": rows})
    _write_json(output_dir / "stoke_secondary_positions_summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract Stoke linked-roster secondary fine positions (strict contract)")
    parser.add_argument("--team-file", type=Path, default=_default_team_file())
    parser.add_argument("--player-file", type=Path, default=_default_player_file())
    parser.add_argument("--team-query", default="Stoke", help="Linked team matcher (default: Stoke)")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "work" / "stoke_secondary_positions",
        help="Directory for Stoke manifest/summary JSON outputs",
    )
    parser.add_argument("--json", action="store_true", help="Print summary JSON to stdout")
    args = parser.parse_args()

    summary = run(
        team_file=ensure_not_legacy_path(args.team_file, label="EQ file"),
        player_file=ensure_not_legacy_path(args.player_file, label="JUG file"),
        team_query=args.team_query,
        output_dir=args.output_dir,
    )
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(f"Wrote: {args.output_dir / 'stoke_secondary_positions_manifest.json'}")
        print(f"Wrote: {args.output_dir / 'stoke_secondary_positions_summary.json'}")
        print(f"Status: {summary['status']}")
        print(
            "Secondary positions: "
            f"{summary['metrics']['players_with_secondary_positions']} / {summary['metrics']['total_roster_rows']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
