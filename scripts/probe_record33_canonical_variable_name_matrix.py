#!/usr/bin/env python3
"""Build canonical single-record variable-name probes for JUG record 33.

The earlier record-33 semantic probe moved the metadata cursor but preserved an
incoherent role/position shape. This script reuses the compact role-block shape
from the runner-proven Stoke physical-variable patch and emits a small matrix of
isolated game roots for runtime validation.
"""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
EDITOR_ROOT = REPO_ROOT / "upstream" / "pm99-skezmod-db-editor"
SCRIPT_DIR = Path(__file__).resolve().parent
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from app.editor_actions import _IndexedRawStageRecord, write_player_staged_records  # noqa: E402
from app.editor_helpers import _player_display_name  # noqa: E402
from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from app.models import PlayerRecord  # noqa: E402
from assert_pm99_isolated_input import sha256  # noqa: E402
from apply_stoke_2015_role_preserved_compact_variable_patch import (  # noqa: E402
    _compact_segments,
    _name_prefix,
    _norm,
    _role_byte,
)
from apply_stoke_2015_semantic_runtime_patch import (  # noqa: E402
    SKILL_LABELS,
    _read_clone_fields,
    _write_decoded_byte,
)


TARGET_RECORD_ID = 33
TARGET_NAME = "Guillermo Amor"


@dataclass(frozen=True)
class Variant:
    slug: str
    role_source: str
    position_source: str
    target_payload_length: int | None = None


VARIANTS = [
    Variant("ui17_pos_visible2_len73", "ui_primary_role_code", "visible_position_code", None),
    Variant("legacy14_pos_visible2_len73", "legacy_role_window_codes[0]", "visible_position_code", None),
    Variant("central9_pos_visible2_len73", "literal:9", "visible_position_code", None),
    Variant("ui17_pos_parser3_len73", "ui_primary_role_code", "parser_position_code", None),
    Variant("ui17_pos_visible2_len80", "ui_primary_role_code", "visible_position_code", 80),
]


def _parse_args() -> argparse.Namespace:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-game",
        default=str(REPO_ROOT / ".local" / "premier-manager-ninety-nine"),
        help="Isolated PM99 game root to copy before patching.",
    )
    parser.add_argument(
        "--out-root",
        default=str(REPO_ROOT / ".local" / f"record33_canonical_variable_matrix_{stamp}"),
        help="Directory that will receive one isolated game root per variant.",
    )
    parser.add_argument("--force", action="store_true", help="Replace --out-root if it already exists.")
    return parser.parse_args()


def _decoded_byte(decoded: bytes, offset: int) -> int:
    return decoded[offset] ^ 0x61


def _resolve_role(fields: dict[str, Any], role_source: str) -> int:
    if role_source == "ui_primary_role_code":
        return int(fields["ui_primary_role_code"])
    if role_source == "legacy_role_window_codes[0]":
        return int(fields["legacy_role_window_codes"][0])
    if role_source.startswith("literal:"):
        return int(role_source.split(":", 1)[1])
    raise ValueError(f"Unsupported role source: {role_source}")


def _resolve_position(fields: dict[str, Any], position_source: str) -> int:
    return int(fields[position_source])


