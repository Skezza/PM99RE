#!/usr/bin/env python3
"""Build a Stoke 2015 variable-length-name runtime candidate.

This is a research proof for the indexed JUG ``dd6361`` linked-player family.
It keeps Stoke's existing EQ roster slots and record IDs, then rewrites each
original Stoke player payload with a 2015 player of the same coarse position.

The safe cut point for these payloads is the indexed suffix anchor, not the
``aaaa`` marker returned by ``PlayerRecord._find_name_end``. The rewrite replaces
only the visible surname/full-name prelude before that anchor and keeps the
suffix block intact, shifted by the name length delta. Anchor-relative semantic
bytes and tail-relative skills are patched after the move.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import struct
import sys
from dataclasses import dataclass
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
    _cp1252_bytes,
    _split_display_name_for_linked_payload,
    write_player_staged_records,
)
from app.editor_helpers import _player_display_name  # noqa: E402
from app.eq_jug_linked import load_eq_linked_team_rosters  # noqa: E402
from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from app.models import PlayerRecord  # noqa: E402
from assert_pm99_isolated_input import sha256  # noqa: E402
from apply_stoke_2015_semantic_runtime_patch import (  # noqa: E402
    NAT_ABBR_TO_PM99_LABEL,
    NAT_ABBR_TO_SOURCE_LABEL,
    POSITION_CODE,
    POSITION_LABEL,
    SKILL_LABELS,
    SOURCE_URL,
    SOURCE_URLS,
    STOKE_ATTRIBUTE_BACKFILL,
    STOKE_SEASON_STATS,
    STOKE_TARGETS,
    StokeTarget,
    _extract_nationality_codes,
    _height_cm,
    _skills_for,
)


ROLE_ORDER = ("G", "D", "M", "F")
POSITION_TO_ABBR = {0: "G", 1: "D", 2: "M", 3: "F"}


SHAY_GIVEN = StokeTarget(
    24,
    "Shay Given",
    "Shay Given",
    24,
    "IRL",
    "G",
    "1.88",
    84,
    "20-04-76",
    "Lifford",
    "Aston Villa",
    (45, 48, 55, 68, 42, 30, 45, 18, 40),
    (0,),
)

SHAY_GIVEN_STATS: dict[str, int | str | None] = {
    "wiki_starts": 5,
    "wiki_subs": 0,
    "wiki_goals": 0,
    "wiki_yellow": 1,
    "wiki_red": 0,
    "espn_app": 3,
    "espn_sub": 0,
    "espn_goals": 0,
    "espn_assists": 0,
    "espn_shots": 0,
    "espn_sot": 0,
    "espn_fouls_committed": 1,
    "espn_fouls_suffered": 1,
}

SHAY_GIVEN_BACKFILL: dict[str, int | str] = {
    "speed": 45,
    "stamina": 48,
    "aggression": 55,
    "quality": 68,
    "heading": 42,
    "dribbling": 30,
    "passing": 45,
    "shooting": 18,
    "tackling": 40,
    "basis": "Senior reserve goalkeeper: FootballSquads bio data plus ESPN 3 PL appearances; older keeper profile with moderate quality and low outfield skills.",
}

# Match the pristine Stoke coarse-position inventory exactly:
#   G=2, D=7, M=7, F=4.
# Odemwingie is dropped from the previous fixed-name twenty because preserving
# the second goalkeeper slot is the stricter user requirement for this proof.
TARGET_NAMES_BY_ROLE: dict[str, list[str]] = {
    "G": ["Jack Butland", "Shay Given"],
    "D": [
        "Phil Bardsley",
        "Erik Pieters",
        "Marc Muniesa",
        "Glen Johnson",
        "Marc Wilson",
        "Ryan Shawcross",
        "Geoff Cameron",
    ],
    "M": [
        "Glenn Whelan",
        "Stephen Ireland",
        "Ibrahim Afellay",
        "Marco van Ginkel",
        "Charlie Adam",
        "Giannelli Imbula",
        "Steve Sidwell",
    ],
    "F": ["Marko Arnautovic", "Joselu Mato", "Mame Diouf", "Jonathan Walters"],
}


@dataclass(frozen=True)
class RuntimeNameSegments:
    first_len_offset: int
    surname_start: int
    surname_end: int
    surname_width: int
    full_len_offset: int
    full_name_start: int
    full_name_end: int
    full_name_width: int


def _parse_args() -> argparse.Namespace:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-game",
        default=str(REPO_ROOT / ".local" / "premier-manager-ninety-nine"),
        help="Clean full PM99 game root containing DBDAT/",
    )
    parser.add_argument(
        "--out-game",
        default=str(REPO_ROOT / ".local" / f"stoke_2015_variable_names_{stamp}"),
        help="Output game root to create",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Artifact directory. Defaults to <out-game>/artifacts/variable_names.",
    )
    parser.add_argument("--team-query", default="Stoke", help="Team query for linked roster lookup")
    parser.add_argument("--force", action="store_true", help="Replace --out-game when it already exists")
    parser.add_argument("--dry-run", action="store_true", help="Build artifacts without writing JUG")
    return parser.parse_args()


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").casefold())


def _dob_parts(value: str) -> tuple[int, int, int]:
    day_text, month_text, year_text = value.split("-")
    year_two = int(year_text)
    return int(day_text), int(month_text), 1900 + year_two


def _encode_byte(value: int) -> int:
    if not 0 <= int(value) <= 255:
        raise ValueError(f"Byte value out of range: {value}")
    return int(value) ^ 0x61


def _decode_byte(payload: bytes, offset: int) -> int:
    return payload[offset] ^ 0x61


def _write_decoded_byte(payload: bytearray, offset: int, value: int) -> None:
    if offset < 0 or offset >= len(payload):
        raise RuntimeError(f"Offset {offset} outside payload length {len(payload)}")
    payload[offset] = _encode_byte(value)


def _stats_for(target: StokeTarget) -> dict[str, int | str | None]:
    if target.game_name == SHAY_GIVEN.game_name:
        return dict(SHAY_GIVEN_STATS)
    stats = STOKE_SEASON_STATS.get(target.game_name)
    if stats is None:
        raise RuntimeError(f"No stats mapped for {target.game_name!r}")
    return dict(stats)


def _skills_row_for(target: StokeTarget) -> tuple[dict[str, int], str]:
    if target.game_name == SHAY_GIVEN.game_name:
        return ({label: int(SHAY_GIVEN_BACKFILL[label]) for label in SKILL_LABELS}, str(SHAY_GIVEN_BACKFILL["basis"]))
    return _skills_for(target)


def _source_row(target: StokeTarget, country_codes: dict[str, int]) -> dict[str, Any]:
    pm99_label = NAT_ABBR_TO_PM99_LABEL[target.nat_abbr]
    if pm99_label not in country_codes:
        raise RuntimeError(f"PM99 country label {pm99_label!r} not present in TEXTOS.PKF")
    day, month, year = _dob_parts(target.dob)
    stats = _stats_for(target)
    skills, attribute_basis = _skills_row_for(target)
    return {
        "game_name": target.game_name,
        "source_name": target.source_name,
        "source_number": target.source_number,
        "source_nat_abbr": target.nat_abbr,
        "source_nat_label": NAT_ABBR_TO_SOURCE_LABEL[target.nat_abbr],
        "pm99_nat_label": pm99_label,
        "pm99_nat_code": int(country_codes[pm99_label]),
        "source_position": target.pos_abbr,
        "pm99_position_code": POSITION_CODE[target.pos_abbr],
        "pm99_position_label": POSITION_LABEL[POSITION_CODE[target.pos_abbr]],
        "height_m": target.height_m,
        "height_cm": _height_cm(target.height_m),
        "weight_kg": target.weight_kg,
        "dob_source": target.dob,
        "birth_day": day,
        "birth_month": month,
        "birth_year": year,
        "birth_place": target.birth_place,
        "previous_club": target.previous_club,
        "wiki_total_starts": stats["wiki_starts"],
        "wiki_total_subs": stats["wiki_subs"],
        "wiki_total_apps": int(stats["wiki_starts"] or 0) + int(stats["wiki_subs"] or 0),
        "wiki_total_goals": stats["wiki_goals"],
        "wiki_yellow_cards": stats["wiki_yellow"],
        "wiki_red_cards": stats["wiki_red"],
        "espn_pl_apps": stats["espn_app"],
        "espn_pl_subs": stats["espn_sub"],
        "espn_pl_goals": stats["espn_goals"],
        "espn_pl_assists": stats["espn_assists"],
        "espn_pl_shots": stats["espn_shots"],
        "espn_pl_shots_on_target": stats["espn_sot"],
        "espn_pl_fouls_committed": stats["espn_fouls_committed"],
        "espn_pl_fouls_suffered": stats["espn_fouls_suffered"],
        "skills": skills,
        "attribute_basis": attribute_basis,
        "fine_role_codes": list(target.fine_roles),
        "source_section": target.source_section,
        "source_url": SOURCE_URL,
        "source_urls": dict(SOURCE_URLS),
    }


def _target_source_rows(country_codes: dict[str, int]) -> dict[str, dict[str, Any]]:
    targets = {target.game_name: target for target in STOKE_TARGETS}
    targets[SHAY_GIVEN.game_name] = SHAY_GIVEN
    return {name: _source_row(targets[name], country_codes) for names in TARGET_NAMES_BY_ROLE.values() for name in names}


def _resolve_stoke_roster(team_file: Path, player_file: Path, team_query: str) -> list[dict[str, Any]]:
    rosters = load_eq_linked_team_rosters(team_file=str(team_file), player_file=str(player_file))
    needle = team_query.strip().casefold()
    for roster in rosters:
        names = [
            str(getattr(roster, "short_name", "") or "").casefold(),
            str(getattr(roster, "full_club_name", "") or "").casefold(),
        ]
        if any(needle in item for item in names):
            rows = sorted(list(getattr(roster, "rows", []) or []), key=lambda row: int(getattr(row, "slot_index", 0)))
            return [
                {
                    "slot": int(getattr(row, "slot_index", 0)) + 1,
                    "pid": int(getattr(row, "player_record_id", 0) or 0),
                    "player_name": str(getattr(row, "player_name", "") or ""),
                    "eq_record_id": int(getattr(roster, "eq_record_id", 0) or 0),
                    "team_name": str(getattr(roster, "short_name", "") or ""),
                    "full_club_name": str(getattr(roster, "full_club_name", "") or ""),
                }
                for row in rows[:20]
            ]
    raise RuntimeError(f"Could not resolve linked roster for team query {team_query!r}")


def _runtime_name_segments(payload: bytes) -> RuntimeNameSegments:
    for first_len_offset in range(5, min(len(payload), 24)):
        surname_width = int(payload[first_len_offset] ^ 0x61)
        surname_start = first_len_offset + 2
        surname_end = surname_start + surname_width
        if not (1 <= surname_width <= 32):
            continue
        if first_len_offset + 1 >= len(payload) or payload[first_len_offset + 1] != 0x61:
            continue
        if surname_end >= len(payload):
            continue
        full_len_offset = surname_end
        if full_len_offset + 1 >= len(payload):
            continue
        full_name_width = int(payload[full_len_offset] ^ 0x61)
        full_name_start = full_len_offset + 2
        full_name_end = full_name_start + full_name_width
        if not (1 <= full_name_width <= 96):
            continue
        if payload[full_len_offset + 1] != 0x61 or full_name_end > len(payload):
            continue
        return RuntimeNameSegments(
            first_len_offset=first_len_offset,
            surname_start=surname_start,
            surname_end=surname_end,
            surname_width=surname_width,
            full_len_offset=full_len_offset,
            full_name_start=full_name_start,
            full_name_end=full_name_end,
            full_name_width=full_name_width,
        )
    raise RuntimeError("Could not resolve runtime surname/full-name segments")


def _split_runtime_name(name: str) -> tuple[str, str]:
    given, surname = _split_display_name_for_linked_payload(name)
    given = " ".join(str(given or "").split()).strip()
    surname = " ".join(str(surname or "").split()).strip()
    if not given or not surname:
        raise ValueError(f"Name must include given and surname: {name!r}")
    return given, surname


def _build_runtime_name_prefix(name: str) -> bytes:
    given, surname = _split_runtime_name(name)
    surname_bytes = _cp1252_bytes(surname)
    # Native PM99 linked-player rows carry a title-case alias surname followed by
    # a display name whose surname is uppercase. Keeping that shape avoids the
    # fallback parser treating the alias and display name as one duplicate run.
    display_name = f"{given} {surname.upper()}".strip()
    full_name_bytes = _cp1252_bytes(display_name)
    if len(surname_bytes) > 255 or len(full_name_bytes) > 255:
        raise ValueError(f"Name segment too long for runtime linked payload: {name!r}")
    return bytes([len(surname_bytes) ^ 0x61, 0x61]) + surname_bytes + bytes([len(full_name_bytes) ^ 0x61, 0x61]) + full_name_bytes


def _read_anchor_fields(payload: bytes, anchor: int) -> dict[str, Any]:
    year = _decode_byte(payload, anchor + 14) | (_decode_byte(payload, anchor + 15) << 8)
    attr_start = len(payload) - 19
    skill_values = [_decode_byte(payload, attr_start + i) for i in range(9)]
    return {
        "indexed_unknown_0": _decode_byte(payload, anchor),
        "indexed_unknown_1": _decode_byte(payload, anchor + 1),
        "nationality_code": _decode_byte(payload, anchor + 8),
        "unknown_9": _decode_byte(payload, anchor + 9),
        "unknown_10": _decode_byte(payload, anchor + 10),
        "position_code": _decode_byte(payload, anchor + 11),
        "birth_day": _decode_byte(payload, anchor + 12),
        "birth_month": _decode_byte(payload, anchor + 13),
        "birth_year": year,
        "height_cm": _decode_byte(payload, anchor + 16),
        "weight_kg": _decode_byte(payload, anchor + 17),
        "post_weight": _decode_byte(payload, anchor + 18) if anchor + 18 < len(payload) else None,
        "skills": dict(zip(SKILL_LABELS, skill_values, strict=True)),
    }


def _patch_variable_payload(decoded: bytes, payload_offset: int, source_row: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    parsed = PlayerRecord.from_bytes(decoded, payload_offset)
    old_name = " ".join(_player_display_name(parsed).split())
    old_anchor = PlayerRecord._find_indexed_suffix_anchor(decoded, old_name)
    if old_anchor is None:
        raise RuntimeError(f"Could not locate indexed suffix anchor for {old_name!r}")
    if decoded[2:5] != b"\xdd\x63\x61":
        raise RuntimeError(f"{old_name!r} is not a dd6361 indexed linked payload: {decoded[2:5].hex()}")

    segments = _runtime_name_segments(decoded)
    if int(segments.full_name_end) != int(old_anchor):
        raise RuntimeError(
            f"{old_name!r} runtime full-name end {segments.full_name_end} does not match indexed anchor {old_anchor}"
        )

    target_name = str(source_row["game_name"])
    before = _read_anchor_fields(decoded, old_anchor)
    old_name_prefix = decoded[int(segments.first_len_offset) : old_anchor]
    new_name_prefix = _build_runtime_name_prefix(target_name)
    patched = bytearray()
    patched.extend(decoded[: int(segments.first_len_offset)])
    patched.extend(new_name_prefix)
    patched.extend(decoded[old_anchor:])
    new_anchor = int(segments.first_len_offset) + len(new_name_prefix)
    delta = len(patched) - len(decoded)

    _write_decoded_byte(patched, new_anchor + 8, int(source_row["pm99_nat_code"]))
    _write_decoded_byte(patched, new_anchor + 11, int(source_row["pm99_position_code"]))
    _write_decoded_byte(patched, new_anchor + 12, int(source_row["birth_day"]))
    _write_decoded_byte(patched, new_anchor + 13, int(source_row["birth_month"]))
    year_bytes = struct.pack("<H", int(source_row["birth_year"]))
    _write_decoded_byte(patched, new_anchor + 14, year_bytes[0])
    _write_decoded_byte(patched, new_anchor + 15, year_bytes[1])
    _write_decoded_byte(patched, new_anchor + 16, int(source_row["height_cm"]))
    _write_decoded_byte(patched, new_anchor + 17, int(source_row["weight_kg"]))

    attr_start = len(patched) - 19
    for index, label in enumerate(SKILL_LABELS):
        _write_decoded_byte(patched, attr_start + index, int(source_row["skills"][label]))

    reparsed = PlayerRecord.from_bytes(bytes(patched), payload_offset)
    applied_name = " ".join(_player_display_name(reparsed).split())
    reparsed_anchor = PlayerRecord._find_indexed_suffix_anchor(bytes(patched), applied_name)
    if _norm(applied_name) != _norm(target_name):
        raise RuntimeError(f"Patched payload reparsed as {applied_name!r}, expected {target_name!r}")
    if int(reparsed_anchor or -1) != int(new_anchor):
        raise RuntimeError(f"Patched anchor drifted for {target_name!r}: {reparsed_anchor} != {new_anchor}")
    if int(getattr(reparsed, "position_primary", -1)) != int(source_row["pm99_position_code"]):
        raise RuntimeError(f"Position readback mismatch for {target_name!r}")
    if int(getattr(reparsed, "nationality", -1)) != int(source_row["pm99_nat_code"]):
        raise RuntimeError(f"Nationality readback mismatch for {target_name!r}")
    if int(getattr(reparsed, "birth_day", -1)) != int(source_row["birth_day"]):
        raise RuntimeError(f"Birth day readback mismatch for {target_name!r}")
    if int(getattr(reparsed, "birth_month", -1)) != int(source_row["birth_month"]):
        raise RuntimeError(f"Birth month readback mismatch for {target_name!r}")
    if int(getattr(reparsed, "birth_year", -1)) != int(source_row["birth_year"]):
        raise RuntimeError(f"Birth year readback mismatch for {target_name!r}")
    if int(getattr(reparsed, "height", -1)) != int(source_row["height_cm"]):
        raise RuntimeError(f"Height readback mismatch for {target_name!r}")
    if int(getattr(reparsed, "weight", -1)) != int(source_row["weight_kg"]):
        raise RuntimeError(f"Weight readback mismatch for {target_name!r}")

    after = _read_anchor_fields(bytes(patched), new_anchor)
    return bytes(patched), {
        "old_name": old_name,
        "new_name": target_name,
        "old_anchor": old_anchor,
        "new_anchor": new_anchor,
        "old_payload_length": len(decoded),
        "new_payload_length": len(patched),
        "payload_length_delta": delta,
        "old_name_prefix_hex": old_name_prefix.hex(),
        "new_name_prefix_hex": new_name_prefix.hex(),
        "old_name_prefix_text": old_name_prefix.decode("cp1252", errors="replace"),
        "new_name_prefix_text": new_name_prefix.decode("cp1252", errors="replace"),
        "runtime_segments": {
            "first_len_offset": int(segments.first_len_offset),
            "surname_start": int(segments.surname_start),
            "surname_end": int(segments.surname_end),
            "surname_width": int(segments.surname_width),
            "full_len_offset": int(segments.full_len_offset),
            "full_name_start": int(segments.full_name_start),
            "full_name_end": int(segments.full_name_end),
            "full_name_width": int(segments.full_name_width),
        },
        "before": before,
        "after": after,
    }


def _assign_targets_by_existing_position(
    roster_rows: list[dict[str, Any]],
    *,
    entries_by_id: dict[int, Any],
    player_file_bytes: bytes,
    source_by_name: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    queues: dict[str, list[dict[str, Any]]] = {
        role: [dict(source_by_name[name]) for name in names]
        for role, names in TARGET_NAMES_BY_ROLE.items()
    }
    assigned: list[dict[str, Any]] = []
    role_counts: dict[str, int] = {role: 0 for role in ROLE_ORDER}

    for row in roster_rows:
        pid = int(row["pid"])
        entry = entries_by_id.get(pid)
        if entry is None:
            raise RuntimeError(f"Stoke slot {row['slot']} PID {pid} not present in JUG index")
        decoded = entry.decode_payload(player_file_bytes)
        parsed = PlayerRecord.from_bytes(decoded, int(entry.payload_offset))
        old_pos_code = int(getattr(parsed, "position_primary", -1))
        old_role = POSITION_TO_ABBR.get(old_pos_code)
        if old_role is None:
            raise RuntimeError(f"Stoke slot {row['slot']} old position {old_pos_code} is unsupported")
        if not queues[old_role]:
            raise RuntimeError(f"No remaining 2015 {old_role} target for Stoke slot {row['slot']}")
        source = queues[old_role].pop(0)
        role_counts[old_role] += 1
        source["slot"] = int(row["slot"])
        source["pid"] = pid
        source["eq_record_id"] = int(row["eq_record_id"])
        source["team_name"] = str(row["team_name"])
        source["full_club_name"] = str(row["full_club_name"])
        source["old_player_name"] = " ".join(_player_display_name(parsed).split())
        source["old_linked_player_name"] = str(row["player_name"])
        source["old_position_code"] = old_pos_code
        source["old_position_label"] = POSITION_LABEL[old_pos_code]
        source["old_position_abbr"] = old_role
        source["payload_offset"] = int(entry.payload_offset)
        source["payload_length"] = int(entry.payload_length)
        assigned.append(source)

    leftovers = {role: [row["game_name"] for row in rows] for role, rows in queues.items() if rows}
    if leftovers:
        raise RuntimeError(f"Unassigned target rows remain after role mapping: {leftovers}")
    return assigned


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "slot",
        "pid",
        "old_player_name",
        "old_position_label",
        "game_name",
        "source_number",
        "source_nat_abbr",
        "source_nat_label",
        "pm99_nat_label",
        "source_position",
        "pm99_position_label",
        "dob_source",
        "height_cm",
        "weight_kg",
        "wiki_total_apps",
        "wiki_total_goals",
        "espn_pl_apps",
        "espn_pl_goals",
        "espn_pl_assists",
        *SKILL_LABELS,
        "attribute_basis",
        "old_payload_length",
        "new_payload_length",
        "payload_length_delta",
        "old_anchor",
        "new_anchor",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            flat = dict(row)
            flat.update(row.get("skills") or {})
            patch = row.get("variable_name_patch") or {}
            flat.update({key: patch.get(key, flat.get(key)) for key in ("old_payload_length", "new_payload_length", "payload_length_delta", "old_anchor", "new_anchor")})
            writer.writerow({key: flat.get(key, "") for key in fieldnames})


def main() -> int:
    args = _parse_args()
    base_game = Path(args.base_game).expanduser().resolve()
    out_game = Path(args.out_game).expanduser().resolve()
    if not base_game.is_dir():
        raise SystemExit(f"Base game root missing: {base_game}")
    if out_game.exists():
        if not args.force:
            raise SystemExit(f"Output game already exists: {out_game}")
        if not args.dry_run:
            shutil.rmtree(out_game)
    if not out_game.exists():
        shutil.copytree(base_game, out_game, symlinks=True)

    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else out_game / "artifacts" / "variable_names"
    output_dir.mkdir(parents=True, exist_ok=True)

    dbdat = out_game / "DBDAT"
    team_file = dbdat / "EQ98030.FDI"
    player_file = dbdat / "JUG98030.FDI"
    coach_file = dbdat / "ENT98030.FDI"
    textos_pkf = dbdat / "TEXTOS.PKF"
    for path in (team_file, player_file, coach_file, textos_pkf):
        if not path.is_file():
            raise SystemExit(f"Required PM99 file missing: {path}")

    country_codes = _extract_nationality_codes(textos_pkf)
    source_by_name = _target_source_rows(country_codes)
    file_data = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(file_data)
    entries_by_id = {int(entry.record_id): entry for entry in indexed.entries}
    roster_rows = _resolve_stoke_roster(team_file, player_file, args.team_query)
    if len(roster_rows) != 20:
        raise RuntimeError(f"Resolved {len(roster_rows)} Stoke rows, expected 20")

    assigned_rows = _assign_targets_by_existing_position(
        roster_rows,
        entries_by_id=entries_by_id,
        player_file_bytes=file_data,
        source_by_name=source_by_name,
    )

    stages: list[tuple[int, _IndexedRawStageRecord]] = []
    patched_rows: list[dict[str, Any]] = []
    for row in assigned_rows:
        entry = entries_by_id[int(row["pid"])]
        decoded = entry.decode_payload(file_data)
        patched_payload, patch_meta = _patch_variable_payload(decoded, int(entry.payload_offset), row)
        row_with_patch = {**row, "variable_name_patch": patch_meta}
        patched_rows.append(row_with_patch)
        stages.append(
            (
                int(entry.payload_offset),
                _IndexedRawStageRecord(
                    raw_payload=patched_payload,
                    container_offset=int(entry.payload_offset),
                    container_length=int(entry.payload_length),
                ),
            )
        )

    backup_path = None
    if stages and not args.dry_run:
        backup_path = write_player_staged_records(str(player_file), stages, create_backup_before_write=True)

    post_file_data = player_file.read_bytes()
    post_indexed = IndexedFDIFile.from_bytes(post_file_data)
    post_entries_by_id = {int(entry.record_id): entry for entry in post_indexed.entries}
    readback_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for row in patched_rows:
        entry = post_entries_by_id.get(int(row["pid"]))
        if entry is None:
            failures.append({**row, "failure": "missing_post_entry"})
            continue
        decoded = entry.decode_payload(post_file_data)
        parsed = PlayerRecord.from_bytes(decoded, int(entry.payload_offset))
        applied_name = " ".join(_player_display_name(parsed).split())
        anchor = PlayerRecord._find_indexed_suffix_anchor(decoded, applied_name)
        fields = _read_anchor_fields(decoded, int(anchor)) if anchor is not None else {}
        ok = (
            _norm(applied_name) == _norm(str(row["game_name"]))
            and int(getattr(parsed, "position_primary", -1)) == int(row["pm99_position_code"])
            and int(getattr(parsed, "nationality", -1)) == int(row["pm99_nat_code"])
            and int(getattr(parsed, "birth_day", -1)) == int(row["birth_day"])
            and int(getattr(parsed, "birth_month", -1)) == int(row["birth_month"])
            and int(getattr(parsed, "birth_year", -1)) == int(row["birth_year"])
            and int(getattr(parsed, "height", -1)) == int(row["height_cm"])
            and int(getattr(parsed, "weight", -1)) == int(row["weight_kg"])
        )
        readback = {
            "slot": int(row["slot"]),
            "pid": int(row["pid"]),
            "old_player_name": str(row["old_player_name"]),
            "old_position_label": str(row["old_position_label"]),
            "target_name": str(row["game_name"]),
            "applied_name": applied_name,
            "post_payload_offset": int(entry.payload_offset),
            "post_payload_length": int(entry.payload_length),
            "post_anchor": anchor,
            "parsed_position_code": int(getattr(parsed, "position_primary", -1)),
            "parsed_nationality_code": int(getattr(parsed, "nationality", -1)),
            "parsed_birth_day": int(getattr(parsed, "birth_day", -1)),
            "parsed_birth_month": int(getattr(parsed, "birth_month", -1)),
            "parsed_birth_year": int(getattr(parsed, "birth_year", -1)),
            "parsed_height_cm": int(getattr(parsed, "height", -1)),
            "parsed_weight_kg": int(getattr(parsed, "weight", -1) or -1),
            "anchor_fields": fields,
            "ok": bool(ok),
        }
        readback_rows.append(readback)
        if not ok:
            failures.append(readback)

    assignment_json = output_dir / "stoke_2015_variable_name_assignments.json"
    assignment_csv = output_dir / "stoke_2015_variable_name_assignments.csv"
    readback_json = output_dir / "stoke_2015_variable_name_readback.json"
    manifest_path = output_dir / "stoke_2015_variable_name_manifest.json"
    assignment_json.write_text(json.dumps(patched_rows, indent=2), encoding="utf-8")
    _write_csv(assignment_csv, patched_rows)
    readback_json.write_text(json.dumps(readback_rows, indent=2), encoding="utf-8")

    manifest = {
        "schema": "pm99-stoke-2015-variable-name-runtime-proof-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "base_game": str(base_game),
        "out_game": str(out_game),
        "dbdat": str(dbdat),
        "team_file": str(team_file),
        "player_file": str(player_file),
        "coach_file": str(coach_file),
        "textos_pkf": str(textos_pkf),
        "team_query": str(args.team_query),
        "dry_run": bool(args.dry_run),
        "backup_path": str(backup_path) if backup_path else None,
        "row_count": len(patched_rows),
        "readback_count": len(readback_rows),
        "failure_count": len(failures),
        "ok": not failures,
        "role_target_names": TARGET_NAMES_BY_ROLE,
        "dropped_from_fixed_name_twenty": ["Peter Odemwingie"],
        "added_for_role_parity": ["Shay Given"],
        "source_urls": {**SOURCE_URLS, "football_squads_stoke_2015_16": SOURCE_URL},
        "input_hashes_after_write": {
            "EQ98030.FDI": sha256(team_file),
            "JUG98030.FDI": sha256(player_file),
            "ENT98030.FDI": sha256(coach_file),
            "TEXTOS.PKF": sha256(textos_pkf),
        },
        "assignment_json": str(assignment_json),
        "assignment_csv": str(assignment_csv),
        "readback_json": str(readback_json),
        "failures": failures,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"ok": manifest["ok"], "out_game": str(out_game), "manifest": str(manifest_path)}, indent=2))
    return 0 if manifest["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
