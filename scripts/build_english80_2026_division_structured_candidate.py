#!/usr/bin/env python3
"""Build an English 80 candidate with explicit 20-club PM99 division blocks."""

from __future__ import annotations

import argparse
import json
import os
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
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from build_english80_2026_football_squads import (  # noqa: E402
    ClubSource,
    DEFAULT_BASE_GAME,
    _json_dump,
    _make_tree_user_writable,
    apply_semantic_patch,
    cap_target_rosters_to_twenty,
)
from build_pm99_repointed_roster_candidate import build_repointed_candidate  # noqa: E402
from patch_english80_division_kits import patch_english80_division_kits  # noqa: E402


DEFAULT_PREVIOUS_BUILD = (
    REPO_ROOT
    / "work"
    / "pm99"
    / "english80_2026_football_squads"
    / "english80_2026_football_squads_20260501T072310Z"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "work" / "pm99" / "english80_2026_division_structured"
DEFAULT_KIT_MANIFEST = REPO_ROOT / "work" / "parallel_recheck" / "team_kits" / "kit_manifest.json"

DIVISION_BLOCKS = [
    {"division_name": "Premier League", "division_select_x": 78, "division_select_y": 302, "source_slice": [0, 20]},
    {"division_name": "First Division", "division_select_x": 78, "division_select_y": 338, "source_slice": [20, 40]},
    {"division_name": "Second Division", "division_select_x": 562, "division_select_y": 302, "source_slice": [40, 60]},
    {"division_name": "Third Division", "division_select_x": 562, "division_select_y": 338, "source_slice": [60, 80]},
]

FIRST_DIVISION_CARRIER_SWAPS: list[tuple[str, str]] = []

SELECTOR_OVERRIDES = {
    "stoke_city": {"team_select_x": 436, "team_select_y": 360},
}

TEAM_NAME_ALIASES = {
    "Aston Villa": "Aston Villa",
    "Bournemouth": "Bournemouth",
    "Brighton & Hove Albion": "Brighton",
    "Crystal Palace": "Crystal Palace",
    "Manchester City": "Man City",
    "Manchester United": "Man Utd",
    "Newcastle United": "Newcastle",
    "Nottingham Forest": "Nottm Forest",
    "Tottenham Hotspur": "Tottenham",
    "West Ham United": "West Ham",
    "Wolverhampton Wanderers": "Wolves",
    "Birmingham City": "Birmingham C.",
    "Blackburn Rovers": "Blackburn R.",
    "Charlton Athletic": "Charlton",
    "Coventry City": "Coventry",
    "Derby County": "Derby County",
    "Hull City": "Hull City",
    "Ipswich Town": "Ipswich",
    "Leicester City": "Leicester",
    "Norwich City": "Norwich",
    "Oxford United": "Oxford Utd",
    "Preston North End": "Preston NE",
    "Queens Park Rangers": "QPR",
    "Sheffield United": "Sheffield Utd",
    "Sheffield Wednesday": "Sheff Wed",
    "Southampton": "Southampton",
    "Stoke City": "Stoke City",
    "West Bromwich Albion": "West Brom",
    "AFC Wimbledon": "AFC W.",
    "Bolton Wanderers": "Bolton",
    "Bradford City": "Bradford",
    "Burton Albion": "Burton",
    "Cardiff City": "Cardiff",
    "Doncaster Rovers": "Doncaster",
    "Exeter City": "Exeter",
    "Huddersfield Town": "Huddersfield",
    "Leyton Orient": "Leyton Orient",
    "Lincoln City": "Lincoln",
    "Luton Town": "Luton",
    "Mansfield Town": "Mansfield",
    "Northampton Town": "Northampton",
    "Peterborough United": "Peterborough",
    "Plymouth Argyle": "Plymouth",
    "Port Vale": "Port Vale",
    "Rotherham United": "Rotherham",
    "Stockport County": "Stockport",
    "Wigan Athletic": "Wigan",
    "Wycombe Wanderers": "Wycombe",
    "Accrington Stanley": "Accrington",
    "Bristol Rovers": "Bristol Rov.",
    "Cambridge United": "Cambridge",
    "Cheltenham Town": "Cheltenham",
    "Colchester United": "Colchester",
    "Crawley Town": "Crawley",
    "Crewe Alexandra": "Crewe Alex.",
    "Fleetwood Town": "Fleetwood",
}


def _norm(value: str) -> str:
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())


