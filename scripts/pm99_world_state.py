#!/usr/bin/env python3
"""Canonical full-DB world-state compile/apply/report helpers for PM99RE.

This module keeps the first implementation on top of released editor surfaces:
- player-batch-edit
- team-roster-batch-edit
- team-edit
- validate-database
- game-ready-audit

Division placement is modelled as an explicit coverage family, but currently
fails closed when the requested placement differs from the baseline because the
editor does not yet expose a released write surface for competition bytes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
EDITOR_ROOT = REPO_ROOT / "upstream" / "pm99-skezmod-db-editor"
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from assert_pm99_isolated_input import core_file_hashes, resolve_game_root, sha256  # noqa: E402
from app.editor_helpers import team_query_matches  # noqa: E402
from app.eq_jug_linked import EQLinkedTeamRoster, load_eq_linked_team_rosters  # noqa: E402
from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from app.loaders import load_teams  # noqa: E402
from app.models import PlayerRecord  # noqa: E402

SCHEMA_ID = "pm99-world-state-v1"
SELECTOR_MAP_SCHEMA_ID = "pm99-club-selector-map-v1"
SELECTOR_KEYS = ("team_select_x", "team_select_y", "division_select_x", "division_select_y")
DIVISION_INDEX_KEYS = ("division_menu_index", "division_index", "selector_division_index")
TEAM_INDEX_KEYS = ("team_menu_index", "team_index", "selector_team_index")
COVERAGE_FAMILIES = (
    "club_identity",
    "player_identity",
    "squad_membership",
    "division_placement",
)


@dataclass(frozen=True)
class CompileBlocker:
    code: str
    severity: str
    family: str
    entity_kind: str
    entity_key: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CoverageVerdict:
    family: str
    status: str
    ok: bool
    message: str
    counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedClub:
    club_key: str
    team_query: str
    team_name: str
    full_club_name: str
    team_id: int | None
    team_offset: int
    league: str
    country: str
    eq_record_id: int | None
    linked_source_available: bool


@dataclass(frozen=True)
class ResolvedPlayer:
    player_key: str
    input_name: str
    record_id: int
    payload_offset: int
    current_name: str
    team_id: int | None


@dataclass(frozen=True)
class PlanBundle:
    payload: dict[str, Any]
    output_dir: Path
    world_plan_path: Path
    player_csv_path: Path | None
    roster_csv_path: Path | None
    team_edit_json_path: Path | None


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split()).casefold()


def _loose_lookup_key(value: Any) -> str:
    text = _normalize_text(value)
    out = []
    last_space = False
    for ch in text:
        if ch.isalnum():
            out.append(ch)
            last_space = False
        elif not last_space:
            out.append(" ")
            last_space = True
    return " ".join("".join(out).split())


def _fallback_linked_roster_match(
    linked_rosters: list[EQLinkedTeamRoster],
    *,
    team_query: str,
    team_name: str,
    full_club_name: str,
) -> EQLinkedTeamRoster | None:
    """
    Recover linked roster identity when the EQ parser exposes concatenated text.

    Some legacy EQ rows parse as strings like "BuryhaGigg Lane": enough to
    resolve the club row uniquely, but not enough for a normal linked-roster
    query match. Only accept a prefix fallback when it identifies exactly one
    linked roster, so broad aliases like "Bury" do not accidentally select
    Shrewsbury.
    """
    haystacks = [_loose_lookup_key(team_query), _loose_lookup_key(team_name), _loose_lookup_key(full_club_name)]
    candidates: dict[int, EQLinkedTeamRoster] = {}
    for roster in linked_rosters:
        roster_keys = [_loose_lookup_key(roster.short_name), _loose_lookup_key(roster.full_club_name)]
        for haystack in haystacks:
            if not haystack:
                continue
            for key in roster_keys:
                if key and haystack.startswith(key):
                    candidates[int(roster.eq_record_id)] = roster
    if len(candidates) == 1:
        return next(iter(candidates.values()))
    return None


def _display_player_name(record: PlayerRecord) -> str:
    name = str(getattr(record, "name", "") or "").strip()
    if not name:
        given = str(getattr(record, "given_name", "") or "").strip()
        surname = str(getattr(record, "surname", "") or "").strip()
        name = " ".join(part for part in (given, surname) if part).strip()
    return " ".join(name.split())


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_dump(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _require_mapping(mapping: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(mapping, dict):
        raise ValueError(f"{label} must be an object")
    return dict(mapping)


def _require_list(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{key} must be an array")
    return list(value)


def _optional_int(mapping: dict[str, Any], key: str) -> int | None:
    value = mapping.get(key)
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError(f"{key} must be an integer, not boolean")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc


def _first_optional_int(mapping: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        if key in mapping and mapping.get(key) not in (None, ""):
            return _optional_int(mapping, key)
    return None


def _proof_selector_from_club_row(item: dict[str, Any]) -> dict[str, int | None]:
    nested = item.get("proof_selector") or item.get("runtime_selector") or {}
    nested = _require_mapping(nested, label="proof selector") if nested else {}
    merged = {**nested, **{key: item[key] for key in item if key in SELECTOR_KEYS}}
    return {
        "team_select_x": _optional_int(merged, "team_select_x"),
        "team_select_y": _optional_int(merged, "team_select_y"),
        "division_select_x": _optional_int(merged, "division_select_x"),
        "division_select_y": _optional_int(merged, "division_select_y"),
    }


def _default_runtime_routes(item: dict[str, Any]) -> list[str]:
    routes = item.get("runtime_routes")
    if routes is None:
        return ["squad", "line_up", "tactics", "results", "league_tables", "fixtures"]
    if not isinstance(routes, list) or not all(isinstance(route, str) and route.strip() for route in routes):
        raise ValueError("runtime_routes must be an array of non-empty strings")
    return [route.strip() for route in routes]


def load_selector_map(path: str | Path) -> dict[str, Any]:
    source_path = Path(path).expanduser().resolve()
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    payload = _require_mapping(payload, label="selector map")
    schema = str(payload.get("schema") or payload.get("schema_id") or "").strip()
    if schema != SELECTOR_MAP_SCHEMA_ID:
        raise ValueError(f"Unsupported selector-map schema {schema!r}; expected {SELECTOR_MAP_SCHEMA_ID}")
    selectors = _require_list(payload, "selectors")
    normalized_selectors = []
    seen_keys: set[str] = set()
    for row in selectors:
        item = _require_mapping(row, label="selector row")
        club_key = str(item.get("club_key") or "").strip()
        team_query = str(item.get("team_query") or item.get("team_name") or item.get("set_name") or "").strip()
        if not club_key and not team_query:
            raise ValueError("Every selector row must define club_key or team_query")
        selector_key = club_key or f"query:{_normalize_text(team_query)}"
        if selector_key in seen_keys:
            raise ValueError(f"Duplicate selector row {selector_key!r}")
        seen_keys.add(selector_key)
        selector = _proof_selector_from_club_row(item)
        missing = [key for key, value in selector.items() if value is None]
        if missing:
            raise ValueError(f"Selector row {selector_key!r} is missing {', '.join(missing)}")
        _default_runtime_routes(item)
        normalized_selectors.append(item)
    payload["selectors"] = normalized_selectors
    payload["source_path"] = str(source_path)
    payload["source_sha256"] = sha256(source_path)
    return payload


def _load_selector_rows_lenient(path: str | Path | None) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if path is None:
        return [], None
    source_path = Path(path).expanduser().resolve()
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    payload = _require_mapping(payload, label="selector map")
    schema = str(payload.get("schema") or payload.get("schema_id") or "").strip()
    if schema != SELECTOR_MAP_SCHEMA_ID:
        raise ValueError(f"Unsupported selector-map schema {schema!r}; expected {SELECTOR_MAP_SCHEMA_ID}")
    rows = [_require_mapping(row, label="selector row") for row in _require_list(payload, "selectors")]
    return rows, {"path": str(source_path), "sha256": sha256(source_path)}


def _selector_row_key_maps(rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_club_key: dict[str, dict[str, Any]] = {}
    by_query: dict[str, dict[str, Any]] = {}
    for row in rows:
        club_key = str(row.get("club_key") or "").strip()
        team_query = str(row.get("team_query") or row.get("team_name") or row.get("set_name") or "").strip()
        if club_key:
            by_club_key[club_key] = row
        if team_query:
            by_query[_normalize_text(team_query)] = row
    return by_club_key, by_query


def build_selector_scaffold(world_path: str | Path, selector_map_path: str | Path | None = None) -> dict[str, Any]:
    world = load_world_state(world_path)
    existing_rows, selector_map_source = _load_selector_rows_lenient(selector_map_path)
    by_club_key, by_query = _selector_row_key_maps(existing_rows)
    selectors: list[dict[str, Any]] = []
    for row in world["clubs"]:
        club = _require_mapping(row, label="club row")
        club_key = str(club.get("club_key") or "").strip()
        team_query = str(club.get("team_query") or club.get("team_name") or club.get("set_name") or club_key).strip()
        existing = by_club_key.get(club_key) or by_query.get(_normalize_text(team_query)) or {}
        merged = {**existing, **{key: club[key] for key in club if key in SELECTOR_KEYS or key == "runtime_routes"}}
        selector = _proof_selector_from_club_row(merged)
        missing = [key for key, value in selector.items() if value is None]
        selector_row: dict[str, Any] = {
            "club_key": club_key,
            "team_query": team_query,
            **selector,
            "runtime_routes": _default_runtime_routes(merged if "runtime_routes" in merged else club),
            "status": "blocked_missing_selector" if missing else "ready",
            "missing": missing,
        }
        selectors.append(selector_row)
    blocked = [row for row in selectors if row["status"] != "ready"]
    return {
        "schema": SELECTOR_MAP_SCHEMA_ID,
        "scaffold": True,
        "world_state_source": {
            "path": world["source_path"],
            "sha256": world["source_sha256"],
        },
        "selector_map_source": selector_map_source,
        "counts": {
            "clubs": len(selectors),
            "ready": len(selectors) - len(blocked),
            "blocked": len(blocked),
        },
        "selectors": selectors,
        "ok": not blocked,
    }


def build_selector_map_from_layout(
    world_path: str | Path,
    selector_map_path: str | Path | None = None,
    *,
    division_select_x: int = 559,
    division_start_y: int = 302,
    division_step_y: int = 39,
    team_select_x: int = 327,
    team_start_y: int = 356,
    team_step_y: int = 39,
) -> dict[str, Any]:
    world = load_world_state(world_path)
    existing_rows, selector_map_source = _load_selector_rows_lenient(selector_map_path)
    by_club_key, by_query = _selector_row_key_maps(existing_rows)
    selectors: list[dict[str, Any]] = []
    for row in world["clubs"]:
        club = _require_mapping(row, label="club row")
        club_key = str(club.get("club_key") or "").strip()
        team_query = str(club.get("team_query") or club.get("team_name") or club.get("set_name") or club_key).strip()
        existing = by_club_key.get(club_key) or by_query.get(_normalize_text(team_query)) or {}
        merged = {**existing, **{key: club[key] for key in club if key in SELECTOR_KEYS or key == "runtime_routes"}}
        selector = _proof_selector_from_club_row(merged)

        division_index = _first_optional_int(club, DIVISION_INDEX_KEYS)
        team_index = _first_optional_int(club, TEAM_INDEX_KEYS)
        generated = []
        if selector["division_select_x"] is None and division_index is not None:
            selector["division_select_x"] = int(division_select_x)
            generated.append("division_select_x")
        if selector["division_select_y"] is None and division_index is not None:
            selector["division_select_y"] = int(division_start_y + (division_index - 1) * division_step_y)
            generated.append("division_select_y")
        if selector["team_select_x"] is None and team_index is not None:
            selector["team_select_x"] = int(team_select_x)
            generated.append("team_select_x")
        if selector["team_select_y"] is None and team_index is not None:
            selector["team_select_y"] = int(team_start_y + (team_index - 1) * team_step_y)
            generated.append("team_select_y")

        missing = [key for key, value in selector.items() if value is None]
        selectors.append(
            {
                "club_key": club_key,
                "team_query": team_query,
                **selector,
                "runtime_routes": _default_runtime_routes(merged if "runtime_routes" in merged else club),
                "status": "blocked_missing_selector" if missing else "ready",
                "missing": missing,
                "generated_fields": generated,
                "menu_indices": {
                    "division_menu_index": division_index,
                    "team_menu_index": team_index,
                },
            }
        )
    blocked = [row for row in selectors if row["status"] != "ready"]
    return {
        "schema": SELECTOR_MAP_SCHEMA_ID,
        "generated_from_layout": True,
        "world_state_source": {
            "path": world["source_path"],
            "sha256": world["source_sha256"],
        },
        "selector_map_source": selector_map_source,
        "layout": {
            "division_select_x": int(division_select_x),
            "division_start_y": int(division_start_y),
            "division_step_y": int(division_step_y),
            "team_select_x": int(team_select_x),
            "team_start_y": int(team_start_y),
            "team_step_y": int(team_step_y),
        },
        "counts": {
            "clubs": len(selectors),
            "ready": len(selectors) - len(blocked),
            "blocked": len(blocked),
        },
        "selectors": selectors,
        "ok": not blocked,
    }


def apply_selector_map_to_world(world: dict[str, Any], selector_map_path: str | Path | None) -> dict[str, Any]:
    if selector_map_path is None:
        return world
    selector_map = load_selector_map(selector_map_path)
    by_club_key, by_query = _selector_row_key_maps([_require_mapping(row, label="selector row") for row in selector_map["selectors"]])

    merged_world = dict(world)
    merged_clubs: list[dict[str, Any]] = []
    for row in world["clubs"]:
        club = _require_mapping(row, label="club row")
        club_key = str(club.get("club_key") or "").strip()
        team_query = str(club.get("team_query") or club.get("team_name") or club.get("set_name") or club_key).strip()
        selector_row = by_club_key.get(club_key) or by_query.get(_normalize_text(team_query))
        if selector_row is not None:
            for key, value in _proof_selector_from_club_row(selector_row).items():
                if key not in club or club.get(key) in (None, ""):
                    club[key] = value
            if "runtime_routes" not in club and "runtime_routes" in selector_row:
                club["runtime_routes"] = _default_runtime_routes(selector_row)
            club["selector_map_source"] = {
                "path": selector_map["source_path"],
                "sha256": selector_map["source_sha256"],
            }
        merged_clubs.append(club)
    merged_world["clubs"] = merged_clubs
    merged_world["selector_map_source"] = {
        "path": selector_map["source_path"],
        "sha256": selector_map["source_sha256"],
    }
    return merged_world


def build_selector_coverage(world_path: str | Path, selector_map_path: str | Path | None = None) -> dict[str, Any]:
    world = apply_selector_map_to_world(load_world_state(world_path), selector_map_path)
    cases = []
    for row in world["clubs"]:
        item = _require_mapping(row, label="club row")
        club_key = str(item.get("club_key") or "").strip()
        selector = _proof_selector_from_club_row(item)
        missing = [key for key, value in selector.items() if value is None]
        cases.append(
            {
                "club_key": club_key,
                "team_query": str(item.get("team_query") or item.get("team_name") or item.get("set_name") or club_key).strip(),
                "selector": selector,
                "status": "blocked_missing_selector" if missing else "ready",
                "blockers": [f"missing_{key}" for key in missing],
                "routes": _default_runtime_routes(item),
            }
        )
    blocked = [case for case in cases if case["status"] != "ready"]
    return {
        "schema": "pm99-selector-coverage-v1",
        "world_state_source": {
            "path": world["source_path"],
            "sha256": world["source_sha256"],
        },
        "selector_map_source": world.get("selector_map_source"),
        "counts": {
            "clubs": len(cases),
            "ready": len(cases) - len(blocked),
            "blocked": len(blocked),
        },
        "cases": cases,
        "ok": not blocked,
    }


def load_world_state(path: str | Path) -> dict[str, Any]:
    source_path = Path(path).expanduser().resolve()
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    payload = _require_mapping(payload, label="world state")
    schema = str(payload.get("schema") or payload.get("schema_id") or "").strip()
    if schema != SCHEMA_ID:
        raise ValueError(f"Unsupported world-state schema {schema!r}; expected {SCHEMA_ID}")

    clubs = _require_list(payload, "clubs")
    players = _require_list(payload, "players")
    squad_memberships = _require_list(payload, "squad_memberships")
    divisions = _require_list(payload, "divisions")

    club_keys: set[str] = set()
    player_keys: set[str] = set()
    for row in clubs:
        item = _require_mapping(row, label="club row")
        club_key = str(item.get("club_key") or "").strip()
        if not club_key:
            raise ValueError("Every club row must define club_key")
        if club_key in club_keys:
            raise ValueError(f"Duplicate club_key {club_key!r}")
        _proof_selector_from_club_row(item)
        _default_runtime_routes(item)
        club_keys.add(club_key)

    for row in players:
        item = _require_mapping(row, label="player row")
        player_key = str(item.get("player_key") or "").strip()
        if not player_key:
            raise ValueError("Every player row must define player_key")
        if player_key in player_keys:
            raise ValueError(f"Duplicate player_key {player_key!r}")
        player_keys.add(player_key)

    for row in squad_memberships:
        item = _require_mapping(row, label="squad membership row")
        club_key = str(item.get("club_key") or "").strip()
        player_key = str(item.get("player_key") or "").strip()
        slot = item.get("slot")
        if club_key not in club_keys:
            raise ValueError(f"Unknown squad_memberships.club_key {club_key!r}")
        if player_key not in player_keys:
            raise ValueError(f"Unknown squad_memberships.player_key {player_key!r}")
        if not isinstance(slot, int) or slot <= 0:
            raise ValueError(f"Invalid squad slot {slot!r} for club_key={club_key!r}")

    for row in divisions:
        item = _require_mapping(row, label="division row")
        club_key = str(item.get("club_key") or "").strip()
        if club_key not in club_keys:
            raise ValueError(f"Unknown divisions.club_key {club_key!r}")
        if not str(item.get("division") or "").strip():
            raise ValueError(f"Division row for {club_key!r} must include division")

    payload["clubs"] = clubs
    payload["players"] = players
    payload["squad_memberships"] = squad_memberships
    payload["divisions"] = divisions
    payload["source_path"] = str(source_path)
    payload["source_sha256"] = sha256(source_path)
    return payload


def _build_player_index(player_file: Path) -> tuple[dict[int, ResolvedPlayer], dict[str, list[ResolvedPlayer]]]:
    data = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(data)
    by_record_id: dict[int, ResolvedPlayer] = {}
    by_name: dict[str, list[ResolvedPlayer]] = {}
    for entry in indexed.entries:
        payload = data[entry.payload_offset : entry.payload_offset + entry.payload_length]
        try:
            record = PlayerRecord.from_bytes(payload, int(entry.payload_offset))
        except Exception:
            continue
        current_name = _display_player_name(record)
        resolved = ResolvedPlayer(
            player_key="",
            input_name=current_name,
            record_id=int(entry.record_id),
            payload_offset=int(entry.payload_offset),
            current_name=current_name,
            team_id=int(getattr(record, "team_id", 0) or 0),
        )
        by_record_id[resolved.record_id] = resolved
        by_name.setdefault(_normalize_text(current_name), []).append(resolved)
    return by_record_id, by_name


def _resolve_clubs(world: dict[str, Any], team_file: Path, player_file: Path) -> tuple[dict[str, ResolvedClub], list[CompileBlocker]]:
    blockers: list[CompileBlocker] = []
    linked_rosters = load_eq_linked_team_rosters(team_file=str(team_file), player_file=str(player_file))
    parsed_teams = load_teams(str(team_file))

    resolved: dict[str, ResolvedClub] = {}
    for row in world["clubs"]:
        item = _require_mapping(row, label="club row")
        club_key = str(item.get("club_key") or "").strip()
        team_query = str(item.get("team_query") or item.get("team_name") or item.get("set_name") or club_key).strip()
        matches = [
            (offset, team)
            for offset, team in parsed_teams
            if team_query_matches(team_query, team_name=str(getattr(team, "name", "") or ""), full_club_name=str(getattr(team, "full_club_name", "") or ""))
        ]
        if not matches:
            blockers.append(
                CompileBlocker(
                    code="club_query_not_found",
                    severity="error",
                    family="club_identity",
                    entity_kind="club",
                    entity_key=club_key,
                    message=f"No team matched team_query={team_query!r}",
                    details={"team_query": team_query},
                )
            )
            continue
        if len(matches) > 1:
            blockers.append(
                CompileBlocker(
                    code="club_query_ambiguous",
                    severity="error",
                    family="club_identity",
                    entity_kind="club",
                    entity_key=club_key,
                    message=f"Multiple teams matched team_query={team_query!r}",
                    details={
                        "team_query": team_query,
                        "matches": [
                            {"offset": int(offset), "team_name": str(getattr(team, 'name', '') or ''), "team_id": int(getattr(team, 'team_id', 0) or 0)}
                            for offset, team in matches[:10]
                        ],
                    },
                )
            )
            continue
        offset, team = matches[0]
        linked_match = None
        for roster in linked_rosters:
            if team_query_matches(team_query, team_name=roster.short_name, full_club_name=roster.full_club_name):
                linked_match = roster
                break
        if linked_match is None:
            linked_match = _fallback_linked_roster_match(
                linked_rosters,
                team_query=team_query,
                team_name=str(getattr(team, "name", "") or ""),
                full_club_name=str(getattr(team, "full_club_name", "") or ""),
            )
        resolved[club_key] = ResolvedClub(
            club_key=club_key,
            team_query=team_query,
            team_name=str(getattr(team, "name", "") or ""),
            full_club_name=str(getattr(team, "full_club_name", "") or ""),
            team_id=int(getattr(team, "team_id", 0) or 0),
            team_offset=int(offset),
            league=str(getattr(team, "league", "") or ""),
            country=str(getattr(team, "country", "") or ""),
            eq_record_id=(int(linked_match.eq_record_id) if linked_match is not None else None),
            linked_source_available=linked_match is not None,
        )
    return resolved, blockers


def _resolve_players(world: dict[str, Any], player_file: Path) -> tuple[dict[str, ResolvedPlayer], list[CompileBlocker]]:
    blockers: list[CompileBlocker] = []
    by_record_id, by_name = _build_player_index(player_file)
    resolved: dict[str, ResolvedPlayer] = {}

    for row in world["players"]:
        item = _require_mapping(row, label="player row")
        player_key = str(item.get("player_key") or "").strip()
        input_name = str(item.get("name") or item.get("current_name") or "").strip()
        record_id_raw = item.get("record_id")
        chosen: ResolvedPlayer | None = None
        if isinstance(record_id_raw, int):
            chosen = by_record_id.get(int(record_id_raw))
            if chosen is None:
                blockers.append(
                    CompileBlocker(
                        code="player_record_id_not_found",
                        severity="error",
                        family="player_identity",
                        entity_kind="player",
                        entity_key=player_key,
                        message=f"Player record_id={record_id_raw} not found",
                        details={"record_id": int(record_id_raw)},
                    )
                )
                continue
        else:
            candidates = by_name.get(_normalize_text(input_name), [])
            if not candidates:
                blockers.append(
                    CompileBlocker(
                        code="player_name_not_found",
                        severity="error",
                        family="player_identity",
                        entity_kind="player",
                        entity_key=player_key,
                        message=f"Player name {input_name!r} not found",
                        details={"name": input_name},
                    )
                )
                continue
            if len(candidates) > 1:
                blockers.append(
                    CompileBlocker(
                        code="player_name_ambiguous",
                        severity="error",
                        family="player_identity",
                        entity_kind="player",
                        entity_key=player_key,
                        message=f"Player name {input_name!r} is ambiguous",
                        details={
                            "name": input_name,
                            "matches": [
                                {
                                    "record_id": int(candidate.record_id),
                                    "current_name": candidate.current_name,
                                    "team_id": candidate.team_id,
                                }
                                for candidate in candidates[:10]
                            ],
                        },
                    )
                )
                continue
            chosen = candidates[0]
        assert chosen is not None
        resolved[player_key] = ResolvedPlayer(
            player_key=player_key,
            input_name=input_name,
            record_id=int(chosen.record_id),
            payload_offset=int(chosen.payload_offset),
            current_name=str(chosen.current_name),
            team_id=int(chosen.team_id or 0),
        )
    return resolved, blockers


def _build_runtime_proof_cases(
    world: dict[str, Any],
    clubs: dict[str, ResolvedClub],
    division_expectations: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    club_smoke: list[dict[str, Any]] = []
    club_rows_by_key = {
        str(_require_mapping(row, label="club row").get("club_key") or "").strip(): _require_mapping(row, label="club row")
        for row in world["clubs"]
    }
    for club_key, item in club_rows_by_key.items():
        resolved_club = clubs.get(club_key)
        selector = _proof_selector_from_club_row(item)
        missing = [key for key, value in selector.items() if value is None]
        status = "ready"
        blockers: list[str] = []
        if resolved_club is None:
            status = "blocked_unresolved_club"
            blockers.append("club_not_resolved")
        if missing:
            status = "blocked_missing_selector" if status == "ready" else status
            blockers.extend(f"missing_{key}" for key in missing)
        club_smoke.append(
            {
                "case_id": f"club_smoke::{club_key}",
                "club_key": club_key,
                "team_query": resolved_club.team_query if resolved_club is not None else str(item.get("team_query") or item.get("team_name") or item.get("set_name") or "").strip(),
                "team_name": resolved_club.team_name if resolved_club is not None else "",
                "proof_mode": "generic_club_route_capture",
                "routes": _default_runtime_routes(item),
                "selector": selector,
                "status": status,
                "blockers": blockers,
            }
        )

    division_season = []
    for item in division_expectations:
        club_key = str(item.get("club_key") or "").strip()
        club_case = next((case for case in club_smoke if case["club_key"] == club_key), None)
        status = "ready" if club_case is not None and club_case["status"] == "ready" and item.get("matches_baseline") else "blocked"
        blockers = [] if status == "ready" else ["division_not_runtime_ready"]
        division_season.append(
            {
                "case_id": f"division_season::{club_key}",
                "club_key": club_key,
                "team_query": item.get("team_query", ""),
                "division": item.get("target_division", ""),
                "country": item.get("target_country", ""),
                "proof_mode": "generic_club_season_sentinel",
                "selector": dict(club_case.get("selector") or {}) if club_case is not None else {},
                "status": status,
                "blockers": blockers,
            }
        )
    return {
        "club_smoke": club_smoke,
        "division_season": division_season,
        "global_runtime": [
            {
                "case_id": "global_route_capture",
                "proof_mode": "generic_club_route_capture",
                "routes": ["squad", "line_up", "tactics", "results", "league_tables", "fixtures"],
                "status": "ready",
                "blockers": [],
            },
            {
                "case_id": "global_season_sentinel",
                "proof_mode": "generic_club_season_sentinel",
                "status": "ready",
                "blockers": [],
            },
        ],
    }


def compile_world_plan(world_path: str | Path, *, game_root: str | Path, selector_map: str | Path | None = None) -> dict[str, Any]:
    world = apply_selector_map_to_world(load_world_state(world_path), selector_map)
    resolved_game_root = resolve_game_root(game_root, require_writable=False)
    team_file = resolved_game_root / "DBDAT" / "EQ98030.FDI"
    player_file = resolved_game_root / "DBDAT" / "JUG98030.FDI"
    coach_file = resolved_game_root / "DBDAT" / "ENT98030.FDI"

    clubs, club_blockers = _resolve_clubs(world, team_file, player_file)
    players, player_blockers = _resolve_players(world, player_file)
    blockers: list[CompileBlocker] = [*club_blockers, *player_blockers]

    player_batch_rows: list[dict[str, Any]] = []
    roster_batch_rows: list[dict[str, Any]] = []
    team_edits: list[dict[str, Any]] = []
    division_expectations: list[dict[str, Any]] = []

    for row in world["players"]:
        item = _require_mapping(row, label="player row")
        player_key = str(item.get("player_key") or "").strip()
        resolved_player = players.get(player_key)
        if resolved_player is None:
            continue
        new_name = str(item.get("new_name") or "").strip() or None
        position = item.get("position")
        nationality = item.get("nationality")
        birth_day = item.get("dob_day")
        birth_month = item.get("dob_month")
        birth_year = item.get("dob_year")
        height = item.get("height")
        weight = item.get("weight")
        attribute_updates = {f"attr{idx}": item.get(f"attr{idx}") for idx in range(12) if item.get(f"attr{idx}") is not None}
        if not any(value is not None for value in [new_name, position, nationality, birth_day, birth_month, birth_year, height, weight, *attribute_updates.values()]):
            continue
        # record_id+offset is authoritative here. Linked roster labels can be
        # stale or lossy versus the indexed player payload, so avoid using them
        # as a second guard that rejects otherwise-valid offset-targeted edits.
        expected_name = "" if item.get("record_id") is not None else str(item.get("name") or item.get("current_name") or resolved_player.current_name or "").strip()
        row_payload: dict[str, Any] = {
            "name": expected_name,
            "offset": int(resolved_player.payload_offset),
            "new_name": new_name,
            "position": position,
            "nationality": nationality,
            "dob_day": birth_day,
            "dob_month": birth_month,
            "dob_year": birth_year,
            "height": height,
            "weight": weight,
        }
        row_payload.update(attribute_updates)
        player_batch_rows.append(row_payload)

    for row in world["clubs"]:
        item = _require_mapping(row, label="club row")
        club_key = str(item.get("club_key") or "").strip()
        resolved_club = clubs.get(club_key)
        if resolved_club is None:
            continue
        command: dict[str, Any] = {
            "team_query": resolved_club.team_query,
            "team_offset": int(resolved_club.team_offset),
            "current_name": resolved_club.team_name,
            "current_full_club_name": resolved_club.full_club_name,
        }
        changed = False
        for source_key, target_key in (
            ("set_name", "set_name"),
            ("set_full_club_name", "set_full_club_name"),
            ("set_stadium", "set_stadium"),
            ("set_chairman_name", "set_chairman_name"),
            ("set_shirt_sponsor", "set_shirt_sponsor"),
            ("set_kit_supplier", "set_kit_supplier"),
            ("set_starting_finance", "set_starting_finance"),
            ("set_ground_size", "set_ground_size"),
        ):
            value = item.get(source_key)
            if value is None or value == "":
                continue
            command[target_key] = value
            changed = True
        if changed:
            team_edits.append(command)

    for row in world["squad_memberships"]:
        item = _require_mapping(row, label="squad membership row")
        club_key = str(item.get("club_key") or "").strip()
        player_key = str(item.get("player_key") or "").strip()
        resolved_club = clubs.get(club_key)
        resolved_player = players.get(player_key)
        if resolved_club is None or resolved_player is None:
            continue
        source = str(item.get("source") or "linked").strip() or "linked"
        if source != "linked":
            blockers.append(
                CompileBlocker(
                    code="same_entry_roster_world_apply_unreleased",
                    severity="error",
                    family="squad_membership",
                    entity_kind="club",
                    entity_key=club_key,
                    message="World-state roster compiler currently supports parser-backed linked rosters only",
                    details={"club_key": club_key, "source": source},
                )
            )
            continue
        if not resolved_club.linked_source_available or resolved_club.eq_record_id is None:
            blockers.append(
                CompileBlocker(
                    code="linked_roster_source_unavailable",
                    severity="error",
                    family="squad_membership",
                    entity_kind="club",
                    entity_key=club_key,
                    message="Target club does not expose a parser-backed EQ->JUG linked roster",
                    details={"club_key": club_key, "team_query": resolved_club.team_query},
                )
            )
            continue
        roster_batch_rows.append(
            {
                "team": resolved_club.team_query,
                "source": "linked",
                "eq_record_id": int(resolved_club.eq_record_id),
                "team_offset": int(resolved_club.team_offset),
                "slot": int(item["slot"]),
                "player_id": int(resolved_player.record_id),
                "flag": int(item.get("flag") if item.get("flag") is not None else 1),
                "pid": "",
            }
        )

    for row in world["divisions"]:
        item = _require_mapping(row, label="division row")
        club_key = str(item.get("club_key") or "").strip()
        resolved_club = clubs.get(club_key)
        if resolved_club is None:
            continue
        target_division = str(item.get("division") or "").strip()
        target_country = str(item.get("country") or "").strip()
        current_division = str(resolved_club.league or "").strip()
        current_country = str(resolved_club.country or "").strip()
        matches_baseline = (
            (not target_division or _normalize_text(target_division) == _normalize_text(current_division))
            and (not target_country or _normalize_text(target_country) == _normalize_text(current_country))
        )
        expectation = {
            "club_key": club_key,
            "team_query": resolved_club.team_query,
            "current_division": current_division,
            "current_country": current_country,
            "target_division": target_division,
            "target_country": target_country,
            "matches_baseline": matches_baseline,
            "status": "baseline_match" if matches_baseline else "blocked_unreleased_write_surface",
        }
        division_expectations.append(expectation)
        if not matches_baseline:
            blockers.append(
                CompileBlocker(
                    code="division_write_surface_unreleased",
                    severity="error",
                    family="division_placement",
                    entity_kind="club",
                    entity_key=club_key,
                    message=(
                        "Division placement differs from baseline, but competition-byte rewriting remains unreleased"
                    ),
                    details=expectation,
                )
            )

    blocker_payloads = [asdict(item) for item in blockers]
    coverage_counts = {family: {"ready": 0, "blocked": 0, "planned": 0} for family in COVERAGE_FAMILIES}
    coverage_counts["club_identity"]["planned"] = len(world["clubs"])
    coverage_counts["club_identity"]["ready"] = len(clubs)
    coverage_counts["club_identity"]["blocked"] = sum(1 for item in blockers if item.family == "club_identity")
    coverage_counts["player_identity"]["planned"] = len(world["players"])
    coverage_counts["player_identity"]["ready"] = len(players)
    coverage_counts["player_identity"]["blocked"] = sum(1 for item in blockers if item.family == "player_identity")
    coverage_counts["squad_membership"]["planned"] = len(world["squad_memberships"])
    coverage_counts["squad_membership"]["ready"] = len(roster_batch_rows)
    coverage_counts["squad_membership"]["blocked"] = sum(1 for item in blockers if item.family == "squad_membership")
    coverage_counts["division_placement"]["planned"] = len(world["divisions"])
    coverage_counts["division_placement"]["ready"] = sum(1 for item in division_expectations if item["matches_baseline"])
    coverage_counts["division_placement"]["blocked"] = sum(1 for item in blockers if item.family == "division_placement")

    coverage_matrix = []
    for family in COVERAGE_FAMILIES:
        blocked = coverage_counts[family]["blocked"]
        planned = coverage_counts[family]["planned"]
        ready = coverage_counts[family]["ready"]
        ok = blocked == 0
        status = "ready" if ok else "blocked"
        coverage_matrix.append(
            asdict(
                CoverageVerdict(
                    family=family,
                    status=status,
                    ok=ok,
                    message=(
                        f"{ready}/{planned} ready"
                        if ok
                        else f"{blocked} blocker(s) across {planned} planned item(s)"
                    ),
                    counts=coverage_counts[family],
                )
            )
        )
    runtime_proof_cases = _build_runtime_proof_cases(world, clubs, division_expectations)

    return {
        "schema": SCHEMA_ID,
        "world_state_source": {
            "path": world["source_path"],
            "sha256": world["source_sha256"],
        },
        "selector_map_source": world.get("selector_map_source"),
        "baseline": {
            "game_root": str(resolved_game_root),
            "team_file": str(team_file),
            "player_file": str(player_file),
            "coach_file": str(coach_file),
            "core_files": core_file_hashes(resolved_game_root),
        },
        "counts": {
            "clubs": len(world["clubs"]),
            "players": len(world["players"]),
            "squad_memberships": len(world["squad_memberships"]),
            "divisions": len(world["divisions"]),
            "team_edits": len(team_edits),
            "player_batch_rows": len(player_batch_rows),
            "roster_batch_rows": len(roster_batch_rows),
        },
        "resolved": {
            "clubs": [asdict(item) for item in clubs.values()],
            "players": [asdict(item) for item in players.values()],
        },
        "operations": {
            "team_edits": team_edits,
            "player_batch_rows": player_batch_rows,
            "roster_batch_rows": roster_batch_rows,
            "division_expectations": division_expectations,
        },
        "runtime_proof_cases": runtime_proof_cases,
        "coverage_matrix": coverage_matrix,
        "blockers": blocker_payloads,
        "ok": not blocker_payloads,
        "ok_to_apply": not blocker_payloads,
    }


def write_plan_bundle(plan: dict[str, Any], output_dir: str | Path) -> PlanBundle:
    resolved_output_dir = Path(output_dir).expanduser().resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    world_plan_path = resolved_output_dir / "world_plan.json"
    _json_dump(world_plan_path, plan)

    player_csv_path: Path | None = None
    player_rows = list((plan.get("operations") or {}).get("player_batch_rows") or [])
    if player_rows:
        player_csv_path = resolved_output_dir / "player_batch.csv"
        fieldnames = [
            "name", "offset", "new_name", "position", "nationality", "dob_day", "dob_month", "dob_year", "height", "weight",
            *[f"attr{idx}" for idx in range(12)],
        ]
        with player_csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in player_rows:
                writer.writerow({key: row.get(key, "") for key in fieldnames})

    roster_csv_path: Path | None = None
    roster_rows = list((plan.get("operations") or {}).get("roster_batch_rows") or [])
    if roster_rows:
        roster_csv_path = resolved_output_dir / "team_roster_batch.csv"
        fieldnames = ["team", "source", "eq_record_id", "team_offset", "slot", "player_id", "flag", "pid"]
        with roster_csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in roster_rows:
                writer.writerow({key: row.get(key, "") for key in fieldnames})

    team_edit_json_path: Path | None = None
    team_edits = list((plan.get("operations") or {}).get("team_edits") or [])
    if team_edits:
        team_edit_json_path = resolved_output_dir / "team_edits.json"
        _json_dump(team_edit_json_path, team_edits)

    return PlanBundle(
        payload=plan,
        output_dir=resolved_output_dir,
        world_plan_path=world_plan_path,
        player_csv_path=player_csv_path,
        roster_csv_path=roster_csv_path,
        team_edit_json_path=team_edit_json_path,
    )


def _run_editor(args: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
    command = [str(REPO_ROOT / "scripts" / "dev_editor.sh"), *args]
    completed = subprocess.run(command, cwd=str(cwd or REPO_ROOT), text=True, capture_output=True, check=False)
    payload: dict[str, Any] = {
        "command": command,
        "returncode": int(completed.returncode),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    stdout_text = completed.stdout.strip()
    if stdout_text.startswith("{"):
        try:
            payload["json"] = json.loads(stdout_text)
        except Exception:
            pass
    return payload


def _xor61_decode_text(raw: bytes) -> str:
    return bytes((byte ^ 0x61) for byte in raw).decode("latin-1", errors="replace").rstrip()


def _xor61_encode_fixed_text(text: str, width: int) -> bytes:
    fitted = str(text or "")[:width].ljust(width)
    return bytes((byte ^ 0x61) for byte in fitted.encode("latin-1", errors="replace"))


def _patch_linked_team_name_fallback(team_file: Path, *, team_offset: int, new_name: str) -> dict[str, Any]:
    """Patch the first fixed-width XOR text field for linked roster-only teams.

    A small number of English selector slots are parser-backed for linked
    rosters but not for the generic TeamRecord metadata editor. Those records
    still expose their menu/display name as the first length-prefixed XOR-0x61
    string at the resolved linked roster offset. This fallback is deliberately
    fixed-width only and is used only after team-edit reports zero matches for a
    known offset.
    """

    data = bytearray(team_file.read_bytes())
    offset = int(team_offset)
    if offset < 0 or offset + 2 > len(data):
        raise ValueError(f"team_offset 0x{offset:08X} is outside {team_file}")

    length_pos = -1
    width = -1
    old_name = ""
    for rel in range(0, 12):
        candidate_pos = offset + rel
        if candidate_pos + 2 > len(data):
            continue
        candidate_width = int.from_bytes(data[candidate_pos:candidate_pos + 2], "little")
        candidate_text_pos = candidate_pos + 2
        candidate_text_end = candidate_text_pos + candidate_width
        if candidate_width < 3 or candidate_width > 60 or candidate_text_end > len(data):
            continue
        candidate_name = _xor61_decode_text(bytes(data[candidate_text_pos:candidate_text_end]))
        if not any(ch.isalpha() for ch in candidate_name):
            continue
        allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .'-&")
        if any(ch not in allowed for ch in candidate_name.strip()):
            continue
        length_pos = candidate_pos
        width = candidate_width
        old_name = candidate_name
        break
    if length_pos < 0 or width <= 0:
        raise ValueError(f"No fixed linked-team name span at 0x{offset:08X}")

    text_pos = length_pos + 2
    text_end = text_pos + width
    old_raw = bytes(data[text_pos:text_end])
    new_raw = _xor61_encode_fixed_text(new_name, width)
    if old_raw == new_raw:
        return {
            "applied_to_disk": False,
            "changed": False,
            "offset": offset,
            "span_start": text_pos,
            "span_width": width,
            "old_name": old_name,
            "new_name": str(new_name or "")[:width].rstrip(),
        }
    backup_path = team_file.with_suffix(team_file.suffix + ".raw_linked_name_fallback.backup")
    if not backup_path.exists():
        backup_path.write_bytes(bytes(data))
    data[text_pos:text_end] = new_raw
    team_file.write_bytes(bytes(data))
    return {
        "applied_to_disk": True,
        "backup_path": str(backup_path),
        "changed": True,
        "offset": offset,
        "span_start": text_pos,
        "span_width": width,
        "old_name": old_name,
        "new_name": str(new_name or "")[:width].rstrip(),
    }


def _editor_json(result: dict[str, Any] | None) -> dict[str, Any]:
    payload = (result or {}).get("json")
    return dict(payload) if isinstance(payload, dict) else {}


def _build_world_apply_readiness(
    *,
    plan: dict[str, Any],
    player_result: dict[str, Any] | None,
    roster_result: dict[str, Any] | None,
    team_results: list[dict[str, Any]],
    validate_result: dict[str, Any] | None,
    audit_result: dict[str, Any] | None,
    skip_player_roundtrip_safety: bool = False,
    allow_raw_team_name_fallbacks: bool = False,
) -> dict[str, Any]:
    operations = dict(plan.get("operations") or {})
    expected_player_rows = len(list(operations.get("player_batch_rows") or []))
    expected_roster_rows = len(list(operations.get("roster_batch_rows") or []))
    expected_team_edits = len(list(operations.get("team_edits") or []))

    player_json = _editor_json(player_result)
    roster_json = _editor_json(roster_result)
    validate_json = _editor_json(validate_result)
    audit_json = _editor_json(audit_result)

    team_bad = []
    team_fallback_count = 0
    for index, result in enumerate(team_results, start=1):
        result_json = _editor_json(result)
        if result_json.get("raw_linked_team_name_fallback"):
            team_fallback_count += 1
        warnings = list(result_json.get("warnings") or [])
        matched_count = int(result_json.get("matched_count") or 0)
        if int(result.get("returncode") or 0) != 0 or warnings or matched_count != 1:
            team_bad.append(
                {
                    "index": index,
                    "returncode": int(result.get("returncode") or 0),
                    "matched_count": matched_count,
                    "warnings": warnings,
                }
            )

    checks = {
        "players": {
            "ok": (
                (expected_player_rows == 0 and player_result is None)
                or (
                    bool(player_result)
                    and not skip_player_roundtrip_safety
                    and int(player_result.get("returncode") or 0) == 0
                    and int(player_json.get("row_count") or 0) == expected_player_rows
                    and int(player_json.get("matched_row_count") or 0) == expected_player_rows
                    and len(list(player_json.get("warnings") or [])) == 0
                    and bool(player_json.get("applied_to_disk"))
                )
            ),
            "expected": expected_player_rows,
            "rows": int(player_json.get("row_count") or 0),
            "matched": int(player_json.get("matched_row_count") or 0),
            "warnings": len(list(player_json.get("warnings") or [])),
            "applied_to_disk": bool(player_json.get("applied_to_disk")),
            "skip_roundtrip_safety": bool(skip_player_roundtrip_safety),
        },
        "roster_relinks": {
            "ok": (
                (expected_roster_rows == 0 and roster_result is None)
                or (
                    bool(roster_result)
                    and int(roster_result.get("returncode") or 0) == 0
                    and int(roster_json.get("row_count") or 0) == expected_roster_rows
                    and int(roster_json.get("matched_row_count") or 0) == expected_roster_rows
                    and len(list(roster_json.get("warnings") or [])) == 0
                    and bool(roster_json.get("applied_to_disk"))
                )
            ),
            "expected": expected_roster_rows,
            "rows": int(roster_json.get("row_count") or 0),
            "matched": int(roster_json.get("matched_row_count") or 0),
            "warnings": len(list(roster_json.get("warnings") or [])),
            "applied_to_disk": bool(roster_json.get("applied_to_disk")),
        },
        "team_edits": {
            "ok": len(team_results) == expected_team_edits and not team_bad and (allow_raw_team_name_fallbacks or team_fallback_count == 0),
            "expected": expected_team_edits,
            "files": len(team_results),
            "bad_or_warning": len(team_bad),
            "raw_linked_name_fallbacks": team_fallback_count,
            "allow_raw_linked_name_fallbacks": bool(allow_raw_team_name_fallbacks),
            "bad": team_bad,
        },
        "database_validation": {
            "ok": bool(validate_result)
            and int(validate_result.get("returncode") or 0) == 0
            and bool(validate_json.get("all_valid")),
            "all_valid": bool(validate_json.get("all_valid")),
        },
        "global_game_ready_audit": {
            "ok": bool(audit_result) and int(audit_result.get("returncode") or 0) == 0 and bool(audit_json.get("ok")),
            "issues": list(audit_json.get("issues") or []),
            "parser_all_valid": bool((audit_json.get("parser_validation") or {}).get("all_valid")),
        },
    }
    required = ["players", "roster_relinks", "team_edits", "database_validation", "global_game_ready_audit"]
    ok = all(bool(checks[name]["ok"]) for name in required)
    return {
        "schema": "pm99-world-apply-readiness-v2",
        "ok": ok,
        "required_checks": required,
        "checks": checks,
        "global_audit_required": True,
    }


def apply_world_plan(
    plan_path: str | Path,
    *,
    game_root: str | Path,
    output_dir: str | Path,
    allow_blocked: bool = False,
    skip_player_roundtrip_safety: bool = False,
    allow_raw_team_name_fallbacks: bool = False,
) -> dict[str, Any]:
    resolved_game_root = resolve_game_root(game_root, require_writable=True)
    resolved_output_dir = Path(output_dir).expanduser().resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    plan = json.loads(Path(plan_path).expanduser().resolve().read_text(encoding="utf-8"))
    blockers = list(plan.get("blockers") or [])
    if blockers and not allow_blocked:
        result = {
            "success": False,
            "phase": "preflight",
            "message": "Plan contains blocking issues; refusing to apply",
            "blockers": blockers,
        }
        _json_dump(resolved_output_dir / "apply_result.json", result)
        return result

    team_file = resolved_game_root / "DBDAT" / "EQ98030.FDI"
    player_file = resolved_game_root / "DBDAT" / "JUG98030.FDI"
    coach_file = resolved_game_root / "DBDAT" / "ENT98030.FDI"

    commands: list[dict[str, Any]] = []
    bundle = write_plan_bundle(plan, resolved_output_dir / "compiled_inputs")
    player_result: dict[str, Any] | None = None
    roster_result: dict[str, Any] | None = None
    team_results: list[dict[str, Any]] = []

    if bundle.player_csv_path is not None:
        if skip_player_roundtrip_safety:
            final = {
                "success": False,
                "phase": "player-batch-edit-preflight",
                "message": "Refusing release apply with --skip-player-roundtrip-safety",
                "commands": commands,
                "blockers": blockers,
            }
            _json_dump(resolved_output_dir / "apply_result.json", final)
            return final
        preflight_command = [
            "python3",
            "-m",
            "app.cli",
            "player-batch-edit",
            str(player_file),
            "--csv",
            str(bundle.player_csv_path),
            "--json",
            "--dry-run",
        ]
        player_preflight_result = _run_editor(preflight_command)
        _json_dump(resolved_output_dir / "player_batch_preflight.json", player_preflight_result)
        commands.append({"step": "player-batch-edit-preflight", **player_preflight_result})
        player_preflight_json = _editor_json(player_preflight_result)
        if player_preflight_result["returncode"] != 0 or list(player_preflight_json.get("warnings") or []):
            final = {
                "success": False,
                "phase": "player-batch-edit-preflight",
                "message": "Refusing release apply because player-batch-edit preflight produced warnings",
                "commands": commands,
                "blockers": blockers,
            }
            _json_dump(resolved_output_dir / "apply_result.json", final)
            return final
        command = [
            "python3", "-m", "app.cli", "player-batch-edit", str(player_file), "--csv", str(bundle.player_csv_path), "--json"
        ]
        player_result = _run_editor(command)
        _json_dump(resolved_output_dir / "player_batch_apply.json", player_result)
        commands.append({"step": "player-batch-edit", **player_result})
        player_json = _editor_json(player_result)
        if player_result["returncode"] != 0 or list(player_json.get("warnings") or []):
            final = {"success": False, "phase": "player-batch-edit", "commands": commands, "blockers": blockers}
            if list(player_json.get("warnings") or []):
                final["message"] = "Refusing release apply because player-batch-edit produced warnings"
            _json_dump(resolved_output_dir / "apply_result.json", final)
            return final

    if bundle.roster_csv_path is not None:
        roster_result = _run_editor([
            "python3", "-m", "app.cli", "team-roster-batch-edit", str(team_file), "--player-file", str(player_file), "--csv", str(bundle.roster_csv_path), "--json"
        ])
        _json_dump(resolved_output_dir / "team_roster_batch_apply.json", roster_result)
        commands.append({"step": "team-roster-batch-edit", **roster_result})
        if roster_result["returncode"] != 0:
            final = {"success": False, "phase": "team-roster-batch-edit", "commands": commands, "blockers": blockers}
            _json_dump(resolved_output_dir / "apply_result.json", final)
            return final

    team_edits = list((plan.get("operations") or {}).get("team_edits") or [])
    team_edits.sort(key=lambda item: int(item.get("team_offset") or -1), reverse=True)
    for index, edit in enumerate(team_edits, start=1):
        # The compiler resolves team_offset before any writes. During a full
        # roster world apply, earlier team renames can make later textual
        # queries stale, so the parser offset is the authoritative target.
        # Apply from high offsets to low offsets because EQ team writes may
        # shift records that appear after the rewritten row.
        command = [
            "python3",
            "-m",
            "app.cli",
            "team-edit",
            str(team_file),
            "--offset",
            str(edit["team_offset"]),
            "--include-uncertain",
            "--json",
        ]
        for flag_name, json_key in (
            ("--set-name", "set_name"),
            ("--set-full-club-name", "set_full_club_name"),
            ("--set-stadium", "set_stadium"),
            ("--set-chairman-name", "set_chairman_name"),
            ("--set-shirt-sponsor", "set_shirt_sponsor"),
            ("--set-kit-supplier", "set_kit_supplier"),
            ("--set-starting-finance", "set_starting_finance"),
            ("--set-ground-size", "set_ground_size"),
        ):
            if json_key in edit and edit[json_key] not in (None, ""):
                command.extend([flag_name, str(edit[json_key])])
        result = _run_editor(command)
        result_json = result.get("json")
        if (
            allow_raw_team_name_fallbacks
            and
            isinstance(result_json, dict)
            and int(result_json.get("matched_count") or 0) == 0
            and edit.get("set_name") not in (None, "")
            and edit.get("team_offset") is not None
        ):
            try:
                fallback = _patch_linked_team_name_fallback(
                    team_file,
                    team_offset=int(edit["team_offset"]),
                    new_name=str(edit["set_name"]),
                )
                result_json["raw_linked_team_name_fallback"] = fallback
                if fallback.get("changed"):
                    result_json["matched_count"] = 1
                    result_json["applied_to_disk"] = True
                    result_json.setdefault("changes", []).append(
                        {
                            "offset": int(edit["team_offset"]),
                            "name": fallback.get("new_name"),
                            "changed_fields": {
                                "name": [fallback.get("old_name"), fallback.get("new_name")]
                            },
                            "source": "raw-linked-team-name-fallback",
                        }
                    )
            except Exception as exc:
                result_json.setdefault("warnings", []).append(
                    {
                        "offset": int(edit.get("team_offset") or 0),
                        "message": f"raw linked team name fallback failed: {exc}",
                    }
                )
        _json_dump(resolved_output_dir / f"team_edit_{index:03d}.json", result)
        team_results.append(result)
        commands.append({"step": f"team-edit-{index}", **result})
        if result["returncode"] != 0:
            final = {"success": False, "phase": f"team-edit-{index}", "commands": commands, "blockers": blockers}
            _json_dump(resolved_output_dir / "apply_result.json", final)
            return final
        result_json = _editor_json(result)
        if int(result_json.get("matched_count") or 0) != 1 or list(result_json.get("warnings") or []):
            final = {
                "success": False,
                "phase": f"team-edit-{index}",
                "message": "Refusing release apply because team-edit did not cleanly match exactly one released row",
                "commands": commands,
                "blockers": blockers,
            }
            _json_dump(resolved_output_dir / "apply_result.json", final)
            return final

    validate_result = _run_editor([
        "python3", "-m", "app.cli", "validate-database", "--players", str(player_file), "--teams", str(team_file), "--coaches", str(coach_file), "--json"
    ])
    _json_dump(resolved_output_dir / "validate_database.json", validate_result)
    commands.append({"step": "validate-database", **validate_result})

    audit_result = _run_editor([
        "python3", "-m", "app.cli", "game-ready-audit", str(team_file), "--player-file", str(player_file), "--coach-file", str(coach_file), "--json"
    ])
    _json_dump(resolved_output_dir / "game_ready_audit.json", audit_result)
    commands.append({"step": "game-ready-audit", **audit_result})

    world_readiness = _build_world_apply_readiness(
        plan=plan,
        player_result=player_result,
        roster_result=roster_result,
        team_results=team_results,
        validate_result=validate_result,
        audit_result=audit_result,
        skip_player_roundtrip_safety=skip_player_roundtrip_safety,
        allow_raw_team_name_fallbacks=allow_raw_team_name_fallbacks,
    )
    _json_dump(resolved_output_dir / "world_apply_readiness.json", world_readiness)

    success = bool(world_readiness.get("ok"))
    final = {
        "success": success,
        "phase": "complete" if success else "post_apply_validation",
        "commands": commands,
        "blockers": blockers,
        "game_root": str(resolved_game_root),
        "core_files": core_file_hashes(resolved_game_root),
        "world_apply_readiness": world_readiness,
        "global_game_ready_audit_ok": bool((_editor_json(audit_result)).get("ok")),
    }
    _json_dump(resolved_output_dir / "apply_result.json", final)
    return final


def render_report(summary_path: str | Path, output_html: str | Path) -> Path:
    summary = json.loads(Path(summary_path).expanduser().resolve().read_text(encoding="utf-8"))
    output_path = Path(output_html).expanduser().resolve()
    rows = []
    for item in list(summary.get("coverage_matrix") or []):
        counts = item.get("counts") or {}
        rows.append(
            f"<tr><td>{item.get('family','')}</td><td>{item.get('status','')}</td><td>{counts.get('ready',0)}</td><td>{counts.get('planned',0)}</td><td>{counts.get('blocked',0)}</td><td>{item.get('message','')}</td></tr>"
        )
    blocker_rows = []
    for blocker in list(summary.get("blockers") or []):
        blocker_rows.append(
            f"<tr><td>{blocker.get('family','')}</td><td>{blocker.get('code','')}</td><td>{blocker.get('entity_key','')}</td><td>{blocker.get('message','')}</td></tr>"
        )
    html = f"""<!doctype html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\" />