def _patch_payload(decoded: bytes, variant: Variant) -> tuple[bytes, dict[str, Any]]:
    if decoded[2:5] != b"\xdd\x63\x60":
        raise RuntimeError(f"Record 33 is not dd6360 compact-shaped: {decoded[2:5].hex()}")

    parsed_before = PlayerRecord.from_bytes(decoded, 0)
    old_name = " ".join(_player_display_name(parsed_before).split())
    segments = _compact_segments(decoded)
    old_name_end = int(segments["name_end"])
    old_role_start = old_name_end - 3
    old_tail_start = old_role_start + 8
    if old_tail_start > len(decoded):
        raise RuntimeError(f"Old compact role block overruns payload: tail_start={old_tail_start}, len={len(decoded)}")

    old_fields = _read_clone_fields(decoded, old_name_end)
    primary_role = _resolve_role(old_fields, variant.role_source)
    position_code = _resolve_position(old_fields, variant.position_source)
    primary_role_byte = _role_byte(primary_role)

    prefix = _name_prefix(TARGET_NAME)
    first_len_offset = int(segments["first_len_offset"])
    new_role_start = first_len_offset + len(prefix)
    new_name_end = new_role_start + 3
    removed_padding = old_role_start - new_role_start
    if removed_padding < 0:
        raise RuntimeError(
            f"Target name exceeds old compact fixed window: old_role_start={old_role_start}, "
            f"new_role_start={new_role_start}"
        )

    role_block = bytearray(
        [
            primary_role_byte,
            0x61,
            primary_role_byte,
            0x61,
            0x61,
            0x61,
            0x61,
            0x61,
        ]
    )
    patched = bytearray()
    patched.extend(decoded[:first_len_offset])
    patched.extend(prefix)
    patched.extend(role_block)
    patched.extend(decoded[old_tail_start:])

    target_len = int(variant.target_payload_length or len(decoded))
    if len(patched) > target_len:
        raise RuntimeError(f"Variant {variant.slug} cannot fit in target length {target_len}")
    patched.extend(b"\x61" * (target_len - len(patched)))

    # Re-emit the runtime-visible semantic lanes at the moved cursor. The matrix
    # intentionally tests position normalization while preserving all other old
    # record-33 semantic values.
    _write_decoded_byte(patched, new_name_end + 5, int(old_fields["visible_nationality_code"]))
    _write_decoded_byte(patched, new_name_end + 6, int(old_fields["unknown_6"]))
    _write_decoded_byte(patched, new_name_end + 7, position_code)
    _write_decoded_byte(patched, new_name_end + 8, position_code)
    _write_decoded_byte(patched, new_name_end + 9, int(old_fields["birth_day"]))
    _write_decoded_byte(patched, new_name_end + 10, int(old_fields["birth_month"]))
    year_bytes = struct.pack("<H", int(old_fields["birth_year"]))
    _write_decoded_byte(patched, new_name_end + 11, year_bytes[0])
    _write_decoded_byte(patched, new_name_end + 12, year_bytes[1])
    _write_decoded_byte(patched, new_name_end + 13, int(old_fields["height_cm"]))
    _write_decoded_byte(patched, new_name_end + 14, int(old_fields["weight_kg"]))
    for index, label in enumerate(SKILL_LABELS):
        _write_decoded_byte(patched, new_name_end + 15 + index, int(old_fields["skills"][label]))

    parsed_after = PlayerRecord.from_bytes(bytes(patched), 0)
    applied_name = " ".join(_player_display_name(parsed_after).split())
    parser_name_end = PlayerRecord._find_name_end(bytes(patched))
    if parser_name_end != new_name_end:
        raise RuntimeError(f"Parser name_end mismatch: expected {new_name_end}, got {parser_name_end}")
    if _norm(applied_name) != _norm(TARGET_NAME):
        raise RuntimeError(f"Patched payload reparsed as {applied_name!r}, expected {TARGET_NAME!r}")

    new_fields = _read_clone_fields(bytes(patched), new_name_end)
    role_block_decoded = [_decoded_byte(bytes(patched), new_role_start + index) for index in range(8)]
    return bytes(patched), {
        "variant": variant.slug,
        "role_source": variant.role_source,
        "position_source": variant.position_source,
        "target_payload_length": target_len,
        "old_name": old_name,
        "applied_name": applied_name,
        "old_payload_length": len(decoded),
        "new_payload_length": len(patched),
        "first_len_offset": first_len_offset,
        "old_name_end": old_name_end,
        "new_name_end": new_name_end,
        "old_role_start": old_role_start,
        "new_role_start": new_role_start,
        "old_tail_start": old_tail_start,
        "removed_fixed_padding_bytes": removed_padding,
        "tail_padding_bytes": target_len - (first_len_offset + len(prefix) + len(role_block) + len(decoded[old_tail_start:])),
        "primary_role_code": primary_role,
        "position_code": position_code,
        "role_block_decoded": role_block_decoded,
        "old_fields": old_fields,
        "new_fields": new_fields,
        "head_hex": bytes(patched[: min(96, len(patched))]).hex(),
    }


def _build_variant(base_game: Path, out_game: Path, variant: Variant) -> dict[str, Any]:
    shutil.copytree(base_game, out_game, symlinks=True)
    player_file = out_game / "DBDAT" / "JUG98030.FDI"
    file_data = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(file_data)
    entries_by_id = {int(entry.record_id): entry for entry in indexed.entries}
    entry = entries_by_id.get(TARGET_RECORD_ID)
    if entry is None:
        raise RuntimeError(f"Record ID {TARGET_RECORD_ID} not found in {player_file}")

    decoded = entry.decode_payload(file_data)
    patched, meta = _patch_payload(decoded, variant)
    backup_path = write_player_staged_records(
        str(player_file),
        [
            (
                int(entry.payload_offset),
                _IndexedRawStageRecord(
                    raw_payload=patched,
                    container_offset=int(entry.payload_offset),
                    container_length=int(entry.payload_length),
                ),
            )
        ],
        create_backup_before_write=False,
    )

    reparsed_indexed = IndexedFDIFile.from_bytes(player_file.read_bytes())
    reparsed_entry = next(item for item in reparsed_indexed.entries if int(item.record_id) == TARGET_RECORD_ID)
    reparsed_payload = reparsed_entry.decode_payload(player_file.read_bytes())
    reparsed = PlayerRecord.from_bytes(reparsed_payload, 0)
    readback_name = " ".join(_player_display_name(reparsed).split())
    summary = {
        **meta,
        "record_id": TARGET_RECORD_ID,
        "payload_offset_before": int(entry.payload_offset),
        "payload_length_before": int(entry.payload_length),
        "payload_offset_after": int(reparsed_entry.payload_offset),
        "payload_length_after": int(reparsed_entry.payload_length),
        "readback_name": readback_name,
        "backup_path": str(backup_path) if backup_path else None,
        "out_game": str(out_game),
        "sha256": sha256(player_file),
    }
    artifact_dir = out_game / "artifacts" / "record33_canonical_variable"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    args = _parse_args()
    base_game = Path(args.base_game).expanduser().resolve()
    out_root = Path(args.out_root).expanduser().resolve()
    if out_root.exists():
        if not args.force:
            raise SystemExit(f"Output root exists: {out_root}")
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True)

    summaries: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for variant in VARIANTS:
        out_game = out_root / variant.slug
        try:
            summaries.append(_build_variant(base_game, out_game, variant))
        except Exception as exc:
            failures.append({"variant": variant.slug, "error": str(exc)})

    manifest = {
        "schema": "pm99-record33-canonical-variable-name-matrix-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "base_game": str(base_game),
        "out_root": str(out_root),
        "target_record_id": TARGET_RECORD_ID,
        "target_name": TARGET_NAME,
        "variant_count": len(VARIANTS),
        "built_count": len(summaries),
        "failure_count": len(failures),
        "failures": failures,
        "summaries": summaries,
    }
    manifest_path = out_root / "matrix_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"ok": not failures, "manifest": str(manifest_path), "built_count": len(summaries)}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