def _short_team_name(display_name: str) -> str:
    if display_name in TEAM_NAME_ALIASES:
        return TEAM_NAME_ALIASES[display_name]
    text = " ".join(str(display_name or "").replace("&", "and").split())
    if len(text) <= 14:
        return text
    return text[:14].rstrip(" .")


def _fit_team_name(display_name: str, max_len: int) -> str:
    candidates = [
        _short_team_name(display_name),
        " ".join(str(display_name or "").split()),
    ]
    for candidate in candidates:
        if len(candidate.encode("cp1252", errors="replace")) <= max_len:
            return candidate
    if display_name == "AFC Wimbledon" and max_len >= 6:
        return "AFC W."
    encoded = candidates[0].encode("cp1252", errors="replace")[:max_len]
    return encoded.decode("cp1252", errors="ignore").rstrip(" .") or candidates[0][:max_len]


def _read_xor_string_span(raw_payload: bytes, cursor: int) -> tuple[str, int, int, int]:
    if cursor + 2 > len(raw_payload):
        raise ValueError("truncated linked team string length")
    size = int.from_bytes(raw_payload[cursor : cursor + 2], "little")
    start = cursor + 2
    end = start + size
    if end > len(raw_payload):
        raise ValueError("truncated linked team string payload")
    decoded = bytes(byte ^ 0x61 for byte in raw_payload[start:end])
    text = decoded.decode("cp1252", errors="replace").rstrip("\x00")
    return text, start, end, end


def _write_xor_string_fixed(raw_payload: bytearray, start: int, end: int, value: str) -> str:
    capacity = end - start
    encoded_value = str(value or "").encode("cp1252", errors="replace")
    if len(encoded_value) > capacity:
        encoded_value = encoded_value[:capacity].rstrip(b" .")
    padded = encoded_value + (b"\x00" * (capacity - len(encoded_value)))
    raw_payload[start:end] = bytes(byte ^ 0x61 for byte in padded)
    return encoded_value.decode("cp1252", errors="replace")


