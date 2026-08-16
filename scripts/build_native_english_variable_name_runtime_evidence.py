#!/usr/bin/env python3
"""Build browser-readable evidence for the native English variable-name proof."""

from __future__ import annotations

import argparse
import html
import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_PROBE_DIR = REPO_ROOT / ".local" / "full_game_variable_name_native_english30_20260503T_probe"
DEFAULT_RUNNER_ROOT = REPO_ROOT / "upstream" / "pm99-runner" / "docs" / "artifacts" / "pm99_runner"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs" / "artifacts" / "full_game_variable_name_windows_20260503"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-dir", default=str(DEFAULT_PROBE_DIR))
    parser.add_argument("--runner-artifact-root", default=str(DEFAULT_RUNNER_ROOT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--prefer-fast-runs", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _load_json(path: Path) -> Any:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _copy_screenshot(source: Path, dest_root: Path, relative: Path) -> str:
    destination = dest_root / "native_english30_screens" / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination.relative_to(dest_root).as_posix()


def _find_proof_screens(club_dir: Path) -> list[Path]:
    screen_dir = club_dir / "screens"
    if not screen_dir.is_dir():
        return []
    preferred = sorted(screen_dir.glob("*squad_inspect_filters_enabled*.png"))
    preferred += sorted(screen_dir.glob("*squad_inspect.png"))
    preferred += sorted(screen_dir.glob("*squad_inspect_scroll*.png"))
    seen: set[Path] = set()
    out: list[Path] = []
    for path in preferred:
        if path in seen:
            continue
        seen.add(path)
        out.append(path)
    if out:
        return out[:3]
    return sorted(screen_dir.glob("*.png"))[-3:]


def build(args: argparse.Namespace) -> dict[str, Any]:
    probe_dir = Path(args.probe_dir).expanduser().resolve()
    runner_root = Path(args.runner_artifact_root).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    probe_summary = _load_json(probe_dir / "summary.json")
    readback = _load_json(probe_dir / "native_linked_readback.json") or []
    batches = _load_json(probe_dir / "runner_batches.json") or []
    if not probe_summary:
        raise RuntimeError(f"Missing probe summary: {probe_dir / 'summary.json'}")

    batch_by_club: dict[str, dict[str, Any]] = {}
    expected_by_club: dict[str, str] = {}
    for batch in batches:
        for club_key, expected in dict(batch.get("expected_names") or {}).items():
            batch_by_club[str(club_key)] = batch
            expected_by_club[str(club_key)] = str(expected)

    rows: list[dict[str, Any]] = []
    for selected in list(probe_summary.get("selected_clubs") or []):
        club_key = str(selected["club_key"])
        batch = batch_by_club.get(club_key, {})
        run_tag = str(batch.get("run_tag") or "")
        if bool(args.prefer_fast_runs):
            fast_run_tag = run_tag.replace("native_english30_b", "native_english30_fast_b")
            if fast_run_tag != run_tag and (runner_root / fast_run_tag).is_dir():
                run_tag = fast_run_tag
        batch_dir = runner_root / run_tag if run_tag else Path()
        safe_key = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in club_key)
        status_path = batch_dir / "club_status" / f"{safe_key}.status"
        status = status_path.read_text(encoding="utf-8").strip() if status_path.is_file() else "missing"
        club_dir = batch_dir / "clubs" / safe_key
        club_summary = _load_json(club_dir / "summary.json") or {}
        screenshots: list[str] = []
        for source in _find_proof_screens(club_dir):
            screenshots.append(
                _copy_screenshot(
                    source,
                    output_dir,
                    Path(run_tag) / safe_key / source.name,
                )
            )
        route_squad = dict((club_summary.get("route_summaries") or {}).get("squad") or {})
        rows.append(
            {
                "club_key": club_key,
                "team_query": selected.get("team_query"),
                "roster_short_name": selected.get("roster_short_name"),
                "old_name": selected.get("old_name"),
                "expected_name": expected_by_club.get(club_key, selected.get("target_name")),
                "record_id": selected.get("record_id"),
                "family": selected.get("family"),
                "status": status,
                "runner_success": bool(club_summary.get("success")) if club_summary else False,
                "dashboard_reached": bool(club_summary.get("dashboard_reached")) if club_summary else False,
                "crash_detected": bool(club_summary.get("crash_detected")) if club_summary else None,
                "wine_debugger_detected": bool(club_summary.get("wine_debugger_detected")) if club_summary else None,
                "squad_screen": route_squad.get("screen"),
                "squad_expected_screen_matched": route_squad.get("expected_screen_matched"),
                "squad_route_signal_matched": route_squad.get("route_signal_matched"),
                "screenshots": screenshots,
                "run_tag": run_tag,
            }
        )

    summary = {
        "success": bool(rows) and all(str(row["status"]) == "0" and bool(row["runner_success"]) for row in rows),
        "scope": "native_english30_variable_name_runtime_evidence",
        "probe_dir": str(probe_dir),
        "runner_artifact_root": str(runner_root),
        "output_dir": str(output_dir),
        "row_count": len(rows),
        "status_counts": dict(Counter(str(row["status"]) for row in rows)),
        "runner_success_count": sum(1 for row in rows if row["runner_success"]),
        "screenshot_count": sum(len(row["screenshots"]) for row in rows),
        "rows": rows,
        "db_readback": {
            "row_count": len(readback),
            "ok_count": sum(1 for row in readback if bool(row.get("readback_ok"))),
            "family_counts": dict(Counter(str(row.get("family") or "") for row in readback)),
        },
    }
    (output_dir / "native_english30_runtime_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "native_english30_runtime.html").write_text(_render_html(summary), encoding="utf-8")
    return summary


def _render_html(summary: dict[str, Any]) -> str:
    rows_html: list[str] = []
    for row in summary["rows"]:
        thumbs = "\n".join(
            f'<a href="{html.escape(src)}"><img src="{html.escape(src)}" loading="lazy" /></a>'
            for src in list(row.get("screenshots") or [])
        )
        status_class = "ok" if str(row.get("status")) == "0" and row.get("runner_success") else "bad"
        rows_html.append(
            "<tr>"
            f'<td><span class="{status_class}">{html.escape(str(row.get("status")))}</span></td>'
            f"<td>{html.escape(str(row.get('club_key')))}<br><small>{html.escape(str(row.get('roster_short_name')))}</small></td>"
            f"<td>{html.escape(str(row.get('old_name')))}<br><strong>{html.escape(str(row.get('expected_name')))}</strong></td>"
            f"<td>{html.escape(str(row.get('record_id')))}<br><small>{html.escape(str(row.get('family')))}</small></td>"
            f"<td>{html.escape(str(row.get('squad_screen')))}<br><small>dashboard={html.escape(str(row.get('dashboard_reached')))} crash={html.escape(str(row.get('crash_detected')))}</small></td>"
            f'<td class="shots">{thumbs}</td>'
            "</tr>"
        )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>PM99 Native English30 Variable Name Runtime Proof</title>
  <style>
    :root {{
      --bg: #10130f;
      --panel: #f4ead8;
      --ink: #1b2019;
      --muted: #5e644f;
      --ok: #217a3a;
      --bad: #b3372b;
      --line: #d1c3a7;
    }}
    body {{
      margin: 0;
      background: radial-gradient(circle at top left, #39452d, var(--bg) 42rem);
      color: var(--panel);
      font-family: Georgia, 'Times New Roman', serif;
    }}
    header {{
      padding: 2rem clamp(1rem, 4vw, 4rem);
    }}
    h1 {{
      margin: 0 0 0.5rem;
      font-size: clamp(2rem, 5vw, 4.5rem);
      letter-spacing: -0.05em;
    }}
    .meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.75rem;
      color: #ecdfc6;
    }}
    .pill {{
      border: 1px solid rgba(244,234,216,0.35);
      border-radius: 999px;
      padding: 0.35rem 0.75rem;
      background: rgba(0,0,0,0.18);
    }}
    main {{
      padding: 0 clamp(1rem, 4vw, 4rem) 4rem;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
      color: var(--ink);
      box-shadow: 0 1rem 4rem rgba(0,0,0,0.35);
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 0.8rem;
      vertical-align: top;
      text-align: left;
    }}
    th {{
      position: sticky;
      top: 0;
      background: #e8d8ba;
      z-index: 1;
    }}
    small {{
      color: var(--muted);
    }}
    .ok {{
      color: var(--ok);
      font-weight: 700;
    }}
    .bad {{
      color: var(--bad);
      font-weight: 700;
    }}
    .shots {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 0.5rem;
      min-width: 260px;
    }}
    .shots img {{
      width: 100%;
      border: 1px solid var(--line);
      display: block;
    }}
  </style>
</head>
<body>
  <header>
    <h1>Native English30 Variable Name Runtime Proof</h1>
    <div class="meta">
      <span class="pill">rows: {summary["row_count"]}</span>
      <span class="pill">success: {html.escape(str(summary["success"]))}</span>
      <span class="pill">runner ok: {summary["runner_success_count"]}</span>
      <span class="pill">screenshots: {summary["screenshot_count"]}</span>
      <span class="pill">statuses: {html.escape(json.dumps(summary["status_counts"], sort_keys=True))}</span>
    </div>
  </header>
  <main>
    <table>
      <thead>
        <tr>
          <th>Status</th>
          <th>Club</th>
          <th>Name Patch</th>
          <th>Record</th>
          <th>Runtime</th>
          <th>Visual Evidence</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows_html)}
      </tbody>
    </table>
  </main>
</body>
</html>
"""


def main() -> int:
    summary = build(_parse_args())
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
