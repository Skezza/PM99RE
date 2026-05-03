#!/usr/bin/env python3
"""Inventory PM99 indexed player-name layout contracts.

This is a research/audit script, not an editor writer.  It classifies every
indexed JUG player payload by the name/metadata cursor contract that a future
variable-length editor must preserve, then joins that inventory to EQ roster
links and the 80 playable selector map.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
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

from app.eq_jug_linked import load_eq_linked_team_rosters  # noqa: E402
from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from app.models import PlayerRecord  # noqa: E402

try:
    from app.editor_helpers import _player_display_name  # type: ignore  # noqa: E402
except Exception:  # pragma: no cover - fallback for older editor checkouts
    def _player_display_name(record: PlayerRecord) -> str:
        return str(getattr(record, "name", "") or "").strip()


@dataclass(frozen=True)
class ContractRow:
    record_id: int
    key: str
    payload_offset: int
    payload_length: int
    head_hex: str
    parse_status: str
    player_name: str
    contract_family: str
    contract_status: str
    name_start: int | None
    name_end: int | None
    metadata_anchor: int | None
    suffix_anchor: int | None
    current_name_bytes: int
    max_prefix_bytes_in_container: int | None
    growth_room_bytes: int | None
    tail_bytes_to_preserve: int | None
    roster_ref_count: int
    playable_80_ref_count: int
    foreign_or_non_playable_ref_count: int
    unlinked: bool
    warning: str


def _norm(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    asciiish = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", asciiish.casefold())


def _display_name(record: PlayerRecord) -> str:
    return " ".join(str(_player_display_name(record) or "").split())


def _encoded_len(value: str) -> int:
    return len(str(value or "").encode("cp1252", errors="replace"))


def _load_world_clubs(path: Path | None, selector_map: Path | None = None) -> list[dict[str, Any]]:
    if selector_map is not None and selector_map.is_file():
        payload = json.loads(selector_map.read_text(encoding="utf-8"))
        selectors = [row for row in list(payload.get("selectors") or []) if isinstance(row, dict)]
        if selectors:
            return selectors
    if path is None or not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [row for row in list(payload.get("clubs") or []) if isinstance(row, dict)]


def _levenshtein_at_most_two(left: str, right: str) -> bool:
    if abs(len(left) - len(right)) > 2:
        return False
    previous = list(range(len(right) + 1))
    for i, lc in enumerate(left, start=1):
        current = [i]
        row_min = i
        for j, rc in enumerate(right, start=1):
            cost = 0 if lc == rc else 1
            value = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            current.append(value)
            row_min = min(row_min, value)
        if row_min > 2:
            return False
        previous = current
    return previous[-1] <= 2


def _selector_roster_match_score(roster: Any, club: dict[str, Any]) -> int:
    queries = [
        club.get("team_query"),
        club.get("set_name"),
        club.get("discovery_text"),
        club.get("club_key"),
        *(club.get("aliases") or []),
    ]
    source = club.get("source") if isinstance(club.get("source"), dict) else {}
    queries.extend([source.get("discovery_text"), source.get("discovery_normalized_text")])
    roster_names = [
        getattr(roster, "short_name", ""),
        getattr(roster, "full_club_name", ""),
    ]
    query_norms = [_norm(str(item or "")) for item in queries if str(item or "").strip()]
    roster_norms = [_norm(str(item or "")) for item in roster_names if str(item or "").strip()]
    best = 0
    for query in query_norms:
        for roster_name in roster_norms:
            if not query or not roster_name:
                continue
            if query == roster_name:
                best = max(best, 100)
            elif query in roster_name or roster_name in query:
                best = max(best, 85 - min(20, abs(len(query) - len(roster_name))))
            elif _levenshtein_at_most_two(query, roster_name):
                best = max(best, 75)
    return int(best)


def _roster_matches_world_club(roster: Any, club: dict[str, Any]) -> bool:
    return _selector_roster_match_score(roster, club) >= 70


def _build_roster_maps(
    *,
    team_file: Path,
    player_file: Path,
    world_clubs: list[dict[str, Any]],
) -> tuple[dict[int, list[dict[str, Any]]], dict[int, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    rosters = load_eq_linked_team_rosters(team_file=str(team_file), player_file=str(player_file))
    playable_roster_by_eq: dict[int, dict[str, Any]] = {}
    unmatched_world: list[dict[str, Any]] = []
    for club in world_clubs:
        scored = [
            (_selector_roster_match_score(roster, club), roster)
            for roster in rosters
            if _roster_matches_world_club(roster, club)
        ]
        scored.sort(key=lambda item: item[0], reverse=True)
        matches = [roster for _, roster in scored]
        if not matches:
            unmatched_world.append(club)
            continue
        # The selector map should resolve to exactly one PM99 selectable slot.
        roster = matches[0]
        playable_roster_by_eq[int(getattr(roster, "eq_record_id", 0) or 0)] = {
            "club_key": str(club.get("club_key") or ""),
            "team_query": str(club.get("team_query") or club.get("set_name") or ""),
            "eq_record_id": int(getattr(roster, "eq_record_id", 0) or 0),
            "team_name": str(getattr(roster, "short_name", "") or ""),
            "full_club_name": str(getattr(roster, "full_club_name", "") or ""),
        }

    refs_by_player_id: dict[int, list[dict[str, Any]]] = defaultdict(list)
    roster_catalog: dict[int, dict[str, Any]] = {}
    for roster in rosters:
        eq_record_id = int(getattr(roster, "eq_record_id", 0) or 0)
        playable = playable_roster_by_eq.get(eq_record_id)
        roster_catalog[eq_record_id] = {
            "eq_record_id": eq_record_id,
            "team_name": str(getattr(roster, "short_name", "") or ""),
            "full_club_name": str(getattr(roster, "full_club_name", "") or ""),
            "is_playable_80": playable is not None,
            "playable_club_key": str((playable or {}).get("club_key") or ""),
        }
        for row in list(getattr(roster, "rows", []) or []):
            player_id = int(getattr(row, "player_record_id", 0) or 0)
            if player_id <= 0:
                continue
            refs_by_player_id[player_id].append(
                {
                    "eq_record_id": eq_record_id,
                    "team_name": str(getattr(roster, "short_name", "") or ""),
                    "full_club_name": str(getattr(roster, "full_club_name", "") or ""),
                    "slot_number": int(getattr(row, "slot_index", 0) or 0) + 1,
                    "flag": int(getattr(row, "flag", 0) or 0),
                    "is_playable_80": playable is not None,
                    "playable_club_key": str((playable or {}).get("club_key") or ""),
                }
            )
    return refs_by_player_id, roster_catalog, list(playable_roster_by_eq.values()), unmatched_world


def _compact_segments(payload: bytes) -> dict[str, int] | None:
    name_end = PlayerRecord._find_name_end(payload)
    if name_end is None:
        return None
    candidates: list[dict[str, int]] = []
    for first_len_offset in range(5, min(len(payload), 24)):
        surname_width = int(payload[first_len_offset] ^ 0x61)
        surname_start = first_len_offset + 2
        surname_end = surname_start + surname_width
        if not (1 <= surname_width <= 48):
            continue
        if first_len_offset + 1 >= len(payload) or payload[first_len_offset + 1] != 0x61:
            continue
        full_len_offset = surname_end
        if full_len_offset + 1 >= len(payload) or payload[full_len_offset + 1] != 0x61:
            continue
        full_width = int(payload[full_len_offset] ^ 0x61)
        full_start = full_len_offset + 2
        full_end = full_start + full_width
        if not (1 <= full_width <= 120 and full_end <= len(payload)):
            continue
        pre_marker_gap = int(name_end) - int(full_end)
        if pre_marker_gap in {3, 4}:
            candidates.append(
                {
                "first_len_offset": first_len_offset,
                "surname_start": surname_start,
                "surname_end": surname_end,
                "surname_width": surname_width,
                "full_len_offset": full_len_offset,
                "full_name_start": full_start,
                "full_name_end": full_end,
                "full_name_width": full_width,
                "name_end": int(name_end),
                    "pre_marker_gap_bytes": int(pre_marker_gap),
                }
            )
    if candidates:
        # Prefer the known runtime-proven gap-3 contract, then the sibling
        # gap-4 contract.  Within a gap, prefer the earliest segment window.
        candidates.sort(key=lambda item: (0 if item["pre_marker_gap_bytes"] == 3 else 1, item["first_len_offset"]))
        return candidates[0]
    return None


def _classify_contract(decoded: bytes, player_name: str) -> dict[str, Any]:
    head = decoded[2:5].hex() if len(decoded) >= 5 else ""
    name_end = PlayerRecord._find_name_end(decoded)
    current_name_bytes = _encoded_len(player_name)
    base = {
        "contract_family": "opaque_or_unknown",
        "contract_status": "preserve_only",
        "name_start": None,
        "name_end": name_end,
        "metadata_anchor": name_end,
        "suffix_anchor": None,
        "current_name_bytes": current_name_bytes,
        "max_prefix_bytes_in_container": None,
        "growth_room_bytes": None,
        "tail_bytes_to_preserve": None,
        "warning": "",
    }

    if head == "dd6360":
        segments = _compact_segments(decoded)
        if segments is None or name_end is None:
            return {
                **base,
                "contract_family": "dd6360_compact_linked_unresolved",
                "contract_status": "needs_reverse_engineering",
                "warning": "Could not resolve length-prefixed compact linked segments.",
            }
        pre_marker_gap = int(segments["pre_marker_gap_bytes"])
        role_start = int(name_end) - pre_marker_gap
        tail_start = int(name_end)
        tail_len = max(0, len(decoded) - tail_start)
        current_prefix = role_start - int(segments["first_len_offset"])
        max_prefix = max(0, len(decoded) - int(segments["first_len_offset"]) - pre_marker_gap - tail_len)
        return {
            **base,
            "contract_family": f"dd6360_compact_linked_gap{pre_marker_gap}_physical_cursor",
            "contract_status": (
                "runtime_sampled_on_stoke_needs_full_surface_evidence"
                if pre_marker_gap == 3
                else "static_sibling_contract_needs_runtime_write_probe"
            ),
            "name_start": int(segments["first_len_offset"]),
            "name_end": int(name_end),
            "metadata_anchor": int(name_end),
            "max_prefix_bytes_in_container": int(max_prefix),
            "growth_room_bytes": int(max_prefix - current_prefix),
            "tail_bytes_to_preserve": int(tail_len),
            "warning": "" if tail_start <= len(decoded) else "role/tail cursor overruns payload",
        }

    if head == "dd6361":
        suffix_anchor = PlayerRecord._find_indexed_suffix_anchor(decoded, player_name)
        if suffix_anchor is None:
            return {
                **base,
                "contract_family": "dd6361_indexed_suffix_unresolved",
                "contract_status": "needs_reverse_engineering",
                "warning": "Could not resolve indexed suffix metadata anchor.",
            }
        max_prefix = int(suffix_anchor) - 5
        return {
            **base,
            "contract_family": "dd6361_indexed_suffix_biography",
            "contract_status": "static_contract_discovered_writer_not_runtime_proven",
            "name_start": 5,
            "name_end": int(suffix_anchor),
            "metadata_anchor": int(suffix_anchor),
            "suffix_anchor": int(suffix_anchor),
            "max_prefix_bytes_in_container": int(max_prefix),
            "growth_room_bytes": int(max_prefix - current_name_bytes),
            "tail_bytes_to_preserve": int(len(decoded) - suffix_anchor),
        }

    if name_end is not None:
        tail_start = int(name_end) + 4
        tail_len = max(0, len(decoded) - tail_start)
        max_prefix = max(0, int(name_end) - 5)
        return {
            **base,
            "contract_family": f"{head or 'legacy'}_marker_metadata",
            "contract_status": "static_contract_discovered_writer_not_runtime_proven",
            "name_start": 5,
            "name_end": int(name_end),
            "metadata_anchor": int(name_end),
            "max_prefix_bytes_in_container": int(max_prefix),
            "growth_room_bytes": int(max_prefix - current_name_bytes),
            "tail_bytes_to_preserve": int(tail_len),
        }

    return base


def _contract_row(
    *,
    entry: Any,
    decoded: bytes,
    record: PlayerRecord | None,
    parse_status: str,
    refs: list[dict[str, Any]],
) -> ContractRow:
    player_name = _display_name(record) if record is not None else ""
    if player_name in {"Unknown Player", "Parse Error"}:
        parse_status = "opaque_preserve"
    contract = _classify_contract(decoded, player_name) if parse_status == "ok" else {
        "contract_family": "opaque_or_non_player_payload",
        "contract_status": "preserve_only",
        "name_start": None,
        "name_end": None,
        "metadata_anchor": None,
        "suffix_anchor": None,
        "current_name_bytes": 0,
        "max_prefix_bytes_in_container": None,
        "growth_room_bytes": None,
        "tail_bytes_to_preserve": None,
        "warning": "",
    }
    playable_refs = [ref for ref in refs if ref.get("is_playable_80")]
    foreign_refs = [ref for ref in refs if not ref.get("is_playable_80")]
    return ContractRow(
        record_id=int(entry.record_id),
        key=str(entry.key),
        payload_offset=int(entry.payload_offset),
        payload_length=int(entry.payload_length),
        head_hex=decoded[2:5].hex() if len(decoded) >= 5 else "",
        parse_status=parse_status,
        player_name=player_name,
        contract_family=str(contract["contract_family"]),
        contract_status=str(contract["contract_status"]),
        name_start=contract["name_start"],
        name_end=contract["name_end"],
        metadata_anchor=contract["metadata_anchor"],
        suffix_anchor=contract["suffix_anchor"],
        current_name_bytes=int(contract["current_name_bytes"]),
        max_prefix_bytes_in_container=contract["max_prefix_bytes_in_container"],
        growth_room_bytes=contract["growth_room_bytes"],
        tail_bytes_to_preserve=contract["tail_bytes_to_preserve"],
        roster_ref_count=len(refs),
        playable_80_ref_count=len(playable_refs),
        foreign_or_non_playable_ref_count=len(foreign_refs),
        unlinked=not refs,
        warning=str(contract["warning"]),
    )


def _write_csv(path: Path, rows: list[ContractRow]) -> None:
    fields = list(ContractRow.__dataclass_fields__.keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def _write_html(path: Path, payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    family_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(row['contract_family'])}</td>"
        f"<td>{row['count']}</td>"
        f"<td>{row['playable_80_records']}</td>"
        f"<td>{row['foreign_or_non_playable_records']}</td>"
        f"<td>{row['unlinked_records']}</td>"
        f"<td>{html.escape(row['status'])}</td>"
        "</tr>"
        for row in payload["contract_families"]
    )
    status_rows = "\n".join(
        f"<tr><td>{html.escape(status)}</td><td>{count}</td></tr>"
        for status, count in sorted(summary["contract_status_counts"].items())
    )
    sample_rows = "\n".join(
        "<tr>"
        f"<td>{row['record_id']}</td>"
        f"<td>{html.escape(row['player_name'])}</td>"
        f"<td>{html.escape(row['contract_family'])}</td>"
        f"<td>{row['payload_length']}</td>"
        f"<td>{row['name_start']}</td>"
        f"<td>{row['metadata_anchor']}</td>"
        f"<td>{row['max_prefix_bytes_in_container']}</td>"
        f"<td>{row['playable_80_ref_count']}</td>"
        f"<td>{row['foreign_or_non_playable_ref_count']}</td>"
        f"<td>{html.escape(row['warning'])}</td>"
        "</tr>"
        for row in payload["sample_rows"][:250]
    )
    path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>PM99 Variable Player Name Contract Research</title>
<style>
body {{ font-family: ui-sans-serif, system-ui, sans-serif; margin: 2rem; color: #1c1b18; }}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0 2rem; font-size: 0.92rem; }}
th, td {{ border: 1px solid #d7d0c3; padding: 0.45rem 0.55rem; vertical-align: top; }}
th {{ background: #f3ead9; text-align: left; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr)); gap: 0.8rem; }}
.card {{ background: #fbf7ee; border: 1px solid #d7d0c3; border-radius: 0.5rem; padding: 0.8rem; }}
.num {{ font-size: 1.7rem; font-weight: 700; }}
code {{ background: #f3ead9; padding: 0.1rem 0.25rem; border-radius: 0.2rem; }}
</style>
</head>
<body>
<h1>PM99 Variable Player Name Contract Research</h1>
<p>Generated at <code>{html.escape(payload['generated_at'])}</code>.</p>
<div class="cards">
<div class="card"><div>Total indexed entries</div><div class="num">{summary['total_indexed_entries']}</div></div>
<div class="card"><div>Parser-backed players</div><div class="num">{summary['parse_ok_count']}</div></div>
<div class="card"><div>Opaque preserve-only</div><div class="num">{summary['opaque_or_non_player_count']}</div></div>
<div class="card"><div>Playable-80 linked players</div><div class="num">{summary['playable_80_player_records']}</div></div>
<div class="card"><div>Foreign/non-playable linked players</div><div class="num">{summary['foreign_or_non_playable_player_records']}</div></div>
<div class="card"><div>Unlinked indexed players</div><div class="num">{summary['unlinked_player_records']}</div></div>
</div>
<h2>Contract Families</h2>
<table><thead><tr><th>Family</th><th>Records</th><th>Playable 80</th><th>Foreign/non-playable</th><th>Unlinked</th><th>Status</th></tr></thead><tbody>{family_rows}</tbody></table>
<h2>Contract Status Counts</h2>
<table><thead><tr><th>Status</th><th>Records</th></tr></thead><tbody>{status_rows}</tbody></table>
<h2>Representative Rows</h2>
<table><thead><tr><th>ID</th><th>Name</th><th>Family</th><th>Len</th><th>Name start</th><th>Anchor</th><th>Max prefix</th><th>Playable refs</th><th>Foreign refs</th><th>Warning</th></tr></thead><tbody>{sample_rows}</tbody></table>
<h2>Artifacts</h2>
<p>JSON: <code>{html.escape(payload['artifacts']['json'])}</code></p>
<p>CSV: <code>{html.escape(payload['artifacts']['csv'])}</code></p>
</body></html>
""",
        encoding="utf-8",
    )