def _patch_linked_visible_names(game_root: Path, assignment: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    team_file = game_root / "DBDAT" / "EQ98030.FDI"
    team_bytes = bytearray(team_file.read_bytes())
    indexed = IndexedFDIFile.from_path(team_file)
    entries_by_id = {int(entry.record_id): entry for entry in indexed.entries}
    events: list[dict[str, Any]] = []

    for item in sorted(assignment["assignments"], key=lambda row: int(row["carrier_eq_record_id"])):
        entry = entries_by_id[int(item["carrier_eq_record_id"])]
        payload_start = int(entry.payload_offset)
        payload_end = payload_start + int(entry.payload_length)
        payload = bytearray(team_bytes[payload_start:payload_end])
        record_size = int.from_bytes(payload[0x26:0x28], "little")

        cursor = 0x2A
        old_short, short_start, short_end, cursor = _read_xor_string_span(payload, cursor)
        old_stadium, _stadium_start, _stadium_end, cursor = _read_xor_string_span(payload, cursor)
        cursor += 1
        if record_size > 0x20C:
            cursor += 1
        old_full, _full_start, _full_end, _cursor = _read_xor_string_span(payload, cursor)

        short_name = _fit_team_name(str(item["target_display_name"]), short_end - short_start)
        written_short = _write_xor_string_fixed(payload, short_start, short_end, short_name)
        team_bytes[payload_start:payload_end] = payload

        events.append(
            {
                "target_club_key": item["target_club_key"],
                "target_display_name": item["target_display_name"],
                "carrier_eq_record_id": int(item["carrier_eq_record_id"]),
                "old_short_name": old_short,
                "new_short_name": written_short,
                "old_full_club_name": old_full,
                "new_full_club_name": old_full,
                "stadium_name": old_stadium,
                "short_capacity": short_end - short_start,
            }
        )

    team_file.write_bytes(bytes(team_bytes))
    manifest = {
        "schema": "pm99-english80-linked-visible-team-names-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "game_root": str(game_root),
        "team_file": str(team_file),
        "event_count": len(events),
        "events": events,
    }
    _json_dump(output_dir / "division_structured_linked_visible_team_names_manifest.json", manifest)
    return manifest


def _load_sources(path: Path) -> list[ClubSource]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: list[ClubSource] = []
    for club in payload["clubs"]:
        out.append(
            ClubSource(
                club_key=str(club["club_key"]),
                display_name=str(club["display_name"]),
                league_key=str(club["league_key"]),
                league_name=str(club["league_name"]),
                league_index=int(club["league_index"]),
                source_url=str(club["source_url"]),
                players=list(club["players"]),
            )
        )
    if len(out) != 80:
        raise RuntimeError(f"Expected 80 source clubs, got {len(out)}")
    return out


def _carrier_slots(previous_assignment: dict[str, Any]) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for item in previous_assignment["assignments"]:
        selector = item["selector"]
        slots.append(
            {
                "carrier_club_key": item["carrier_club_key"],
                "carrier_eq_record_id": int(item["carrier_eq_record_id"]),
                "carrier_team_query": item["carrier_team_query"],
                "selector": dict(selector),
                "roster": list(item["roster"]),
            }
        )
    return slots


def _pick_carriers_for_block(targets: list[ClubSource], carriers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unused = list(carriers)
    picked: list[dict[str, Any] | None] = [None] * len(targets)
    for index, target in enumerate(targets):
        target_norm = _norm(target.display_name).replace("city", "")
        for carrier in unused:
            carrier_norm = _norm(carrier["carrier_team_query"]).replace("city", "")
            if target_norm and (target_norm == carrier_norm or target_norm in carrier_norm or carrier_norm in target_norm):
                picked[index] = carrier
                unused.remove(carrier)
                break
    for index, value in enumerate(picked):
        if value is None:
            picked[index] = unused.pop(0)
    out = [dict(item) for item in picked if item is not None]
    target_index = {target.club_key: index for index, target in enumerate(targets)}
    for left_key, right_key in FIRST_DIVISION_CARRIER_SWAPS:
        left_index = target_index.get(left_key)
        right_index = target_index.get(right_key)
        if left_index is not None and right_index is not None:
            out[left_index], out[right_index] = out[right_index], out[left_index]
    return out


def build_structured_assignment(previous_assignment: dict[str, Any], sources: list[ClubSource]) -> dict[str, Any]:
    carriers = _carrier_slots(previous_assignment)
    assignments: list[dict[str, Any]] = []
    division_summary: list[dict[str, Any]] = []
    for block in DIVISION_BLOCKS:
        start, end = block["source_slice"]
        targets = sources[start:end]
        block_carriers = [
            carrier
            for carrier in carriers
            if int(carrier["selector"]["division_select_x"]) == int(block["division_select_x"])
            and int(carrier["selector"]["division_select_y"]) == int(block["division_select_y"])
        ]
        if len(block_carriers) != 20:
            raise RuntimeError(f"{block['division_name']} has {len(block_carriers)} carriers, expected 20")
        block_carriers.sort(
            key=lambda carrier: (
                int(carrier["selector"]["team_select_y"]),
                int(carrier["selector"]["team_select_x"]),
            )
        )
        chosen_carriers = _pick_carriers_for_block(targets, block_carriers)
        for target, carrier in zip(targets, chosen_carriers, strict=True):
            selector = dict(carrier["selector"])
            selector.update(SELECTOR_OVERRIDES.get(target.club_key, {}))
            carrier_rows = {int(row.get("slot") or 0): dict(row) for row in carrier["roster"]}
            roster: list[dict[str, Any]] = []
            for player in sorted(target.players, key=lambda row: int(row["slot"])):
                slot = int(player["slot"])
                row = carrier_rows.get(slot, {})
                roster.append(
                    {
                        **row,
                        "slot": slot,
                        "target_name": str(player["runtime_safe_name"]),
                        "applied_name": str(player["runtime_safe_name"]),
                        "source_target_name": str(player["source_name"]),
                        "source_number": int(player["source_number"]),
                        "source_nat_abbr": str(player["source_nat_abbr"]),
                        "source_position": str(player["source_position"]),
                        "source_url": target.source_url,
                    }
                )
            assignments.append(
                {
                    "slot": len(assignments) + 1,
                    "target_club_key": target.club_key,
                    "target_display_name": target.display_name,
                    "target_league": target.league_name,
                    "target_pm99_division": block["division_name"],
                    "source_league": target.league_name,
                    "source_url": target.source_url,
                    "carrier_club_key": carrier["carrier_club_key"],
                    "carrier_eq_record_id": int(carrier["carrier_eq_record_id"]),
                    "carrier_team_query": carrier["carrier_team_query"],
                    "compile_team_query": carrier["carrier_team_query"],
                    "selector": selector,
                    "roster": roster,
                    "skipped_target_names": [],
                    "source_skipped_target_names": [],
                }
            )
            division_summary.append(
                {
                    "target_club_key": target.club_key,
                    "target_display_name": target.display_name,
                    "target_league": target.league_name,
                    "target_pm99_division": block["division_name"],
                    "carrier_team_query": carrier["carrier_team_query"],
                    "carrier_eq_record_id": int(carrier["carrier_eq_record_id"]),
                    "selector": selector,
                }
            )
    return {
        "schema": "pm99-english80-division-structured-assignment-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "division_policy": {
            "premier": "source slots 1-20",
            "division_1": "source slots 21-40",
            "division_2": "source slots 41-60",
            "division_3": "source slots 61-80",
        },
        "assignments": assignments,
        "division_summary": division_summary,
    }


def build_world(previous_world: dict[str, Any], assignment: dict[str, Any]) -> dict[str, Any]:
    assignment_by_key = {item["target_club_key"]: item for item in assignment["assignments"]}
    world = json.loads(json.dumps(previous_world))
    world["schema"] = "pm99-english80-division-structured-world-v1"
    world["generated_at"] = datetime.now(UTC).isoformat()
    world["division_policy"] = assignment["division_policy"]
    for club in world["clubs"]:
        row = assignment_by_key.get(club["club_key"])
        if row is None:
            continue
        selector = row["selector"]
        club["target_pm99_division"] = row["target_pm99_division"]
        club["team_query"] = _short_team_name(str(row["target_display_name"]))
        club["selector_discovery_team_query"] = row["carrier_team_query"]
        club["division_select_x"] = int(selector["division_select_x"])
        club["division_select_y"] = int(selector["division_select_y"])
        club["team_select_x"] = int(selector["team_select_x"])
        club["team_select_y"] = int(selector["team_select_y"])
    return world


def apply_team_names(game_root: Path, assignment: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    team_file = game_root / "DBDAT" / "EQ98030.FDI"
    indexed = IndexedFDIFile.from_path(team_file)
    entries_by_id = {int(entry.record_id): entry for entry in indexed.entries}
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{EDITOR_ROOT}:{REPO_ROOT}:{env.get('PYTHONPATH', '')}"
    events: list[dict[str, Any]] = []
    for item in sorted(assignment["assignments"], key=lambda row: int(row["carrier_eq_record_id"]), reverse=True):
        entry = entries_by_id[int(item["carrier_eq_record_id"])]
        target_name = _short_team_name(str(item["target_display_name"]))
        command = [
            sys.executable,
            "-m",
            "app.cli",
            "team-edit",
            str(team_file),
            "--offset",
            str(int(entry.payload_offset)),
            "--include-uncertain",
            "--set-name",
            target_name,
            "--json",
        ]
        proc = subprocess.run(command, cwd=str(EDITOR_ROOT), env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            raise RuntimeError(f"team-edit failed for {item['target_display_name']}: {proc.stderr or proc.stdout}")
        events.append(
            {
                "target_club_key": item["target_club_key"],
                "target_display_name": item["target_display_name"],
                "visible_team_name": target_name,
                "carrier_eq_record_id": int(item["carrier_eq_record_id"]),
                "team_offset": int(entry.payload_offset),
            }
        )
    manifest = {
        "schema": "pm99-english80-division-structured-team-names-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "game_root": str(game_root),
        "team_file": str(team_file),
        "event_count": len(events),
        "events": events,
    }
    _json_dump(output_dir / "division_structured_team_names_manifest.json", manifest)
    return manifest


def build(args: argparse.Namespace) -> dict[str, Any]:
    previous_build = Path(args.previous_build).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else (
        Path(args.output_root).expanduser().resolve()
        / f"english80_2026_division_structured_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    )
    if output_dir.exists():
        if not args.force:
            raise FileExistsError(output_dir)
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    sources = _load_sources(previous_build / "football_squads_source_ledger.json")
    previous_assignment = json.loads((previous_build / "slot_assignment_english80_2026_football_squads.json").read_text(encoding="utf-8"))
    previous_world = json.loads((previous_build / "world_english80_2026_football_squads.json").read_text(encoding="utf-8"))

    assignment = build_structured_assignment(previous_assignment, sources)
    assignment_path = output_dir / "slot_assignment_english80_2026_division_structured.json"
    world_path = output_dir / "world_english80_2026_division_structured.json"
    source_path = output_dir / "football_squads_source_ledger.json"
    _json_dump(assignment_path, assignment)
    _json_dump(world_path, build_world(previous_world, assignment))
    shutil.copy2(previous_build / "football_squads_source_ledger.json", source_path)

    base_game = Path(args.base_game).expanduser().resolve()
    writable_base_game = output_dir / "base_game_writable"
    shutil.copytree(base_game, writable_base_game, symlinks=True)
    _make_tree_user_writable(writable_base_game)
    game_root = output_dir / "game"
    repointed = build_repointed_candidate(
        base_game=writable_base_game,
        assignment_path=assignment_path,
        out_game=game_root,
        force=True,
    )
    roster_cap = cap_target_rosters_to_twenty(game_root, assignment_path, output_dir)
    semantic = apply_semantic_patch(game_root, sources, output_dir)
    team_names = apply_team_names(game_root, assignment, output_dir)
    linked_visible_names = _patch_linked_visible_names(game_root, assignment, output_dir)
    kit_patch = patch_english80_division_kits(
        game_root=game_root,
        assignment_path=assignment_path,
        output_dir=output_dir / "kit_patch",
        kit_manifest_path=Path(args.kit_manifest).expanduser().resolve(),
    )

    manifest = {
        "schema": "pm99-english80-division-structured-build-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "ok": bool(repointed["ok"]) and bool(semantic["readback_ok"]) and bool(kit_patch["ok"]),
        "output_dir": str(output_dir),
        "game_root": str(game_root),
        "assignment": str(assignment_path),
        "world_state": str(world_path),
        "source_ledger": str(source_path),
        "repointed_manifest": str(game_root / "repointed_roster_manifest.json"),
        "semantic_manifest": str(output_dir / "english80_semantic_manifest.json"),
        "roster_cap_manifest": str(output_dir / "english80_roster_count_cap_manifest.json"),
        "team_names_manifest": str(output_dir / "division_structured_team_names_manifest.json"),
        "linked_visible_team_names_manifest": str(output_dir / "division_structured_linked_visible_team_names_manifest.json"),
        "kit_patch_manifest": str(output_dir / "kit_patch" / "english80_division_kit_patch_summary.json"),
        "kit_patch_contact_sheet": str(output_dir / "kit_patch" / "english80_division_kit_contact_sheet.png"),
        "club_count": len(sources),
        "allocation_count": int(repointed["allocation_count"]),
        "semantic_readback_ok": bool(semantic["readback_ok"]),
        "roster_cap_count": int(roster_cap["capped_count"]),
        "team_name_count": int(team_names["event_count"]),
        "linked_visible_team_name_count": int(linked_visible_names["event_count"]),
        "kit_patch_ok": bool(kit_patch["ok"]),
        "kit_patch_status_counts": dict(kit_patch["status_counts"]),
    }
    _json_dump(output_dir / "division_structured_build_manifest.json", manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-build", default=str(DEFAULT_PREVIOUS_BUILD))
    parser.add_argument("--base-game", default=str(DEFAULT_BASE_GAME))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--kit-manifest", default=str(DEFAULT_KIT_MANIFEST))
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    manifest = build(parse_args())
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if manifest["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
