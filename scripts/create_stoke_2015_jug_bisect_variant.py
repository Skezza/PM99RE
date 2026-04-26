#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
EDITOR_ROOT = REPO_ROOT / "upstream" / "pm99-skezmod-db-editor"
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from assert_pm99_isolated_input import core_file_hashes, resolve_fixture_root, resolve_game_root, sha256  # noqa: E402
from app.editor_helpers import _player_display_name  # noqa: E402
from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from app.models import PlayerRecord  # noqa: E402
from app.xor import xor_encode  # noqa: E402

FIELD_GROUPS: dict[str, tuple[str, ...]] = {
    "names": ("name",),
    "fields": ("nationality", "dob", "height", "weight"),
    "payload": ("payload",),
    "all": ("name", "nationality", "dob", "height", "weight"),
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a Stoke 2015 JUG-only bisect variant from an isolated PM99 game root.",
    )
    parser.add_argument("--source-game-root", required=True, help="Existing isolated PM99 game root")
    parser.add_argument(
        "--baseline-game-root",
        default="",
        help="Optional isolated PM99 baseline root. Defaults to the pristine fixture.",
    )
    parser.add_argument(
        "--manifest",
        default=str(
            REPO_ROOT
            / "work"
            / "pm99"
            / "joe"
            / "stoke_2015_noinject_fast_20260410T194922Z"
            / "patches"
            / "stoke_2015_metadata"
            / "stoke_2015_metadata_manifest.json"
        ),
        help="Path to stoke_2015_metadata_manifest.json with slot/pid rows",
    )
    parser.add_argument(
        "--slots",
        required=True,
        help="Slots to revert against the baseline (example: 2-10, 11-20, 2,5,7-9)",
    )
    parser.add_argument(
        "--surfaces",
        default="all",
        help="Comma-separated surfaces to revert (names,fields,payload,all)",
    )
    parser.add_argument(
        "--output-root",
        default=str(REPO_ROOT / "work" / "pm99" / "joe"),
        help="Directory under which the variant directory is created",
    )
    parser.add_argument(
        "--variant-id",
        default="",
        help="Optional explicit variant directory name",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip validate-database after writing the variant; useful for high-throughput runtime matrices.",
    )
    return parser.parse_args()


def _copy_game_tree(source_game_root: Path, target_game_root: Path) -> None:
    target_game_root.parent.mkdir(parents=True, exist_ok=True)
    if target_game_root.exists():
        raise RuntimeError(f"Target game root already exists: {target_game_root}")
    target_game_root.mkdir(parents=True, exist_ok=False)
    subprocess.run(
        [
            "cp",
            "-a",
            "--reflink=auto",
            f"{source_game_root}/.",
            str(target_game_root),
        ],
        check=True,
    )


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


def _parse_surfaces(text: str) -> list[str]:
    raw_tokens = [item.strip().lower() for item in text.split(",") if item.strip()]
    if not raw_tokens:
        raw_tokens = ["all"]

    expanded: list[str] = []
    for token in raw_tokens:
        if token not in FIELD_GROUPS:
            raise ValueError(f"Unsupported surface token: {token}")
        for item in FIELD_GROUPS[token]:
            if item not in expanded:
                expanded.append(item)
    if "payload" in expanded and len(expanded) > 1:
        raise ValueError("payload is an exact raw-record restore surface and cannot be combined with parser-field surfaces")
    return expanded


def _indexed_entry_by_id(player_file: Path) -> dict[int, Any]:
    indexed = IndexedFDIFile.from_path(player_file)
    return {int(entry.record_id): entry for entry in indexed.entries}


