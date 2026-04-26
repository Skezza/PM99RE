#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import shutil
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
from app.models import PlayerRecord  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create debug variants from the isolated Stoke 2015 no-injection game root.",
    )
    parser.add_argument("--source-game-root", required=True, help="Existing isolated PM99 game root")
    parser.add_argument(
        "--mode",
        required=True,
        choices=("nofaces", "roster_only", "pristine_eq", "pristine_jug"),
        help=(
            "Variant mode: restore pristine MINIFOTO only, restore MINIFOTO and reverse metadata on JUG, "
            "or restore pristine EQ/JUG from the fixture for file-level runtime bisects"
        ),
    )
    parser.add_argument(
        "--metadata-manifest",
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
        help="Path to the Stoke 2015 metadata manifest with batch_rows",
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


def _indexed_entry_by_id(player_file: Path) -> dict[int, Any]:
    indexed = IndexedFDIFile.from_path(player_file)
    return {int(entry.record_id): entry for entry in indexed.entries}


def _player_metadata_from_entry(*, player_bytes: bytes, entry: Any) -> dict[str, int]:
    decoded = entry.decode_payload(player_bytes)
    parsed = PlayerRecord.from_bytes(decoded, int(entry.payload_offset))
    return {
        "nationality": int(getattr(parsed, "nationality", 0) or 0),
        "dob_day": int(getattr(parsed, "birth_day", 0) or 0),
        "dob_month": int(getattr(parsed, "birth_month", 0) or 0),
        "dob_year": int(getattr(parsed, "birth_year", 0) or 0),
        "height": int(getattr(parsed, "height", 0) or 0),
        "weight": int(getattr(parsed, "weight", 0) or 0),
    }


def _write_reverse_metadata_csv(
    *,
    csv_path: Path,
    metadata_manifest: dict[str, Any],
    pristine_player_file: Path,
    target_player_file: Path,
) -> list[dict[str, Any]]:
    batch_rows = list(metadata_manifest.get("batch_rows") or [])
    if not batch_rows:
        raise RuntimeError("Metadata manifest is missing batch_rows")

    pristine_entries = _indexed_entry_by_id(pristine_player_file)
    target_entries = _indexed_entry_by_id(target_player_file)
    pristine_bytes = pristine_player_file.read_bytes()

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

    reverse_rows: list[dict[str, Any]] = []
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in batch_rows:
            record_id = int(row["pid"])
            pristine_entry = pristine_entries.get(record_id)
            target_entry = target_entries.get(record_id)
            if pristine_entry is None or target_entry is None:
                raise RuntimeError(f"Missing record id {record_id} while reversing metadata")
            pristine_meta = _player_metadata_from_entry(player_bytes=pristine_bytes, entry=pristine_entry)
            payload = {
                "slot": int(row["slot"]),
                "pid": record_id,
                "name": str(row["name"]),
                "offset": int(target_entry.payload_offset),
                **pristine_meta,
            }
            reverse_rows.append(payload)
            writer.writerow(
                {
                    "name": payload["name"],
                    "offset": payload["offset"],
                    "new_name": "",
                    "team_id": "",
                    "squad_number": "",
                    "position": "",
                    "nationality": payload["nationality"],
                    "dob_day": payload["dob_day"],
                    "dob_month": payload["dob_month"],
                    "dob_year": payload["dob_year"],
                    "age": "",
                    "age_year": "",
                    "height": payload["height"],
                    "weight": payload["weight"],
                }
            )
    return reverse_rows


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
    fixture_root = resolve_fixture_root()
    metadata_manifest_path = Path(args.metadata_manifest).expanduser().resolve()
    metadata_manifest = json.loads(metadata_manifest_path.read_text(encoding="utf-8"))

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    variant_id = args.variant_id.strip() or f"stoke_2015_{args.mode}_{timestamp}"
    variant_root = Path(args.output_root).expanduser().resolve() / variant_id
    game_root = variant_root / "game"
    patch_dir = variant_root / "patches" / args.mode
    patch_dir.mkdir(parents=True, exist_ok=True)

    _copy_game_tree(source_game_root, game_root)

    pristine_dbdat = fixture_root / "DBDAT"
    pristine_minifoto = pristine_dbdat / "MINIFOTO.PKF"
    target_minifoto = game_root / "DBDAT" / "MINIFOTO.PKF"

    if args.mode in {"nofaces", "roster_only"}:
        shutil.copy2(pristine_minifoto, target_minifoto)
    if args.mode == "pristine_eq":
        shutil.copy2(pristine_dbdat / "EQ98030.FDI", game_root / "DBDAT" / "EQ98030.FDI")
    if args.mode == "pristine_jug":
        shutil.copy2(pristine_dbdat / "JUG98030.FDI", game_root / "DBDAT" / "JUG98030.FDI")

    reverse_rows: list[dict[str, Any]] = []
    reverse_csv_path = patch_dir / "reverse_metadata.csv"
    reverse_result: dict[str, Any] | None = None
    if args.mode == "roster_only":
        reverse_rows = _write_reverse_metadata_csv(
            csv_path=reverse_csv_path,
            metadata_manifest=metadata_manifest,
            pristine_player_file=fixture_root / "DBDAT" / "JUG98030.FDI",
            target_player_file=game_root / "DBDAT" / "JUG98030.FDI",
        )
        reverse_result = _run_editor_cli(
            [
                "./scripts/dev_editor.sh",
                "python3",
                "-m",
                "app.cli",
                "player-batch-edit",
                str(game_root / "DBDAT" / "JUG98030.FDI"),
                "--csv",
                str(reverse_csv_path),
                "--json",
            ]
        )
        if int(reverse_result["returncode"]) != 0:
            (patch_dir / "reverse_metadata_apply_result.json").write_text(
                json.dumps(reverse_result, indent=2) + "\n",
                encoding="utf-8",
            )
            raise RuntimeError(
                f"Reverse metadata batch edit failed (exit {reverse_result['returncode']}): {reverse_csv_path}"
            )
        (patch_dir / "reverse_metadata_apply_result.json").write_text(
            json.dumps(reverse_result, indent=2) + "\n",
            encoding="utf-8",
        )

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
        "scope": "stoke_2015_debug_variant",
        "timestamp_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": args.mode,
        "source_game_root": str(source_game_root),
        "variant_root": str(variant_root),
        "game_root": str(game_root),
        "metadata_manifest_path": str(metadata_manifest_path),
        "pristine_fixture_root": str(fixture_root),
        "reverse_metadata_csv": str(reverse_csv_path) if args.mode == "roster_only" else "",
        "reverse_metadata_rows": reverse_rows,
        "reverse_metadata_apply_result": str(patch_dir / "reverse_metadata_apply_result.json")
        if args.mode == "roster_only"
        else "",
        "validate_database_path": str(patch_dir / "validate_database.json"),
        "core_files": core_file_hashes(game_root),
        "hashes": {
            "source_minifoto": sha256(source_game_root / "DBDAT" / "MINIFOTO.PKF"),
            "variant_minifoto": sha256(target_minifoto),
            "source_eq": sha256(source_game_root / "DBDAT" / "EQ98030.FDI"),
            "variant_eq": sha256(game_root / "DBDAT" / "EQ98030.FDI"),
            "source_jug": sha256(source_game_root / "DBDAT" / "JUG98030.FDI"),
            "variant_jug": sha256(game_root / "DBDAT" / "JUG98030.FDI"),
        },
    }
    manifest_path = patch_dir / "variant_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "success": True,
                "mode": args.mode,
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
