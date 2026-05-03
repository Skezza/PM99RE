#!/usr/bin/env python3
"""Build a Stoke 2015 candidate with physically variable compact name blocks.

The earlier compact "variable" probes changed the embedded name-length bytes but
left the old fixed-width padding before the role/metadata bytes. MANAGPRE then
followed the shortened name lengths and parsed that padding as metadata.

This candidate keeps the runner-proven compact dd6360 payload family, but moves
the role/metadata block immediately after each natural name prefix. The removed
fixed-width padding is appended at the end of the payload, preserving the
80-byte linked-player runtime-safety length while making the name block itself
truly variable length.
"""

from __future__ import annotations

import argparse
import json
import shutil
import struct
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

from app.editor_actions import _IndexedRawStageRecord, write_player_staged_records  # noqa: E402
from app.editor_helpers import _player_display_name  # noqa: E402
from app.eq_jug_linked import load_eq_linked_team_rosters  # noqa: E402
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
    _source_rows,
    _write_decoded_byte,
)
from apply_stoke_2015_variable_names_runtime_patch import (  # noqa: E402
    _extract_nationality_codes,
)


def _parse_args() -> argparse.Namespace:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-game",
        default=str(REPO_ROOT / ".local" / "stoke_2015_stats_backfill_20260501T065744Z"),
        help="Runner-proven fixed-name compact Stoke 2015 game root.",
    )
    parser.add_argument(
        "--out-game",
        default=str(REPO_ROOT / ".local" / f"stoke_2015_physical_variable_names_{stamp}"),
        help="Output game root to create.",
    )
    parser.add_argument("--team-query", default="Stoke")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _resolve_roster(team_file: Path, player_file: Path, team_query: str) -> list[dict[str, object]]:
    needle = team_query.casefold()
    for roster in load_eq_linked_team_rosters(team_file=str(team_file), player_file=str(player_file)):
        names = [
            str(getattr(roster, "short_name", "") or "").casefold(),
            str(getattr(roster, "full_club_name", "") or "").casefold(),
        ]
        if not any(needle in item for item in names):
            continue
        rows = sorted(list(getattr(roster, "rows", []) or []), key=lambda row: int(getattr(row, "slot_index", 0)))
        return [
            {
                "slot": int(getattr(row, "slot_index", 0)) + 1,
                "pid": int(getattr(row, "player_record_id", 0) or 0),
                "player_name": str(getattr(row, "player_name", "") or ""),
            }
            for row in rows[:20]
        ]
    raise RuntimeError(f"Could not resolve roster for {team_query!r}")


def _decoded_byte(decoded: bytes, offset: int) -> int:
    return decoded[offset] ^ 0x61


def _expected_clone_fields(source_row: dict[str, Any]) -> dict[str, Any]:
    year_bytes = struct.pack("<H", int(source_row["birth_year"]))
    return {
        "visible_nationality_code": int(source_row["pm99_nat_code"]),
        "parser_position_code": int(source_row["pm99_position_code"]),
        "visible_position_code": int(source_row["pm99_position_code"]),
        "birth_day": int(source_row["birth_day"]),
        "birth_month": int(source_row["birth_month"]),
        "birth_year": year_bytes[0] | (year_bytes[1] << 8),
        "height_cm": int(source_row["height_cm"]),
        "weight_kg": int(source_row["weight_kg"]),
        "skills": dict(source_row["skills"]),
    }


def _assert_expected_fields(actual: dict[str, Any], expected: dict[str, Any], player_name: str) -> None:
    comparable = {key: actual[key] for key in expected}
    if comparable != expected:
        raise RuntimeError(
            f"Moved metadata readback mismatch for {player_name!r}: "
            f"expected {expected!r}, got {comparable!r}"
        )


