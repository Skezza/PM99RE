#!/usr/bin/env python3
"""Extract and summarize PM99 fine-grained player positions.

Research utility for PM99RE. This script is designed to be straightforward to
promote into upstream tooling once integration work starts.
"""

from __future__ import annotations

import argparse
from collections import Counter
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
from app.models import PlayerRecord

FINE_CODE_TO_LABEL: dict[int, str] = {
    0: "Keeper",
    1: "Right Back",
    2: "Left Back",
    3: "Sweeper",
    4: "Inside Centre Left",
    5: "Inside Centre Right",
    6: "Mid. Right",
    7: "Inside Right",
    8: "Centre Forward",
    9: "Central Mid.",
    10: "Mid. Left",
    11: "Right Winger",
    12: "Striker",
    13: "Left Winger",
    14: "Defensive Midfielder",
    15: "Right Forward",
    16: "Left Forward",
    17: "Inside Left",
    98: "Unassigned",
}

COARSE_CODE_TO_LABEL: dict[int, str] = {
    0: "Goalkeeper",
    1: "Defender",
    2: "Midfielder",
    3: "Forward",
}

REQUESTED_LABELS = (
    "Inside Centre Right",
    "Inside Right",
    "Striker",
    "Centre Forward",
)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_jug_path() -> Path:
    root = choose_preferred_game_root()
    return root / "DBDAT" / "JUG98030.FDI"


def _decode_slot_byte(encoded_byte: int) -> int:
    xor_value = int(encoded_byte) ^ 0x61
    if xor_value <= 0:
        return 98
    return int(xor_value - 1)


def _decode_marker_slots(raw: bytes) -> dict[str, Any] | None:
    name_end = PlayerRecord._find_name_end_in_data(raw)
    if name_end is None:
        return None

    start = int(name_end) - 1
    if start < 0 or (start + 6) > len(raw):
        return None

    slots = [_decode_slot_byte(raw[start + i]) for i in range(6)]
    return {
        "fine_position_source": "name_end_minus2_slot1",
        "fine_position_code": int(slots[0]),
        "fine_position_slots": [int(value) for value in slots],
        "decode_anchor": {
            "name_end": int(name_end),
            "slot_window_start": int(start),
            "slot_window_end_exclusive": int(start + 6),
        },
    }


def _decode_indexed_face_component0(raw: bytes, parsed_name: str) -> dict[str, Any] | None:
    anchor = PlayerRecord._find_indexed_suffix_anchor(raw, parsed_name)
    if anchor is None:
        return None

    anchor = int(anchor)
    if (anchor + 2) >= len(raw):
        return None

    slots: list[int] = []
    for rel in range(6):
        idx = anchor + 2 + rel
        if idx >= len(raw):
            break
        xor_value = int(raw[idx]) ^ 0x61
        if 1 <= xor_value <= 18:
            slots.append(int(xor_value - 1))
        else:
            break

    code = int(slots[0]) if slots else 98
    return {
        "fine_position_source": "indexed_face_component0",
        "fine_position_code": code,
        "fine_position_slots": [int(value) for value in slots],
        "decode_anchor": {
            "indexed_suffix_anchor": anchor,
            "face_component_start": int(anchor + 2),
            "face_component_end_exclusive": int(anchor + 2 + len(slots)),
        },
    }


