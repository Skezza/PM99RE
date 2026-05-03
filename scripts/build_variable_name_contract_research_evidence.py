#!/usr/bin/env python3
"""Build an evidence pack for variable-name contract research outputs."""

from __future__ import annotations

import argparse
import html
import json
import os
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_ROOT = REPO_ROOT / "upstream" / "pm99-runner" / "scripts" / "pm99_runner"
DEFAULT_LATEST_FILE = REPO_ROOT / ".local" / "latest_variable_name_contract_research_dir.txt"
SQUAD_SCREEN_DHASH_16 = int(
    "744c51cc87274f2719af192f192e1b2e592e5b2f192e1b2e1b2e1b2e1b2f859f",
    16,
)
TRANSFER_SCREEN_DHASH_16 = int(
    "724c514c554f155d155cd55d975c955d855d975d955d075d955d955c339f258f",
    16,
)
SCREEN_DHASH_THRESHOLD = 40


def _read_json(path: Path) -> dict[str, Any] | list[Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _resolve_out_dir(cli_out_dir: str | None, latest_file: Path) -> Path:
    if cli_out_dir:
        return Path(cli_out_dir).expanduser().resolve()
    try:
        raw = latest_file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise SystemExit(f"Unable to read latest-output pointer: {latest_file} ({exc})") from exc
    if not raw:
        raise SystemExit(f"Latest-output pointer is empty: {latest_file}")
    return (REPO_ROOT / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return os.path.relpath(path, root).replace(os.sep, "/")


def _discover_static_contracts(out_dir: Path) -> dict[str, Any]:
    contracts_dir = out_dir / "contracts"
    contract_json = contracts_dir / "variable_player_name_contracts.json"
    stdout_json = out_dir / "contracts_stdout.json"
    contract_payload = _read_json(contract_json)
    stdout_payload = _read_json(stdout_json)

    family_counts: dict[str, int] = {}
    if isinstance(stdout_payload, dict):
        family_counts.update(
            {
                str(key): int(value)
                for key, value in (stdout_payload.get("contract_family_counts") or {}).items()
            }
        )
    if not family_counts and isinstance(contract_payload, dict):
        for row in contract_payload.get("contract_families") or []:
            if isinstance(row, dict) and row.get("contract_family") is not None:
                family_counts[str(row["contract_family"])] = int(row.get("count") or 0)

    total_indexed_entries = None
    playable_80_total = None
    parse_ok_count = None
    playable_80_player_records = None
    foreign_or_non_playable_player_records = None
    opaque_or_non_player_count = None
    unlinked_player_records = None
    contract_status_counts: dict[str, int] = {}
    if isinstance(stdout_payload, dict):
        total_indexed_entries = stdout_payload.get("total_indexed_entries")
        playable_80_total = stdout_payload.get("playable_80_roster_count")
        parse_ok_count = stdout_payload.get("parse_ok_count")
        playable_80_player_records = stdout_payload.get("playable_80_player_records")
        foreign_or_non_playable_player_records = stdout_payload.get("foreign_or_non_playable_player_records")
        opaque_or_non_player_count = stdout_payload.get("opaque_or_non_player_count")
        unlinked_player_records = stdout_payload.get("unlinked_player_records")
        contract_status_counts.update(
            {
                str(key): int(value)
                for key, value in (stdout_payload.get("contract_status_counts") or {}).items()
            }
        )
    if total_indexed_entries is None:
        indexed_audit = _read_json(out_dir / "player_indexed_directory_audit.json")
        if isinstance(indexed_audit, dict):
            total_indexed_entries = indexed_audit.get("directory_entry_count")
    if isinstance(contract_payload, dict):
        summary = contract_payload.get("summary")
        if isinstance(summary, dict):
            parse_ok_count = parse_ok_count if parse_ok_count is not None else summary.get("parse_ok_count")
            playable_80_player_records = (
                playable_80_player_records
                if playable_80_player_records is not None
                else summary.get("playable_80_player_records")
            )
            foreign_or_non_playable_player_records = (
                foreign_or_non_playable_player_records
                if foreign_or_non_playable_player_records is not None
                else summary.get("foreign_or_non_playable_player_records")
            )
            opaque_or_non_player_count = (
                opaque_or_non_player_count
                if opaque_or_non_player_count is not None
                else summary.get("opaque_or_non_player_count")
            )
            unlinked_player_records = (
                unlinked_player_records if unlinked_player_records is not None else summary.get("unlinked_player_records")
            )
            if not contract_status_counts:
                contract_status_counts.update(
                    {str(key): int(value) for key, value in (summary.get("contract_status_counts") or {}).items()}
                )

    return {
        "contracts_json": contract_json if contract_json.is_file() else None,
        "contracts_stdout_json": stdout_json if stdout_json.is_file() else None,
        "contract_payload": contract_payload if isinstance(contract_payload, dict) else None,
        "stdout_payload": stdout_payload if isinstance(stdout_payload, dict) else None,
        "contract_family_counts": dict(sorted(family_counts.items())),
        "contract_status_counts": dict(sorted(contract_status_counts.items())),
        "total_indexed_entries": int(total_indexed_entries or 0),
        "parse_ok_count": int(parse_ok_count or 0),
        "playable_80_total": int(playable_80_total or 0),
        "playable_80_player_records": int(playable_80_player_records or 0),
        "foreign_or_non_playable_player_records": int(foreign_or_non_playable_player_records or 0),
        "opaque_or_non_player_count": int(opaque_or_non_player_count or 0),
        "unlinked_player_records": int(unlinked_player_records or 0),
    }


def _infer_route_kind(label: str) -> str | None:
    value = str(label or "")
    if "squad" in value:
        return "squad"
    if "transfer" in value:
        return "transfers"
    return None


def _step_label(step: dict[str, Any]) -> str:
    node = step.get("step")
    if isinstance(node, dict):
        return str(node.get("label") or "")
    return ""


def _route_expected_screen(route_kind: str) -> str | None:
    if route_kind == "squad":
        return "squad_management_screen"
    if route_kind == "transfers":
        return "transfer_market_screen"
    return None


def _route_is_valid(summary_payload: dict[str, Any] | None, route_kind: str) -> bool:
    if not isinstance(summary_payload, dict):
        return False
    route_summaries = summary_payload.get("route_summaries")
    if isinstance(route_summaries, dict):
        route_summary = route_summaries.get(route_kind)
        if isinstance(route_summary, dict):
            return bool(route_summary.get("expected_screen_matched")) and not bool(route_summary.get("classification_skipped"))

    expected_screen = _route_expected_screen(route_kind)
    if expected_screen is None:
        return False
    for step in summary_payload.get("steps") or []:
        if not isinstance(step, dict):
            continue
        classification = step.get("screen_classification")
        if not isinstance(classification, dict):
            continue
        if classification.get("screen") == expected_screen and not bool(classification.get("classification_skipped")):
            return True
    return False


def _representative_screenshot_candidates(
    case: dict[str, Any], summary_payload: dict[str, Any] | None, route_kind: str
) -> list[str]:
    expected_screen = _route_expected_screen(route_kind)
    candidates: list[str] = []
    seen: set[str] = set()

    def _add(screenshot: str) -> None:
        if screenshot and screenshot not in seen:
            seen.add(screenshot)
            candidates.append(screenshot)

    if isinstance(summary_payload, dict):
        for step in summary_payload.get("steps") or []:
            if not isinstance(step, dict):
                continue
            label = _step_label(step)
            screenshot = step.get("screenshot")
            if not screenshot:
                continue
            classification = step.get("screen_classification")
            screen = classification.get("screen") if isinstance(classification, dict) else None
            if expected_screen and screen == expected_screen:
                if route_kind == "squad" and ("squad" in label or "profile" in label):
                    _add(str(screenshot))
                if route_kind == "transfers" and ("transfer" in label or "dashboard_select_transfers" in label):
                    _add(str(screenshot))
        for step in summary_payload.get("steps") or []:
            if not isinstance(step, dict):
                continue
            label = _step_label(step)
            if label.startswith("return_from_") and not (route_kind == "squad" and label == "return_from_squad"):
                continue
            screenshot = step.get("screenshot")
            if not screenshot:
                continue
            if route_kind == "squad" and "squad" in label:
                _add(str(screenshot))
            if route_kind == "transfers" and "transfer" in label:
                _add(str(screenshot))

    for screenshot in case.get("screenshots") or []:
        name = Path(str(screenshot)).name
        if route_kind == "squad" and "squad_inspect" in name:
            _add(str(screenshot))
        if route_kind == "squad" and "return_from_squad" in name:
            _add(str(screenshot))
        if route_kind == "transfers" and "transfers_inspect" in name:
            _add(str(screenshot))
    return candidates


def _representative_screenshot(case: dict[str, Any], summary_payload: dict[str, Any] | None, route_kind: str) -> str | None:
    candidates = _representative_screenshot_candidates(case, summary_payload, route_kind)
    return candidates[0] if candidates else None


def _dhash_16(image_path: Path) -> int | None:
    try:
        from PIL import Image

        size = 16
        image = Image.open(image_path).convert("L").resize((size + 1, size))
        pixels = list(image.getdata())
        value = 0
        for y in range(size):
            row = pixels[y * (size + 1) : (y + 1) * (size + 1)]
            for x in range(size):
                value = (value << 1) | (1 if row[x] > row[x + 1] else 0)
        return value
    except Exception:
        return None


def _hash_screen_classification(image_path: Path) -> dict[str, Any] | None:
    value = _dhash_16(image_path)
    if value is None:
        return None
    squad_distance = (value ^ SQUAD_SCREEN_DHASH_16).bit_count()
    transfer_distance = (value ^ TRANSFER_SCREEN_DHASH_16).bit_count()
    if squad_distance <= SCREEN_DHASH_THRESHOLD and squad_distance <= transfer_distance:
        return {
            "screen": "squad_management_screen",
            "confidence": max(0.0, 1.0 - squad_distance / SCREEN_DHASH_THRESHOLD),
            "reason": "local_dhash_squad_management",
            "matched_indicators": [f"dhash16_distance:{squad_distance}"],
            "ocr_mode": "none",
            "error": "",
        }
    if transfer_distance <= SCREEN_DHASH_THRESHOLD:
        return {
            "screen": "transfer_market_screen",
            "confidence": max(0.0, 1.0 - transfer_distance / SCREEN_DHASH_THRESHOLD),
            "reason": "local_dhash_transfer_market",
            "matched_indicators": [f"dhash16_distance:{transfer_distance}"],
            "ocr_mode": "none",
            "error": "",
        }
    return None


@lru_cache(maxsize=1024)
def _offline_classify_screen(image_path: str) -> dict[str, Any]:
    path = Path(image_path)
    if not path.is_file():
        return {"screen": "unknown", "confidence": 0.0, "reason": "missing_image"}
    hash_classification = _hash_screen_classification(path)
    if hash_classification is not None:
        return hash_classification
    return {
        "screen": "unknown",
        "confidence": 0.0,
        "reason": "local_dhash_no_match",
        "matched_indicators": [],
        "ocr_mode": "none",
        "error": "",
    }


def _offline_screen_matches(rel_path: str | None, out_dir: Path, expected_screen: str | None) -> tuple[bool, dict[str, Any] | None]:
    if not rel_path or expected_screen is None:
        return False, None
    classification = _offline_classify_screen(str((out_dir / rel_path).resolve()))
    return classification.get("screen") == expected_screen, classification


def _local_screenshot_relpath(screenshot: str | None, summary_path: Path | None, out_dir: Path) -> str | None:
    if not screenshot or summary_path is None:
        return None
    shot_path = Path(str(screenshot))
    if not shot_path.is_absolute():
        return _relpath((summary_path.parent / shot_path).resolve(), out_dir)

    parts = shot_path.parts
    if "clubs" in parts:
        clubs_index = parts.index("clubs")
        if len(parts) > clubs_index + 2 and parts[clubs_index + 1] == summary_path.parent.name:
            candidate = summary_path.parent.joinpath(*parts[clubs_index + 2 :])
            return _relpath(candidate.resolve(), out_dir)

    if shot_path.exists():
        return _relpath(shot_path.resolve(), out_dir)
    return None


def _record_case_evidence(
    *,
    case: dict[str, Any],
    summary_path: Path | None,
    source_summary_path: Path,
    out_dir: Path,
    visual_runs: list[dict[str, Any]],
    club_index: dict[str, dict[str, Any]],
) -> None:
    club_key = str(case.get("club_key") or case.get("set_name") or "").strip()
    if not club_key:
        return
    team_query = str(case.get("team_query") or case.get("set_name") or club_key)
    screenshots = [str(item) for item in (case.get("screenshots") or []) if str(item)]
    case_status = int(case.get("status") or 0)
    case_ok = bool(case.get("ok"))

    summary_payload = _read_json(summary_path) if summary_path and summary_path.is_file() else None
    if not isinstance(summary_payload, dict):
        summary_payload = None

    if summary_payload and not screenshots:
        for step in summary_payload.get("steps") or []:
            if isinstance(step, dict) and step.get("screenshot"):
                screenshots.append(str(step["screenshot"]))

    rel_summary = _relpath(summary_path, out_dir) if summary_path and summary_path.exists() else None
    route_hits = Counter()
    for shot in screenshots:
        route = _infer_route_kind(Path(shot).name)
        if route:
            route_hits[route] += 1
    if summary_payload:
        for step in summary_payload.get("steps") or []:
            if not isinstance(step, dict):
                continue
            route = _infer_route_kind(_step_label(step))
            if route:
                route_hits[route] += 1

    def _select_validated_candidate(route_kind: str) -> tuple[str | None, str | None, bool, dict[str, Any] | None]:
        expected_screen = _route_expected_screen(route_kind)
        first_shot: str | None = None
        first_rel: str | None = None
        first_classification: dict[str, Any] | None = None
        for shot in _representative_screenshot_candidates(case, summary_payload, route_kind):
            rel = _local_screenshot_relpath(shot, summary_path, out_dir)
            if not first_shot:
                first_shot = shot
                first_rel = rel
            valid, classification = _offline_screen_matches(rel, out_dir, expected_screen)
            if first_classification is None:
                first_classification = classification
            if valid:
                return shot, rel, True, classification
        return first_shot, first_rel, False, first_classification

    squad_shot, squad_rel, offline_squad_valid, offline_squad = _select_validated_candidate("squad")
    transfers_shot, transfers_rel, offline_transfers_valid, offline_transfers = _select_validated_candidate("transfers")
    valid_squad = _route_is_valid(summary_payload, "squad") or offline_squad_valid
    valid_transfers = _route_is_valid(summary_payload, "transfers") or offline_transfers_valid

    record = club_index.setdefault(
        club_key,
        {
            "club_key": club_key,
            "team_query": team_query,
            "matrix_runs": [],
            "visual_sample_runs": [],
            "has_squad_evidence": False,
            "has_transfers_evidence": False,
            "representative_squad_screenshot": None,
            "representative_transfers_screenshot": None,
            "best_status": None,
            "best_ok": False,
            "any_summary": None,
        },
    )
    record["team_query"] = record.get("team_query") or team_query
    evidence_entry = {
        "source_summary": _relpath(source_summary_path, out_dir),
        "case_summary": rel_summary,
        "ok": case_ok,
        "status": case_status,
        "phase_reached": str((summary_payload or {}).get("phase_reached") or ""),
        "screenshot_count": len(screenshots),
        "representative_squad_screenshot": squad_rel,
        "representative_transfers_screenshot": transfers_rel,
        "route_hits": dict(route_hits),
        "valid_squad_screen": valid_squad,
        "valid_transfers_screen": valid_transfers,
        "offline_squad_classification": offline_squad,
        "offline_transfers_classification": offline_transfers,
    }

    source_rel = _relpath(source_summary_path, out_dir)
    is_visual_sample = "/runner_artifacts/" in f"/{source_rel}" or source_rel.startswith("runner_artifacts/")
    target_key = "visual_sample_runs" if is_visual_sample else "matrix_runs"
    record[target_key].append(evidence_entry)

    if valid_squad and evidence_entry["representative_squad_screenshot"]:
        record["has_squad_evidence"] = True
        record["representative_squad_screenshot"] = (
            record["representative_squad_screenshot"] or evidence_entry["representative_squad_screenshot"]
        )
    if valid_transfers and evidence_entry["representative_transfers_screenshot"]:
        record["has_transfers_evidence"] = True
        record["representative_transfers_screenshot"] = (
            record["representative_transfers_screenshot"] or evidence_entry["representative_transfers_screenshot"]
        )
    if record["best_status"] is None or case_status < int(record["best_status"]):
        record["best_status"] = case_status
    record["best_ok"] = bool(record["best_ok"] or case_ok)
    record["any_summary"] = record["any_summary"] or rel_summary


def _resolve_case_summary(source_summary: Path, case: dict[str, Any]) -> Path | None:
    summary_path = case.get("summary_path")
    if isinstance(summary_path, str) and summary_path.strip():
        candidate = Path(summary_path)
        if candidate.is_file():
            return candidate.resolve()
    club_key = str(case.get("club_key") or case.get("set_name") or "").strip()
    if not club_key:
        return None
    candidate = source_summary.parent / "clubs" / club_key / "summary.json"
    if candidate.is_file():
        return candidate.resolve()
    return None


def _record_orphan_club_summary(out_dir: Path, club_summary: Path, club_index: dict[str, dict[str, Any]]) -> None:
    rel = _relpath(club_summary, out_dir)
    if "/clubs/" not in f"/{rel}":
        return
    club_key = club_summary.parent.name
    existing = club_index.get(club_key)
    if existing and (existing.get("matrix_runs") or existing.get("visual_sample_runs")):
        return
    payload = _read_json(club_summary)
    if not isinstance(payload, dict):
        return
    screenshots = sorted(str(p.relative_to(club_summary.parent)) for p in (club_summary.parent / "screens").glob("*.png"))
    phase = str(payload.get("phase_reached") or "")
    ok = phase == "return_from_transfers" and not bool(payload.get("crash_detected"))
    pseudo_case = {
        "club_key": club_key,
        "set_name": club_key,
        "team_query": club_key,
        "ok": ok,
        "status": 0 if ok else 1,
        "screenshots": screenshots,
        "summary_path": str(club_summary),
    }
    source_summary = club_summary.parents[2] / "summary.json"
    if not source_summary.is_file():
        source_summary = club_summary
    _record_case_evidence(
        case=pseudo_case,
        summary_path=club_summary,
        source_summary_path=source_summary,
        out_dir=out_dir,
        visual_runs=[],
        club_index=club_index,
    )


def _resolve_pointer_path(out_dir: Path, pointer_name: str) -> Path | None:
    pointer_path = out_dir / pointer_name
    if not pointer_path.is_file():
        return None
    raw = pointer_path.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    candidate = candidate.resolve()
    return candidate if candidate.exists() else None


def _intended_runner_roots(out_dir: Path) -> list[Path]:
    pointer_names = (
        "latest_80club_fastvalid_matrix_dir.txt",
        "latest_80club_fastvalid_rerun2_matrix_dir.txt",
        "latest_80club_fastvalid_rerun_matrix_dir.txt",
        "latest_80club_classvalid_rerun_matrix_dir.txt",
    )
    roots: list[Path] = []
    seen: set[Path] = set()
    for pointer_name in pointer_names:
        root = _resolve_pointer_path(out_dir, pointer_name)
        if root is None or root in seen:
            continue
        if (root / "summary.json").is_file():
            roots.append(root)
            seen.add(root)
    return roots


def _discover_runner_summaries(out_dir: Path) -> dict[str, Any]:
    intended_roots = _intended_runner_roots(out_dir)
    if intended_roots:
        root_summaries = [root / "summary.json" for root in intended_roots]
    else:
        root_summaries = sorted(
            p for p in out_dir.rglob("summary.json") if p.is_file() and "/clubs/" not in f"/{_relpath(p, out_dir)}"
        )
    club_index: dict[str, dict[str, Any]] = {}
    root_matrix_missing: set[str] = set()
    root_matrix_failed: set[str] = set()
    visual_runs: list[dict[str, Any]] = []
    matrix_roots: list[str] = []

    for summary_path in root_summaries:
        payload = _read_json(summary_path)
        if not isinstance(payload, dict):
            continue
        rel = _relpath(summary_path, out_dir)
        if rel.startswith("runner_80club") and "/summary.json" in f"/{rel}" and "matrix" in rel:
            matrix_roots.append(rel)
            for club_key in payload.get("missing_clubs") or []:
                if str(club_key).strip():
                    root_matrix_missing.add(str(club_key).strip())
            for row in payload.get("failed_cases") or []:
                if isinstance(row, dict) and str(row.get("club_key") or "").strip():
                    root_matrix_failed.add(str(row.get("club_key") or "").strip())
        cases = [row for row in (payload.get("cases") or []) if isinstance(row, dict)]
        for batch in payload.get("batches") or []:
            if isinstance(batch, dict):
                cases.extend(row for row in (batch.get("cases") or []) if isinstance(row, dict))
        if not cases:
            continue
        if rel.startswith("runner_artifacts/"):
            visual_runs.append(
                {
                    "summary": rel,
                    "success": bool(payload.get("success")),
                    "case_count": len(cases),
                    "scope": str(payload.get("scope") or ""),
                }
            )
        for case in cases:
            case_summary = _resolve_case_summary(summary_path, case)
            _record_case_evidence(
                case=case,
                summary_path=case_summary,
                source_summary_path=summary_path,
                out_dir=out_dir,
                visual_runs=visual_runs,
                club_index=club_index,
            )

    orphan_roots = intended_roots or [out_dir]
    for root in orphan_roots:
        for club_summary in sorted(root.rglob("clubs/*/summary.json")):
            _record_orphan_club_summary(out_dir, club_summary, club_index)

    found_clubs = set(club_index)
    failed_clubs = set(root_matrix_failed)
    missing_clubs = set(root_matrix_missing)
    for club_key, row in club_index.items():
        has_both = bool(row.get("has_squad_evidence") and row.get("has_transfers_evidence"))
        if has_both:
            failed_clubs.discard(club_key)
            missing_clubs.discard(club_key)
        elif row.get("matrix_runs"):
            failed_clubs.add(club_key)

    playable_80_target = len(found_clubs | failed_clubs | missing_clubs)
    if playable_80_target == 0:
        playable_80_target = len(found_clubs)
    matched_clubs = {
        club_key
        for club_key, row in club_index.items()
        if row.get("has_squad_evidence") and row.get("has_transfers_evidence")
    }

    squad_evidence_count = sum(1 for row in club_index.values() if row.get("has_squad_evidence"))
    transfers_evidence_count = sum(1 for row in club_index.values() if row.get("has_transfers_evidence"))

    representative_links = []
    for club_key in sorted(matched_clubs):
        row = club_index[club_key]
        representative_links.append(
            {
                "club_key": club_key,
                "team_query": row.get("team_query") or club_key,
                "squad_screenshot": row.get("representative_squad_screenshot"),
                "transfers_screenshot": row.get("representative_transfers_screenshot"),
                "summary": row.get("any_summary"),
            }
        )

    clubs = []
    for club_key in sorted(club_index):
        row = club_index[club_key]
        clubs.append(
            {
                "club_key": club_key,
                "team_query": row.get("team_query") or club_key,
                "matched": club_key in matched_clubs,
                "has_squad_evidence": bool(row.get("has_squad_evidence")),
                "has_transfers_evidence": bool(row.get("has_transfers_evidence")),
                "best_ok": bool(row.get("best_ok")),
                "best_status": row.get("best_status"),
                "representative_squad_screenshot": row.get("representative_squad_screenshot"),
                "representative_transfers_screenshot": row.get("representative_transfers_screenshot"),
                "matrix_runs": row.get("matrix_runs") or [],
                "visual_sample_runs": row.get("visual_sample_runs") or [],
            }
        )

    return {
        "visual_runs": visual_runs,
        "matrix_root_summaries": matrix_roots,
        "playable_80_target": playable_80_target,
        "matched_clubs": sorted(matched_clubs),
        "failed_clubs": sorted(failed_clubs - matched_clubs),
        "missing_clubs": sorted(missing_clubs - matched_clubs),
        "squad_evidence_count": squad_evidence_count,
        "transfers_evidence_count": transfers_evidence_count,
        "representative_links": representative_links,
        "clubs": clubs,
    }


def _write_json_report(out_dir: Path, report: dict[str, Any]) -> Path:
    evidence_dir = out_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / "variable_name_contract_research_evidence.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _link(rel_path: str | None) -> str:
    if not rel_path:
        return ""
    escaped = html.escape(rel_path)
    label = html.escape(Path(rel_path).name)
    return f'<a href="../{escaped}">{label}</a>'


def _thumb(rel_path: str | None) -> str:
    if not rel_path:
        return ""
    escaped = html.escape(rel_path)
    label = html.escape(Path(rel_path).name)
    return (
        f'<a href="../{escaped}">'
        f'<img src="../{escaped}" alt="{label}" loading="lazy" '
        'style="width:220px;max-width:100%;border:1px solid #b8c4d0;border-radius:4px;background:#111">'
        "</a>"
    )


def _render_html(report: dict[str, Any]) -> str:
    summary = report["summary"]
    contract_rows = "".join(
        f"<tr><td>{html.escape(name)}</td><td>{count}</td></tr>"
        for name, count in report["static_contracts"]["contract_family_counts"].items()
    )
    status_rows = "".join(
        f"<tr><td>{html.escape(name)}</td><td>{count}</td></tr>"
        for name, count in report["static_contracts"]["contract_status_counts"].items()
    )
    club_rows = "".join(
        (
            "<tr>"
            f"<td>{html.escape(str(row['club_key']))}</td>"
            f"<td>{html.escape(str(row['team_query']))}</td>"
            f"<td>{'yes' if row['matched'] else 'no'}</td>"
            f"<td>{'yes' if row['has_squad_evidence'] else 'no'}</td>"
            f"<td>{'yes' if row['has_transfers_evidence'] else 'no'}</td>"
            f"<td>{'' if row['best_status'] is None else int(row['best_status'])}</td>"
            f"<td>{_link(row['representative_squad_screenshot'])}</td>"
            f"<td>{_link(row['representative_transfers_screenshot'])}</td>"
            "</tr>"
        )
        for row in report["runner_artifacts"]["clubs"]
    )
    rep_rows = "".join(
        (
            "<tr>"
            f"<td>{html.escape(str(row['club_key']))}</td>"
            f"<td>{html.escape(str(row['team_query']))}</td>"
            f"<td>{_thumb(row['squad_screenshot'])}<br>{_link(row['squad_screenshot'])}</td>"
            f"<td>{_thumb(row['transfers_screenshot'])}<br>{_link(row['transfers_screenshot'])}</td>"
            f"<td>{_link(row['summary'])}</td>"
            "</tr>"
        )
        for row in report["runner_artifacts"]["representative_links"]
    )
    failed = ", ".join(report["runner_artifacts"]["failed_clubs"]) or "none"
    missing = ", ".join(report["runner_artifacts"]["missing_clubs"]) or "none"
    visual_runs = "".join(
        f"<li>{html.escape(row['summary'])} ({row['case_count']} case{'s' if row['case_count'] != 1 else ''}, success={str(row['success']).lower()})</li>"
        for row in report["runner_artifacts"]["visual_runs"]
    ) or "<li>none</li>"
    matrix_roots = "".join(
        f"<li>{html.escape(item)}</li>" for item in report["runner_artifacts"]["matrix_root_summaries"]
    ) or "<li>none</li>"

    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <title>Variable Name Contract Research Evidence</title>
  <style>
    body {{ font-family: sans-serif; margin: 24px; color: #1f2933; background: #f7f9fb; }}
    h1, h2 {{ margin-bottom: 0.3rem; }}
    .meta, .card-grid {{ margin-bottom: 24px; }}
    .card-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
    .card {{ background: white; border: 1px solid #d8e1ea; border-radius: 8px; padding: 12px; }}
    .label {{ font-size: 0.85rem; color: #52606d; }}
    .value {{ font-size: 1.6rem; font-weight: 700; }}
    table {{ border-collapse: collapse; width: 100%; background: white; }}
    th, td {{ border: 1px solid #d8e1ea; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #eef2f6; }}
    code {{ background: #eef2f6; padding: 0.1rem 0.3rem; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>Variable Name Contract Research Evidence</h1>
  <div class=\"meta\">
    <div>Output dir: <code>{html.escape(report['out_dir'])}</code></div>
    <div>Generated from latest pointer: <code>{html.escape(report['latest_pointer'])}</code></div>
  </div>
  <div class=\"card-grid\">
    <div class=\"card\"><div class=\"label\">Total indexed entries</div><div class=\"value\">{summary['total_indexed_entries']}</div></div>
    <div class=\"card\"><div class=\"label\">Parsed player payloads</div><div class=\"value\">{summary['parse_ok_count']}</div></div>
    <div class=\"card\"><div class=\"label\">Contract families</div><div class=\"value\">{summary['contract_family_count']}</div></div>
    <div class=\"card\"><div class=\"label\">Playable player records</div><div class=\"value\">{summary['playable_80_player_records']}</div></div>
    <div class=\"card\"><div class=\"label\">Foreign/non-playable records</div><div class=\"value\">{summary['foreign_or_non_playable_player_records']}</div></div>
    <div class=\"card\"><div class=\"label\">Playable 80 target</div><div class=\"value\">{summary['playable_80_target']}</div></div>
    <div class=\"card\"><div class=\"label\">Playable 80 matched</div><div class=\"value\">{summary['playable_80_matched']}</div></div>
    <div class=\"card\"><div class=\"label\">Squad screenshot evidence</div><div class=\"value\">{summary['squad_screenshot_evidence_count']}</div></div>
    <div class=\"card\"><div class=\"label\">Transfer screenshot evidence</div><div class=\"value\">{summary['transfer_screenshot_evidence_count']}</div></div>
    <div class=\"card\"><div class=\"label\">Failed clubs</div><div class=\"value\">{summary['failed_club_count']}</div></div>
    <div class=\"card\"><div class=\"label\">Missing clubs</div><div class=\"value\">{summary['missing_club_count']}</div></div>
  </div>

  <h2>Static Contracts</h2>
  <table>
    <thead><tr><th>Contract family</th><th>Count</th></tr></thead>
    <tbody>{contract_rows}</tbody>
  </table>

  <h2>Writer Status Buckets</h2>
  <table>
    <thead><tr><th>Status</th><th>Count</th></tr></thead>
    <tbody>{status_rows}</tbody>
  </table>

  <h2>Runner Sources</h2>
  <div><strong>Visual sample summaries</strong></div>
  <ul>{visual_runs}</ul>
  <div><strong>Matrix summaries</strong></div>
  <ul>{matrix_roots}</ul>

  <h2>Representative Screenshots</h2>
  <table>
    <thead><tr><th>Club</th><th>Query</th><th>Squad</th><th>Transfers</th><th>Summary</th></tr></thead>
    <tbody>{rep_rows}</tbody>
  </table>

  <h2>Club Coverage</h2>
  <table>
    <thead><tr><th>Club</th><th>Query</th><th>Matched</th><th>Squad</th><th>Transfers</th><th>Status</th><th>Squad shot</th><th>Transfers shot</th></tr></thead>
    <tbody>{club_rows}</tbody>
  </table>

  <h2>Outstanding Clubs</h2>
  <div><strong>Failed:</strong> {html.escape(failed)}</div>
  <div><strong>Missing:</strong> {html.escape(missing)}</div>
</body>
</html>
"""


def _write_html_report(out_dir: Path, report: dict[str, Any]) -> Path:
    evidence_dir = out_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / "variable_name_contract_research_evidence.html"
    path.write_text(_render_html(report), encoding="utf-8")
    return path


def build_report(out_dir: Path, latest_file: Path) -> dict[str, Any]:
    static_contracts = _discover_static_contracts(out_dir)
    runner_artifacts = _discover_runner_summaries(out_dir)

    playable_80_target = max(static_contracts["playable_80_total"], runner_artifacts["playable_80_target"])
    summary = {
        "total_indexed_entries": static_contracts["total_indexed_entries"],
        "parse_ok_count": static_contracts["parse_ok_count"],
        "contract_family_count": len(static_contracts["contract_family_counts"]),
        "contract_family_counts": static_contracts["contract_family_counts"],
        "contract_status_counts": static_contracts["contract_status_counts"],
        "playable_80_player_records": static_contracts["playable_80_player_records"],
        "foreign_or_non_playable_player_records": static_contracts["foreign_or_non_playable_player_records"],
        "opaque_or_non_player_count": static_contracts["opaque_or_non_player_count"],
        "unlinked_player_records": static_contracts["unlinked_player_records"],
        "playable_80_target": playable_80_target,
        "playable_80_matched": len(runner_artifacts["matched_clubs"]),
        "squad_screenshot_evidence_count": runner_artifacts["squad_evidence_count"],
        "transfer_screenshot_evidence_count": runner_artifacts["transfers_evidence_count"],
        "failed_club_count": len(runner_artifacts["failed_clubs"]),
        "missing_club_count": len(runner_artifacts["missing_clubs"]),
    }

    return {
        "out_dir": str(out_dir),
        "latest_pointer": str(latest_file),
        "summary": summary,
        "static_contracts": {
            "contracts_json": _relpath(static_contracts["contracts_json"], out_dir)
            if static_contracts["contracts_json"]
            else None,
            "contracts_stdout_json": _relpath(static_contracts["contracts_stdout_json"], out_dir)
            if static_contracts["contracts_stdout_json"]
            else None,
            "contract_family_counts": static_contracts["contract_family_counts"],
            "contract_status_counts": static_contracts["contract_status_counts"],
        },
        "runner_artifacts": runner_artifacts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out_dir", nargs="?", help="Research output directory. Defaults to the latest pointer file.")
    parser.add_argument(
        "--latest-file",
        default=str(DEFAULT_LATEST_FILE),
        help="Path to the file containing the latest output directory.",
    )
    args = parser.parse_args()

    latest_file = Path(args.latest_file).expanduser().resolve()
    out_dir = _resolve_out_dir(args.out_dir, latest_file)
    if not out_dir.is_dir():
        raise SystemExit(f"Output directory does not exist: {out_dir}")

    report = build_report(out_dir, latest_file)
    json_path = _write_json_report(out_dir, report)
    html_path = _write_html_report(out_dir, report)
    print(json.dumps({
        "out_dir": str(out_dir),
        "json_report": str(json_path),
        "html_report": str(html_path),
        "summary": report["summary"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
