#!/usr/bin/env python3
"""Extract player fine-role slot bytes with absolute offsets and labels.

This probe is intended as an upstream-ingestible forensic artifact producer.
It emits both machine-readable JSON and analyst-friendly CSV.
"""

from __future__ import annotations

import argparse
import csv
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
from probe_player_fine_positions import FINE_CODE_TO_LABEL


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_team_file() -> Path:
    root = choose_preferred_game_root()
    return root / "DBDAT" / "EQ98030.FDI"


def _default_player_file() -> Path:
    root = choose_preferred_game_root()
    return root / "DBDAT" / "JUG98030.FDI"


def _normalize_team_text(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum() or ch.isspace()).strip()


def _slug(value: str) -> str:
    out = "".join(ch.lower() if ch.isalnum() else "_" for ch in value)
    out = "_".join(part for part in out.split("_") if part)
    return out or "team"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _resolve_team_roster(*, team_file: Path, player_file: Path, team_query: str) -> EQLinkedTeamRoster:
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


def _decode_marker_slots(raw: bytes) -> tuple[int | None, list[dict[str, Any]]]:
    name_end = PlayerRecord._find_name_end_in_data(raw)
    if name_end is None:
        return None, []
    start = int(name_end) - 1
    if start < 0 or (start + 6) > len(raw):
        return int(name_end), []
    slots: list[dict[str, Any]] = []
    for slot in range(6):
        offset = start + slot
        raw_byte = int(raw[offset])
        xor_value = raw_byte ^ 0x61
        code = int(xor_value - 1) if xor_value > 0 else 98
        slots.append(
            {
                "slot": int(slot),
                "offset": int(offset),
                "raw_byte": int(raw_byte),
                "xor": int(xor_value),
                "code": int(code),
                "label": FINE_CODE_TO_LABEL.get(int(code), f"Unknown({int(code)})"),
            }
        )
    return int(name_end), slots


def _decode_indexed_slots(raw: bytes, parsed_name: str) -> tuple[int | None, list[dict[str, Any]]]:
    anchor = PlayerRecord._find_indexed_suffix_anchor(raw, parsed_name)
    if anchor is None:
        return None, []
    anchor = int(anchor)
    slots: list[dict[str, Any]] = []
    for slot in range(6):
        offset = anchor + 2 + slot
        if offset >= len(raw):
            break
        raw_byte = int(raw[offset])
        xor_value = raw_byte ^ 0x61
        if not (1 <= xor_value <= 18):
            break
        code = int(xor_value - 1)
        slots.append(
            {
                "slot": int(slot),
                "offset": int(offset),
                "raw_byte": int(raw_byte),
                "xor": int(xor_value),
                "code": int(code),
                "label": FINE_CODE_TO_LABEL.get(int(code), f"Unknown({int(code)})"),
            }
        )
    return anchor, slots


