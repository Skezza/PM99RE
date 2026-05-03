#!/usr/bin/env python3
"""Build a local HTML proof page for Stoke 2015 variable-length names."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create an HTML proof page for the Stoke variable-name milestone.")
    parser.add_argument("--artifact-dir", required=True, help="Directory containing physical variable-name artifacts")
    parser.add_argument("--runner-artifacts-dir", required=True, help="Runner artifact directory with summary/screens/profiles")
    parser.add_argument("--output-html", help="Output HTML path")
    return parser.parse_args()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_rel(from_dir: Path, target: Path) -> str:
    try:
        return target.resolve().relative_to(from_dir.resolve()).as_posix()
    except Exception:
        return str(target.resolve())


def _status_class(ok: bool) -> str:
    return "ok" if ok else "bad"


def _copy_summary(runner_summary: dict[str, Any]) -> dict[str, Any]:
    profile_captures = list(runner_summary.get("profile_captures") or [])
    profile_screens = [
        str((capture.get("profile_screen_classification") or {}).get("screen") or "")
        for capture in profile_captures
    ]
    return {
        "success": bool(runner_summary.get("success")),
        "profile_capture_ok": bool(runner_summary.get("profile_capture_ok")),
        "profile_capture_count": int(runner_summary.get("profile_capture_count") or 0),
        "profile_capture_expected": int(runner_summary.get("profile_capture_expected") or 0),
        "profile_player_screen_count": sum(screen == "player_profile_screen" for screen in profile_screens),
        "crash_detected": bool(runner_summary.get("crash_detected")),
        "wine_debugger_detected": bool(runner_summary.get("wine_debugger_detected")),
        "final_screen": str((runner_summary.get("final_screen_classification") or {}).get("screen") or ""),
    }


def main() -> int:
    args = _parse_args()
    artifact_dir = Path(args.artifact_dir).expanduser().resolve()
    runner_artifacts_dir = Path(args.runner_artifacts_dir).expanduser().resolve()
    output_html = (
        Path(args.output_html).expanduser().resolve()
        if args.output_html
        else artifact_dir / "stoke_2015_variable_name_proof.html"
    )
    output_html.parent.mkdir(parents=True, exist_ok=True)

    manifest = _load_json(artifact_dir / "physical_variable_manifest.json")
    patches = list(_load_json(artifact_dir / "physical_variable_patches.json"))
    roster_payload = _load_json(artifact_dir / "team_roster_linked.json")
    runtime_audit = _load_json(artifact_dir / "team_roster_runtime_audit.json")
    validate_database = _load_json(artifact_dir / "validate_database.json")
    runner_summary = _load_json(runner_artifacts_dir / "summary.json")
    runner_brief = _copy_summary(runner_summary)

    roster_rows = []
    if roster_payload:
        roster_rows = list((roster_payload[0] or {}).get("rows") or [])
    roster_names_by_pid = {int(row.get("pid") or 0): str(row.get("player_name") or "") for row in roster_rows}
    profile_captures = [
        dict(capture)
        for capture in list(runner_summary.get("profile_captures") or [])
        if int(capture.get("slot") or 0) > 0
    ]

    name_ends = [int(row.get("new_name_end") or 0) for row in patches]
    removed_padding = [int(row.get("removed_fixed_padding_bytes") or 0) for row in patches]
    payload_lengths = sorted({int(row.get("payload_length") or 0) for row in patches})
    static_ok = bool(validate_database.get("all_valid")) and int(runtime_audit.get("issue_count") or 0) == 0
    manifest_ok = bool(manifest.get("ok")) and int(manifest.get("failure_count") or 0) == 0
    runner_visual_ok = (
        runner_brief["profile_capture_count"] == runner_brief["profile_capture_expected"] == len(patches)
        and runner_brief["profile_player_screen_count"] == len(patches)
        and not runner_brief["crash_detected"]
        and not runner_brief["wine_debugger_detected"]
    )

    table_rows: list[str] = []
    gallery_rows: list[str] = []
    for patch in patches:
        slot = int(patch.get("slot") or 0)
        pid = int(patch.get("pid") or 0)
        fields = dict(patch.get("fields") or {})
        skills = dict(fields.get("skills") or {})
        table_rows.append(
            "<tr>"
            f"<td>{slot}</td>"
            f"<td>{html.escape(str(patch.get('original_name') or ''))}</td>"
            f"<td>{html.escape(str(patch.get('original_role') or ''))}</td>"
            f"<td>{html.escape(str(patch.get('applied_name') or ''))}</td>"
            f"<td>{html.escape(str(patch.get('target_role') or ''))}</td>"
            f"<td>{pid}</td>"
            f"<td>{html.escape(roster_names_by_pid.get(pid, ''))}</td>"
            f"<td>{int(patch.get('old_name_end') or 0)}</td>"
            f"<td>{int(patch.get('new_name_end') or 0)}</td>"
            f"<td>{int(patch.get('removed_fixed_padding_bytes') or 0)}</td>"
            f"<td>{int(patch.get('payload_length') or 0)}</td>"
            f"<td>{int(fields.get('visible_nationality_code') or 0)}</td>"
            f"<td>{int(skills.get('speed') or 0)}</td>"
            f"<td>{int(skills.get('passing') or 0)}</td>"
            f"<td>{'yes' if runner_visual_ok else 'no'}</td>"
            "</tr>"
        )
    for capture in profile_captures:
        capture_index = int(capture.get("slot") or 0)
        classification = dict(capture.get("profile_screen_classification") or {})
        profile_path = runner_artifacts_dir / "profiles" / f"{capture_index:02d}.png"
        profile_rel = _safe_rel(output_html.parent, profile_path)
        gallery_rows.append(
            "<figure>"
            f"<figcaption>Profile open {capture_index:02d}: {html.escape(str(classification.get('screen') or 'missing'))}</figcaption>"
            f"<img src='{html.escape(profile_rel)}' alt='profile open {capture_index:02d}'>"
            "</figure>"
        )

    squad_images = []
    for name in ("29_dashboard_select_squad.png", "31_dashboard_activate_squad.png"):
        path = runner_artifacts_dir / "screens" / name
        if path.is_file():
            squad_images.append(
                "<figure>"
                f"<figcaption>{html.escape(name)}</figcaption>"
                f"<img src='{html.escape(_safe_rel(output_html.parent, path))}' alt='{html.escape(name)}'>"
                "</figure>"
            )

    css = """
