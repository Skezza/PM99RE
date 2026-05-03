#!/usr/bin/env python3
"""Build an evidence pack for the English 80 variable-name squad proof."""

from __future__ import annotations

import argparse
import html
import json
import os
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LATEST_FILE = REPO_ROOT / ".local" / "latest_english80_2026_variable_names_dir.txt"
SQUAD_SCREEN_DHASH_16 = int(
    "744c51cc87274f2719af192f192e1b2e592e5b2f192e1b2e1b2e1b2e1b2f859f",
    16,
)
SCREEN_DHASH_THRESHOLD = 40


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _resolve_build_dir(value: str | None, latest_file: Path) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    raw = latest_file.read_text(encoding="utf-8").strip()
    if not raw:
        raise SystemExit(f"Latest variable-name build pointer is empty: {latest_file}")
    path = Path(raw)
    return path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return os.path.relpath(path, root).replace(os.sep, "/")


def _display_rel(path: Path | None, build_dir: Path) -> str | None:
    if path is None:
        return None
    return _relpath(path, build_dir)


def _dhash_16(path: Path) -> int | None:
    try:
        from PIL import Image

        size = 16
        image = Image.open(path).convert("L").resize((size + 1, size))
        pixels = list(image.getdata())
        value = 0
        for y in range(size):
            row = pixels[y * (size + 1) : (y + 1) * (size + 1)]
            for x in range(size):
                value = (value << 1) | (1 if row[x] > row[x + 1] else 0)
        return value
    except Exception:
        return None


@lru_cache(maxsize=2048)
def _is_squad_screen(path_text: str) -> tuple[bool, int | None]:
    path = Path(path_text)
    if not path.is_file():
        return False, None
    value = _dhash_16(path)
    if value is None:
        return False, None
    distance = (value ^ SQUAD_SCREEN_DHASH_16).bit_count()
    return distance <= SCREEN_DHASH_THRESHOLD, distance


def _local_screenshot_path(summary_path: Path, screenshot: str) -> Path | None:
    shot_path = Path(str(screenshot))
    if not str(screenshot).strip():
        return None
    if not shot_path.is_absolute():
        candidate = summary_path.parent / shot_path
        return candidate.resolve() if candidate.is_file() else None
    if shot_path.is_file():
        return shot_path.resolve()

    parts = shot_path.parts
    if "clubs" in parts:
        index = parts.index("clubs")
        if len(parts) > index + 2 and parts[index + 1] == summary_path.parent.name:
            candidate = summary_path.parent.joinpath(*parts[index + 2 :])
            return candidate.resolve() if candidate.is_file() else None
    if "screens" in parts:
        index = parts.index("screens")
        candidate = summary_path.parent.joinpath(*parts[index:])
        return candidate.resolve() if candidate.is_file() else None
    return None


def _step_label(step: dict[str, Any]) -> str:
    node = step.get("step")
    if isinstance(node, dict):
        return str(node.get("label") or "")
    return ""


def _candidate_squad_screens(summary_path: Path, payload: dict[str, Any]) -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path | None) -> None:
        if path is not None and path not in seen:
            seen.add(path)
            candidates.append(path)

    for step in payload.get("steps") or []:
        if not isinstance(step, dict):
            continue
        label = _step_label(step)
        screenshot = step.get("screenshot")
        if not screenshot:
            continue
        if "squad" in label:
            add(_local_screenshot_path(summary_path, str(screenshot)))

    for path in sorted((summary_path.parent / "screens").glob("*squad*.png")):
        add(path.resolve())
    return candidates


def _discover_runner_matrix(build_dir: Path, explicit_matrix: str | None) -> Path | None:
    if explicit_matrix:
        path = Path(explicit_matrix).expanduser().resolve()
        return path if path.is_dir() else None
    pointer = build_dir / "latest_80club_squad_matrix_dir.txt"
    if pointer.is_file():
        raw = pointer.read_text(encoding="utf-8").strip()
        if raw:
            path = Path(raw)
            path = path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()
            if path.is_dir():
                return path
    roots = sorted(build_dir.glob("runner_80club_squad_matrix_*"))
    return roots[-1].resolve() if roots else None