<title>PM99 Full-DB World Report</title>
<style>
body {{ font-family: sans-serif; margin: 2rem; }}
table {{ border-collapse: collapse; width: 100%; margin-bottom: 2rem; }}
th, td {{ border: 1px solid #ccc; padding: 0.5rem; text-align: left; }}
th {{ background: #f5f5f5; }}
.ok {{ color: #0a7a20; }}
.bad {{ color: #8a1111; }}
code {{ background: #f5f5f5; padding: 0.1rem 0.25rem; }}
</style>
</head>
<body>
<h1>PM99 Full-DB World Report</h1>
<p>Status: <strong class=\"{'ok' if summary.get('ok') else 'bad'}\">{'OK' if summary.get('ok') else 'BLOCKED'}</strong></p>
<h2>Coverage</h2>
<table>
<thead><tr><th>Family</th><th>Status</th><th>Ready</th><th>Planned</th><th>Blocked</th><th>Message</th></tr></thead>
<tbody>{''.join(rows) or '<tr><td colspan="6">No coverage rows</td></tr>'}</tbody>
</table>
<h2>Blockers</h2>
<table>
<thead><tr><th>Family</th><th>Code</th><th>Entity</th><th>Message</th></tr></thead>
<tbody>{''.join(blocker_rows) or '<tr><td colspan="4">No blockers</td></tr>'}</tbody>
</table>
<pre>{json.dumps(summary.get('counts', {}), indent=2, sort_keys=True)}</pre>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")
    return output_path


def _cmd_import_validate(args: argparse.Namespace) -> int:
    world = load_world_state(args.world_state)
    output = {
        "schema": world["schema"],
        "source_path": world["source_path"],
        "source_sha256": world["source_sha256"],
        "counts": {
            "clubs": len(world["clubs"]),
            "players": len(world["players"]),
            "squad_memberships": len(world["squad_memberships"]),
            "divisions": len(world["divisions"]),
        },
        "ok": True,
    }
    if args.json:
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        print(f"schema={output['schema']}")
        print(f"clubs={output['counts']['clubs']} players={output['counts']['players']} squad_memberships={output['counts']['squad_memberships']} divisions={output['counts']['divisions']}")
    return 0


def _cmd_compile_plan(args: argparse.Namespace) -> int:
    plan = compile_world_plan(args.world_state, game_root=args.game_root, selector_map=args.selector_map)
    bundle = write_plan_bundle(plan, args.output_dir)
    if args.json:
        print(json.dumps({
            "ok": bool(plan.get("ok")),
            "world_plan_path": str(bundle.world_plan_path),
            "player_csv_path": str(bundle.player_csv_path) if bundle.player_csv_path else None,
            "roster_csv_path": str(bundle.roster_csv_path) if bundle.roster_csv_path else None,
            "team_edit_json_path": str(bundle.team_edit_json_path) if bundle.team_edit_json_path else None,
            "blockers": plan.get("blockers", []),
        }, indent=2, sort_keys=True))
    else:
        print(f"world_plan={bundle.world_plan_path}")
        print(f"ok={plan.get('ok')}")
        print(f"blockers={len(plan.get('blockers') or [])}")
    return 0 if bool(plan.get("ok")) else 1


def _cmd_selector_coverage(args: argparse.Namespace) -> int:
    result = build_selector_coverage(args.world_state, selector_map_path=args.selector_map)
    if args.output_json:
        _json_dump(Path(args.output_json).expanduser().resolve(), result)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        counts = result["counts"]
        print(f"clubs={counts['clubs']} ready={counts['ready']} blocked={counts['blocked']}")
    return 0 if bool(result.get("ok")) else 1


def _cmd_selector_scaffold(args: argparse.Namespace) -> int:
    result = build_selector_scaffold(args.world_state, selector_map_path=args.selector_map)
    if args.output_json:
        _json_dump(Path(args.output_json).expanduser().resolve(), result)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        counts = result["counts"]
        print(f"selectors={counts['clubs']} ready={counts['ready']} missing={counts['blocked']}")
    return 0 if bool(result.get("ok")) or not bool(args.strict) else 1


def _cmd_selector_generate(args: argparse.Namespace) -> int:
    result = build_selector_map_from_layout(
        args.world_state,
        selector_map_path=args.selector_map,
        division_select_x=int(args.division_select_x),
        division_start_y=int(args.division_start_y),
        division_step_y=int(args.division_step_y),
        team_select_x=int(args.team_select_x),
        team_start_y=int(args.team_start_y),
        team_step_y=int(args.team_step_y),
    )
    if args.output_json:
        _json_dump(Path(args.output_json).expanduser().resolve(), result)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        counts = result["counts"]
        print(f"selectors={counts['clubs']} ready={counts['ready']} missing={counts['blocked']}")
    return 0 if bool(result.get("ok")) or not bool(args.strict) else 1


def _cmd_apply_plan(args: argparse.Namespace) -> int:
    result = apply_world_plan(
        args.plan,
        game_root=args.game_root,
        output_dir=args.output_dir,
        allow_blocked=bool(args.allow_blocked),
        skip_player_roundtrip_safety=bool(args.skip_player_roundtrip_safety),
        allow_raw_team_name_fallbacks=bool(args.allow_raw_team_name_fallbacks),
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"success={result.get('success')}")
        print(f"phase={result.get('phase')}")
        print(f"commands={len(result.get('commands') or [])}")
    return 0 if bool(result.get("success")) else 1


def _cmd_render_report(args: argparse.Namespace) -> int:
    output = render_report(args.summary_json, args.output_html)
    payload = {"output_html": str(output), "ok": True}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(str(output))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PM99 full-DB world-state helpers")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("world-import-validate", help="Validate canonical world-state input")
    validate_parser.add_argument("world_state", help="Path to canonical world-state JSON")
    validate_parser.add_argument("--json", action="store_true", help="Emit JSON result")
    validate_parser.set_defaults(func=_cmd_import_validate)

    compile_parser = subparsers.add_parser("world-compile-plan", help="Compile world-state into editor-facing plan artifacts")
    compile_parser.add_argument("world_state", help="Path to canonical world-state JSON")
    compile_parser.add_argument("--game-root", required=True, help="Baseline PM99 game root used for resolution")
    compile_parser.add_argument("--output-dir", required=True, help="Directory for plan artifacts")
    compile_parser.add_argument("--selector-map", help="Optional club selector map JSON")
    compile_parser.add_argument("--json", action="store_true", help="Emit JSON result")
    compile_parser.set_defaults(func=_cmd_compile_plan)

    selector_parser = subparsers.add_parser("world-selector-coverage", help="Report club runtime selector coverage")
    selector_parser.add_argument("world_state", help="Path to canonical world-state JSON")
    selector_parser.add_argument("--selector-map", help="Optional club selector map JSON")
    selector_parser.add_argument("--output-json", help="Optional JSON report path")
    selector_parser.add_argument("--json", action="store_true", help="Emit JSON result")
    selector_parser.set_defaults(func=_cmd_selector_coverage)

    scaffold_parser = subparsers.add_parser("world-selector-scaffold", help="Generate a fill-in selector map for a world-state file")
    scaffold_parser.add_argument("world_state", help="Path to canonical world-state JSON")
    scaffold_parser.add_argument("--selector-map", help="Optional existing selector map to merge")
    scaffold_parser.add_argument("--output-json", help="Optional scaffold JSON path")
    scaffold_parser.add_argument("--strict", action="store_true", help="Exit nonzero when selectors are still missing")
    scaffold_parser.add_argument("--json", action="store_true", help="Emit JSON result")
    scaffold_parser.set_defaults(func=_cmd_selector_scaffold)

    generate_parser = subparsers.add_parser("world-selector-generate", help="Generate selector coordinates from menu row indices")
    generate_parser.add_argument("world_state", help="Path to canonical world-state JSON")
    generate_parser.add_argument("--selector-map", help="Optional existing selector map to merge")
    generate_parser.add_argument("--output-json", help="Optional generated selector-map JSON path")
    generate_parser.add_argument("--strict", action="store_true", help="Exit nonzero when selectors are still missing")
    generate_parser.add_argument("--division-select-x", type=int, default=559)
    generate_parser.add_argument("--division-start-y", type=int, default=302)
    generate_parser.add_argument("--division-step-y", type=int, default=39)
    generate_parser.add_argument("--team-select-x", type=int, default=327)
    generate_parser.add_argument("--team-start-y", type=int, default=356)
    generate_parser.add_argument("--team-step-y", type=int, default=39)
    generate_parser.add_argument("--json", action="store_true", help="Emit JSON result")
    generate_parser.set_defaults(func=_cmd_selector_generate)

    apply_parser = subparsers.add_parser("world-apply-plan", help="Apply compiled plan to a writable PM99 game root")
    apply_parser.add_argument("plan", help="Path to world_plan.json")
    apply_parser.add_argument("--game-root", required=True, help="Writable PM99 game root")
    apply_parser.add_argument("--output-dir", required=True, help="Directory for apply artifacts")
    apply_parser.add_argument("--allow-blocked", action="store_true", help="Apply even when blockers exist")
    apply_parser.add_argument(
        "--skip-player-roundtrip-safety",
        action="store_true",
        help="Investigation-only mode: pass --skip-roundtrip-safety to player-batch-edit. Release applies fail closed when this is set.",
    )
    apply_parser.add_argument(
        "--allow-raw-team-name-fallbacks",
        action="store_true",
        help="Investigation-only mode: allow fixed-width raw linked-team name fallback writes after team-edit misses.",
    )
    apply_parser.add_argument("--json", action="store_true", help="Emit JSON result")
    apply_parser.set_defaults(func=_cmd_apply_plan)

    render_parser = subparsers.add_parser("world-render-report", help="Render a compact HTML report from a plan/apply summary JSON")
    render_parser.add_argument("summary_json", help="Summary JSON path")
    render_parser.add_argument("--output-html", required=True, help="Output HTML path")
    render_parser.add_argument("--json", action="store_true", help="Emit JSON result")
    render_parser.set_defaults(func=_cmd_render_report)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
