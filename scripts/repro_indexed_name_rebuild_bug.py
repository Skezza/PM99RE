#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
EDITOR_ROOT = REPO_ROOT / "upstream" / "pm99-skezmod-db-editor"
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from assert_pm99_isolated_input import default_fixture_file, ensure_not_legacy_path, sha256  # noqa: E402
from app.editor_helpers import _player_display_name  # noqa: E402
from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from app.models import PlayerRecord  # noqa: E402


DEFAULT_MANIFEST = (
    REPO_ROOT
    / "work"
    / "pm99"
    / "joe"
    / "stoke_2015_noinject_fast_20260410T194922Z"
    / "patches"
    / "stoke_2015_metadata"
    / "stoke_2015_metadata_manifest.json"
)
DEFAULT_COMPARE_SOURCE_ROOT = (
    REPO_ROOT / "work" / "pm99" / "joe" / "stoke_bisect_slots2_20_fixed_20260410T211407Z" / "game"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reproduce indexed Stoke player suffix corruption by applying name-only "
            "batch edits to a pristine JUG98030.FDI copy and comparing parsed metadata."
        )
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="Path to stoke_2015_metadata_manifest.json",
    )
    parser.add_argument(
        "--players",
        default="",
        help="Optional source JUG98030.FDI path. Defaults to the pristine fixture file.",
    )
    parser.add_argument(
        "--compare-source-game-root",
        default=str(DEFAULT_COMPARE_SOURCE_ROOT),
        help="Optional edited game root to compare against the reproduced after-state",
    )
    parser.add_argument(
        "--slots",
        default="11-15",
        help="Slot selection from the manifest (example: 11-15 or 11,14)",
    )
    parser.add_argument(
        "--output-root",
        default=str(REPO_ROOT / "artifacts" / "research"),
        help="Directory under which the timestamped repro bundle is created",
    )
    parser.add_argument(
        "--bundle-id",
        default="",
        help="Optional explicit output directory name",
    )
    return parser.parse_args()


def _parse_slots(text: str, *, known_slots: set[int]) -> list[int]:
    slots: set[int] = set()
    for part in [item.strip() for item in text.split(",") if item.strip()]:
        if "-" in part:
            lo_text, hi_text = part.split("-", 1)
            lo = int(lo_text)
            hi = int(hi_text)
            if hi < lo:
                raise ValueError(f"Invalid slot range: {part}")
            slots.update(range(lo, hi + 1))
        else:
            slots.add(int(part))
    invalid = sorted(slot for slot in slots if slot not in known_slots)
    if invalid:
        raise ValueError(f"Requested slots are outside manifest range: {invalid}")
    return sorted(slots)


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["cp", "-a", "--reflink=auto", str(source), str(target)], check=True)


def _ensure_user_writable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | 0o200)