def _discover_runner_evidence(build_dir: Path, world: dict[str, Any], matrix_dir: Path | None) -> dict[str, Any]:
    expected_clubs = [str(row["club_key"]) for row in world.get("clubs", []) if isinstance(row, dict) and row.get("club_key")]
    club_rows: dict[str, dict[str, Any]] = {
        club: {
            "club_key": club,
            "ok": False,
            "status": None,
            "summary": None,
            "squad_screenshot": None,
            "squad_scroll_screenshots": [],
            "squad_screen_valid": False,
            "squad_dhash_distance": None,
            "screenshot_count": 0,
        }
        for club in expected_clubs
    }
    matrix_summary = None
    batch_summaries: list[str] = []

    if matrix_dir is None:
        return {
            "matrix_dir": None,
            "matrix_summary": None,
            "batch_summaries": [],
            "expected_club_count": len(expected_clubs),
            "seen_club_count": 0,
            "ok_club_count": 0,
            "squad_screen_evidence_count": 0,
            "valid_squad_screen_count": 0,
            "missing_clubs": expected_clubs,
            "failed_clubs": [],
            "clubs": list(club_rows.values()),
        }

    matrix_payload = _read_json(matrix_dir / "summary.json")
    if isinstance(matrix_payload, dict):
        matrix_summary = _relpath(matrix_dir / "summary.json", build_dir)
        for batch in matrix_payload.get("batches") or []:
            if isinstance(batch, dict) and batch.get("summary_path"):
                batch_summaries.append(str(batch["summary_path"]))
            for case in batch.get("cases") or [] if isinstance(batch, dict) else []:
                if not isinstance(case, dict):
                    continue
                club_key = str(case.get("club_key") or "")
                if club_key not in club_rows:
                    continue
                row = club_rows[club_key]
                row["ok"] = bool(row["ok"] or case.get("ok"))
                status = case.get("status")
                if isinstance(status, int):
                    row["status"] = status if row["status"] is None else min(int(row["status"]), status)
                if case.get("summary_path"):
                    row["summary"] = str(case["summary_path"])

    for summary_path in sorted(matrix_dir.rglob("clubs/*/summary.json")):
        club_key = summary_path.parent.name
        if club_key not in club_rows:
            continue
        payload = _read_json(summary_path)
        if not isinstance(payload, dict):
            continue
        row = club_rows[club_key]
        row["summary"] = _relpath(summary_path, build_dir)
        row["ok"] = bool(row["ok"] or payload.get("success") or payload.get("phase_reached") in {"return_from_squad", "return_from_transfers"})
        candidates = _candidate_squad_screens(summary_path, payload)
        row["screenshot_count"] = len(list((summary_path.parent / "screens").glob("*.png")))
        scroll_screens = [path for path in candidates if "scroll" in path.name or "proof" in path.name]
        row["squad_scroll_screenshots"] = [_relpath(path, build_dir) for path in scroll_screens[:4]]
        for candidate in candidates:
            valid, distance = _is_squad_screen(str(candidate))
            if row["squad_screenshot"] is None:
                row["squad_screenshot"] = _relpath(candidate, build_dir)
                row["squad_dhash_distance"] = distance
            if valid:
                row["squad_screenshot"] = _relpath(candidate, build_dir)
                row["squad_screen_valid"] = True
                row["squad_dhash_distance"] = distance
                break

    clubs = [club_rows[club] for club in expected_clubs]
    missing = [row["club_key"] for row in clubs if not row.get("summary")]
    failed = [row["club_key"] for row in clubs if row.get("summary") and not row.get("ok")]
    squad_evidence = [row["club_key"] for row in clubs if row.get("squad_screenshot")]
    valid_squad = [row["club_key"] for row in clubs if row.get("squad_screen_valid")]
    return {
        "matrix_dir": str(matrix_dir),
        "matrix_summary": matrix_summary,
        "batch_summaries": batch_summaries,
        "expected_club_count": len(expected_clubs),
        "seen_club_count": len([row for row in clubs if row.get("summary")]),
        "ok_club_count": len([row for row in clubs if row.get("ok")]),
        "squad_screen_evidence_count": len(squad_evidence),
        "valid_squad_screen_count": len(valid_squad),
        "missing_clubs": missing,
        "failed_clubs": failed,
        "clubs": clubs,
    }