def _patch_physical_variable_payload(decoded: bytes, source_row: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    if decoded[2:5] != b"\xdd\x63\x60":
        raise RuntimeError(f"Expected dd6360 compact payload for {source_row['game_name']!r}, got {decoded[2:5].hex()}")

    parsed_before = PlayerRecord.from_bytes(decoded, 0)
    old_display_name = " ".join(_player_display_name(parsed_before).split())
    segments = _compact_segments(decoded)
    old_name_end = int(segments["name_end"])
    old_role_start = old_name_end - 3
    old_tail_start = old_role_start + 8
    old_payload_length = len(decoded)

    if old_tail_start > old_payload_length:
        raise RuntimeError(f"Compact role/metadata block overruns payload for {old_display_name!r}")

    target_name = str(source_row["game_name"])
    prefix = _name_prefix(target_name)
    first_len_offset = int(segments["first_len_offset"])
    new_role_start = first_len_offset + len(prefix)
    new_name_end = new_role_start + 3
    removed_padding = old_role_start - new_role_start
    if removed_padding < 0:
        raise RuntimeError(
            f"Natural variable prefix for {target_name!r} exceeds compact name window: "
            f"new_role_start={new_role_start}, old_role_start={old_role_start}"
        )

    primary_role = int(list(source_row["fine_role_codes"])[0])
    primary_role_byte = _role_byte(primary_role)
    # Use the compact clone shape that the editor can audit after moving the
    # cursor: UI primary role, spacer, legacy primary role, then zero secondary
    # role slots. This preserves the starting-position lane while avoiding old
    # secondary-role bytes occupying the moved marker window.
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
    tail = decoded[old_tail_start:]

    patched = bytearray()
    patched.extend(decoded[:first_len_offset])
    patched.extend(prefix)
    patched.extend(role_block)
    patched.extend(tail)

    # Preserve the certified linked-player payload length, but move padding out
    # of the parse path so the native cursor lands on role/metadata bytes.
    if len(patched) > old_payload_length:
        raise RuntimeError(f"Physical variable payload grew unexpectedly for {target_name!r}")
    tail_padding = old_payload_length - len(patched)
    patched.extend(b"\x61" * tail_padding)
    if len(patched) != old_payload_length:
        raise RuntimeError(f"Payload length changed unexpectedly for {target_name!r}")

    # Re-apply semantic fields at the moved metadata anchor. The source proof
    # already has these values, but writing them at the new offsets guards
    # against future source roots that have stale fields.
    _write_decoded_byte(patched, new_name_end + 5, int(source_row["pm99_nat_code"]))
    _write_decoded_byte(patched, new_name_end + 7, int(source_row["pm99_position_code"]))
    _write_decoded_byte(patched, new_name_end + 8, int(source_row["pm99_position_code"]))
    _write_decoded_byte(patched, new_name_end + 9, int(source_row["birth_day"]))
    _write_decoded_byte(patched, new_name_end + 10, int(source_row["birth_month"]))
    year_bytes = struct.pack("<H", int(source_row["birth_year"]))
    _write_decoded_byte(patched, new_name_end + 11, year_bytes[0])
    _write_decoded_byte(patched, new_name_end + 12, year_bytes[1])
    _write_decoded_byte(patched, new_name_end + 13, int(source_row["height_cm"]))
    _write_decoded_byte(patched, new_name_end + 14, int(source_row["weight_kg"]))
    for index, label in enumerate(SKILL_LABELS):
        _write_decoded_byte(patched, new_name_end + 15 + index, int(source_row["skills"][label]))

    parsed_after = PlayerRecord.from_bytes(bytes(patched), 0)
    applied_name = " ".join(_player_display_name(parsed_after).split())
    parser_name_end = PlayerRecord._find_name_end(bytes(patched))
    if parser_name_end != new_name_end:
        raise RuntimeError(
            f"Parser name_end mismatch for {target_name!r}: expected {new_name_end}, got {parser_name_end}"
        )
    if _norm(applied_name) != _norm(target_name):
        raise RuntimeError(f"Patched payload reparsed as {applied_name!r}, expected {target_name!r}")

    fields = _read_clone_fields(bytes(patched), new_name_end)
    expected = _expected_clone_fields(source_row)
    _assert_expected_fields(fields, expected, target_name)

    role_block_decoded = [_decoded_byte(bytes(patched), new_role_start + i) for i in range(8)]
    return bytes(patched), {
        "old_name": old_display_name,
        "applied_name": applied_name,
        "payload_length": old_payload_length,
        "first_len_offset": first_len_offset,
        "old_name_end": old_name_end,
        "new_name_end": new_name_end,
        "old_role_start": old_role_start,
        "new_role_start": new_role_start,
        "removed_fixed_padding_bytes": removed_padding,
        "tail_padding_bytes": tail_padding,
        "natural_name_prefix_length": len(prefix),
        "role_block_decoded": role_block_decoded,
        "fields": fields,
        "head_hex": bytes(patched[: min(72, len(patched))]).hex(),
    }


def main() -> int:
    args = _parse_args()
    base_game = Path(args.base_game).expanduser().resolve()
    out_game = Path(args.out_game).expanduser().resolve()
    if out_game.exists():
        if not args.force:
            raise SystemExit(f"Output exists: {out_game}")
        shutil.rmtree(out_game)
    shutil.copytree(base_game, out_game, symlinks=True)
    artifact_dir = out_game / "artifacts" / "physical_variable_names"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    dbdat = out_game / "DBDAT"
    team_file = dbdat / "EQ98030.FDI"
    player_file = dbdat / "JUG98030.FDI"
    coach_file = dbdat / "ENT98030.FDI"
    country_codes = _extract_nationality_codes(dbdat / "TEXTOS.PKF")
    source_by_name = {_norm(row["game_name"]): row for row in _source_rows(country_codes)}
    roster_rows = _resolve_roster(team_file, player_file, args.team_query)

    file_data = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(file_data)
    entries_by_id = {int(entry.record_id): entry for entry in indexed.entries}
    stages: list[tuple[int, _IndexedRawStageRecord]] = []
    patch_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for roster_row in roster_rows:
        player_name = str(roster_row["player_name"])
        source_row = source_by_name.get(_norm(player_name))
        if source_row is None:
            failures.append({"slot": roster_row["slot"], "player_name": player_name, "reason": "missing_source_row"})
            continue
        entry = entries_by_id[int(roster_row["pid"])]
        decoded = entry.decode_payload(file_data)
        try:
            patched, meta = _patch_physical_variable_payload(decoded, source_row)
        except Exception as exc:
            failures.append(
                {
                    "slot": roster_row["slot"],
                    "pid": roster_row["pid"],
                    "player_name": player_name,
                    "reason": str(exc),
                }
            )
            continue
        stages.append(
            (
                int(entry.payload_offset),
                _IndexedRawStageRecord(
                    raw_payload=patched,
                    container_offset=int(entry.payload_offset),
                    container_length=int(entry.payload_length),
                ),
            )
        )
        patch_rows.append({"slot": roster_row["slot"], "pid": roster_row["pid"], "target_name": player_name, **meta})

    backup_path = None
    if not failures:
        backup_path = write_player_staged_records(str(player_file), stages, create_backup_before_write=True)

    (artifact_dir / "physical_variable_patches.json").write_text(json.dumps(patch_rows, indent=2), encoding="utf-8")
    (artifact_dir / "team_roster.json").write_text(json.dumps(roster_rows, indent=2), encoding="utf-8")
    manifest = {
        "schema": "pm99-stoke-2015-physical-variable-compact-names-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "base_game": str(base_game),
        "out_game": str(out_game),
        "ok": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "contract": (
            "Compact dd6360 name blocks are physically variable; role/metadata follows the natural "
            "name prefix; removed fixed padding is appended at payload tail to preserve runtime-safe length."
        ),
        "jug_backup_path": str(backup_path) if backup_path else None,
        "patches_json": str(artifact_dir / "physical_variable_patches.json"),
        "team_roster_json": str(artifact_dir / "team_roster.json"),
        "hashes": {
            "EQ98030.FDI": sha256(team_file),
            "JUG98030.FDI": sha256(player_file),
            "ENT98030.FDI": sha256(coach_file),
        },
    }
    (artifact_dir / "physical_variable_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": manifest["ok"],
                "out_game": str(out_game),
                "manifest": str(artifact_dir / "physical_variable_manifest.json"),
                "patch_rows": len(patch_rows),
                "failure_count": len(failures),
            },
            indent=2,
        )
    )
    return 0 if manifest["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
