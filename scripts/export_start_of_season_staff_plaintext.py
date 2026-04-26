#!/usr/bin/env python3
"""Export deterministic plaintext start-of-season staff proof artifacts.

This wraps the existing probe logic and writes flat proof outputs for:
- focus team staff rows (default: Stoke City)
- all 20 Premier League manager-listing clubs, preserving deterministic
  best-match rows even when the local DB league label differs

This is read-only with respect to game/database files.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

import probe_start_season_staff as probe


def _normalize_spaces(value: str) -> str:
    return " ".join((value or "").split())


def _row_name_source(row: dict[str, Any]) -> str:
    if str(row.get("coach_decoded_name") or "").strip():
        return "decoded_payload"
    if str(row.get("coach_label") or "").startswith("Coach "):
        return "placeholder_slot_label"
    return "stored_label"


def _flatten_team_row(row: dict[str, Any]) -> dict[str, Any]:
    staff_name = str(row.get("coach_resolved_name") or "")
    return {
        "slot_index": int(row.get("slot_index", -1) or -1),
        "team_name": str(row.get("team_name") or ""),
        "full_club_name": str(row.get("full_club_name") or ""),
        "country": str(row.get("country") or ""),
        "league": str(row.get("league") or ""),
        "coach_record_id": row.get("coach_record_id"),
        "coach_offset": row.get("coach_offset"),
        "staff_name": staff_name,
        "coach_label": str(row.get("coach_label") or ""),
        "name_source": _row_name_source(row),
        "placeholder_name": staff_name.startswith("Coach "),
    }


def _build_focus_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [_flatten_team_row(row) for row in list(payload.get("focus_rows") or [])]


def _build_premier_listing_rows_all(payload: dict[str, Any], pdf_dir: Path) -> list[dict[str, Any]]:
    linked_rows = probe._build_linked_rows(
        team_file=Path(str(payload["inputs"]["team_file"])),
        coach_file=Path(str(payload["inputs"]["coach_file"])),
    )
    rows: list[dict[str, Any]] = []
    for listing in probe._parse_premier_manager_listing(pdf_dir):
        canonical_team = probe.PDF_TEAM_LABEL_TO_QUERY.get(listing.team_label, listing.team_label)
        mapped, candidate_count = probe._resolve_team_row(
            canonical_team=canonical_team,
            team_label=listing.team_label,
            linked_rows=linked_rows,
        )
        flat = {
            "team_label": listing.team_label,
            "canonical_team": canonical_team,
            "manager_listing": listing.manager_label,
            "candidate_match_count": int(candidate_count),
            "mapping_status": "mapped" if mapped else "missing_map",
        }
        if mapped:
            flat.update(_flatten_team_row(mapped))
            if str(flat["league"]) != "Premier League":
                flat["mapping_status"] = "league_mismatch"
        else:
            flat.update(
                {
                    "slot_index": -1,
                    "team_name": "",
                    "full_club_name": "",
                    "country": "",
                    "league": "",
                    "coach_record_id": None,
                    "coach_offset": None,
                    "staff_name": "",
                    "coach_label": "",
                    "name_source": "",
                    "placeholder_name": False,
                }
            )
        rows.append(flat)
    return rows


def _build_summary(
    payload: dict[str, Any],
    focus_rows: list[dict[str, Any]],
    premier_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    audit = dict(payload.get("audit") or {})
    return {
        "reproducibility_hash": str(audit.get("reproducibility_hash") or ""),
        "decoded_link_count": int(audit.get("decoded_link_count") or 0),
        "team_count": int(audit.get("team_count") or 0),
        "focus_club_count": len(focus_rows),
        "focus_staff_entry_count": sum(
            1 for row in focus_rows if str(row.get("staff_name") or "").strip()
        ),
        "premier_league_club_count": len(premier_rows),
        "premier_league_staff_entry_count": sum(
            1 for row in premier_rows if str(row.get("staff_name") or "").strip()
        ),
        "premier_league_mapped_count": sum(
            1 for row in premier_rows if row.get("mapping_status") == "mapped"
        ),
        "premier_league_league_mismatch_count": sum(
            1 for row in premier_rows if row.get("mapping_status") == "league_mismatch"
        ),
        "premier_league_missing_map_count": sum(
            1 for row in premier_rows if row.get("mapping_status") == "missing_map"
        ),
        "premier_league_placeholder_name_count": sum(
            1 for row in premier_rows if row.get("placeholder_name")
        ),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "team_label",
        "canonical_team",
        "manager_listing",
        "mapping_status",
        "candidate_match_count",
        "slot_index",
        "team_name",
        "full_club_name",
        "country",
        "league",
        "coach_record_id",
        "coach_offset",
        "staff_name",
        "coach_label",
        "name_source",
        "placeholder_name",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def _write_stoke_txt(path: Path, rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    lines = [
        "Stoke City Start-of-Season Staff Proof",
        f"reproducibility_hash={summary['reproducibility_hash']}",
        f"focus_club_count={summary['focus_club_count']}",
        f"focus_staff_entry_count={summary['focus_staff_entry_count']}",
        "",
    ]
    for row in rows:
        lines.append(
            " | ".join(
                [
                    f"full_club_name={row['full_club_name']}",
                    f"team_name={row['team_name']}",
                    f"league={row['league']}",
                    f"slot_index={row['slot_index']}",
                    f"coach_record_id={row['coach_record_id']}",
                    f"coach_offset={row['coach_offset']}",
                    f"staff_name={row['staff_name']}",
                    f"name_source={row['name_source']}",
                ]
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_premier_txt(path: Path, rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    lines = [
        "Premier League Start-of-Season Staff Proof",
        f"reproducibility_hash={summary['reproducibility_hash']}",
        f"club_count={summary['premier_league_club_count']}",
        f"staff_entry_count={summary['premier_league_staff_entry_count']}",
        f"mapped_count={summary['premier_league_mapped_count']}",
        f"league_mismatch_count={summary['premier_league_league_mismatch_count']}",
        f"missing_map_count={summary['premier_league_missing_map_count']}",
        "",
    ]
    for row in rows:
        lines.append(
            " | ".join(
                [
                    f"canonical_team={row['canonical_team']}",
                    f"manager_listing={row['manager_listing']}",
                    f"mapping_status={row['mapping_status']}",
                    f"mapped_team={row['team_name']}",
                    f"local_league={row['league']}",
                    f"slot_index={row['slot_index']}",
                    f"coach_record_id={row['coach_record_id']}",
                    f"staff_name={row['staff_name']}",
                    f"name_source={row['name_source']}",
                ]
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export deterministic plaintext start-of-season staff proof artifacts."
    )
    parser.add_argument(
        "--team-file",
        default=str(REPO_ROOT / "DBDAT" / "EQ98030.FDI"),
        help="Path to EQ98030.FDI",
    )
    parser.add_argument(
        "--coach-file",
        default=str(REPO_ROOT / "DBDAT" / "ENT98030.FDI"),
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
        "--output-dir",
        default=str(REPO_ROOT / "docs" / "artifacts" / "staff_extraction"),
        help="Directory for proof artifacts",
    )
    args = parser.parse_args()

    team_file = Path(str(args.team_file)).expanduser().resolve()
    coach_file = Path(str(args.coach_file)).expanduser().resolve()
    pdf_dir = Path(str(args.pdf_dir)).expanduser().resolve()
    output_dir = Path(str(args.output_dir)).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat().replace("-", "")

    payload = probe._build_payload(
        team_file=team_file,
        coach_file=coach_file,
        pdf_dir=pdf_dir,
        focus_teams=[
            _normalize_spaces(item) for item in list(args.focus_team or []) if str(item).strip()
        ],
    )
    focus_rows = _build_focus_rows(payload)
    premier_rows = _build_premier_listing_rows_all(payload, pdf_dir)
    summary = _build_summary(payload, focus_rows, premier_rows)

    proof_payload = {
        "summary": summary,
        "inputs": dict(payload.get("inputs") or {}),
        "focus_rows": focus_rows,
        "premier_league_rows": premier_rows,
    }

    json_path = output_dir / f"start_of_season_staff_proof_{stamp}.json"
    csv_path = output_dir / f"premier_league_start_of_season_staff_{stamp}.csv"
    stoke_txt_path = output_dir / f"stoke_city_start_of_season_staff_{stamp}.txt"
    premier_txt_path = output_dir / f"premier_league_start_of_season_staff_{stamp}.txt"

    _write_json(json_path, proof_payload)
    _write_csv(csv_path, premier_rows)
    _write_stoke_txt(stoke_txt_path, focus_rows, summary)
    _write_premier_txt(premier_txt_path, premier_rows, summary)

    print(f"output_dir={output_dir}")
    print(f"json={json_path}")
    print(f"csv={csv_path}")
    print(f"stoke_txt={stoke_txt_path}")
    print(f"premier_txt={premier_txt_path}")
    print(
        "counts="
        + json.dumps(
            {
                "decoded_link_count": summary["decoded_link_count"],
                "team_count": summary["team_count"],
                "focus_club_count": summary["focus_club_count"],
                "focus_staff_entry_count": summary["focus_staff_entry_count"],
                "premier_league_club_count": summary["premier_league_club_count"],
                "premier_league_staff_entry_count": summary["premier_league_staff_entry_count"],
                "premier_league_mapped_count": summary["premier_league_mapped_count"],
                "premier_league_league_mismatch_count": summary[
                    "premier_league_league_mismatch_count"
                ],
                "premier_league_missing_map_count": summary["premier_league_missing_map_count"],
            },
            ensure_ascii=False,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