def _load_manifest_rows(manifest_path: Path, selected_slots: list[int]) -> list[dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = list(manifest.get("batch_rows") or [])
    by_slot = {int(row["slot"]): row for row in rows}
    return [by_slot[slot] for slot in selected_slots]


def _write_csv(csv_path: Path, *, manifest_rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "name",
        "offset",
        "new_name",
        "team_id",
        "squad_number",
        "position",
        "nationality",
        "dob_day",
        "dob_month",
        "dob_year",
        "age",
        "age_year",
        "height",
        "weight",
    ]
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in manifest_rows:
            writer.writerow(
                {
                    "name": "",
                    "offset": int(row["offset"]),
                    "new_name": str(row["name"]),
                    "team_id": "",
                    "squad_number": "",
                    "position": "",
                    "nationality": "",
                    "dob_day": "",
                    "dob_month": "",
                    "dob_year": "",
                    "age": "",
                    "age_year": "",
                    "height": "",
                    "weight": "",
                }
            )


def _load_indexed_entry_map(player_file: Path) -> tuple[dict[int, Any], bytes]:
    indexed = IndexedFDIFile.from_path(player_file)
    return {int(entry.record_id): entry for entry in indexed.entries}, player_file.read_bytes()


def _payload_sha256(entry: Any, file_bytes: bytes) -> str:
    import hashlib

    payload = entry.decode_payload(file_bytes)
    h = hashlib.sha256()
    h.update(payload)
    return h.hexdigest()


def _capture_record_state(player_file: Path, *, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entry_map, file_bytes = _load_indexed_entry_map(player_file)
    out: list[dict[str, Any]] = []
    for row in rows:
        pid = int(row["pid"])
        entry = entry_map[pid]
        payload = entry.decode_payload(file_bytes)
        parsed = PlayerRecord.from_bytes(payload, int(entry.payload_offset))
        out.append(
            {
                "slot": int(row["slot"]),
                "pid": pid,
                "payload_offset": int(entry.payload_offset),
                "payload_length": int(entry.payload_length),
                "payload_sha256": _payload_sha256(entry, file_bytes),
                "name": _player_display_name(parsed),
                "team_id": int(getattr(parsed, "team_id", 0) or 0),
                "squad_number": int(getattr(parsed, "squad_number", 0) or 0),
                "position_primary": int(getattr(parsed, "position_primary", 0) or 0),
                "nationality": int(getattr(parsed, "nationality", 0) or 0),
                "birth_day": int(getattr(parsed, "birth_day", 0) or 0),
                "birth_month": int(getattr(parsed, "birth_month", 0) or 0),
                "birth_year": int(getattr(parsed, "birth_year", 0) or 0),
                "height": int(getattr(parsed, "height", 0) or 0),
                "weight": (int(getattr(parsed, "weight", 0) or 0) if getattr(parsed, "weight", None) is not None else None),
                "skills": [int(v) for v in list(getattr(parsed, "skills", []) or [])],
                "extended": [int(v) for v in list(getattr(parsed, "extended", []) or [])],
                "indexed_unknown_0": getattr(parsed, "indexed_unknown_0", None),
                "indexed_unknown_1": getattr(parsed, "indexed_unknown_1", None),
                "indexed_face_components": [int(v) for v in list(getattr(parsed, "indexed_face_components", []) or [])],
                "indexed_unknown_9": getattr(parsed, "indexed_unknown_9", None),
                "indexed_unknown_10": getattr(parsed, "indexed_unknown_10", None),
            }
        )
    return out


def _run_editor_cli(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=str(REPO_ROOT), capture_output=True, text=True, check=False)
    return {
        "command": command,
        "returncode": int(completed.returncode),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _semantic_signature(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "team_id",
        "squad_number",
        "position_primary",
        "nationality",
        "birth_day",
        "birth_month",
        "birth_year",
        "height",
        "weight",
        "skills",
        "extended",
    )
    return {key: row[key] for key in keys}


def _suffix_signature(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "indexed_unknown_0",
        "indexed_unknown_1",
        "indexed_face_components",
        "indexed_unknown_9",
        "indexed_unknown_10",
    )
    return {key: row[key] for key in keys}


def main() -> int:
    args = _parse_args()
    manifest_path = Path(args.manifest).expanduser().resolve()
    source_player_file = (
        ensure_not_legacy_path(args.players, label="players file").resolve()
        if str(args.players).strip()
        else default_fixture_file("DBDAT/JUG98030.FDI")
    )
    compare_source_root = (
        ensure_not_legacy_path(args.compare_source_game_root, label="compare source root").resolve()
        if str(args.compare_source_game_root).strip()
        else None
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    known_slots = {int(row["slot"]) for row in list(manifest.get("batch_rows") or [])}
    selected_slots = _parse_slots(args.slots, known_slots=known_slots)
    manifest_rows = _load_manifest_rows(manifest_path, selected_slots)

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    bundle_id = args.bundle_id.strip() or f"indexed_name_rebuild_bug_{timestamp}"
    bundle_root = Path(args.output_root).expanduser().resolve() / bundle_id
    if bundle_root.exists():
        raise RuntimeError(f"Output bundle already exists: {bundle_root}")
    bundle_root.mkdir(parents=True, exist_ok=False)

    baseline_player_file = bundle_root / "baseline" / "JUG98030.FDI"
    working_player_file = bundle_root / "work" / "JUG98030.FDI"
    _copy_file(source_player_file, baseline_player_file)
    _copy_file(source_player_file, working_player_file)
    _ensure_user_writable(working_player_file)

    before_rows = _capture_record_state(baseline_player_file, rows=manifest_rows)

    rename_csv = bundle_root / "rename_subset.csv"
    _write_csv(rename_csv, manifest_rows=manifest_rows)
    batch_result = _run_editor_cli(
        [
            "./scripts/dev_editor.sh",
            "python3",
            "-m",
            "app.cli",
            "player-batch-edit",
            str(working_player_file),
            "--csv",
            str(rename_csv),
            "--json",
        ]
    )
    (bundle_root / "player_batch_edit_result.json").write_text(json.dumps(batch_result, indent=2) + "\n", encoding="utf-8")
    if int(batch_result["returncode"]) != 0:
        raise RuntimeError(f"player-batch-edit failed for {bundle_id}")

    after_rows = _capture_record_state(working_player_file, rows=manifest_rows)
    compare_rows = (
        _capture_record_state(compare_source_root / "DBDAT" / "JUG98030.FDI", rows=manifest_rows)
        if compare_source_root is not None
        else None
    )

    before_by_slot = {int(row["slot"]): row for row in before_rows}
    after_by_slot = {int(row["slot"]): row for row in after_rows}
    compare_by_slot = {int(row["slot"]): row for row in (compare_rows or [])}

    comparisons: list[dict[str, Any]] = []
    suffix_changed_count = 0
    semantic_changed_count = 0
    compare_suffix_match_count = 0
    for manifest_row in manifest_rows:
        slot = int(manifest_row["slot"])
        before = before_by_slot[slot]
        after = after_by_slot[slot]
        compare = compare_by_slot.get(slot)
        suffix_changed = _suffix_signature(before) != _suffix_signature(after)
        semantic_changed = _semantic_signature(before) != _semantic_signature(after)
        compare_suffix_match = (compare is not None and _suffix_signature(after) == _suffix_signature(compare))
        if suffix_changed:
            suffix_changed_count += 1
        if semantic_changed:
            semantic_changed_count += 1
        if compare_suffix_match:
            compare_suffix_match_count += 1
        comparisons.append(
            {
                "slot": slot,
                "pid": int(manifest_row["pid"]),
                "requested_new_name": str(manifest_row["name"]),
                "before": before,
                "after": after,
                "compare_source": compare,
                "suffix_changed": suffix_changed,
                "semantic_fields_changed": semantic_changed,
                "compare_source_suffix_match": compare_suffix_match,
            }
        )

    summary = {
        "scope": "indexed_name_rebuild_bug_repro",
        "timestamp_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bundle_root": str(bundle_root),
        "manifest_path": str(manifest_path),
        "source_players_path": str(source_player_file),
        "compare_source_game_root": str(compare_source_root) if compare_source_root is not None else None,
        "selected_slots": selected_slots,
        "before_sha256": sha256(baseline_player_file),
        "after_sha256": sha256(working_player_file),
        "suffix_changed_count": suffix_changed_count,
        "semantic_changed_count": semantic_changed_count,
        "compare_source_suffix_match_count": compare_suffix_match_count,
        "comparisons": comparisons,
    }
    (bundle_root / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"success": True, "bundle_root": str(bundle_root), "summary_path": str(bundle_root / "summary.json")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