def _load_build_facts(build_dir: Path) -> dict[str, Any]:
    manifest = _read_json(build_dir / "variable_name_build_manifest.json")
    readback = _read_json(build_dir / "variable_name_readback.json")
    source = _read_json(build_dir / "football_squads_source_ledger.json")
    world = _read_json(build_dir / "world_english80_2026_variable_names.json")
    if not isinstance(manifest, dict):
        raise SystemExit(f"Missing or invalid manifest: {build_dir / 'variable_name_build_manifest.json'}")
    if not isinstance(readback, list):
        raise SystemExit(f"Missing or invalid readback: {build_dir / 'variable_name_readback.json'}")
    if not isinstance(source, dict):
        raise SystemExit(f"Missing or invalid source ledger: {build_dir / 'football_squads_source_ledger.json'}")
    if not isinstance(world, dict):
        raise SystemExit(f"Missing or invalid world state: {build_dir / 'world_english80_2026_variable_names.json'}")
    by_club: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in readback:
        if isinstance(row, dict):
            by_club[str(row.get("club_key") or "")].append(row)
    club_rows = []
    source_clubs = {str(club.get("club_key") or ""): club for club in source.get("clubs", []) if isinstance(club, dict)}
    world_clubs = {str(club.get("club_key") or ""): club for club in world.get("clubs", []) if isinstance(club, dict)}
    for club_key in sorted(world_clubs):
        players = sorted(by_club.get(club_key, []), key=lambda row: int(row.get("slot") or 0))
        source_club = source_clubs.get(club_key, {})
        club_rows.append(
            {
                "club_key": club_key,
                "club_name": world_clubs[club_key].get("target_display_name") or source_club.get("display_name") or club_key,
                "source_url": source_club.get("source_url") or world_clubs[club_key].get("source_url"),
                "player_count": len(players),
                "payload_grew_count": sum(1 for row in players if int(row.get("payload_length_delta") or 0) > 0),
                "variable_name_end_count": sum(1 for row in players if int(row.get("name_end_delta") or 0) != 0),
                "players": [
                    {
                        "slot": int(row.get("slot") or 0),
                        "source_name": row.get("source_name"),
                        "target_name": row.get("target_name"),
                        "applied_name": row.get("applied_name"),
                        "old_name": row.get("old_name"),
                        "payload_length_delta": int(row.get("payload_length_delta") or 0),
                        "name_end_delta": int(row.get("name_end_delta") or 0),
                    }
                    for row in players
                ],
            }
        )
    return {
        "manifest": manifest,
        "readback": readback,
        "source": source,
        "world": world,
        "clubs": club_rows,
    }


def _link(rel_path: str | None, label: str | None = None) -> str:
    if not rel_path:
        return ""
    if rel_path.startswith(("http://", "https://")):
        escaped_url = html.escape(rel_path, quote=True)
        return f'<a href="{escaped_url}">{html.escape(label or rel_path)}</a>'
    escaped = html.escape(rel_path)
    return f'<a href="../{escaped}">{html.escape(label or Path(rel_path).name)}</a>'


def _thumb(rel_path: str | None) -> str:
    if not rel_path:
        return ""
    escaped = html.escape(rel_path)
    label = html.escape(Path(rel_path).name)
    return (
        f'<a href="../{escaped}"><img src="../{escaped}" alt="{label}" loading="lazy" '
        'style="width:240px;max-width:100%;border:1px solid #b8c4d0;border-radius:4px;background:#111"></a>'
    )