def _sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _parse_payload_summary(payload: bytes, payload_offset: int) -> dict[str, Any]:
    parsed = PlayerRecord.from_bytes(payload, payload_offset)
    attrs = list(getattr(parsed, "skills", []) or [])
    extended = list(getattr(parsed, "extended", []) or [])
    return {
        "name": _player_display_name(parsed),
        "team_id": int(getattr(parsed, "team_id", 0) or 0),
        "squad_number": int(getattr(parsed, "squad_number", 0) or 0),
        "nationality": int(getattr(parsed, "nationality", 0) or 0),
        "position_primary": int(getattr(parsed, "position_primary", 0) or 0),
        "dob_day": int(getattr(parsed, "birth_day", 0) or 0),
        "dob_month": int(getattr(parsed, "birth_month", 0) or 0),
        "dob_year": int(getattr(parsed, "birth_year", 0) or 0),
        "height": int(getattr(parsed, "height", 0) or 0),
        "weight": (int(getattr(parsed, "weight", 0) or 0) if getattr(parsed, "weight", None) is not None else None),
        "indexed_unknown_0": getattr(parsed, "indexed_unknown_0", None),
        "indexed_unknown_1": getattr(parsed, "indexed_unknown_1", None),
        "indexed_unknown_9": getattr(parsed, "indexed_unknown_9", None),
        "indexed_unknown_10": getattr(parsed, "indexed_unknown_10", None),
        "indexed_face_components": list(getattr(parsed, "indexed_face_components", []) or []),
        "skills": [int(v) for v in attrs],
        "extended": [int(v) for v in extended],
    }


def _load_player_view(player_file: Path) -> dict[int, dict[str, Any]]:
    entries = _indexed_entry_by_id(player_file)
    player_bytes = player_file.read_bytes()
    out: dict[int, dict[str, Any]] = {}
    for record_id, entry in entries.items():
        decoded = entry.decode_payload(player_bytes)
        parsed = PlayerRecord.from_bytes(decoded, int(entry.payload_offset))
        out[int(record_id)] = {
            "offset": int(entry.payload_offset),
            "name": _player_display_name(parsed),
            "nationality": int(getattr(parsed, "nationality", 0) or 0),
            "dob_day": int(getattr(parsed, "birth_day", 0) or 0),
            "dob_month": int(getattr(parsed, "birth_month", 0) or 0),
            "dob_year": int(getattr(parsed, "birth_year", 0) or 0),
            "height": int(getattr(parsed, "height", 0) or 0),
            "weight": int(getattr(parsed, "weight", 0) or 0),
        }
    return out


def _load_payload_hash_view(player_file: Path) -> dict[int, str]:
    entries = _indexed_entry_by_id(player_file)
    player_bytes = player_file.read_bytes()
    out: dict[int, str] = {}
    for record_id, entry in entries.items():
        decoded = entry.decode_payload(player_bytes)
        out[int(record_id)] = _sha256_bytes(decoded)
    return out