def run(*, team_file: Path, player_file: Path, team_query: str, output_dir: Path) -> dict[str, Any]:
    roster = _resolve_team_roster(team_file=team_file, player_file=player_file, team_query=team_query)
    valid, uncertain = gather_player_records(str(player_file))
    by_id: dict[int, Any] = {}
    for row in [*valid, *uncertain]:
        record_id = int(getattr(row.record, "record_id", 0) or 0)
        if record_id > 0 and record_id not in by_id:
            by_id[record_id] = row

    rows: list[dict[str, Any]] = []
    for slot_index, slot in enumerate(getattr(roster, "rows", []), start=1):
        pid = int(getattr(slot, "player_record_id", 0) or 0)
        player_row = by_id.get(pid)
        if player_row is None:
            rows.append(
                {
                    "slot": int(slot_index),
                    "pid": int(pid),
                    "name": None,
                    "record_header": None,
                    "decode_source": "missing",
                    "name_end": None,
                    "indexed_anchor": None,
                    "marker_slots": [],
                    "indexed_slots": [],
                    "active_slots": [],
                    "active_codes": [],
                    "active_labels": [],
                }
            )
            continue

        record = player_row.record
        name = str(getattr(record, "name", "") or "").strip()
        raw = bytes(getattr(record, "raw_data", b"") or b"")
        header = raw[2:5].hex() if len(raw) >= 5 else ""

        name_end, marker_slots = _decode_marker_slots(raw)
        indexed_anchor, indexed_slots = _decode_indexed_slots(raw, name)

        if header == "dd6361":
            decode_source = "indexed"
            active_slots = list(indexed_slots)
        elif marker_slots:
            decode_source = "marker"
            active_slots = list(marker_slots)
        else:
            decode_source = "unresolved"
            active_slots = []

        rows.append(
            {
                "slot": int(slot_index),
                "pid": int(pid),
                "name": name,
                "record_header": header,
                "decode_source": decode_source,
                "name_end": name_end,
                "indexed_anchor": indexed_anchor,
                "marker_slots": marker_slots,
                "indexed_slots": indexed_slots,
                "active_slots": active_slots,
                "active_codes": [int(item["code"]) for item in active_slots],
                "active_labels": [str(item["label"]) for item in active_slots],
            }
        )

    team_short = str(getattr(roster, "short_name", "") or team_query).strip()
    team_full = str(getattr(roster, "full_club_name", "") or "").strip()
    stem = _slug(team_full or team_short or team_query) + "_role_slots"

    manifest_path = output_dir / f"{stem}_manifest.json"
    table_path = output_dir / f"{stem}_table.csv"
    summary_path = output_dir / f"{stem}_summary.json"

    manifest = {
        "generated_at_utc": _iso_now(),
        "team_query": team_query,
        "team_short_name": team_short,
        "team_full_name": team_full,
        "team_file": str(team_file),
        "player_file": str(player_file),
        "rows": rows,
    }
    _write_json(manifest_path, manifest)

    with table_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "slot",
                "pid",
                "name",
                "record_header",
                "decode_source",
                "name_end",
                "indexed_anchor",
                "active_codes",
                "active_labels",
                "active_offsets",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["slot"],
                    row["pid"],
                    row["name"] or "",
                    row["record_header"] or "",
                    row["decode_source"],
                    row["name_end"],
                    row["indexed_anchor"],
                    ";".join(str(code) for code in row["active_codes"]),
                    ";".join(str(label) for label in row["active_labels"]),
                    ";".join(str(item["offset"]) for item in row["active_slots"]),
                ]
            )

    summary = {
        "generated_at_utc": _iso_now(),
        "team_query": team_query,
        "team_short_name": team_short,
        "team_full_name": team_full,
        "team_file": str(team_file),
        "player_file": str(player_file),
        "metrics": {
            "total_rows": len(rows),
            "decoded_indexed_rows": sum(1 for row in rows if row["decode_source"] == "indexed"),
            "decoded_marker_rows": sum(1 for row in rows if row["decode_source"] == "marker"),
            "unresolved_rows": sum(1 for row in rows if row["decode_source"] == "unresolved"),
            "missing_rows": sum(1 for row in rows if row["decode_source"] == "missing"),
            "rows_with_multiple_active_roles": sum(1 for row in rows if len(row["active_codes"]) > 1),
        },
        "artifacts": {
            "manifest_json": str(manifest_path),
            "table_csv": str(table_path),
        },
    }
    _write_json(summary_path, summary)
    return {"manifest_path": manifest_path, "table_path": table_path, "summary_path": summary_path, "summary": summary}


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract fine-role slot bytes for a linked team roster")
    parser.add_argument("--team-file", type=Path, default=_default_team_file())
    parser.add_argument("--player-file", type=Path, default=_default_player_file())
    parser.add_argument("--team-query", type=str, default="Stoke")
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "work")
    parser.add_argument("--json", action="store_true", help="Print summary JSON to stdout")
    args = parser.parse_args()

    result = run(
        team_file=ensure_not_legacy_path(args.team_file, label="EQ file"),
        player_file=ensure_not_legacy_path(args.player_file, label="JUG file"),
        team_query=str(args.team_query),
        output_dir=args.output_dir.expanduser().resolve(),
    )

    print(f"Wrote: {result['manifest_path']}")
    print(f"Wrote: {result['table_path']}")
    print(f"Wrote: {result['summary_path']}")
    if args.json:
        print(json.dumps(result["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