def _summarize(rows: list[ContractRow], playable_rosters: list[dict[str, Any]], unmatched_world: list[dict[str, Any]]) -> dict[str, Any]:
    family_counts: Counter[str] = Counter(row.contract_family for row in rows)
    status_counts: Counter[str] = Counter(row.contract_status for row in rows)
    parse_ok_count = sum(1 for row in rows if row.parse_status == "ok")
    opaque_count = len(rows) - parse_ok_count
    player_rows = [row for row in rows if row.parse_status == "ok"]
    playable_player_records = sum(1 for row in player_rows if row.playable_80_ref_count > 0)
    foreign_player_records = sum(1 for row in player_rows if row.foreign_or_non_playable_ref_count > 0)
    unlinked_player_records = sum(1 for row in player_rows if row.unlinked)
    families = []
    for family, count in family_counts.most_common():
        family_rows = [row for row in rows if row.contract_family == family]
        statuses = Counter(row.contract_status for row in family_rows)
        families.append(
            {
                "contract_family": family,
                "count": count,
                "status": ", ".join(f"{key}:{value}" for key, value in statuses.most_common()),
                "playable_80_records": sum(1 for row in family_rows if row.playable_80_ref_count > 0),
                "foreign_or_non_playable_records": sum(
                    1 for row in family_rows if row.foreign_or_non_playable_ref_count > 0
                ),
                "unlinked_records": sum(1 for row in family_rows if row.unlinked and row.parse_status == "ok"),
                "min_payload_length": min((row.payload_length for row in family_rows), default=None),
                "max_payload_length": max((row.payload_length for row in family_rows), default=None),
            }
        )
    return {
        "total_indexed_entries": len(rows),
        "parse_ok_count": parse_ok_count,
        "opaque_or_non_player_count": opaque_count,
        "playable_80_roster_count": len(playable_rosters),
        "playable_80_player_records": playable_player_records,
        "foreign_or_non_playable_player_records": foreign_player_records,
        "unlinked_player_records": unlinked_player_records,
        "contract_family_counts": dict(family_counts),
        "contract_status_counts": dict(status_counts),
        "unmatched_world_clubs": [
            {"club_key": str(row.get("club_key") or ""), "team_query": str(row.get("team_query") or "")}
            for row in unmatched_world
        ],
        "all_playable_world_clubs_matched": not unmatched_world and len(playable_rosters) == 80,
    }, families


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--player-file", default=str(REPO_ROOT / ".local/premier-manager-ninety-nine/DBDAT/JUG98030.FDI"))
    parser.add_argument("--team-file", default=str(REPO_ROOT / ".local/premier-manager-ninety-nine/DBDAT/EQ98030.FDI"))
    parser.add_argument("--world-state", default=str(REPO_ROOT / ".local/selector_maps/pm99_vanilla_english_80_world_stub.json"))
    parser.add_argument("--selector-map", default=str(REPO_ROOT / ".local/selector_maps/pm99_vanilla_english_80_selector_map.json"))
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    player_file = Path(args.player_file).expanduser().resolve()
    team_file = Path(args.team_file).expanduser().resolve()
    world_state = Path(args.world_state).expanduser().resolve() if args.world_state else None
    selector_map = Path(args.selector_map).expanduser().resolve() if args.selector_map else None
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    world_clubs = _load_world_clubs(world_state, selector_map)
    refs_by_player_id, roster_catalog, playable_rosters, unmatched_world = _build_roster_maps(
        team_file=team_file,
        player_file=player_file,
        world_clubs=world_clubs,
    )
    file_bytes = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(file_bytes)

    rows: list[ContractRow] = []
    parse_errors: list[dict[str, Any]] = []
    for entry in indexed.entries:
        decoded = entry.decode_payload(file_bytes)
        record: PlayerRecord | None = None
        parse_status = "ok"
        try:
            record = PlayerRecord.from_bytes(decoded, int(entry.payload_offset))
            if _display_name(record) in {"", "Unknown Player", "Parse Error"}:
                parse_status = "opaque_preserve"
        except Exception as exc:
            parse_status = "parse_error"
            parse_errors.append(
                {
                    "record_id": int(entry.record_id),
                    "payload_offset": int(entry.payload_offset),
                    "payload_length": int(entry.payload_length),
                    "error": str(exc),
                }
            )
        rows.append(
            _contract_row(
                entry=entry,
                decoded=decoded,
                record=record,
                parse_status=parse_status,
                refs=refs_by_player_id.get(int(entry.record_id), []),
            )
        )

    summary, families = _summarize(rows, playable_rosters, unmatched_world)
    csv_path = output_dir / "variable_player_name_contracts.csv"
    json_path = output_dir / "variable_player_name_contracts.json"
    html_path = output_dir / "variable_player_name_contracts.html"
    _write_csv(csv_path, rows)

    sample_rows: list[dict[str, Any]] = []
    seen_families: set[str] = set()
    for row in rows:
        if row.contract_family in seen_families:
            continue
        sample_rows.append(asdict(row))
        seen_families.add(row.contract_family)
    sample_rows.extend(asdict(row) for row in rows if row.playable_80_ref_count > 0 and len(sample_rows) < 250)

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "player_file": str(player_file),
        "team_file": str(team_file),
        "world_state": str(world_state) if world_state else None,
        "selector_map": str(selector_map) if selector_map else None,
        "summary": summary,
        "contract_families": families,
        "playable_rosters": sorted(playable_rosters, key=lambda row: str(row.get("club_key") or "")),
        "roster_catalog_count": len(roster_catalog),
        "parse_errors": parse_errors,
        "sample_rows": sample_rows,
        "artifacts": {
            "json": str(json_path),
            "csv": str(csv_path),
            "html": str(html_path),
        },
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_html(html_path, payload)
    print(json.dumps({"success": True, **summary, "output_dir": str(output_dir)}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
