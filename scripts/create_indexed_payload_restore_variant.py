#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from app.xor import xor_encode  # noqa: E402


def _sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clone an isolated PM99 root and restore exact indexed payloads by record id from a baseline root.",
    )
    parser.add_argument("--source-game-root", required=True, help="Existing isolated PM99 game root")
    parser.add_argument(
        "--baseline-game-root",
        default="",
        help="Optional isolated PM99 baseline root. Defaults to the pristine fixture.",
    )
    parser.add_argument(
        "--relative-file",
        required=True,
        help="Relative indexed file path inside the game root, e.g. DBDAT/EQ98030.FDI",
    )
    parser.add_argument(
        "--record-ids",
        required=True,
        help="Comma-separated indexed record ids to restore exactly from the baseline root",
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
    return parser.parse_args()


def _parse_record_ids(text: str) -> list[int]:
    record_ids: list[int] = []
    seen: set[int] = set()
    for token in [item.strip() for item in text.split(",") if item.strip()]:
        record_id = int(token)
        if record_id <= 0:
            raise ValueError(f"Indexed record ids must be positive integers: {token}")
        if record_id not in seen:
            seen.add(record_id)
            record_ids.append(record_id)
    if not record_ids:
        raise ValueError("record-ids resolved to an empty set")
    return record_ids


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


def _indexed_entry_by_id(file_path: Path) -> dict[int, Any]:
    indexed = IndexedFDIFile.from_path(file_path)
    return {int(entry.record_id): entry for entry in indexed.entries}


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
    relative_file = Path(str(args.relative_file).strip())
    if relative_file.is_absolute():
        raise ValueError("relative-file must be relative to the game root")
    record_ids = _parse_record_ids(args.record_ids)

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    variant_id = args.variant_id.strip() or f"indexed_payload_restore_{relative_file.stem.lower()}_{timestamp}"
    variant_root = Path(args.output_root).expanduser().resolve() / variant_id
    game_root = variant_root / "game"
    patch_dir = variant_root / "patches" / "indexed_payload_restore"
    patch_dir.mkdir(parents=True, exist_ok=True)

    _copy_game_tree(source_game_root, game_root)

    source_file = source_game_root / relative_file
    baseline_file = baseline_game_root / relative_file
    target_file = game_root / relative_file

    source_bytes = source_file.read_bytes()
    baseline_bytes = baseline_file.read_bytes()
    target_input_bytes = target_file.read_bytes()

    source_entries = _indexed_entry_by_id(source_file)
    baseline_entries = _indexed_entry_by_id(baseline_file)
    target_entries = _indexed_entry_by_id(target_file)

    patched = bytearray(target_input_bytes)
    rows: list[dict[str, Any]] = []
    for record_id in record_ids:
        source_entry = source_entries.get(record_id)
        baseline_entry = baseline_entries.get(record_id)
        target_entry = target_entries.get(record_id)
        if source_entry is None or baseline_entry is None or target_entry is None:
            raise RuntimeError(f"Missing indexed entry for record id {record_id}")

        source_payload = source_entry.decode_payload(source_bytes)
        baseline_payload = baseline_entry.decode_payload(baseline_bytes)
        target_payload_before = target_entry.decode_payload(target_input_bytes)

        if int(source_entry.payload_length) != int(target_entry.payload_length):
            raise RuntimeError(
                f"Source/target payload length mismatch for record id {record_id}: "
                f"{source_entry.payload_length} != {target_entry.payload_length}"
            )
        if int(baseline_entry.payload_length) != int(target_entry.payload_length):
            raise RuntimeError(
                f"Baseline/target payload length mismatch for record id {record_id}: "
                f"{baseline_entry.payload_length} != {target_entry.payload_length}"
            )

        target_offset = int(target_entry.payload_offset)
        target_length = int(target_entry.payload_length)
        patched[target_offset : target_offset + target_length] = xor_encode(baseline_payload)

        rows.append(
            {
                "record_id": record_id,
                "target_offset": target_offset,
                "payload_length": target_length,
                "source_target_input_match": bool(source_payload == target_payload_before),
                "baseline_equals_target_before": bool(baseline_payload == target_payload_before),
                "sha256": {
                    "source_decoded": _sha256_bytes(source_payload),
                    "target_before_decoded": _sha256_bytes(target_payload_before),
                    "baseline_decoded": _sha256_bytes(baseline_payload),
                },
            }
        )

    target_file.write_bytes(bytes(patched))

    target_output_bytes = target_file.read_bytes()
    target_output_entries = _indexed_entry_by_id(target_file)
    for row in rows:
        record_id = int(row["record_id"])
        target_entry = target_output_entries.get(record_id)
        if target_entry is None:
            raise RuntimeError(f"Missing indexed entry for record id {record_id} after write")
        target_payload_after = target_entry.decode_payload(target_output_bytes)
        row["sha256"]["target_after_decoded"] = _sha256_bytes(target_payload_after)
        row["post_write_matches_baseline"] = bool(
            row["sha256"]["target_after_decoded"] == row["sha256"]["baseline_decoded"]
        )

    report_path = patch_dir / "payload_restore_result.json"
    report_path.write_text(json.dumps({"rows": rows}, indent=2, sort_keys=True) + "\n", encoding="utf-8")

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

    manifest = {
        "scope": "indexed_payload_restore_variant",
        "timestamp_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "variant_root": str(variant_root),
        "game_root": str(game_root),
        "source_game_root": str(source_game_root),
        "baseline_game_root": str(baseline_game_root),
        "relative_file": str(relative_file),
        "record_ids": record_ids,
        "payload_restore_result": str(report_path),
        "validate_database_path": str(patch_dir / "validate_database.json"),
        "core_files": core_file_hashes(game_root),
        "hashes": {
            "source_file": sha256(source_file),
            "baseline_file": sha256(baseline_file),
            "variant_file": sha256(target_file),
        },
    }
    manifest_path = patch_dir / "variant_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "success": True,
                "variant_root": str(variant_root),
                "game_root": str(game_root),
                "manifest_path": str(manifest_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
