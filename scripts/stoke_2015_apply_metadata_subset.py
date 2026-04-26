#!/usr/bin/env python3
"""Apply a manifest-backed subset of Stoke 2015 metadata to an isolated PM99 game root.

This is the runtime-bisect companion to ``stoke_2015_apply_metadata.py``. It reuses the
previously generated Stoke metadata manifest, stages a CSV containing only the requested
slots/fields, applies the change through the upstream editor CLI, validates the database,
and writes row-level verification artifacts.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from assert_pm99_isolated_input import resolve_game_root, sha256  # noqa: E402
from stoke_2015_apply_metadata import _run_cli, _verify_rows  # noqa: E402


FIELD_GROUPS: dict[str, tuple[str, ...]] = {
    "nationality": ("nationality",),
    "dob": ("dob",),
    "height": ("height",),
    "weight": ("weight",),
    "stature": ("height", "weight"),
    "all": ("nationality", "dob", "height", "weight"),
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply a subset of Stoke 2015 metadata from an existing manifest")
    parser.add_argument("--game-root", "--game-dir", dest="game_root", required=True, help="Writable isolated PM99 game root")
    parser.add_argument("--manifest", required=True, help="Path to stoke_2015_metadata_manifest.json")
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "artifacts" / f"stoke_2015_metadata_subset_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"),
        help="Artifact output directory",
    )
    parser.add_argument(
        "--slots",
        default="all",
        help="Slot selector (example: all, 1,3,5-8)",
    )
    parser.add_argument(
        "--fields",
        default="all",
        help="Comma-separated field groups/fields (available: nationality,dob,height,weight,stature,all)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Generate CSV and manifest only")
    return parser.parse_args()


def _parse_slots(text: str, *, known_slots: set[int]) -> list[int]:
    if not text.strip() or text.strip().lower() == "all":
        return sorted(known_slots)

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


def _parse_fields(text: str) -> list[str]:
    raw_tokens = [item.strip().lower() for item in text.split(",") if item.strip()]
    if not raw_tokens:
        raw_tokens = ["all"]

    expanded: list[str] = []
    for token in raw_tokens:
        if token not in FIELD_GROUPS:
            raise ValueError(f"Unsupported field token: {token}")
        for item in FIELD_GROUPS[token]:
            if item not in expanded:
                expanded.append(item)
    return expanded


def _write_subset_csv(csv_path: Path, rows: list[dict[str, Any]], *, selected_fields: set[str]) -> None:
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
        for row in rows:
            writer.writerow(
                {
                    "name": row["name"],
                    "offset": row["offset"],
                    "new_name": "",
                    "team_id": "",
                    "squad_number": "",
                    "position": "",
                    "nationality": row["nationality_code"] if "nationality" in selected_fields else "",
                    "dob_day": row["birth_day"] if "dob" in selected_fields else "",
                    "dob_month": row["birth_month"] if "dob" in selected_fields else "",
                    "dob_year": row["birth_year_calibrated"] if "dob" in selected_fields else "",
                    "age": "",
                    "age_year": "",
                    "height": row["height_cm"] if "height" in selected_fields else "",
                    "weight": row["weight_kg"] if "weight" in selected_fields else "",
                }
            )


def _verify_selected_fields(
    player_file: Path,
    rows: list[dict[str, Any]],
    *,
    selected_fields: set[str],
) -> list[dict[str, Any]]:
    base_rows = _verify_rows(player_file, rows)
    field_keys: list[str] = []
    if "nationality" in selected_fields:
        field_keys.append("nationality")
    if "dob" in selected_fields:
        field_keys.extend(["birth_day", "birth_month", "birth_year"])
    if "height" in selected_fields:
        field_keys.append("height")
    if "weight" in selected_fields:
        field_keys.append("weight")

    verification: list[dict[str, Any]] = []
    for row in base_rows:
        expected = dict(row["expected"])
        actual = dict(row["actual"])
        filtered_expected = {key: expected[key] for key in field_keys}
        filtered_actual = {key: actual[key] for key in field_keys}
        verification.append(
            {
                "slot": int(row["slot"]),
                "name": row["name"],
                "pid": int(row["pid"]),
                "offset": int(row["offset"]),
                "selected_fields": list(field_keys),
                "expected": filtered_expected,
                "actual": filtered_actual,
                "matches": filtered_expected == filtered_actual,
            }
        )
    return verification


def main() -> int:
    args = _parse_args()
    game_root = resolve_game_root(args.game_root, require_writable=not bool(args.dry_run), default_to_fixture=False)
    if game_root is None:
        raise SystemExit("A writable isolated PM99 game root is required")

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(args.manifest).expanduser().resolve()
    if not manifest_path.is_file():
        raise SystemExit(f"Manifest not found: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_rows = list(manifest.get("batch_rows") or [])
    if not manifest_rows:
        raise SystemExit(f"Manifest has no batch_rows: {manifest_path}")

    selected_fields = set(_parse_fields(args.fields))
    known_slots = {int(row["slot"]) for row in manifest_rows}
    selected_slots = _parse_slots(args.slots, known_slots=known_slots)
    selected_rows = [row for row in manifest_rows if int(row["slot"]) in selected_slots]
    if not selected_rows:
        raise SystemExit("Selection resolved to zero manifest rows")

    player_file = Path(game_root) / "DBDAT" / "JUG98030.FDI"
    team_file = Path(game_root) / "DBDAT" / "EQ98030.FDI"
    coach_file = Path(game_root) / "DBDAT" / "ENT98030.FDI"

    csv_path = output_dir / "stoke_2015_metadata_subset_batch.csv"
    _write_subset_csv(csv_path, selected_rows, selected_fields=selected_fields)

    subset_manifest = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source_manifest_path": str(manifest_path),
        "game_root": str(game_root),
        "player_file": str(player_file),
        "team_file": str(team_file),
        "coach_file": str(coach_file),
        "dry_run": bool(args.dry_run),
        "slots": selected_slots,
        "fields": sorted(selected_fields),
        "row_count": len(selected_rows),
        "batch_rows": selected_rows,
        "csv_path": str(csv_path),
        "input_hashes": {
            "JUG98030.FDI": sha256(player_file),
            "EQ98030.FDI": sha256(team_file),
            "ENT98030.FDI": sha256(coach_file),
        },
    }
    subset_manifest_path = output_dir / "stoke_2015_metadata_subset_manifest.json"
    subset_manifest_path.write_text(json.dumps(subset_manifest, indent=2), encoding="utf-8")

    result: dict[str, Any] = {
        "manifest_path": str(subset_manifest_path),
        "source_manifest_path": str(manifest_path),
        "csv_path": str(csv_path),
        "dry_run": bool(args.dry_run),
        "slots": selected_slots,
        "fields": sorted(selected_fields),
        "row_count": len(selected_rows),
    }

    if not args.dry_run:
        batch_cmd = [
            "./scripts/dev_editor.sh",
            "python3",
            "-m",
            "app.cli",
            "player-batch-edit",
            str(player_file),
            "--csv",
            str(csv_path),
            "--json",
        ]
        batch_result = _run_cli(batch_cmd, cwd=REPO_ROOT)
        result["player_batch_edit"] = batch_result
        if batch_result["returncode"] != 0:
            result_path = output_dir / "stoke_2015_metadata_subset_apply_result.json"
            result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
            raise SystemExit(
                f"player-batch-edit failed for subset apply (exit {batch_result['returncode']}), see {result_path}"
            )

        validate_cmd = [
            "./scripts/dev_editor.sh",
            "python3",
            "-m",
            "app.cli",
            "validate-database",
            "--players",
            str(player_file),
            "--teams",
            str(team_file),
            "--coaches",
            str(coach_file),
            "--json",
        ]
        validate_result = _run_cli(validate_cmd, cwd=REPO_ROOT)
        result["validate_database"] = validate_result

        verification_rows = _verify_selected_fields(player_file, selected_rows, selected_fields=selected_fields)
        verification_path = output_dir / "stoke_2015_metadata_subset_verification.json"
        verification_path.write_text(json.dumps(verification_rows, indent=2), encoding="utf-8")
        result["verification_path"] = str(verification_path)
        result["verification_ok"] = all(bool(row.get("matches")) for row in verification_rows)

    result["final_hashes"] = {
        "JUG98030.FDI": sha256(player_file),
        "EQ98030.FDI": sha256(team_file),
        "ENT98030.FDI": sha256(coach_file),
    }
    result_path = output_dir / "stoke_2015_metadata_subset_apply_result.json"
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "result_path": str(result_path),
                "manifest_path": str(subset_manifest_path),
                "csv_path": str(csv_path),
                "slots": selected_slots,
                "fields": sorted(selected_fields),
            },
            indent=2,
        )
    )
    if not args.dry_run and not result.get("verification_ok", False):
        raise SystemExit(f"Subset verification failed, see {result_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
