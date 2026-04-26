#!/usr/bin/env python3
"""Validate package-encoded staff names vs in-game surfaced names.

This probe is read-only. It does not mutate game/database files.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_EDITOR = REPO_ROOT / "upstream" / "pm99-skezmod-db-editor"

if str(UPSTREAM_EDITOR) not in sys.path:
    sys.path.insert(0, str(UPSTREAM_EDITOR))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from assert_pm99_isolated_input import choose_preferred_game_root, ensure_not_legacy_path
from app.editor_actions import _load_indexed_coach_slots  # type: ignore
from app.editor_sources import gather_coach_records  # type: ignore


def _normalize_spaces(value: str) -> str:
    return " ".join((value or "").split())


def _surname_key(value: str) -> str:
    tokens = re.findall(r"[A-Za-z']+", value or "")
    if not tokens:
        return ""
    return tokens[-1].lower().replace("'", "")


def _iter_json_strings(payload: Any) -> Iterable[str]:
    if isinstance(payload, dict):
        for value in payload.values():
            yield from _iter_json_strings(value)
        return
    if isinstance(payload, list):
        for value in payload:
            yield from _iter_json_strings(value)
        return
    if isinstance(payload, str):
        yield payload


def _extract_name_hits(record: Any, target_name: str) -> list[dict[str, Any]]:
    target_norm = _normalize_spaces(target_name).lower()
    hits: list[dict[str, Any]] = []
    for entry in record:
        coach = entry.record
        full_name = _normalize_spaces(getattr(coach, "full_name", "") or "")
        given_name = _normalize_spaces(getattr(coach, "given_name", "") or "")
        surname = _normalize_spaces(getattr(coach, "surname", "") or "")
        joined = _normalize_spaces(f"{given_name} {surname}")

        candidates = [full_name.lower(), joined.lower(), given_name.lower(), surname.lower()]
        if not any(target_norm == item for item in candidates if item):
            continue
        hits.append(
            {
                "offset": int(entry.offset),
                "full_name": full_name,
                "given_name": given_name,
                "surname": surname,
            }
        )
    return hits


def _probe_coach_file(path: Path, target_name: str) -> dict[str, Any]:
    valid_records, uncertain_records = gather_coach_records(str(path))
    slots = _load_indexed_coach_slots(str(path))

    placeholder_slots = sum(
        1 for slot in slots if str(slot.get("coach_name") or "").startswith("Coach ")
    )
    decoded_named_slots = sum(
        1
        for slot in slots
        if str(slot.get("coach_name") or "").strip()
        and not str(slot.get("coach_name") or "").startswith("Coach ")
    )
    target_hits = _extract_name_hits(valid_records, target_name)

    return {
        "file": str(path),
        "valid_record_count": len(valid_records),
        "uncertain_record_count": len(uncertain_records),
        "slot_count": len(slots),
        "placeholder_slot_count": int(placeholder_slots),
        "decoded_named_slot_count": int(decoded_named_slots),
        "target_name": target_name,
        "target_hits": target_hits,
    }


def _raw_plaintext_presence(path: Path, needle: str) -> bool:
    lower = path.read_bytes().lower()
    return needle.lower().encode("latin-1", "ignore") in lower


def _run_staff_probe(
    *,
    team_file: Path,
    coach_file: Path,
    pdf_dir: Path,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "probe_start_season_staff.py"),
        "--team-file",
        str(team_file),
        "--coach-file",
        str(coach_file),
        "--pdf-dir",
        str(pdf_dir),
        "--json",
    ]
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(proc.stdout)


def _premier_alignment(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out_rows: list[dict[str, Any]] = []
    surname_match_count = 0
    surname_mismatch_count = 0
    placeholder_count = 0
    missing_map_count = 0

    for row in rows:
        mapped = row.get("mapped")
        manager_listing = str(row.get("manager_listing") or "")
        listing_key = _surname_key(manager_listing)
        mapped_name = "NONE"
        status = "missing_map"
        if mapped:
            mapped_name = str(mapped.get("coach_resolved_name") or "")
            if mapped_name.startswith("Coach "):
                status = "placeholder"
                placeholder_count += 1
            else:
                mapped_key = _surname_key(mapped_name)
                if mapped_key and mapped_key == listing_key:
                    status = "surname_match"
                    surname_match_count += 1
                else:
                    status = "surname_mismatch"
                    surname_mismatch_count += 1
        else:
            missing_map_count += 1

        out_rows.append(
            {
                "team_label": str(row.get("team_label") or ""),
                "manager_listing": manager_listing,
                "mapped_staff": mapped_name,
                "status": status,
            }
        )

    return {
        "row_count": len(out_rows),
        "surname_match_count": surname_match_count,
        "surname_mismatch_count": surname_mismatch_count,
        "placeholder_count": placeholder_count,
        "missing_map_count": missing_map_count,
        "rows": out_rows,
    }


def _extract_excerpt(text: str, needle: str, radius: int = 64) -> str:
    idx = text.lower().find(needle.lower())
    if idx < 0:
        return _normalize_spaces(text[: radius * 2])
    start = max(0, idx - radius)
    end = min(len(text), idx + len(needle) + radius)
    return _normalize_spaces(text[start:end])


def _scan_runner_summaries(
    *,
    runner_root: Path,
    names: list[str],
    sample_limit: int = 3,
) -> dict[str, Any]:
    summary_files = sorted(p for p in runner_root.glob("**/summary.json") if p.is_file())
    hits: dict[str, dict[str, Any]] = {
        name: {"hit_count": 0, "files": set(), "samples": []} for name in names
    }

    for summary_file in summary_files:
        try:
            payload = json.loads(summary_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        for text in _iter_json_strings(payload):
            clean = text.strip()
            if not clean:
                continue
            lower = clean.lower()
            for name in names:
                needle = name.lower()
                count = lower.count(needle)
                if count <= 0:
                    continue
                bucket = hits[name]
                bucket["hit_count"] += count
                bucket["files"].add(str(summary_file))
                if len(bucket["samples"]) < sample_limit:
                    bucket["samples"].append(
                        {
                            "file": str(summary_file),
                            "excerpt": _extract_excerpt(clean, name),
                        }
                    )

    normalized: dict[str, Any] = {}
    for name, bucket in hits.items():
        normalized[name] = {
            "hit_count": int(bucket["hit_count"]),
            "file_count": len(bucket["files"]),
            "samples": bucket["samples"],
        }
    return {
        "runner_root": str(runner_root),
        "summary_file_count": len(summary_files),
        "name_hits": normalized,
    }


def _build_validation_report(args: argparse.Namespace) -> dict[str, Any]:
    coach_files = [
        Path(str(args.coach_file)).expanduser().resolve(),
        Path(str(args.install_coach_file)).expanduser().resolve(),
    ]
    coach_file_reports = [
        _probe_coach_file(path, args.target_name)
        for path in coach_files
        if path.exists()
    ]
    plaintext_presence = [
        {
            "file": str(path),
            "target_plaintext_present": _raw_plaintext_presence(path, args.target_name),
        }
        for path in coach_files
        if path.exists()
    ]

    staff_probe_payload = _run_staff_probe(
        team_file=Path(str(args.team_file)).expanduser().resolve(),
        coach_file=Path(str(args.coach_file)).expanduser().resolve(),
        pdf_dir=Path(str(args.pdf_dir)).expanduser().resolve(),
    )
    premier_alignment = _premier_alignment(
        list(staff_probe_payload.get("premier_league_rows") or [])
    )

    stoke_rows = [
        row
        for row in list(staff_probe_payload.get("focus_rows") or [])
        if _normalize_spaces(str(row.get("full_club_name") or "")).lower() == "stoke city"
        or _normalize_spaces(str(row.get("team_name") or "")).lower() in {"stoke c.", "stoke city"}
    ]

    target_surname = _surname_key(args.target_name)
    scan_names = [args.target_name]
    if target_surname and target_surname not in [name.lower() for name in scan_names]:
        scan_names.append(target_surname)
    scan_names.extend(["strachan", "ferguson", "wenger"])
    runner_probe = _scan_runner_summaries(
        runner_root=Path(str(args.runner_root)).expanduser().resolve(),
        names=scan_names,
        sample_limit=int(args.sample_limit),
    )

    target_hit_count = int(runner_probe["name_hits"].get(args.target_name, {}).get("hit_count", 0))
    target_surname_hit_count = int(runner_probe["name_hits"].get(target_surname, {}).get("hit_count", 0))
    package_hits = sum(len(item.get("target_hits") or []) for item in coach_file_reports)
    plaintext_hits = sum(1 for item in plaintext_presence if item.get("target_plaintext_present"))

    verdict = {
        "target_name": args.target_name,
        "target_in_package_decoded_records": package_hits > 0,
        "target_in_raw_plaintext_bytes": plaintext_hits > 0,
        "target_in_runner_ocr_exact": target_hit_count > 0,
        "target_surname_in_runner_ocr": target_surname_hit_count > 0,
    }

    return {
        "inputs": {
            "team_file": str(Path(str(args.team_file)).expanduser().resolve()),
            "coach_file": str(Path(str(args.coach_file)).expanduser().resolve()),
            "install_coach_file": str(Path(str(args.install_coach_file)).expanduser().resolve()),
            "pdf_dir": str(Path(str(args.pdf_dir)).expanduser().resolve()),
            "runner_root": str(Path(str(args.runner_root)).expanduser().resolve()),
        },
        "coach_file_reports": coach_file_reports,
        "plaintext_presence": plaintext_presence,
        "stoke_focus_rows": stoke_rows,
        "premier_league_alignment": premier_alignment,
        "runner_ocr_probe": runner_probe,
        "verdict": verdict,
    }


def _print_text_report(report: dict[str, Any]) -> None:
    verdict = dict(report.get("verdict") or {})
    print("Staff Encoding Validation")
    print("=========================")
    print(
        "Target: "
        + str(verdict.get("target_name") or "")
        + " | package_decoded="
        + str(verdict.get("target_in_package_decoded_records"))
        + " | raw_plaintext="
        + str(verdict.get("target_in_raw_plaintext_bytes"))
        + " | runner_exact="
        + str(verdict.get("target_in_runner_ocr_exact"))
    )
    print("")

    print("Coach File Reports")
    print("------------------")
    for item in list(report.get("coach_file_reports") or []):
        hits = item.get("target_hits") or []
        hit_text = ", ".join(
            f"offset={int(hit.get('offset') or 0)} name={str(hit.get('full_name') or '')}"
            for hit in hits
        ) or "none"
        print(
            f"{item.get('file')}: valid={int(item.get('valid_record_count') or 0)}, "
            + f"slots={int(item.get('slot_count') or 0)}, "
            + f"placeholder_slots={int(item.get('placeholder_slot_count') or 0)}, "
            + f"decoded_named_slots={int(item.get('decoded_named_slot_count') or 0)}"
        )
        print(f"  target_hits: {hit_text}")
    for item in list(report.get("plaintext_presence") or []):
        print(
            f"{item.get('file')}: raw_plaintext_target_present={bool(item.get('target_plaintext_present'))}"
        )
    print("")

    stoke_rows = list(report.get("stoke_focus_rows") or [])
    print("Stoke Focus Row")
    print("---------------")
    if not stoke_rows:
        print("No Stoke City rows found.")
    for row in stoke_rows:
        print(
            f"{row.get('team_name')} ({row.get('league')}) -> {row.get('coach_resolved_name')} "
            + f"[slot={int(row.get('slot_index') or 0):03d}, record_id={int(row.get('coach_record_id') or 0)}, "
            + f"offset={int(row.get('coach_offset') or 0)}]"
        )
    print("")

    premier = dict(report.get("premier_league_alignment") or {})
    print("Premier League Alignment")
    print("------------------------")
    print(
        f"rows={int(premier.get('row_count') or 0)}, "
        + f"surname_match={int(premier.get('surname_match_count') or 0)}, "
        + f"surname_mismatch={int(premier.get('surname_mismatch_count') or 0)}, "
        + f"placeholder={int(premier.get('placeholder_count') or 0)}, "
        + f"missing_map={int(premier.get('missing_map_count') or 0)}"
    )
    for row in list(premier.get("rows") or []):
        print(
            f"{row.get('team_label')} | manager_listing={row.get('manager_listing')} "
            + f"| mapped_staff={row.get('mapped_staff')} | status={row.get('status')}"
        )
    print("")

    runner = dict(report.get("runner_ocr_probe") or {})
    print("Runner OCR Probe")
    print("----------------")
    print(
        f"root={runner.get('runner_root')} | summary_files={int(runner.get('summary_file_count') or 0)}"
    )
    for name, payload in dict(runner.get("name_hits") or {}).items():
        print(
            f"{name}: hit_count={int(payload.get('hit_count') or 0)}, "
            + f"file_count={int(payload.get('file_count') or 0)}"
        )
        for sample in list(payload.get("samples") or []):
            print(
                f"  sample={sample.get('file')} :: {sample.get('excerpt')}"
            )


def parse_args() -> argparse.Namespace:
    default_game_root = choose_preferred_game_root()
    parser = argparse.ArgumentParser(
        description="Validate encoded staff names in package files against in-game OCR artifacts."
    )
    parser.add_argument(
        "--team-file",
        default=str(default_game_root / "DBDAT" / "EQ98030.FDI"),
        help="Team FDI path",
    )
    parser.add_argument(
        "--coach-file",
        default=str(default_game_root / "DBDAT" / "ENT98030.FDI"),
        help="Coach FDI path used by the editor/research package",
    )
    parser.add_argument(
        "--install-coach-file",
        default=str(default_game_root / "DBDAT" / "ENT98030.FDI"),
        help="Coach FDI path from installed game data",
    )
    parser.add_argument(
        "--pdf-dir",
        default=str(REPO_ROOT / ".local" / "PM99RE-demo-pdfs"),
        help="Directory containing manager listing PDFs",
    )
    parser.add_argument(
        "--runner-root",
        default=str(REPO_ROOT / "upstream" / "pm99-skezmod-db-editor" / "docs" / "artifacts" / "pm99_runner"),
        help="Runner artifacts root containing summary.json files",
    )
    parser.add_argument(
        "--target-name",
        default="Trevor Francis",
        help="Exact target staff name to validate",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=3,
        help="Maximum OCR sample excerpts per tracked name",
    )
    parser.add_argument(
        "--json-output",
        default="",
        help="Optional path to write JSON report",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON payload to stdout",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.team_file = str(ensure_not_legacy_path(args.team_file, label="team file"))
    args.coach_file = str(ensure_not_legacy_path(args.coach_file, label="coach file"))
    args.install_coach_file = str(ensure_not_legacy_path(args.install_coach_file, label="install coach file"))
    report = _build_validation_report(args)

    json_output = str(args.json_output or "").strip()
    if json_output:
        output_path = Path(json_output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_text_report(report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
