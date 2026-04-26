#!/usr/bin/env python3
"""Probe deterministic start-of-season staff mapping (team -> coach slot).

Outputs:
- deterministic linkage audit metrics
- focused team rows (for example Stoke City)
- Premier League 20-club mapping using manager-listing PDF labels
- unresolved placeholder counts for manager/staff names

This is read-only. It does not mutate game/database files.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_EDITOR = REPO_ROOT / "upstream" / "pm99-skezmod-db-editor"

if str(UPSTREAM_EDITOR) not in sys.path:
    sys.path.insert(0, str(UPSTREAM_EDITOR))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from assert_pm99_isolated_input import choose_preferred_game_root, ensure_not_legacy_path
from app.editor_actions import (  # type: ignore
    _load_indexed_coach_slots,
    _team_sequence_sort_key,
    inspect_team_coach_links,
)
from app.editor_sources import gather_team_records  # type: ignore
from app.roster_reconcile import PDF_TEAM_LABEL_TO_QUERY  # type: ignore


@dataclass(frozen=True)
class ManagerListingRow:
    team_label: str
    manager_label: str


def _normalize_spaces(value: str) -> str:
    return " ".join((value or "").split())


def _norm_key(value: str) -> str:
    text = _normalize_spaces(value).upper().replace("&", "AND")
    text = "".join(ch for ch in text if ch.isalnum() or ch.isspace())
    return _normalize_spaces(text)


def _compact_key(value: str) -> str:
    return "".join(ch for ch in _norm_key(value) if ch.isalnum())


def _title_words(text: str) -> str:
    words: list[str] = []
    for token in text.split():
        if len(token) <= 1:
            words.append(token.upper())
            continue
        if "'" in token:
            parts = token.split("'")
            parts = [p[:1].upper() + p[1:].lower() if p else p for p in parts]
            words.append("'".join(parts))
            continue
        words.append(token[:1].upper() + token[1:].lower())
    return " ".join(words)


def _extract_probable_name_from_payload(payload: bytes) -> str | None:
    """Best-effort decode for coach slots still labeled as placeholders."""
    text = "".join(
        ch if 32 <= ord(ch) <= 126 else " "
        for ch in payload.decode("latin-1", "ignore")
    )
    head = text[:320]

    marker_upper = re.search(
        r"a([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+([A-Z][A-Z'\-]{2,}(?:\s+[A-Z][A-Z'\-]{2,})*)",
        head,
    )
    if marker_upper:
        given = _normalize_spaces(marker_upper.group(1))
        surname = _title_words(_normalize_spaces(marker_upper.group(2)))
        full = _normalize_spaces(f"{given} {surname}")
        if full:
            return full

    marker_title = re.search(
        r"a([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})",
        head,
    )
    if marker_title:
        full = _normalize_spaces(marker_title.group(1))
        if full and len(full.split()) >= 2:
            return full

    free_upper = re.search(
        r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+([A-Z][A-Z'\-]{2,}(?:\s+[A-Z][A-Z'\-]{2,})*)\b",
        head,
    )
    if free_upper:
        given = _normalize_spaces(free_upper.group(1))
        surname = _title_words(_normalize_spaces(free_upper.group(2)))
        full = _normalize_spaces(f"{given} {surname}")
        if full:
            return full

    marker_initial = re.search(
        r"\b([A-Z]\.)\s*([A-Z][a-z]{2,}(?:[\s\-][A-Z][a-z]{2,})*)\b",
        head,
    )
    if marker_initial:
        full = _normalize_spaces(f"{marker_initial.group(1)} {marker_initial.group(2)}")
        if full:
            return full

    # Some slots surface compact mixed tokens (for example "cfaMatiura").
    # Strip lower-case prefixes and keep the trailing title-ish token.
    stop_words = {
        "coach",
        "team",
        "club",
        "manager",
        "league",
        "the",
        "and",
        "for",
        "with",
        "from",
        "used",
        "both",
    }
    candidate_tokens: list[str] = []
    for token in re.findall(r"[A-Za-z][A-Za-z'\.\-]{2,}", head[:120]):
        first_upper = next((idx for idx, ch in enumerate(token) if ch.isupper()), None)
        if first_upper is None:
            continue
        core = token[first_upper:]
        if len(core) < 3 or not core[0].isupper():
            continue
        normalized = _title_words(_normalize_spaces(core))
        if normalized.lower() in stop_words:
            continue
        candidate_tokens.append(normalized)

    if candidate_tokens:
        deduped: list[str] = []
        for token in candidate_tokens:
            if token not in deduped:
                deduped.append(token)
        if len(deduped) >= 2 and len(deduped[-2]) == 2 and deduped[-2].endswith("."):
            return _normalize_spaces(f"{deduped[-2]} {deduped[-1]}")
        return deduped[-1]

    return None


def _run_pdftotext(pdf_path: Path, *, layout: bool = False) -> str:
    cmd = ["pdftotext"]
    if layout:
        cmd.append("-layout")
    cmd.extend([str(pdf_path), "-"])
    try:
        return subprocess.check_output(cmd).decode("utf-8", "ignore")
    except FileNotFoundError as exc:
        raise RuntimeError("pdftotext is required but not installed") from exc


def _parse_two_column_listing(pdf_path: Path, title: str) -> list[dict[str, str]]:
    # Plain pdftotext output keeps PM99 listing columns as separate line blocks
    # (all names first, then all teams), which this parser expects.
    text = _run_pdftotext(pdf_path, layout=False)
    rows: list[dict[str, str]] = []
    for page in text.split("\f"):
        lines = [_normalize_spaces(line) for line in page.splitlines() if line.strip()]
        if title not in lines:
            continue
        data_lines: list[str] = []
        started = False
        for line in lines:
            if line == "TEAM":
                started = True
                continue
            if not started:
                continue
            if line in {title, "NAME", "TEAM"}:
                continue
            if line.startswith("Pag."):
                continue
            if line.startswith("Data Base - Premier Manager 99"):
                break
            if line.startswith("(C) Copyright 1998/99 GREMLIN INTERACTIVE"):
                break
            data_lines.append(line)
        if not data_lines:
            continue
        if len(data_lines) % 2 != 0:
            continue
        half = len(data_lines) // 2
        for manager_label, team_label in zip(data_lines[:half], data_lines[half:]):
            rows.append(
                {
                    "manager": _normalize_spaces(manager_label),
                    "team": _normalize_spaces(team_label),
                }
            )
    return rows


def _parse_premier_manager_listing(pdf_dir: Path) -> list[ManagerListingRow]:
    pdf_path = pdf_dir / "Premier League Managers.pdf"
    if not pdf_path.exists():
        return []
    rows = _parse_two_column_listing(pdf_path, "LISTING OF ALL MANAGERS")
    out: list[ManagerListingRow] = []
    for row in rows:
        team_label = _normalize_spaces(str(row.get("team", "")))
        manager_label = _normalize_spaces(str(row.get("manager", "")))
        if not team_label or not manager_label:
            continue
        out.append(ManagerListingRow(team_label=team_label, manager_label=manager_label))
    return out


def _label_set_for_canonical(canonical_team: str) -> set[str]:
    labels = {
        label
        for label, canonical in PDF_TEAM_LABEL_TO_QUERY.items()
        if canonical == canonical_team
    }
    labels.add(canonical_team)
    return {_compact_key(item) for item in labels if item}


def _resolve_team_row(
    *,
    canonical_team: str,
    team_label: str,
    linked_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, int]:
    label_keys = _label_set_for_canonical(canonical_team)
    label_keys.add(_compact_key(team_label))
    candidates: list[dict[str, Any]] = []
    by_compact: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in linked_rows:
        by_compact[_compact_key(str(row.get("team_name", "")))].append(row)
    for key in label_keys:
        candidates.extend(by_compact.get(key, []))
    if not candidates:
        for row in linked_rows:
            team_key = _compact_key(str(row.get("team_name", "")))
            if not team_key:
                continue
            for key in label_keys:
                if not key:
                    continue
                if min(len(team_key), len(key)) < 6:
                    continue
                if team_key.startswith(key) or key.startswith(team_key):
                    candidates.append(row)
                    break
    dedup = {int(item.get("slot_index", -1)): item for item in candidates}
    candidates = list(dedup.values())

    def _score(item: dict[str, Any]) -> tuple[int, int]:
        team_key = _compact_key(str(item.get("team_name", "")))
        deltas = [abs(len(team_key) - len(k)) for k in label_keys if k]
        best_delta = min(deltas) if deltas else 999
        non_eng_penalty = 0 if str(item.get("country", "")) == "England" else 100
        return non_eng_penalty, best_delta

    candidates.sort(key=_score)
    if not candidates:
        return None, 0
    return candidates[0], len(candidates)


def _build_linked_rows(*, team_file: Path, coach_file: Path) -> list[dict[str, Any]]:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        audit = inspect_team_coach_links(
            team_file=str(team_file),
            coach_file=str(coach_file),
            include_links=True,
        )
        team_valid, _team_uncertain = gather_team_records(str(team_file))
        team_entries = sorted(list(team_valid), key=_team_sequence_sort_key)
        coach_slots = _load_indexed_coach_slots(str(coach_file))
    slot_payload_map = {
        int(slot.get("slot_index", -1)): bytes(slot.get("decoded_payload") or b"")
        for slot in coach_slots
    }

    linked_rows: list[dict[str, Any]] = []
    for row in list(audit.get("links") or []):
        slot_index = int(row.get("slot_index", -1) or -1)
        team_entry = team_entries[slot_index] if 0 <= slot_index < len(team_entries) else None
        record = team_entry.record if team_entry is not None else None
        coach_label = str(row.get("coach_name") or "")
        decoded_name = _extract_probable_name_from_payload(slot_payload_map.get(slot_index, b""))
        resolved_name = decoded_name or coach_label
        linked_rows.append(
            {
                "slot_index": slot_index,
                "team_name": str(row.get("team_name") or ""),
                "full_club_name": str(getattr(record, "full_club_name", "") or ""),
                "team_offset": int(row.get("team_offset", 0) or 0),
                "team_id": row.get("team_id"),
                "country": str(getattr(record, "country", "") or ""),
                "league": str(getattr(record, "league", "") or ""),
                "coach_record_id": int(row.get("coach_record_id", 0) or 0),
                "coach_offset": int(row.get("coach_offset", 0) or 0),
                "coach_label": coach_label,
                "coach_decoded_name": decoded_name,
                "coach_resolved_name": resolved_name,
                "coach_name_is_placeholder": coach_label.startswith("Coach "),
            }
        )
    return linked_rows


def _build_payload(
    *,
    team_file: Path,
    coach_file: Path,
    pdf_dir: Path,
    focus_teams: list[str],
) -> dict[str, Any]:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        audit = inspect_team_coach_links(
            team_file=str(team_file),
            coach_file=str(coach_file),
            include_links=True,
        )
    linked_rows = _build_linked_rows(team_file=team_file, coach_file=coach_file)

    premier_slice_rows = [
        row
        for row in linked_rows
        if str(row.get("country") or "") == "England"
        and str(row.get("league") or "") == "Premier League"
    ]

    focus_payload: list[dict[str, Any]] = []
    for focus in focus_teams:
        aliases = _label_set_for_canonical(focus)
        aliases.add(_compact_key(focus))
        for row in linked_rows:
            if _compact_key(str(row.get("team_name", ""))) in aliases or _compact_key(
                str(row.get("full_club_name", ""))
            ) in aliases:
                focus_payload.append(row)

    premier_listing = _parse_premier_manager_listing(pdf_dir)
    premier_rows: list[dict[str, Any]] = []
    for listing in premier_listing:
        canonical_team = PDF_TEAM_LABEL_TO_QUERY.get(listing.team_label, listing.team_label)
        mapped, candidate_count = _resolve_team_row(
            canonical_team=canonical_team,
            team_label=listing.team_label,
            linked_rows=linked_rows,
        )
        mapped_valid = mapped
        if mapped_valid and str(mapped_valid.get("league") or "") != "Premier League":
            mapped_valid = None
        premier_rows.append(
            {
                "team_label": listing.team_label,
                "canonical_team": canonical_team,
                "manager_listing": listing.manager_label,
                "candidate_match_count": candidate_count,
                "mapped": mapped_valid,
            }
        )

    unresolved_premier = 0
    for row in premier_rows:
        mapped = row.get("mapped") or {}
        name = str(mapped.get("coach_resolved_name") or "")
        if name.startswith("Coach "):
            unresolved_premier += 1

    premier_slice_placeholder_count = sum(
        1
        for row in premier_slice_rows
        if str(row.get("coach_resolved_name") or "").startswith("Coach ")
    )

    return {
        "audit": {
            "ok": bool(audit.get("ok")),
            "team_count": int(audit.get("team_count", 0) or 0),
            "coach_slot_count": int(audit.get("coach_slot_count", 0) or 0),
            "decoded_link_count": int(audit.get("decoded_link_count", 0) or 0),
            "unresolved_count": int(audit.get("unresolved_count", 0) or 0),
            "inconsistent_count": int(audit.get("inconsistent_count", 0) or 0),
            "coverage_ratio": float(audit.get("coverage_ratio", 0.0) or 0.0),
            "reproducibility_hash": str(audit.get("reproducibility_hash") or ""),
        },
        "inputs": {
            "team_file": str(team_file),
            "coach_file": str(coach_file),
            "pdf_dir": str(pdf_dir),
            "focus_teams": list(focus_teams),
        },
        "focus_rows": focus_payload,
        "premier_league_slice_rows": sorted(
            premier_slice_rows,
            key=lambda item: int(item.get("slot_index", -1) or -1),
        ),
        "premier_league_slice_row_count": len(premier_slice_rows),
        "premier_league_slice_placeholder_count": premier_slice_placeholder_count,
        "premier_league_listing_count": len(premier_listing),
        "premier_league_rows": premier_rows,
        "premier_league_unresolved_name_count": unresolved_premier,
    }


def _print_text(payload: dict[str, Any]) -> None:
    audit = dict(payload.get("audit") or {})
    print("Start-of-Season Staff Probe")
    print(
        "Deterministic link audit: "
        + f"ok={bool(audit.get('ok'))} "
        + f"decoded={int(audit.get('decoded_link_count') or 0)}/{int(audit.get('team_count') or 0)} "
        + f"unresolved={int(audit.get('unresolved_count') or 0)} "
        + f"inconsistent={int(audit.get('inconsistent_count') or 0)} "
        + f"coverage={float(audit.get('coverage_ratio') or 0.0):.4f}"
    )
    print(f"reproducibility_hash={str(audit.get('reproducibility_hash') or '')}")

    focus_rows = list(payload.get("focus_rows") or [])
    print("\nFocus Team Rows")
    if not focus_rows:
        print("No focus-team rows resolved.")
    else:
        for row in sorted(focus_rows, key=lambda item: int(item.get("slot_index", -1) or -1)):
            print(
                f"{str(row.get('team_name') or '')} ({str(row.get('league') or '')}) -> "
                + f"{str(row.get('coach_resolved_name') or '')} "
                + f"[slot={int(row.get('slot_index') or 0):03d}, coach_record_id={int(row.get('coach_record_id') or 0)}]"
            )

    print("\nPremier League (DB Slice)")
    print(
        f"rows={int(payload.get('premier_league_slice_row_count') or 0)} "
        + f"placeholder_names={int(payload.get('premier_league_slice_placeholder_count') or 0)}"
    )
    for row in list(payload.get("premier_league_slice_rows") or []):
        print(
            f"{int(row.get('slot_index') or 0):02d} "
            + f"{str(row.get('team_name') or '')} -> "
            + f"{str(row.get('coach_resolved_name') or '')}"
        )

    print("\nPremier League (Manager Listing Aligned)")
    print(
        f"rows={int(payload.get('premier_league_listing_count') or 0)} "
        + f"unresolved_names={int(payload.get('premier_league_unresolved_name_count') or 0)}"
    )
    for row in sorted(
        list(payload.get("premier_league_rows") or []),
        key=lambda item: str(item.get("canonical_team") or ""),
    ):
        mapped = dict(row.get("mapped") or {})
        if not mapped:
            print(
                f"{str(row.get('canonical_team') or '')} | manager_listing={str(row.get('manager_listing') or '')} | "
                + "mapped=NONE"
            )
            continue
        print(
            f"{str(row.get('canonical_team') or '')} | manager_listing={str(row.get('manager_listing') or '')} | "
            + f"mapped_team={str(mapped.get('team_name') or '')} | "
            + f"staff={str(mapped.get('coach_resolved_name') or '')} | "
            + f"slot={int(mapped.get('slot_index') or 0):03d}"
        )


def main() -> int:
    default_game_root = choose_preferred_game_root()
    parser = argparse.ArgumentParser(
        description="Probe deterministic start-of-season staff mapping (team -> coach slot)."
    )
    parser.add_argument(
        "--team-file",
        default=str(default_game_root / "DBDAT" / "EQ98030.FDI"),
        help="Path to EQ98030.FDI",
    )
    parser.add_argument(
        "--coach-file",
        default=str(default_game_root / "DBDAT" / "ENT98030.FDI"),
        help="Path to ENT98030.FDI",
    )
    parser.add_argument(
        "--pdf-dir",
        default=str(REPO_ROOT / ".local" / "PM99RE-demo-pdfs"),
        help="Directory containing manager listing PDFs",
    )
    parser.add_argument(
        "--focus-team",
        action="append",
        default=["Stoke City"],
        help="Canonical team to include in focus rows (repeatable)",
    )
    parser.add_argument(
        "--json-output",
        help="Optional output JSON file path",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON payload to stdout",
    )
    args = parser.parse_args()

    payload = _build_payload(
        team_file=ensure_not_legacy_path(args.team_file, label="EQ file"),
        coach_file=ensure_not_legacy_path(args.coach_file, label="coach file"),
        pdf_dir=Path(str(args.pdf_dir)).expanduser().resolve(),
        focus_teams=[_normalize_spaces(item) for item in list(args.focus_team or []) if str(item).strip()],
    )

    if args.json_output:
        out_path = Path(str(args.json_output)).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        _print_text(payload)
        if args.json_output:
            print(f"\nJSON report: {Path(str(args.json_output)).expanduser().resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