def _extract_name(row: Any) -> str:
    record = row.record
    name = str(getattr(record, "name", "") or "").strip()
    if name:
        return name
    given = str(getattr(record, "given_name", "") or "").strip()
    surname = str(getattr(record, "surname", "") or "").strip()
    return f"{given} {surname}".strip()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run(jug_file: Path, output_dir: Path) -> dict[str, Any]:
    valid, uncertain = gather_player_records(str(jug_file))
    rows: list[dict[str, Any]] = []

    source_counter: Counter[str] = Counter()
    fine_code_counter: Counter[int] = Counter()
    unresolved_rows = 0

    for row in [*valid, *uncertain]:
        record = row.record
        raw = bytes(getattr(record, "raw_data", b"") or b"")
        parsed_name = _extract_name(row)

        decoded = _decode_marker_slots(raw)
        if decoded is None:
            decoded = _decode_indexed_face_component0(raw, parsed_name)

        if decoded is None:
            unresolved_rows += 1
            decoded = {
                "fine_position_source": "unresolved",
                "fine_position_code": 98,
                "fine_position_slots": [],
                "decode_anchor": {},
            }

        fine_code = int(decoded["fine_position_code"])
        source_counter[str(decoded["fine_position_source"])] += 1
        fine_code_counter[fine_code] += 1

        rows.append(
            {
                "offset": int(getattr(row, "offset", 0) or 0),
                "source": str(getattr(row, "source", "")),
                "name": parsed_name,
                "position_primary": int(getattr(record, "position_primary", 0) or 0),
                "position_primary_label": COARSE_CODE_TO_LABEL.get(
                    int(getattr(record, "position_primary", 0) or 0),
                    f"Unknown ({int(getattr(record, 'position_primary', 0) or 0)})",
                ),
                "fine_position_code": fine_code,
                "fine_position_label": FINE_CODE_TO_LABEL.get(fine_code, f"Unknown ({fine_code})"),
                "fine_position_source": str(decoded["fine_position_source"]),
                "fine_position_slots": [int(value) for value in decoded["fine_position_slots"]],
                "decode_anchor": dict(decoded["decode_anchor"]),
            }
        )

    total_players = len(rows)
    players_assigned = sum(1 for row in rows if row["fine_position_source"] != "unresolved")
    unknown_label_count = sum(1 for row in rows if row["fine_position_code"] not in FINE_CODE_TO_LABEL)
    unresolved_or_unknown_count = int(unresolved_rows + unknown_label_count)
    coverage_ratio = (players_assigned / total_players) if total_players else 0.0

    requested_label_counts = {
        label: sum(1 for row in rows if row["fine_position_label"] == label)
        for label in REQUESTED_LABELS
    }

    status = (
        "PASS"
        if total_players > 0
        and players_assigned == total_players
        and unresolved_or_unknown_count == 0
        else "FAIL"
    )

    codebook = {
        "generated_at": _iso_now(),
        "code_to_label": {str(code): label for code, label in sorted(FINE_CODE_TO_LABEL.items())},
        "code_counts": {str(code): int(count) for code, count in sorted(fine_code_counter.items())},
        "requested_labels": list(REQUESTED_LABELS),
        "requested_label_counts": requested_label_counts,
        "decode_contract": {
            "marker_slot_contract": {
                "source_name": "name_end_minus2_slot1",
                "window_rule": "Read six bytes at offsets name_end-1..name_end+4",
                "decode_rule": "slot_code = ((byte ^ 0x61) - 1) when xor>0 else 98",
                "primary_rule": "Primary fine position = decoded slot 0",
            },
            "indexed_fallback_contract": {
                "source_name": "indexed_face_component0",
                "window_rule": "Read indexed face-component bytes at anchor+2..anchor+7 while xor in [1,18]",
                "decode_rule": "component_code = (byte ^ 0x61) - 1",
                "primary_rule": "Primary fine position = first decoded face component",
            },
        },
    }

    summary = {
        "task": "fine_positions_decode_repro",
        "generated_at": _iso_now(),
        "status": status,
        "inputs": {
            "jug_file": str(jug_file),
            "total_valid_rows": len(valid),
            "total_uncertain_rows": len(uncertain),
        },
        "metrics": {
            "total_players": total_players,
            "players_assigned": players_assigned,
            "unresolved_or_unknown_count": unresolved_or_unknown_count,
            "coverage_ratio": round(coverage_ratio, 10),
            "source_counts": {name: int(count) for name, count in sorted(source_counter.items())},
            "fine_code_counts": {str(code): int(count) for code, count in sorted(fine_code_counter.items())},
            "requested_label_counts": requested_label_counts,
        },
        "criteria": {
            "players_assigned_equals_total_players": players_assigned == total_players,
            "unresolved_or_unknown_count_equals_zero": unresolved_or_unknown_count == 0,
            "coverage_ratio_equals_1_0": abs(coverage_ratio - 1.0) < 1e-12,
            "requested_labels_present": all(requested_label_counts.get(label, 0) > 0 for label in REQUESTED_LABELS),
        },
        "notes": [
            "This script reproduces parser-side fine-position extraction from raw player payload bytes.",
            "If corpus bytes change, absolute counts may change; the decode contract remains the same.",
        ],
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "player_fine_positions_manifest.json", {"rows": rows})
    _write_json(output_dir / "fine_position_codebook.json", codebook)
    _write_json(output_dir / "fine_positions_summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract PM99 fine-grained player position coverage")
    parser.add_argument("--jug-file", type=Path, default=_default_jug_path())
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "work" / "fine_positions_decode_repro",
        help="Directory for manifest/codebook/summary JSON output",
    )
    parser.add_argument("--json", action="store_true", help="Print summary JSON to stdout")
    args = parser.parse_args()

    summary = run(jug_file=ensure_not_legacy_path(args.jug_file, label="JUG file"), output_dir=args.output_dir)
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(f"Wrote: {args.output_dir / 'player_fine_positions_manifest.json'}")
        print(f"Wrote: {args.output_dir / 'fine_position_codebook.json'}")
        print(f"Wrote: {args.output_dir / 'fine_positions_summary.json'}")
        print(f"Status: {summary['status']}")
        print(f"Coverage: {summary['metrics']['players_assigned']} / {summary['metrics']['total_players']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
