#!/usr/bin/env python3
"""DB-only Stars repair experiment for PM99.

Creates an isolated DBDAT copy and pads short linked Stars player payloads in
JUG98030.FDI to the runtime-safe length threshold used by the current-squad
filter investigation. This intentionally does not clone opaque bytes from other
players and does not patch MANAGPRE.EXE.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from app.editor_actions import _IndexedRawStageRecord, write_player_staged_records
from app.eq_jug_linked import load_eq_linked_team_rosters
from app.fdi_indexed import IndexedFDIFile

MIN_RUNTIME_SAFE_LEN = 80


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dbdat", required=True, type=Path)
    parser.add_argument("--out-dbdat", required=True, type=Path)
    parser.add_argument("--team", default="Stars")
    parser.add_argument("--min-len", type=int, default=MIN_RUNTIME_SAFE_LEN)
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def _norm(value: str) -> str:
    return " ".join(str(value or "").split()).casefold()


def main() -> int:
    args = _parse_args()
    src = args.source_dbdat.resolve()
    out = args.out_dbdat.resolve()
    if not src.is_dir():
        raise SystemExit(f"missing source DBDAT: {src}")
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(src, out)

    eq_file = out / "EQ98030.FDI"
    jug_file = out / "JUG98030.FDI"
    roster_matches = [
        roster
        for roster in load_eq_linked_team_rosters(team_file=str(eq_file), player_file=str(jug_file))
        if _norm(getattr(roster, "short_name", "")) == _norm(args.team)
        or _norm(getattr(roster, "full_club_name", "")) == _norm(args.team)
    ]
    if len(roster_matches) != 1:
        raise SystemExit(f"expected exactly one {args.team!r} roster, found {len(roster_matches)}")
    roster = roster_matches[0]
    target_ids = {int(getattr(row, "player_record_id", 0) or 0) for row in getattr(roster, "rows", [])}

    before_bytes = jug_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(before_bytes)
    staged = []
    changes = []
    for entry in indexed.entries:
        record_id = int(entry.record_id)
        if record_id not in target_ids:
            continue
        decoded = entry.decode_payload(before_bytes)
        old_len = int(entry.payload_length)
        if old_len >= int(args.min_len):
            changes.append(
                {
                    "player_record_id": record_id,
                    "payload_offset_before": int(entry.payload_offset),
                    "old_len": old_len,
                    "new_len": old_len,
                    "changed": False,
                    "reason": "already_runtime_safe_length",
                }
            )
            continue
        filler = decoded[-1:] if decoded else b"\x61"
        patched = decoded + (filler * (int(args.min_len) - old_len))
        staged.append(
            (
                int(entry.payload_offset),
                _IndexedRawStageRecord(
                    raw_payload=patched,
                    container_offset=int(entry.payload_offset),
                    container_length=old_len,
                ),
            )
        )
        changes.append(
            {
                "player_record_id": record_id,
                "payload_offset_before": int(entry.payload_offset),
                "old_len": old_len,
                "new_len": len(patched),
                "changed": True,
                "appended_decoded_hex": (filler * (len(patched) - old_len)).hex(),
                "appended_decoded_ascii": (filler * (len(patched) - old_len)).decode("cp1252", errors="replace"),
            }
        )

    backup_path = None
    if staged:
        backup_path = write_player_staged_records(
            str(jug_file),
            staged,
            create_backup_before_write=False,
        )

    after_bytes = jug_file.read_bytes()
    after_indexed = IndexedFDIFile.from_bytes(after_bytes)
    after_by_id = {int(entry.record_id): entry for entry in after_indexed.entries}
    for change in changes:
        entry = after_by_id.get(int(change["player_record_id"]))
        if entry is not None:
            change["payload_offset_after"] = int(entry.payload_offset)
            change["indexed_len_after"] = int(entry.payload_length)

    changed_offsets = [c for c in changes if c.get("changed")]
    report = {
        "source_dbdat": str(src),
        "out_dbdat": str(out),
        "team": args.team,
        "eq_record_id": int(getattr(roster, "eq_record_id", 0) or 0),
        "team_name": str(getattr(roster, "short_name", "") or ""),
        "full_club_name": str(getattr(roster, "full_club_name", "") or ""),
        "min_runtime_safe_len": int(args.min_len),
        "backup_path": backup_path,
        "jug_size_before": len(before_bytes),
        "jug_size_after": len(after_bytes),
        "total_size_delta": len(after_bytes) - len(before_bytes),
        "changed_payload_count": len(changed_offsets),
        "changes": sorted(changes, key=lambda item: int(item["player_record_id"])),
    }

    report_path = args.report or (out.parent / "stars_db_payload_padding_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