def _selected_field_snapshot(row: dict[str, Any], *, selected_surfaces: set[str]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    if "name" in selected_surfaces:
        snapshot["name"] = row["name"]
    if "nationality" in selected_surfaces:
        snapshot["nationality"] = row["nationality"]
    if "dob" in selected_surfaces:
        snapshot["dob_day"] = row["dob_day"]
        snapshot["dob_month"] = row["dob_month"]
        snapshot["dob_year"] = row["dob_year"]
    if "height" in selected_surfaces:
        snapshot["height"] = row["height"]
    if "weight" in selected_surfaces:
        snapshot["weight"] = row["weight"]
    return snapshot


def _actual_modified_slots_for_fields(
    *,
    manifest_rows: list[dict[str, Any]],
    lhs_view: dict[int, dict[str, Any]],
    rhs_view: dict[int, dict[str, Any]],
    selected_surfaces: set[str],
) -> list[int]:
    slots: list[int] = []
    for row in manifest_rows:
        pid = int(row["pid"])
        lhs_row = lhs_view.get(pid)
        rhs_row = rhs_view.get(pid)
        if lhs_row is None or rhs_row is None:
            raise RuntimeError(f"Missing pid {pid} while computing field-diff slots")
        if _selected_field_snapshot(lhs_row, selected_surfaces=selected_surfaces) != _selected_field_snapshot(
            rhs_row, selected_surfaces=selected_surfaces
        ):
            slots.append(int(row["slot"]))
    return sorted(slots)


def _actual_modified_slots_for_payload(
    *,
    manifest_rows: list[dict[str, Any]],
    lhs_hashes: dict[int, str],
    rhs_hashes: dict[int, str],
) -> list[int]:
    slots: list[int] = []
    for row in manifest_rows:
        pid = int(row["pid"])
        lhs_hash = lhs_hashes.get(pid)
        rhs_hash = rhs_hashes.get(pid)
        if lhs_hash is None or rhs_hash is None:
            raise RuntimeError(f"Missing pid {pid} while computing payload-diff slots")
        if lhs_hash != rhs_hash:
            slots.append(int(row["slot"]))
    return sorted(slots)


def _write_revert_csv(
    csv_path: Path,
    *,
    manifest_rows: list[dict[str, Any]],
    source_view: dict[int, dict[str, Any]],
    baseline_view: dict[int, dict[str, Any]],
    selected_surfaces: set[str],
) -> list[dict[str, Any]]:
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
    rows_out: list[dict[str, Any]] = []
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in manifest_rows:
            pid = int(row["pid"])
            source_meta = source_view.get(pid)
            baseline_meta = baseline_view.get(pid)
            if source_meta is None or baseline_meta is None:
                raise RuntimeError(f"Missing pid {pid} in source/baseline player file")
            payload = {
                "slot": int(row["slot"]),
                "pid": pid,
                "source": source_meta,
                "baseline": baseline_meta,
            }
            rows_out.append(payload)
            writer.writerow(
                {
                    "name": source_meta["name"],
                    "offset": source_meta["offset"],
                    "new_name": baseline_meta["name"] if "name" in selected_surfaces else "",
                    "team_id": "",
                    "squad_number": "",
                    "position": "",
                    "nationality": baseline_meta["nationality"] if "nationality" in selected_surfaces else "",
                    "dob_day": baseline_meta["dob_day"] if "dob" in selected_surfaces else "",
                    "dob_month": baseline_meta["dob_month"] if "dob" in selected_surfaces else "",
                    "dob_year": baseline_meta["dob_year"] if "dob" in selected_surfaces else "",
                    "age": "",
                    "age_year": "",
                    "height": baseline_meta["height"] if "height" in selected_surfaces else "",
                    "weight": baseline_meta["weight"] if "weight" in selected_surfaces else "",
                }
            )
    return rows_out


def _restore_exact_payloads(
    target_player_file: Path,
    *,
    source_player_file: Path,
    baseline_player_file: Path,
    manifest_rows: list[dict[str, Any]],
    report_path: Path,
) -> list[dict[str, Any]]:
    source_bytes = source_player_file.read_bytes()
    baseline_bytes = baseline_player_file.read_bytes()
    target_input_bytes = target_player_file.read_bytes()

    source_entries = _indexed_entry_by_id(source_player_file)
    baseline_entries = _indexed_entry_by_id(baseline_player_file)
    target_entries = _indexed_entry_by_id(target_player_file)

    patched = bytearray(target_input_bytes)
    row_reports: list[dict[str, Any]] = []

    for row in manifest_rows:
        pid = int(row["pid"])
        slot = int(row["slot"])
        source_entry = source_entries.get(pid)
        baseline_entry = baseline_entries.get(pid)
        target_entry = target_entries.get(pid)
        if source_entry is None or baseline_entry is None or target_entry is None:
            raise RuntimeError(f"Missing indexed entry for pid {pid} while restoring exact payloads")

        source_payload = source_entry.decode_payload(source_bytes)
        target_payload_before = target_entry.decode_payload(target_input_bytes)
        baseline_payload = baseline_entry.decode_payload(baseline_bytes)

        if int(source_entry.payload_length) != int(target_entry.payload_length):
            raise RuntimeError(
                f"Source/target payload length mismatch for pid {pid}: "
                f"{source_entry.payload_length} != {target_entry.payload_length}"
            )
        if int(baseline_entry.payload_length) != int(target_entry.payload_length):
            raise RuntimeError(
                f"Baseline/target payload length mismatch for pid {pid}: "
                f"{baseline_entry.payload_length} != {target_entry.payload_length}"
            )

        target_offset = int(target_entry.payload_offset)
        target_length = int(target_entry.payload_length)
        patched[target_offset : target_offset + target_length] = xor_encode(baseline_payload)

        row_reports.append(
            {
                "slot": slot,
                "pid": pid,
                "target_offset": target_offset,
                "payload_length": target_length,
                "source_target_input_match": bool(source_payload == target_payload_before),
                "baseline_equals_target_before": bool(baseline_payload == target_payload_before),
                "sha256": {
                    "source_decoded": _sha256_bytes(source_payload),
                    "target_before_decoded": _sha256_bytes(target_payload_before),
                    "baseline_decoded": _sha256_bytes(baseline_payload),
                },
                "source": _parse_payload_summary(source_payload, int(source_entry.payload_offset)),
                "target_before": _parse_payload_summary(target_payload_before, target_offset),
                "baseline": _parse_payload_summary(baseline_payload, int(baseline_entry.payload_offset)),
            }
        )

    target_player_file.write_bytes(bytes(patched))

    target_output_bytes = target_player_file.read_bytes()
    target_output_entries = _indexed_entry_by_id(target_player_file)
    for payload_row in row_reports:
        pid = int(payload_row["pid"])
        target_entry = target_output_entries.get(pid)
        if target_entry is None:
            raise RuntimeError(f"Missing pid {pid} after payload restore write")
        target_payload_after = target_entry.decode_payload(target_output_bytes)
        payload_row["sha256"]["target_after_decoded"] = _sha256_bytes(target_payload_after)
        payload_row["target_after"] = _parse_payload_summary(target_payload_after, int(target_entry.payload_offset))
        payload_row["post_write_matches_baseline"] = bool(
            payload_row["sha256"]["target_after_decoded"] == payload_row["sha256"]["baseline_decoded"]
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({"rows": row_reports}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return row_reports


def _run_editor_cli(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=str(REPO_ROOT), capture_output=True, text=True, check=False)
    return {
        "command": command,
        "returncode": int(completed.returncode),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def main() -> int:
    args = _parse_args()
    source_game_root = resolve_game_root(args.source_game_root, require_writable=False)
    baseline_game_root = (
        resolve_game_root(args.baseline_game_root, require_writable=False)
        if str(args.baseline_game_root).strip()
        else resolve_fixture_root()
    )
    manifest_path = Path(args.manifest).expanduser().resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_rows = list(manifest.get("batch_rows") or [])
    if not manifest_rows:
        raise RuntimeError(f"Manifest has no batch_rows: {manifest_path}")

    selected_surfaces = set(_parse_surfaces(args.surfaces))
    known_slots = {int(row["slot"]) for row in manifest_rows}
    selected_slots = _parse_slots(args.slots, known_slots=known_slots)
    selected_rows = [row for row in manifest_rows if int(row["slot"]) in selected_slots]
    if not selected_rows:
        raise RuntimeError("Selection resolved to zero manifest rows")
    reverted_slots = sorted(selected_slots)
    source_manifest_slots = sorted(known_slots)

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    variant_id = args.variant_id.strip() or f"stoke_2015_jug_bisect_{args.slots}_{timestamp}"
    variant_root = Path(args.output_root).expanduser().resolve() / variant_id
    game_root = variant_root / "game"
    patch_dir = variant_root / "patches" / "jug_bisect"
    patch_dir.mkdir(parents=True, exist_ok=True)

    _copy_game_tree(source_game_root, game_root)

    source_player_file = source_game_root / "DBDAT" / "JUG98030.FDI"
    baseline_player_file = baseline_game_root / "DBDAT" / "JUG98030.FDI"
    target_player_file = game_root / "DBDAT" / "JUG98030.FDI"

    source_view = _load_player_view(source_player_file)
    baseline_view = _load_player_view(baseline_player_file)
    source_payload_hashes: dict[int, str] | None = None
    baseline_payload_hashes: dict[int, str] | None = None
    if "payload" in selected_surfaces:
        source_payload_hashes = _load_payload_hash_view(source_player_file)
        baseline_payload_hashes = _load_payload_hash_view(baseline_player_file)

    if "payload" in selected_surfaces:
        if source_payload_hashes is None or baseline_payload_hashes is None:
            raise RuntimeError("Internal error: payload hashes were not loaded")
        source_actual_modified_slots = _actual_modified_slots_for_payload(
            manifest_rows=manifest_rows,
            lhs_hashes=source_payload_hashes,
            rhs_hashes=baseline_payload_hashes,
        )
    else:
        source_actual_modified_slots = _actual_modified_slots_for_fields(
            manifest_rows=manifest_rows,
            lhs_view=source_view,
            rhs_view=baseline_view,
            selected_surfaces=selected_surfaces,
        )
    csv_path: Path | None = None
    payload_restore_result_path: Path | None = None
    if "payload" in selected_surfaces:
        payload_restore_result_path = patch_dir / "payload_restore_result.json"
        revert_rows = _restore_exact_payloads(
            target_player_file,
            source_player_file=source_player_file,
            baseline_player_file=baseline_player_file,
            manifest_rows=selected_rows,
            report_path=payload_restore_result_path,
        )
        apply_result = {
            "mode": "payload_restore",
            "row_count": len(revert_rows),
            "all_rows_match_baseline_post_write": all(bool(row.get("post_write_matches_baseline")) for row in revert_rows),
            "report_path": str(payload_restore_result_path),
        }
    else:
        csv_path = patch_dir / "revert_subset.csv"
        revert_rows = _write_revert_csv(
            csv_path,
            manifest_rows=selected_rows,
            source_view=source_view,
            baseline_view=baseline_view,
            selected_surfaces=selected_surfaces,
        )

        apply_result = _run_editor_cli(
            [
                "./scripts/dev_editor.sh",
                "python3",
                "-m",
                "app.cli",
                "player-batch-edit",
                str(target_player_file),
                "--csv",
                str(csv_path),
                "--json",
            ]
        )
        (patch_dir / "player_batch_edit_result.json").write_text(json.dumps(apply_result, indent=2) + "\n", encoding="utf-8")
        if int(apply_result["returncode"]) != 0:
            raise RuntimeError(f"player-batch-edit failed for variant {variant_id}")

    if bool(args.skip_validation):
        validate_result = {
            "command": [],
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "skipped": True,
        }
        (patch_dir / "validate_database.json").write_text(
            json.dumps(validate_result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    else:
        validate_result = _run_editor_cli(
            [
                "./scripts/dev_editor.sh",
                "python3",
                "-m",
                "app.cli",
                "validate-database",
                "--players",
                str(game_root / "DBDAT" / "JUG98030.FDI"),
                "--teams",
                str(game_root / "DBDAT" / "EQ98030.FDI"),
                "--coaches",
                str(game_root / "DBDAT" / "ENT98030.FDI"),
                "--json",
            ]
        )
        (patch_dir / "validate_database.json").write_text(
            validate_result["stdout"] if validate_result["stdout"] else json.dumps(validate_result, indent=2) + "\n",
            encoding="utf-8",
        )
        if int(validate_result["returncode"]) != 0:
            raise RuntimeError(f"validate-database failed for variant {variant_id}")
    if "payload" in selected_surfaces:
        target_payload_hashes = _load_payload_hash_view(target_player_file)
        if baseline_payload_hashes is None:
            raise RuntimeError("Internal error: baseline payload hashes were not loaded")
        variant_actual_modified_slots = _actual_modified_slots_for_payload(
            manifest_rows=manifest_rows,
            lhs_hashes=target_payload_hashes,
            rhs_hashes=baseline_payload_hashes,
        )
    else:
        target_view = _load_player_view(target_player_file)
        variant_actual_modified_slots = _actual_modified_slots_for_fields(
            manifest_rows=manifest_rows,
            lhs_view=target_view,
            rhs_view=baseline_view,
            selected_surfaces=selected_surfaces,
        )
    manifest_out = {
        "scope": "stoke_2015_jug_bisect_variant",
        "timestamp_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "variant_root": str(variant_root),
        "game_root": str(game_root),
        "source_game_root": str(source_game_root),
        "baseline_game_root": str(baseline_game_root),
        "manifest_path": str(manifest_path),
        "slots": reverted_slots,
        "reverted_slots": reverted_slots,
        "source_manifest_slots": source_manifest_slots,
        "source_modified_slots": source_actual_modified_slots,
        "variant_modified_slots": variant_actual_modified_slots,
        "surfaces": sorted(selected_surfaces),
        "rows": revert_rows,
        "csv_path": str(csv_path) if csv_path else None,
        "player_batch_edit_result": (str(patch_dir / "player_batch_edit_result.json") if csv_path else None),
        "payload_restore_result": str(payload_restore_result_path) if payload_restore_result_path else None,
        "validate_database_path": str(patch_dir / "validate_database.json"),
        "core_files": core_file_hashes(game_root),
        "hashes": {
            "source_jug": sha256(source_player_file),
            "baseline_jug": sha256(baseline_player_file),
            "variant_jug": sha256(target_player_file),
            "variant_eq": sha256(game_root / "DBDAT" / "EQ98030.FDI"),
            "variant_minifoto": sha256(game_root / "DBDAT" / "MINIFOTO.PKF"),
        },
    }
    manifest_out_path = patch_dir / "variant_manifest.json"
    manifest_out_path.write_text(json.dumps(manifest_out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "success": True,
                "variant_root": str(variant_root),
                "game_root": str(game_root),
                "manifest_path": str(manifest_out_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
