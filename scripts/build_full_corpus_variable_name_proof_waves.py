#!/usr/bin/env python3
"""Build full-corpus variable-name proof waves for PM99 runner.

This is a research/proof helper. It deliberately separates:

- DB proof: every parser-backed indexed JUG player gets a unique variable name.
- Runtime proof: playable-club rosters are repointed in waves so the runner can
  screenshot those records in visible Current Squad tables.

Opaque/non-player records are preserved and listed explicitly.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import shutil
import struct
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
EDITOR_ROOT = REPO_ROOT / "upstream" / "pm99-skezmod-db-editor"
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.editor_actions import (  # noqa: E402
    _IndexedRawStageRecord,
    _indexed_variable_name_compact_segments,
    _indexed_variable_name_prefix,
    _patch_indexed_player_variable_name_payload,
    batch_edit_team_roster_records,
    write_player_staged_records,
)
from app.eq_jug_linked import EQLinkedTeamRoster, load_eq_linked_team_rosters  # noqa: E402
from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from app.models import PlayerRecord  # noqa: E402
from assert_pm99_isolated_input import sha256  # noqa: E402
from build_native_english_variable_name_runtime_probe import _match_rosters_to_clubs  # noqa: E402
from probe_full_jug_variable_names_db_only import _display_name, _norm  # noqa: E402


DEFAULT_BASE_GAME = REPO_ROOT / ".local" / "record33_vanilla_control_20260502T_clean"
DEFAULT_WORLD_STATE = REPO_ROOT / ".local" / "selector_maps" / "pm99_vanilla_english_80_world_stub.json"
DEFAULT_SELECTOR_MAP = REPO_ROOT / ".local" / "selector_maps" / "pm99_vanilla_english_80_selector_map.json"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "work" / "pm99" / "full_corpus_variable_name_proof"

_SKIP_DIR_NAMES = {"PM99.rep", "__pycache__"}
_SKIP_FILE_SUBSTRINGS = (".bak", "bak_", "backup", ".original", ".pre_", ".stable_", "pm99.lock")
_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


@dataclass(frozen=True)
class TargetRow:
    proof_index: int
    record_id: int
    key: str
    payload_offset: int
    old_payload_length: int
    head_hex: str
    old_name: str
    target_name: str


@dataclass(frozen=True)
class PatchRow:
    proof_index: int
    record_id: int
    key: str
    payload_offset: int
    head_hex: str
    old_name: str
    target_name: str
    applied_name: str
    family: str
    anchor_status: str
    old_payload_length: int
    new_payload_length: int
    payload_length_delta: int
    name_end_delta: int


@dataclass(frozen=True)
class CarrierSlot:
    carrier_index: int
    club_key: str
    team_query: str
    selector_team_query: str
    roster_eq_record_id: int
    roster_short_name: str
    roster_full_club_name: str
    roster_match_score: float
    slot: int
    original_player_record_id: int
    original_flag: int
    original_player_name: str


def _parse_args() -> argparse.Namespace:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-game", default=str(DEFAULT_BASE_GAME))
    parser.add_argument("--world-state", default=str(DEFAULT_WORLD_STATE))
    parser.add_argument("--selector-map", default=str(DEFAULT_SELECTOR_MAP))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT / stamp))
    parser.add_argument(
        "--wave-size",
        type=int,
        default=0,
        help="Carrier rows per wave. Default 0 means every real linked roster row in the 80 playable clubs.",
    )
    parser.add_argument("--runner-batch-size", type=int, default=10)
    parser.add_argument(
        "--dd6360-contract",
        choices=("product", "native-stream"),
        default="product",
        help=(
            "dd6360 variable-name rewrite contract. 'product' uses the editor's current fail-closed "
            "runtime gate; 'native-stream' uses the reverse-engineered native PM99 stream cursor."
        ),
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _shell_quote(value: object) -> str:
    text = str(value)
    if re.fullmatch(r"[A-Za-z0-9_./:=+-]+", text):
        return text
    return "'" + text.replace("'", "'\"'\"'") + "'"


def _safe_tag_fragment(value: object) -> str:
    fragment = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "").strip()).strip("_").lower()
    return fragment or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ").lower()


def _should_skip_file(path: Path) -> bool:
    lowered = path.name.casefold()
    return any(token in lowered for token in _SKIP_FILE_SUBSTRINGS)


def _should_skip_dir_name(name: str) -> bool:
    lowered = str(name or "").casefold()
    return (
        lowered in {item.casefold() for item in _SKIP_DIR_NAMES}
        or lowered.endswith(".rep")
        or any(token in lowered for token in _SKIP_FILE_SUBSTRINGS)
    )


def _copy_or_link_file(source: Path, destination: Path, *, copy: bool) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    if copy:
        shutil.copy2(source, destination)
        return
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _copy_lean_game_root(source_game: Path, output_game: Path, *, copy_db_files: set[str]) -> None:
    if output_game.exists():
        shutil.rmtree(output_game)
    output_game.mkdir(parents=True)
    copy_db_files = {item.casefold() for item in copy_db_files}
    for dirpath, dirnames, filenames in os.walk(source_game):
        src_dir = Path(dirpath)
        relative_dir = src_dir.relative_to(source_game)
        dirnames[:] = [name for name in dirnames if not _should_skip_dir_name(name)]
        (output_game / relative_dir).mkdir(parents=True, exist_ok=True)
        for filename in filenames:
            source = src_dir / filename
            if _should_skip_file(source):
                continue
            relative = source.relative_to(source_game)
            _copy_or_link_file(
                source,
                output_game / relative,
                copy=relative.as_posix().casefold() in copy_db_files,
            )


def _proof_name(index: int) -> str:
    # Four letter slots give 456,976 unique names. Encoded prefix is 10 bytes:
    # one-byte surname + display "ABC D".
    n = int(index)
    chars: list[str] = []
    for _ in range(4):
        chars.append(_ALPHABET[n % len(_ALPHABET)])
        n //= len(_ALPHABET)
    if n:
        raise ValueError(f"proof index {index} exceeds four-letter proof-name space")
    return f"{chars[2]}{chars[1]}{chars[0]} {chars[3]}"


def _decoded_byte(decoded: bytes, offset: int) -> int:
    return int(decoded[offset] ^ 0x61)


def _write_decoded_byte(decoded: bytearray, offset: int, value: int) -> None:
    if offset < 0 or offset >= len(decoded):
        raise RuntimeError(f"Native dd6360 write offset {offset} outside payload length {len(decoded)}")
    decoded[offset] = int(value) ^ 0x61


def _role_byte(role_code: int) -> int:
    if int(role_code) == 98:
        decoded = 0
    elif 0 <= int(role_code) <= 17:
        decoded = int(role_code) + 1
    else:
        raise ValueError(f"Fine role out of range: {role_code}")
    return decoded ^ 0x61


def _native_xor_string_end(decoded_payload: bytes, cursor: int) -> int:
    if cursor + 2 > len(decoded_payload):
        raise RuntimeError(f"Native dd6360 string length truncated at {cursor}")
    size = _decoded_byte(decoded_payload, cursor) | (_decoded_byte(decoded_payload, cursor + 1) << 8)
    if not (0 <= size <= 255):
        raise RuntimeError(f"Native dd6360 string length {size} outside one-byte proof contract at {cursor}")
    end = cursor + 2 + size
    if end > len(decoded_payload):
        raise RuntimeError(
            f"Native dd6360 string payload overruns record: cursor={cursor}, size={size}, length={len(decoded_payload)}"
        )
    return end


def _native_dd6360_role_start(decoded_payload: bytes) -> int:
    # MANAGPRE.EXE consumes bytes 5..7 as record fields, then parses two
    # native XOR/u16 strings starting at byte 8 before reading role metadata.
    cursor = 8
    cursor = _native_xor_string_end(decoded_payload, cursor)
    cursor = _native_xor_string_end(decoded_payload, cursor)
    return cursor


def _read_native_dd6360_fields(decoded_payload: bytes, role_start: int) -> dict[str, Any]:
    required_end = role_start + 27
    if required_end > len(decoded_payload):
        raise RuntimeError(
            f"Native dd6360 semantic block overruns payload: role_start={role_start}, "
            f"need={required_end}, length={len(decoded_payload)}"
        )
    primary_role_decoded = _decoded_byte(decoded_payload, role_start)
    return {
        "primary_role_code": int(primary_role_decoded - 1) if primary_role_decoded > 0 else 98,
        "visible_nationality_code": _decoded_byte(decoded_payload, role_start + 8),
        "unknown_9": _decoded_byte(decoded_payload, role_start + 9),
        "parser_position_code": _decoded_byte(decoded_payload, role_start + 10),
        "visible_position_code": _decoded_byte(decoded_payload, role_start + 11),
        "birth_day": _decoded_byte(decoded_payload, role_start + 12),
        "birth_month": _decoded_byte(decoded_payload, role_start + 13),
        "birth_year": _decoded_byte(decoded_payload, role_start + 14)
        | (_decoded_byte(decoded_payload, role_start + 15) << 8),
        "height_cm": _decoded_byte(decoded_payload, role_start + 16),
        "weight_kg": _decoded_byte(decoded_payload, role_start + 17),
        "skills": [_decoded_byte(decoded_payload, role_start + 18 + index) for index in range(9)],
    }


def _patch_dd6360_native_stream_variable_name_payload(
    decoded_payload: bytes,
    current_name: str,
    target_name: str,
) -> tuple[bytes, dict[str, Any]]:
    if decoded_payload[2:5] != b"\xdd\x63\x60":
        raise RuntimeError(f"Native dd6360 contract received unsupported family {decoded_payload[2:5].hex()}")

    editor_segments = _indexed_variable_name_compact_segments(decoded_payload)
    if editor_segments is None:
        raise RuntimeError("Could not resolve dd6360 editor-visible compact segments")
    gap = int(editor_segments["pre_marker_gap_bytes"])
    old_editor_name_end = int(editor_segments["name_end"])
    old_editor_first_len_offset = int(editor_segments["first_len_offset"])

    old_native_role_start = _native_dd6360_role_start(decoded_payload)
    old_native_tail_start = old_native_role_start + 8
    fields = _read_native_dd6360_fields(decoded_payload, old_native_role_start)

    prefix = _indexed_variable_name_prefix(target_name)
    native_first_len_offset = 8
    new_native_role_start = native_first_len_offset + len(prefix)
    if new_native_role_start > old_native_role_start:
        raise RuntimeError(
            f"Native dd6360 target name exceeds stable native string window: "
            f"new_role_start={new_native_role_start}, old_role_start={old_native_role_start}"
        )

    primary_role_code = int(fields["primary_role_code"])
    if not (0 <= primary_role_code <= 17):
        primary_role_code = 98
    role = _role_byte(primary_role_code)
    # Keep a sane primary/legacy role shape, and make the last role byte non-zero
    # so the editor-side fallback marker does not drift onto the moved metadata.
    role_block = bytearray([role, 0x61, role, 0x61, 0x61, 0x61, 0x61, role])

    patched = bytearray()
    patched.extend(decoded_payload[:native_first_len_offset])
    patched.extend(prefix)
    patched.extend(role_block)
    patched.extend(decoded_payload[old_native_tail_start:])
    natural_payload_length = len(patched)
    if natural_payload_length > len(decoded_payload):
        raise RuntimeError(
            f"Native dd6360 payload grew unexpectedly: {natural_payload_length} > {len(decoded_payload)}"
        )
    patched.extend(b"\x61" * (len(decoded_payload) - natural_payload_length))

    _write_decoded_byte(patched, new_native_role_start + 8, fields["visible_nationality_code"])
    _write_decoded_byte(patched, new_native_role_start + 9, fields["unknown_9"])
    _write_decoded_byte(patched, new_native_role_start + 10, fields["parser_position_code"])
    _write_decoded_byte(patched, new_native_role_start + 11, fields["visible_position_code"])
    _write_decoded_byte(patched, new_native_role_start + 12, fields["birth_day"])
    _write_decoded_byte(patched, new_native_role_start + 13, fields["birth_month"])
    year_bytes = struct.pack("<H", int(fields["birth_year"]))
    _write_decoded_byte(patched, new_native_role_start + 14, year_bytes[0])
    _write_decoded_byte(patched, new_native_role_start + 15, year_bytes[1])
    _write_decoded_byte(patched, new_native_role_start + 16, fields["height_cm"])
    _write_decoded_byte(patched, new_native_role_start + 17, fields["weight_kg"])
    for index, value in enumerate(fields["skills"]):
        _write_decoded_byte(patched, new_native_role_start + 18 + index, int(value))

    patched_bytes = bytes(patched)
    parsed = PlayerRecord.from_bytes(patched_bytes, 0)
    applied_name = _display_name(parsed)
    if _norm(applied_name) != _norm(target_name):
        raise RuntimeError(f"Native dd6360 patched payload reparsed as {applied_name!r}, expected {target_name!r}")
    if patched_bytes[2:5] != decoded_payload[2:5]:
        raise RuntimeError("Native dd6360 signature changed")

    new_editor_name_end = PlayerRecord._find_name_end(patched_bytes)
    return patched_bytes, {
        "family": f"dd6360_native_stream_gap{gap}",
        "old_name": current_name,
        "target_name": target_name,
        "applied_name": applied_name,
        "old_name_end": old_editor_name_end,
        "new_name_end": int(new_editor_name_end) if new_editor_name_end is not None else -1,
        "old_payload_length": len(decoded_payload),
        "new_payload_length": len(patched_bytes),
        "natural_payload_length": natural_payload_length,
        "payload_length_delta": len(patched_bytes) - len(decoded_payload),
        "name_end_delta": (int(new_editor_name_end) - old_editor_name_end) if new_editor_name_end is not None else 0,
        "anchor_status": "native_stream",
        "first_len_offset": native_first_len_offset,
        "editor_first_len_offset": old_editor_first_len_offset,
        "pre_marker_gap_bytes": gap,
        "old_role_start": old_native_role_start,
        "new_role_start": new_native_role_start,
        "tail_padding_bytes": len(decoded_payload) - natural_payload_length,
    }


def _load_targets(player_file: Path) -> tuple[list[TargetRow], list[dict[str, Any]]]:
    data = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(data)
    targets: list[TargetRow] = []
    preserve_only: list[dict[str, Any]] = []
    for entry in indexed.entries:
        decoded = entry.decode_payload(data)
        head_hex = decoded[2:5].hex() if len(decoded) >= 5 else ""
        try:
            parsed = PlayerRecord.from_bytes(decoded, int(entry.payload_offset))
            old_name = _display_name(parsed)
            if not old_name or old_name in {"Unknown Player", "Parse Error"}:
                raise RuntimeError("opaque_or_non_player_payload")
            proof_index = len(targets)
            targets.append(
                TargetRow(
                    proof_index=proof_index,
                    record_id=int(entry.record_id),
                    key=str(entry.key),
                    payload_offset=int(entry.payload_offset),
                    old_payload_length=int(entry.payload_length),
                    head_hex=head_hex,
                    old_name=old_name,
                    target_name=_proof_name(proof_index),
                )
            )
        except Exception as exc:
            preserve_only.append(
                {
                    "record_id": int(entry.record_id),
                    "key": str(entry.key),
                    "payload_offset": int(entry.payload_offset),
                    "payload_length": int(entry.payload_length),
                    "head_hex": head_hex,
                    "status": "preserve_only",
                    "failure": str(exc),
                }
            )
    return targets, preserve_only


def _patch_full_jug(
    player_file: Path,
    targets: list[TargetRow],
    *,
    dd6360_contract: str = "product",
) -> tuple[list[PatchRow], list[dict[str, Any]]]:
    data = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(data)
    entries_by_id = {int(entry.record_id): entry for entry in indexed.entries}
    stages: list[tuple[int, _IndexedRawStageRecord]] = []
    patch_rows: list[PatchRow] = []
    blocked_rows: list[dict[str, Any]] = []
    for target in targets:
        entry = entries_by_id[int(target.record_id)]
        decoded = entry.decode_payload(data)
        try:
            if dd6360_contract == "native-stream" and decoded[2:5] == b"\xdd\x63\x60":
                patched, meta = _patch_dd6360_native_stream_variable_name_payload(
                    decoded,
                    target.old_name,
                    target.target_name,
                )
            else:
                patched, meta = _patch_indexed_player_variable_name_payload(
                    decoded,
                    target.old_name,
                    target.target_name,
                )
        except Exception as exc:
            blocked_rows.append(
                {
                    **asdict(target),
                    "status": "preserve_only",
                    "failure": str(exc),
                    "head_hex": target.head_hex,
                    "old_payload_length": int(entry.payload_length),
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
        patch_rows.append(
            PatchRow(
                proof_index=target.proof_index,
                record_id=target.record_id,
                key=target.key,
                payload_offset=int(entry.payload_offset),
                head_hex=target.head_hex,
                old_name=target.old_name,
                target_name=target.target_name,
                applied_name=str(meta["applied_name"]),
                family=str(meta["family"]),
                anchor_status=str(meta.get("anchor_status") or ""),
                old_payload_length=int(meta["old_payload_length"]),
                new_payload_length=int(meta["new_payload_length"]),
                payload_length_delta=int(meta["payload_length_delta"]),
                name_end_delta=int(meta["name_end_delta"]),
            )
        )
    if stages:
        write_player_staged_records(str(player_file), stages, create_backup_before_write=False)
    return patch_rows, blocked_rows


def _verify_jug(player_file: Path, patches: list[PatchRow]) -> list[dict[str, Any]]:
    data = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(data)
    entries_by_id = {int(entry.record_id): entry for entry in indexed.entries}
    failures: list[dict[str, Any]] = []
    for row in patches:
        entry = entries_by_id.get(int(row.record_id))
        if entry is None:
            failures.append({**asdict(row), "failure": "missing_post_entry"})
            continue
        try:
            decoded = entry.decode_payload(data)
            parsed = PlayerRecord.from_bytes(decoded, int(entry.payload_offset))
            actual = _display_name(parsed)
            if _norm(actual) != _norm(row.target_name):
                failures.append({**asdict(row), "failure": "post_name_mismatch", "actual": actual})
            if int(entry.payload_length) != int(row.new_payload_length):
                failures.append(
                    {
                        **asdict(row),
                        "failure": "post_payload_length_mismatch",
                        "actual_payload_length": int(entry.payload_length),
                    }
                )
        except Exception as exc:
            failures.append({**asdict(row), "failure": f"post_exception:{exc}"})
    return failures


def _load_clubs(world_state: Path) -> list[dict[str, Any]]:
    world = json.loads(world_state.read_text(encoding="utf-8"))
    clubs = [row for row in list(world.get("clubs") or []) if isinstance(row, dict) and row.get("club_key")]
    if len(clubs) != 80:
        raise RuntimeError(f"Expected 80 playable clubs, got {len(clubs)} from {world_state}")
    return clubs


def _build_carrier_slots(
    *,
    base_game: Path,
    clubs: list[dict[str, Any]],
) -> tuple[list[CarrierSlot], list[dict[str, Any]]]:
    rosters = list(
        load_eq_linked_team_rosters(
            team_file=str(base_game / "DBDAT" / "EQ98030.FDI"),
            player_file=str(base_game / "DBDAT" / "JUG98030.FDI"),
        )
    )
    matches = _match_rosters_to_clubs(clubs=clubs, rosters=rosters)
    missing = [str(club.get("club_key")) for club in clubs if str(club.get("club_key") or "") not in matches]
    if missing:
        raise RuntimeError(f"Missing parser-backed linked roster matches for playable clubs: {missing}")

    carrier_slots: list[CarrierSlot] = []
    capacity_rows: list[dict[str, Any]] = []
    for club_index, club in enumerate(clubs, start=1):
        club_key = str(club.get("club_key") or "")
        roster, score = matches[club_key]
        rows = sorted(
            list(getattr(roster, "rows", []) or []),
            key=lambda row: int(getattr(row, "slot_index", 0) or 0),
        )
        capacity_rows.append(
            {
                "club_index": club_index,
                "club_key": club_key,
                "team_query": str(club.get("team_query") or ""),
                "roster_eq_record_id": int(getattr(roster, "eq_record_id", 0) or 0),
                "roster_short_name": str(getattr(roster, "short_name", "") or ""),
                "roster_full_club_name": str(getattr(roster, "full_club_name", "") or ""),
                "roster_match_score": round(float(score), 2),
                "linked_row_count": len(rows),
            }
        )
        for row in rows:
            carrier_slots.append(
                CarrierSlot(
                    carrier_index=len(carrier_slots),
                    club_key=club_key,
                    team_query=str(getattr(roster, "short_name", "") or club.get("team_query") or club_key),
                    selector_team_query=str(club.get("team_query") or ""),
                    roster_eq_record_id=int(getattr(roster, "eq_record_id", 0) or 0),
                    roster_short_name=str(getattr(roster, "short_name", "") or ""),
                    roster_full_club_name=str(getattr(roster, "full_club_name", "") or ""),
                    roster_match_score=round(float(score), 2),
                    slot=int(getattr(row, "slot_index", 0) or 0) + 1,
                    original_player_record_id=int(getattr(row, "player_record_id", 0) or 0),
                    original_flag=int(getattr(row, "flag", 0) or 0),
                    original_player_name=" ".join(str(getattr(row, "player_name", "") or "").split()),
                )
            )
    if not carrier_slots:
        raise RuntimeError("No parser-backed linked roster carrier slots were found")
    return carrier_slots, capacity_rows


def _write_roster_csv(path: Path, carrier_slots: list[CarrierSlot], patches: list[PatchRow]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, patch in enumerate(patches):
        carrier = carrier_slots[index]
        rows.append(
            {
                "team": carrier.team_query,
                "eq_record_id": carrier.roster_eq_record_id,
                "source": "linked",
                "slot": carrier.slot,
                "player_id": patch.record_id,
                "flag": 0,
                "proof_index": patch.proof_index,
                "carrier_index": carrier.carrier_index,
                "club_key": carrier.club_key,
                "selector_team_query": carrier.selector_team_query,
                "roster_eq_record_id": carrier.roster_eq_record_id,
                "roster_short_name": carrier.roster_short_name,
                "roster_full_club_name": carrier.roster_full_club_name,
                "roster_match_score": carrier.roster_match_score,
                "original_player_record_id": carrier.original_player_record_id,
                "original_flag": carrier.original_flag,
                "original_player_name": carrier.original_player_name,
                "target_name": patch.target_name,
            }
        )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["team", "eq_record_id", "source", "slot", "player_id", "flag"])
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in ["team", "eq_record_id", "source", "slot", "player_id", "flag"]})
    return rows


def _readback_wave_rosters(game_dir: Path, assignments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rosters = list(
        load_eq_linked_team_rosters(
            team_file=str(game_dir / "DBDAT" / "EQ98030.FDI"),
            player_file=str(game_dir / "DBDAT" / "JUG98030.FDI"),
        )
    )
    roster_by_eq = {int(getattr(roster, "eq_record_id", 0) or 0): roster for roster in rosters}
    rows: list[dict[str, Any]] = []
    for assignment in assignments:
        roster = roster_by_eq.get(int(assignment["roster_eq_record_id"]))
        actual = ""
        if roster is not None:
            slot_index = int(assignment["slot"]) - 1
            roster_rows = list(getattr(roster, "rows", []) or [])
            if 0 <= slot_index < len(roster_rows):
                actual = " ".join(str(getattr(roster_rows[slot_index], "player_name", "") or "").split())
        rows.append(
            {
                **assignment,
                "linked_roster_name": actual,
                "readback_ok": _norm(actual) == _norm(str(assignment["target_name"])),
            }
        )
    return rows


def _build_waves(
    *,
    output_dir: Path,
    full_game: Path,
    clubs: list[dict[str, Any]],
    carrier_slots: list[CarrierSlot],
    patches: list[PatchRow],
    wave_size: int,
    runner_batch_size: int,
    world_state: Path,
    selector_map: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    waves: list[dict[str, Any]] = []
    runner_batches: list[dict[str, Any]] = []
    if wave_size <= 0:
        wave_size = len(carrier_slots)
    wave_size = min(int(wave_size), len(carrier_slots))
    wave_count = math.ceil(len(patches) / wave_size)
    for wave_index in range(wave_count):
        wave_no = wave_index + 1
        chunk = patches[wave_index * wave_size : (wave_index + 1) * wave_size]
        wave_dir = output_dir / f"wave_{wave_no:02d}"
        game_dir = wave_dir / "game"
        wave_dir.mkdir(parents=True, exist_ok=True)
        _copy_lean_game_root(full_game, game_dir, copy_db_files={"DBDAT/JUG98030.FDI", "DBDAT/EQ98030.FDI"})
        roster_csv = wave_dir / "proof_roster.csv"
        assignments = _write_roster_csv(roster_csv, carrier_slots[: len(chunk)], chunk)
        result = batch_edit_team_roster_records(
            team_file=str(game_dir / "DBDAT" / "EQ98030.FDI"),
            csv_path=str(roster_csv),
            player_file=str(game_dir / "DBDAT" / "JUG98030.FDI"),
            write_changes=True,
        )
        backup_path = getattr(result, "backup_path", None)
        if backup_path:
            Path(str(backup_path)).unlink(missing_ok=True)
        readback = _readback_wave_rosters(game_dir, assignments)
        wave_club_keys = sorted({str(row["club_key"]) for row in assignments})
        wave_summary = {
            "wave_no": wave_no,
            "wave_dir": str(wave_dir),
            "game_dir": str(game_dir),
            "roster_csv": str(roster_csv),
            "player_count": len(chunk),
            "carrier_slot_count": len(assignments),
            "wave_size": wave_size,
            "club_count": len(wave_club_keys),
            "club_keys": wave_club_keys,
            "proof_index_min": min((row.proof_index for row in chunk), default=None),
            "proof_index_max": max((row.proof_index for row in chunk), default=None),
            "matched_row_count": int(getattr(result, "matched_row_count", 0) or 0),
            "linked_change_count": len(getattr(result, "linked_changes", []) or []),
            "warning_count": len(getattr(result, "warnings", []) or []),
            "warnings": [str(getattr(warning, "message", warning)) for warning in list(getattr(result, "warnings", []) or [])],
            "readback_ok_count": sum(1 for row in readback if row["readback_ok"]),
            "readback_failures": [row for row in readback if not row["readback_ok"]][:25],
            "hashes": {
                "MANAGPRE.EXE": sha256(game_dir / "MANAGPRE.EXE"),
                "DBDAT/JUG98030.FDI": sha256(game_dir / "DBDAT" / "JUG98030.FDI"),
                "DBDAT/EQ98030.FDI": sha256(game_dir / "DBDAT" / "EQ98030.FDI"),
            },
        }
        _json_dump(wave_dir / "assignments.json", assignments)
        _write_csv(wave_dir / "assignments.csv", assignments)
        _json_dump(wave_dir / "linked_roster_readback.json", readback)
        _write_csv(wave_dir / "linked_roster_readback.csv", readback)
        _json_dump(wave_dir / "summary.json", wave_summary)
        waves.append(wave_summary)

        club_keys_in_order = [str(club["club_key"]) for club in clubs if str(club["club_key"]) in set(wave_club_keys)]
        for batch_start in range(0, len(club_keys_in_order), runner_batch_size):
            batch_no = (batch_start // runner_batch_size) + 1
            batch_clubs = club_keys_in_order[batch_start : batch_start + runner_batch_size]
            proof_tag = _safe_tag_fragment(output_dir.name)
            tag = f"full_corpus_varnames_{proof_tag}_w{wave_no:02d}_b{batch_no:02d}_runtime"
            command = [
                "./scripts/run_2025_roster_visual_sample.sh",
                "--game-root",
                str(game_dir),
                "--world-state",
                str(world_state),
                "--selector-map",
                str(selector_map),
                "--run-tag",
                tag,
                "--capture-route",
                "squad",
                "--profile-count",
                "0",
                "--squad-enable-status-filters",
                "--squad-scroll-proof-pages",
                "1",
                "--squad-scroll-clicks",
                "6",
                "--skip-setup",
                "--skip-build",
                "--cleanup-on-failure",
            ]
            for club_key in batch_clubs:
                command.extend(["--club-key", club_key])
            batch = {
                "wave_no": wave_no,
                "batch_no": batch_no,
                "run_tag": tag,
                "club_keys": batch_clubs,
                "command": command,
            }
            runner_batches.append(batch)
            script_path = wave_dir / f"run_wave_{wave_no:02d}_batch_{batch_no:02d}.sh"
            script_path.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                f"cd {_shell_quote(REPO_ROOT)}\n"
                "PM99_RUNNER_WORKER_LANE_COUNT=${PM99_RUNNER_WORKER_LANE_COUNT:-2} \\\n"
                "PM99_RUNNER_DOCKER_TIMEOUT_SECONDS=${PM99_RUNNER_DOCKER_TIMEOUT_SECONDS:-1800} \\\n"
                "PM99_RUNNER_SKIP_CLASSIFICATION=${PM99_RUNNER_SKIP_CLASSIFICATION:-1} \\\n"
                + " ".join(_shell_quote(part) for part in command)
                + "\n",
                encoding="utf-8",
            )
            script_path.chmod(0o755)
    return waves, runner_batches


def _write_runner_matrix(output_dir: Path, runner_batches: list[dict[str, Any]]) -> Path:
    script_path = output_dir / "run_all_runner_batches.sh"
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        f"ROOT_DIR={_shell_quote(REPO_ROOT)}",
        "cd \"${ROOT_DIR}\"",
        "PARALLEL_JOBS=\"${PM99_FULL_CORPUS_VARNAME_PARALLEL_JOBS:-8}\"",
        "mkdir -p \"$(dirname \"${BASH_SOURCE[0]}\")/runner_logs\"",
        "run_one() {",
        "  local wave=\"$1\" batch=\"$2\" script=\"$3\"",
        "  local log_dir=\"$(dirname \"${BASH_SOURCE[0]}\")/runner_logs\"",
        "  bash \"$script\" >\"${log_dir}/wave_${wave}_batch_${batch}.stdout\" 2>\"${log_dir}/wave_${wave}_batch_${batch}.stderr\"",
        "}",
        "pids=()",
    ]
    for batch in runner_batches:
        rel_script = Path(f"wave_{int(batch['wave_no']):02d}") / f"run_wave_{int(batch['wave_no']):02d}_batch_{int(batch['batch_no']):02d}.sh"
        lines.extend(
            [
                "while [ \"${#pids[@]}\" -ge \"${PARALLEL_JOBS}\" ]; do",
                "  wait -n || true",
                "  live=()",
                "  for pid in \"${pids[@]}\"; do kill -0 \"$pid\" 2>/dev/null && live+=(\"$pid\") || true; done",
                "  pids=(\"${live[@]}\")",
                "done",
                f"run_one {_shell_quote(f'{int(batch['wave_no']):02d}')} {_shell_quote(f'{int(batch['batch_no']):02d}')} {_shell_quote(str(output_dir / rel_script))} &",
                "pids+=(\"$!\")",
            ]
        )
    lines.extend(
        [
            "status=0",
            "for pid in \"${pids[@]}\"; do",
            "  wait \"$pid\" || status=1",
            "done",
            "exit \"$status\"",
            "",
        ]
    )
    script_path.write_text("\n".join(lines), encoding="utf-8")
    script_path.chmod(0o755)
    return script_path


def build(args: argparse.Namespace) -> dict[str, Any]:
    base_game = Path(args.base_game).expanduser().resolve()
    world_state = Path(args.world_state).expanduser().resolve()
    selector_map = Path(args.selector_map).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    if output_dir.exists():
        if not args.force:
            raise FileExistsError(output_dir)
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    clubs = _load_clubs(world_state)
    carrier_slots, carrier_capacity = _build_carrier_slots(base_game=base_game, clubs=clubs)
    base_player_file = base_game / "DBDAT" / "JUG98030.FDI"
    targets, preserve_only = _load_targets(base_player_file)
    full_game = output_dir / "full_variable_game"
    _copy_lean_game_root(base_game, full_game, copy_db_files={"DBDAT/JUG98030.FDI", "DBDAT/EQ98030.FDI"})
    patch_rows, product_blocked = _patch_full_jug(
        full_game / "DBDAT" / "JUG98030.FDI",
        targets,
        dd6360_contract=str(args.dd6360_contract),
    )
    post_failures = _verify_jug(full_game / "DBDAT" / "JUG98030.FDI", patch_rows)
    if post_failures:
        _json_dump(output_dir / "post_write_failures.json", post_failures[:500])
        raise RuntimeError(f"Full JUG variable-name readback failed: {len(post_failures)} failures")

    waves, runner_batches = _build_waves(
        output_dir=output_dir,
        full_game=full_game,
        clubs=clubs,
        carrier_slots=carrier_slots,
        patches=patch_rows,
        wave_size=int(args.wave_size),
        runner_batch_size=int(args.runner_batch_size),
        world_state=world_state,
        selector_map=selector_map,
    )
    runner_matrix = _write_runner_matrix(output_dir, runner_batches)
    payload_deltas = Counter(row.payload_length_delta for row in patch_rows)
    family_counts = Counter(row.family for row in patch_rows)
    summary = {
        "success": True,
        "scope": "full_corpus_variable_name_proof_waves",
        "base_game": str(base_game),
        "full_game": str(full_game),
        "world_state": str(world_state),
        "selector_map": str(selector_map),
        "output_dir": str(output_dir),
        "dd6360_contract": str(args.dd6360_contract),
        "record_count": len(targets) + len(preserve_only),
        "parser_backed_player_count": len(targets),
        "supported_player_count": len(patch_rows),
        "product_blocked_player_count": len(product_blocked),
        "preserve_only_count": len(preserve_only) + len(product_blocked),
        "opaque_preserve_only_count": len(preserve_only),
        "patch_count": len(patch_rows),
        "post_write_failure_count": len(post_failures),
        "carrier_slot_count": len(carrier_slots),
        "carrier_capacity": carrier_capacity,
        "family_counts": dict(sorted(family_counts.items())),
        "payload_length_delta_counts": {str(key): int(value) for key, value in sorted(payload_deltas.items())},
        "payload_grew_count": sum(1 for row in patch_rows if row.payload_length_delta > 0),
        "payload_same_count": sum(1 for row in patch_rows if row.payload_length_delta == 0),
        "payload_shrank_count": sum(1 for row in patch_rows if row.payload_length_delta < 0),
        "max_payload_length_delta": max((row.payload_length_delta for row in patch_rows), default=0),
        "min_payload_length_delta": min((row.payload_length_delta for row in patch_rows), default=0),
        "wave_count": len(waves),
        "runner_batch_count": len(runner_batches),
        "runner_matrix_script": str(runner_matrix),
        "waves": waves,
        "runner_batches": runner_batches,
        "hashes": {
            "input_JUG98030.FDI": sha256(base_player_file),
            "output_JUG98030.FDI": sha256(full_game / "DBDAT" / "JUG98030.FDI"),
            "output_EQ98030.FDI": sha256(full_game / "DBDAT" / "EQ98030.FDI"),
            "MANAGPRE.EXE": sha256(full_game / "MANAGPRE.EXE"),
        },
    }
    _json_dump(output_dir / "targets.json", [asdict(row) for row in targets])
    _write_csv(output_dir / "targets.csv", [asdict(row) for row in targets])
    _json_dump(output_dir / "product_blocked.json", product_blocked)
    _write_csv(output_dir / "product_blocked.csv", product_blocked)
    combined_preserve_only = [*preserve_only, *product_blocked]
    _json_dump(output_dir / "preserve_only.json", combined_preserve_only)
    _write_csv(output_dir / "preserve_only.csv", combined_preserve_only)
    _json_dump(output_dir / "patches.json", [asdict(row) for row in patch_rows])
    _write_csv(output_dir / "patches.csv", [asdict(row) for row in patch_rows])
    _json_dump(output_dir / "carrier_slots.json", [asdict(row) for row in carrier_slots])
    _write_csv(output_dir / "carrier_slots.csv", [asdict(row) for row in carrier_slots])
    _json_dump(output_dir / "carrier_capacity.json", carrier_capacity)
    _write_csv(output_dir / "carrier_capacity.csv", carrier_capacity)
    _json_dump(output_dir / "runner_batches.json", runner_batches)
    _json_dump(output_dir / "summary.json", summary)
    return summary


def main() -> int:
    summary = build(_parse_args())
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