def _render_html(report: dict[str, Any]) -> str:
    summary = report["summary"]
    build = report["build"]
    runner = report["runner"]
    growth_rows = "".join(
        "<tr>"
        f"<td>{html.escape(row['club_key'])}</td>"
        f"<td>{int(row['slot'])}</td>"
        f"<td>{html.escape(str(row['old_name']))}</td>"
        f"<td>{html.escape(str(row['target_name']))}</td>"
        f"<td>{int(row['payload_length_delta'])}</td>"
        f"<td>{int(row['name_end_delta'])}</td>"
        "</tr>"
        for row in report["growth_examples"]
    )
    club_rows = []
    runner_by_club = {row["club_key"]: row for row in runner["clubs"]}
    for club in build["clubs"]:
        run = runner_by_club.get(club["club_key"], {})
        names = ", ".join(str(player["target_name"]) for player in club["players"][:20])
        club_rows.append(
            "<tr>"
            f"<td>{html.escape(str(club['club_key']))}</td>"
            f"<td>{html.escape(str(club['club_name']))}</td>"
            f"<td>{_link(str(club.get('source_url') or ''), 'source')}</td>"
            f"<td>{int(club['player_count'])}</td>"
            f"<td>{int(club['payload_grew_count'])}</td>"
            f"<td>{int(club['variable_name_end_count'])}</td>"
            f"<td>{'yes' if run.get('ok') else 'no'}</td>"
            f"<td>{'yes' if run.get('squad_screenshot') else 'no'}</td>"
            f"<td>{'yes' if run.get('squad_screen_valid') else 'no'}</td>"
            f"<td>{'' if run.get('squad_dhash_distance') is None else int(run['squad_dhash_distance'])}</td>"
            f"<td>{_thumb(run.get('squad_screenshot'))}<br>{_link(run.get('squad_screenshot'))}</td>"
            f"<td>{html.escape(names)}</td>"
            "</tr>"
        )
    payload_rows = "".join(
        f"<tr><td>{html.escape(str(delta))}</td><td>{count}</td></tr>"
        for delta, count in sorted(summary["payload_length_delta_counts"].items(), key=lambda item: int(item[0]))
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>English 80 Variable-Length Player Name Proof</title>
  <style>
    body {{ font-family: sans-serif; margin: 24px; color: #1f2933; background: #f7f9fb; }}
    h1, h2 {{ margin-bottom: 0.35rem; }}
    .meta {{ margin-bottom: 20px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin-bottom: 24px; }}
    .card {{ background: white; border: 1px solid #d8e1ea; border-radius: 8px; padding: 12px; }}
    .label {{ color: #52606d; font-size: 0.85rem; }}
    .value {{ font-size: 1.6rem; font-weight: 700; }}
    table {{ border-collapse: collapse; width: 100%; background: white; margin-bottom: 24px; }}
    th, td {{ border: 1px solid #d8e1ea; padding: 7px; text-align: left; vertical-align: top; }}
    th {{ background: #eef2f6; position: sticky; top: 0; }}
    code {{ background: #eef2f6; padding: 0.1rem 0.3rem; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>English 80 Variable-Length Player Name Proof</h1>
  <div class="meta">
    <div>Build: <code>{html.escape(report['build_dir'])}</code></div>
    <div>Generated: <code>{html.escape(report['generated_at_utc'])}</code></div>
    <div>Source snapshot: <code>{html.escape(str(summary.get('source_snapshot_date') or ''))}</code></div>
    <div>Runner matrix: <code>{html.escape(str(runner.get('matrix_dir') or 'not run'))}</code></div>
  </div>
  <div class="grid">
    <div class="card"><div class="label">Build OK</div><div class="value">{str(summary['build_ok']).lower()}</div></div>
    <div class="card"><div class="label">Clubs Patched</div><div class="value">{summary['club_count']}</div></div>
    <div class="card"><div class="label">Players Patched</div><div class="value">{summary['player_count']}</div></div>
    <div class="card"><div class="label">Source URLs</div><div class="value">{summary['source_url_count']}</div></div>
    <div class="card"><div class="label">Payloads Grown</div><div class="value">{summary['payload_grew_count']}</div></div>
    <div class="card"><div class="label">Variable Name Ends</div><div class="value">{summary['variable_name_end_count']}</div></div>
    <div class="card"><div class="label">Patch Failures</div><div class="value">{summary['failure_count']}</div></div>
    <div class="card"><div class="label">Runner Seen Clubs</div><div class="value">{summary['runner_seen_club_count']}</div></div>
    <div class="card"><div class="label">Runner OK Clubs</div><div class="value">{summary['runner_ok_club_count']}</div></div>
    <div class="card"><div class="label">Squad Screenshots</div><div class="value">{summary['squad_screen_evidence_count']}</div></div>
    <div class="card"><div class="label">DHash Valid Squad Screens</div><div class="value">{summary['valid_squad_screen_count']}</div></div>
    <div class="card"><div class="label">Milestone Closed</div><div class="value">{str(summary['milestone_closed']).lower()}</div></div>
  </div>

  <h2>Payload Length Deltas</h2>
  <table><thead><tr><th>Delta bytes</th><th>Rows</th></tr></thead><tbody>{payload_rows}</tbody></table>

  <h2>Payload Growth Examples</h2>
  <table><thead><tr><th>Club</th><th>Slot</th><th>Old Name</th><th>Variable Name</th><th>Payload Delta</th><th>Name-End Delta</th></tr></thead><tbody>{growth_rows}</tbody></table>

  <h2>Club Evidence</h2>
  <table>
    <thead><tr><th>Club Key</th><th>Club</th><th>Source</th><th>Players</th><th>Grown Payloads</th><th>Name-End Changes</th><th>Runner OK</th><th>Screenshot</th><th>DHash Valid</th><th>DHash Distance</th><th>Squad Screenshot</th><th>Patched Names</th></tr></thead>
    <tbody>{''.join(club_rows)}</tbody>
  </table>
</body>
</html>
"""


def build_report(build_dir: Path, latest_file: Path, matrix_dir: Path | None) -> dict[str, Any]:
    from datetime import UTC, datetime

    facts = _load_build_facts(build_dir)
    manifest = facts["manifest"]
    source = facts["source"]
    runner = _discover_runner_evidence(build_dir, facts["world"], matrix_dir)
    payload_counts = Counter(int(row.get("payload_length_delta") or 0) for row in facts["readback"] if isinstance(row, dict))
    growth_examples = sorted(
        (
            {
                "club_key": str(row.get("club_key") or ""),
                "slot": int(row.get("slot") or 0),
                "old_name": row.get("old_name"),
                "target_name": row.get("target_name"),
                "payload_length_delta": int(row.get("payload_length_delta") or 0),
                "name_end_delta": int(row.get("name_end_delta") or 0),
            }
            for row in facts["readback"]
            if isinstance(row, dict) and int(row.get("payload_length_delta") or 0) > 0
        ),
        key=lambda row: (-int(row["payload_length_delta"]), row["club_key"], int(row["slot"])),
    )[:30]
    summary = {
        "build_ok": bool(manifest.get("ok")),
        "club_count": int(manifest.get("club_count") or len(facts["clubs"])),
        "player_count": int(manifest.get("player_count") or len(facts["readback"])),
        "source_url_count": int(manifest.get("source_url_count") or 0),
        "source_snapshot_date": source.get("snapshot_date"),
        "payload_length_delta_counts": {str(key): payload_counts[key] for key in sorted(payload_counts)},
        "payload_grew_count": int(manifest.get("payload_grew_count") or 0),
        "payload_same_count": int(manifest.get("payload_same_count") or 0),
        "payload_shrank_count": int(manifest.get("payload_shrank_count") or 0),
        "max_payload_length_delta": int(manifest.get("max_payload_length_delta") or 0),
        "variable_name_end_count": int(manifest.get("variable_name_end_count") or 0),
        "failure_count": int(manifest.get("failure_count") or 0),
        "runner_expected_club_count": runner["expected_club_count"],
        "runner_seen_club_count": runner["seen_club_count"],
        "runner_ok_club_count": runner["ok_club_count"],
        "squad_screen_evidence_count": runner["squad_screen_evidence_count"],
        "valid_squad_screen_count": runner["valid_squad_screen_count"],
        "runner_missing_club_count": len(runner["missing_clubs"]),
        "runner_failed_club_count": len(runner["failed_clubs"]),
    }
    summary["milestone_closed"] = bool(
        summary["build_ok"]
        and summary["club_count"] == 80
        and summary["player_count"] == 1600
        and summary["failure_count"] == 0
        and summary["source_url_count"] == 80
        and summary["runner_expected_club_count"] == 80
        and summary["runner_seen_club_count"] == 80
        and summary["runner_ok_club_count"] == 80
        and summary["squad_screen_evidence_count"] == 80
        and summary["valid_squad_screen_count"] == 80
        and summary["runner_missing_club_count"] == 0
        and summary["runner_failed_club_count"] == 0
    )
    return {
        "schema": "pm99-english80-variable-name-evidence-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "build_dir": str(build_dir),
        "latest_pointer": str(latest_file),
        "summary": summary,
        "manifest": manifest,
        "build": {
            "manifest": _display_rel(build_dir / "variable_name_build_manifest.json", build_dir),
            "readback_json": _display_rel(build_dir / "variable_name_readback.json", build_dir),
            "readback_csv": _display_rel(build_dir / "variable_name_readback.csv", build_dir),
            "source_ledger": _display_rel(build_dir / "football_squads_source_ledger.json", build_dir),
            "world_state": _display_rel(build_dir / "world_english80_2026_variable_names.json", build_dir),
            "clubs": facts["clubs"],
        },
        "runner": runner,
        "growth_examples": growth_examples,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build_dir", nargs="?", help="Variable-name build dir. Defaults to latest pointer.")
    parser.add_argument("--latest-file", default=str(DEFAULT_LATEST_FILE))
    parser.add_argument("--matrix-dir", default="", help="Explicit runner matrix dir.")
    args = parser.parse_args()

    latest_file = Path(args.latest_file).expanduser().resolve()
    build_dir = _resolve_build_dir(args.build_dir, latest_file)
    if not build_dir.is_dir():
        raise SystemExit(f"Build dir does not exist: {build_dir}")
    matrix_dir = _discover_runner_matrix(build_dir, args.matrix_dir or None)
    report = build_report(build_dir, latest_file, matrix_dir)
    evidence_dir = build_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    json_path = evidence_dir / "english80_variable_name_evidence.json"
    html_path = evidence_dir / "english80_variable_name_evidence.html"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    html_path.write_text(_render_html(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "build_dir": str(build_dir),
                "json_report": str(json_path),
                "html_report": str(html_path),
                "summary": report["summary"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report["summary"]["milestone_closed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