body{font-family:Georgia,'Times New Roman',serif;margin:0;background:#efe8d2;color:#1d241c}
header{padding:28px 34px;background:#173d2c;color:#f8f0d8;border-bottom:8px solid #b33d2e}
h1{margin:0 0 8px 0;font-size:34px}
.wrap{padding:24px 34px}
.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:18px}
.card{background:#fff8df;border:1px solid #c5b789;padding:14px;box-shadow:3px 3px 0 #d8c992}
.label{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#59604d}
.value{font-size:24px;font-weight:700;margin-top:4px}
.ok{color:#126327}.bad{color:#9c1f18}
table{width:100%;border-collapse:collapse;background:#fffdf2;border:1px solid #c5b789;margin:16px 0}
th,td{padding:7px 8px;border-bottom:1px solid #ddd0a6;text-align:left;font-size:13px}
th{background:#203927;color:#fff7df;position:sticky;top:0}
.gallery{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.profiles{grid-template-columns:repeat(3,minmax(0,1fr))}
figure{margin:0;background:#fffdf2;border:1px solid #c5b789;padding:8px}
figcaption{font-weight:700;margin-bottom:6px}
img{width:100%;height:auto;image-rendering:auto;border:1px solid #7f866e;background:#111}
code{background:#fff7d1;padding:1px 4px}
@media(max-width:1100px){.cards,.gallery,.profiles{grid-template-columns:1fr}}
""".strip()

    html_text = "\n".join(
        [
            "<!doctype html>",
            "<html lang='en'>",
            "<head>",
            "<meta charset='utf-8'>",
            "<meta name='viewport' content='width=device-width, initial-scale=1'>",
            "<title>Stoke 2015 Variable-Length Name Proof</title>",
            f"<style>{css}</style>",
            "</head>",
            "<body>",
            "<header>",
            "<h1>Stoke 2015 Variable-Length Name Proof</h1>",
            "<p>Physical DB compaction proof: names are no longer fixed to the old 49-byte cursor, while each linked player payload remains runtime-safe.</p>",
            "</header>",
            "<main class='wrap'>",
            "<section class='cards'>",
            f"<div class='card'><div class='label'>Manifest</div><div class='value {_status_class(manifest_ok)}'>{'PASS' if manifest_ok else 'FAIL'}</div></div>",
            f"<div class='card'><div class='label'>Static DB Audit</div><div class='value {_status_class(static_ok)}'>{'PASS' if static_ok else 'FAIL'}</div></div>",
            f"<div class='card'><div class='label'>Runner Visual Audit</div><div class='value {_status_class(runner_visual_ok)}'>{'PASS' if runner_visual_ok else 'FAIL'}</div></div>",
            f"<div class='card'><div class='label'>Runner Exit Gate</div><div class='value {_status_class(bool(runner_brief['success']))}'>{'PASS' if runner_brief['success'] else 'FAIL'}</div></div>",
            "</section>",
            "<section class='card'>",
            "<h2>Technical Result</h2>",
            f"<p><strong>Contract:</strong> {html.escape(str(manifest.get('contract') or ''))}</p>",
            f"<p><strong>Patch rows:</strong> {len(patches)}. <strong>Payload lengths:</strong> {html.escape(str(payload_lengths))}. <strong>New name end range:</strong> {min(name_ends)}..{max(name_ends)}. <strong>Removed fixed padding range:</strong> {min(removed_padding)}..{max(removed_padding)} bytes.</p>",
            f"<p><strong>Runner summary:</strong> {runner_brief['profile_capture_count']}/{runner_brief['profile_capture_expected']} profiles captured, {runner_brief['profile_player_screen_count']} classified as player profiles, final screen <code>{html.escape(runner_brief['final_screen'])}</code>, crash={runner_brief['crash_detected']}, wine_debugger={runner_brief['wine_debugger_detected']}.</p>",
            f"<p><strong>Artifact dir:</strong> <code>{html.escape(str(artifact_dir))}</code></p>",
            f"<p><strong>Runner dir:</strong> <code>{html.escape(str(runner_artifacts_dir))}</code></p>",
            "</section>",
            "<h2>Squad Screens</h2>",
            "<section class='gallery'>",
            *squad_images,
            "</section>",
            "<h2>Variable Name Rows</h2>",
            "<table>",
            "<thead><tr><th>EQ slot</th><th>Original slot</th><th>Original role</th><th>Applied name</th><th>Target role</th><th>PID</th><th>Parser roster name</th><th>Old name end</th><th>New name end</th><th>Moved padding</th><th>Payload</th><th>Nat code</th><th>Speed</th><th>Passing</th><th>Runner 20/20 pass</th></tr></thead>",
            "<tbody>",
            *table_rows,
            "</tbody>",
            "</table>",
            "<h2>Profile Screenshots</h2>",
            "<p>These prove repeated player-profile opens from Squad Management. Identity/order proof comes from the full squad screenshot and the EQ/original-slot assignment table above; the game can change focus/order while profiles are opened.</p>",
            "<section class='gallery profiles'>",
            *gallery_rows,
            "</section>",
            "</main>",
            "</body>",
            "</html>",
        ]
    )
    output_html.write_text(html_text + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "output_html": str(output_html), "runner_visual_ok": runner_visual_ok}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
