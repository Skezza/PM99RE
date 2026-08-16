#!/usr/bin/env python3
"""Build browser evidence for the full-corpus variable-name proof."""

from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageStat
except Exception:  # pragma: no cover - optional evidence hardening dependency
    Image = None  # type: ignore[assignment]
    ImageStat = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROOF_ROOT = REPO_ROOT / "work" / "pm99" / "full_corpus_variable_name_proof" / "20260503T_full_closeout"
DEFAULT_RUNNER_ARTIFACT_ROOT = REPO_ROOT / "upstream" / "pm99-runner" / "docs" / "artifacts" / "pm99_runner"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proof-root", default=str(DEFAULT_PROOF_ROOT))
    parser.add_argument("--runner-artifact-root", default=str(DEFAULT_RUNNER_ARTIFACT_ROOT))
    parser.add_argument("--output", default="")
    parser.add_argument(
        "--rescan-images",
        action="store_true",
        help="Recompute crash/squad-screen flags from PNG pixels instead of trusting runner summary flags.",
    )
    return parser.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _rel(path: Path, *, start: Path) -> str:
    return os.path.relpath(path.resolve(), start=start.resolve()).replace(os.sep, "/")


def _pick_squad_screenshot(case: dict[str, Any]) -> str:
    screenshots = [str(item) for item in list(case.get("screenshots") or [])]
    preferences = [
        "squad_inspect_scroll",
        "squad_inspect_filters_enabled",
        "squad_inspect_retry",
        "squad_inspect",
    ]
    for token in preferences:
        for shot in reversed(screenshots):
            if token in shot:
                return shot
    return screenshots[-1] if screenshots else ""


def _ratio(pixels: list[tuple[int, int, int]], predicate: Any) -> float:
    return sum(1 for pixel in pixels if predicate(pixel)) / max(1, len(pixels))


def _looks_like_application_cannot_continue(path: Path) -> bool:
    """Detect the PM99 crash modal that otherwise fools screenshot-only runs."""
    if Image is None or ImageStat is None or not path.is_file():
        return False
    try:
        image = Image.open(path).convert("RGB")
    except Exception:
        return False
    if image.width < 445 or image.height < 290:
        return False

    title = list(image.crop((202, 179, 438, 204)).getdata())
    icon = list(image.crop((214, 210, 250, 246)).getdata())
    panel = image.crop((203, 205, 437, 284))
    text = list(image.crop((255, 215, 425, 235)).getdata())

    title_dark = _ratio(title, lambda rgb: rgb[0] < 80 and rgb[1] < 80 and rgb[2] < 80)
    warning_orange = _ratio(icon, lambda rgb: rgb[0] > 180 and 80 < rgb[1] < 180 and rgb[2] < 90)
    panel_mean = sum(ImageStat.Stat(panel).mean) / 3
    text_dark = _ratio(text, lambda rgb: rgb[0] < 80 and rgb[1] < 80 and rgb[2] < 80)

    return title_dark > 0.45 and warning_orange > 0.03 and panel_mean > 150 and text_dark > 0.01


def _looks_like_squad_management(path: Path) -> bool:
    if Image is None or ImageStat is None or not path.is_file():
        return False
    try:
        image = Image.open(path).convert("RGB")
    except Exception:
        return False
    if image.width < 640 or image.height < 460:
        return False

    header = list(image.crop((150, 5, 450, 55)).getdata())
    table = image.crop((5, 95, 535, 462))
    table_pixels = list(table.getdata())
    header_white = _ratio(header, lambda rgb: rgb[0] > 200 and rgb[1] > 200 and rgb[2] > 200)
    table_light = _ratio(table_pixels, lambda rgb: rgb[0] > 150 and rgb[1] > 150 and rgb[2] > 150)
    table_mean = sum(ImageStat.Stat(table).mean) / 3
    return header_white > 0.04 and table_light > 0.45 and table_mean > 160


def _case_sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
    return (int(item.get("wave_no") or 0), int(item.get("batch_no") or 0), str(item.get("club_key") or ""))


def build(proof_root: Path, runner_artifact_root: Path, output: Path, *, rescan_images: bool = False) -> dict[str, Any]:
    proof_summary = _load_json(proof_root / "summary.json")
    runner_batches = list(_load_json(proof_root / "runner_batches.json"))
    cases: list[dict[str, Any]] = []
    batch_rows: list[dict[str, Any]] = []

    for batch in runner_batches:
        run_tag = str(batch["run_tag"])
        artifact_dir = runner_artifact_root / run_tag
        summary_path = artifact_dir / "summary.json"
        batch_summary: dict[str, Any] | None = None
        if summary_path.exists():
            batch_summary = _load_json(summary_path)
        batch_success = bool(batch_summary and batch_summary.get("success"))
        batch_cases = list(batch_summary.get("cases") or []) if batch_summary else []
        batch_rows.append(
            {
                "wave_no": int(batch["wave_no"]),
                "batch_no": int(batch["batch_no"]),
                "run_tag": run_tag,
                "expected_clubs": list(batch.get("club_keys") or []),
                "summary_path": str(summary_path),
                "exists": summary_path.exists(),
                "success": batch_success,
                "case_count": len(batch_cases),
                "ok_case_count": sum(1 for case in batch_cases if case.get("ok")),
            }
        )
        for case in batch_cases:
            shot = str(case.get("selected_screenshot") or "") or _pick_squad_screenshot(case)
            shot_path = artifact_dir / shot if shot else None
            if rescan_images:
                crash_dialog = _looks_like_application_cannot_continue(shot_path) if shot_path else False
                squad_screen = _looks_like_squad_management(shot_path) if shot_path else False
                visual_ok = (
                    bool(case.get("process_ok", case.get("status") == 0))
                    and bool(shot_path and shot_path.exists())
                    and not crash_dialog
                    and squad_screen
                )
            else:
                crash_dialog = bool(case.get("application_cannot_continue"))
                squad_screen = bool(case.get("squad_management_screen"))
                visual_ok = bool(case.get("visual_ok", case.get("ok")))
            cases.append(
                {
                    "wave_no": int(batch["wave_no"]),
                    "batch_no": int(batch["batch_no"]),
                    "run_tag": run_tag,
                    "club_key": str(case.get("club_key") or ""),
                    "team_query": str(case.get("team_query") or ""),
                    "ok": bool(case.get("ok")),
                    "visual_ok": visual_ok,
                    "application_cannot_continue": crash_dialog,
                    "squad_management_screen": squad_screen,
                    "status": int(case.get("status") or 0),
                    "screenshot": str(shot_path) if shot_path else "",
                    "screenshot_rel": _rel(shot_path, start=output.parent) if shot_path and shot_path.exists() else "",
                    "summary_path": str(case.get("summary_path") or ""),
                    "screenshot_count": len(list(case.get("screenshots") or [])),
                }
            )

    expected_case_count = sum(len(list(batch.get("club_keys") or [])) for batch in runner_batches)
    ok_cases = [case for case in cases if case["ok"]]
    visual_ok_cases = [case for case in cases if case["visual_ok"]]
    failed_cases = [case for case in cases if not case["ok"]]
    visual_failed_cases = [case for case in cases if not case["visual_ok"]]
    crash_dialog_cases = [case for case in cases if case["application_cannot_continue"]]
    complete_batches = [row for row in batch_rows if row["exists"]]
    successful_batches = [row for row in batch_rows if row["success"]]
    missing_batches = [row for row in batch_rows if not row["exists"]]
    failed_batches = [row for row in batch_rows if row["exists"] and not row["success"]]

    evidence_summary = {
        "success": (
            bool(proof_summary.get("success"))
            and int(proof_summary.get("post_write_failure_count") or 0) == 0
            and not any(int(wave.get("warning_count") or 0) for wave in list(proof_summary.get("waves") or []))
            and not any(list(wave.get("readback_failures") or []) for wave in list(proof_summary.get("waves") or []))
            and len(successful_batches) == len(runner_batches)
            and len(ok_cases) == expected_case_count
            and not failed_cases
            and len(visual_ok_cases) == expected_case_count
            and not crash_dialog_cases
        ),
        "proof_root": str(proof_root),
        "runner_artifact_root": str(runner_artifact_root),
        "html": str(output),
        "dd6360_contract": str(proof_summary.get("dd6360_contract") or ""),
        "supported_player_count": int(proof_summary.get("supported_player_count") or 0),
        "preserve_only_count": int(proof_summary.get("preserve_only_count") or 0),
        "record_count": int(proof_summary.get("record_count") or 0),
        "carrier_slot_count": int(proof_summary.get("carrier_slot_count") or 0),
        "wave_count": int(proof_summary.get("wave_count") or 0),
        "runner_batch_count": len(runner_batches),
        "complete_batch_count": len(complete_batches),
        "successful_batch_count": len(successful_batches),
        "failed_batch_count": len(failed_batches),
        "missing_batch_count": len(missing_batches),
        "expected_case_count": expected_case_count,
        "case_count": len(cases),
        "ok_case_count": len(ok_cases),
        "failed_case_count": len(failed_cases),
        "visual_ok_case_count": len(visual_ok_cases),
        "visual_failed_case_count": len(visual_failed_cases),
        "application_cannot_continue_count": len(crash_dialog_cases),
        "squad_management_screen_count": sum(1 for case in cases if case["squad_management_screen"]),
        "failed_batches": failed_batches,
        "missing_batches": missing_batches,
        "failed_cases": failed_cases,
        "visual_failed_cases": visual_failed_cases,
        "application_cannot_continue_cases": crash_dialog_cases,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    summary_path = output.with_suffix(".summary.json")
    _json_dump(summary_path, evidence_summary)

    def card(label: str, value: Any) -> str:
        return f"<div class='card'><div class='label'>{html.escape(label)}</div><div class='value'>{html.escape(str(value))}</div></div>"

    cards = [
        card("Supported player records", evidence_summary["supported_player_count"]),
        card("Preserve-only opaque rows", evidence_summary["preserve_only_count"]),
        card("dd6360 contract", evidence_summary["dd6360_contract"] or "n/a"),
        card("Carrier slots per full wave", evidence_summary["carrier_slot_count"]),
        card("DB proof waves", evidence_summary["wave_count"]),
        card("Runner batches", f"{evidence_summary['successful_batch_count']}/{evidence_summary['runner_batch_count']}"),
        card("Runner club cases", f"{evidence_summary['ok_case_count']}/{evidence_summary['expected_case_count']}"),
        card("Visual squad cases", f"{evidence_summary['visual_ok_case_count']}/{evidence_summary['expected_case_count']}"),
        card("Crash modal detections", evidence_summary["application_cannot_continue_count"]),
        card("Squad-screen detections", evidence_summary["squad_management_screen_count"]),
    ]

    wave_rows = []
    for wave in list(proof_summary.get("waves") or []):
        ok = int(wave.get("readback_ok_count") or 0) == int(wave.get("player_count") or 0)
        wave_rows.append(
            "<tr>"
            f"<td>{int(wave.get('wave_no') or 0)}</td>"
            f"<td>{int(wave.get('player_count') or 0)}</td>"
            f"<td>{int(wave.get('club_count') or 0)}</td>"
            f"<td>{html.escape(str(wave.get('proof_index_min')))}..{html.escape(str(wave.get('proof_index_max')))}</td>"
            f"<td class='{ 'ok' if ok else 'bad' }'>{html.escape(str(wave.get('readback_ok_count')))} / {html.escape(str(wave.get('player_count')))}</td>"
            f"<td>{int(wave.get('warning_count') or 0)}</td>"
            "</tr>"
        )

    family_rows = []
    for family, count in sorted(dict(proof_summary.get("family_counts") or {}).items()):
        family_rows.append(f"<tr><td>{html.escape(str(family))}</td><td>{int(count)}</td></tr>")

    batch_table_rows = []
    for row in batch_rows:
        status_class = "ok" if row["success"] else ("bad" if row["exists"] else "pending")
        status = "ok" if row["success"] else ("failed" if row["exists"] else "missing")
        batch_table_rows.append(
            "<tr>"
            f"<td>{row['wave_no']}</td>"
            f"<td>{row['batch_no']}</td>"
            f"<td>{html.escape(row['run_tag'])}</td>"
            f"<td class='{status_class}'>{status}</td>"
            f"<td>{row['ok_case_count']} / {len(row['expected_clubs'])}</td>"
            "</tr>"
        )

    case_cards = []
    for case in sorted(cases, key=_case_sort_key):
        cls = "case okcase" if case["visual_ok"] else "case badcase"
        img = ""
        if case["screenshot_rel"]:
            img = f"<img src='{html.escape(case['screenshot_rel'])}' loading='lazy' alt='{html.escape(case['club_key'])} squad proof'>"
        marker = "visual ok" if case["visual_ok"] else "visual failed"
        if case["application_cannot_continue"]:
            marker = "Application cannot continue"
        elif not case["squad_management_screen"]:
            marker = "not squad management"
        case_cards.append(
            f"<article class='{cls}'>"
            f"<h3>W{case['wave_no']:02d} B{case['batch_no']:02d} {html.escape(case['club_key'])}</h3>"
            f"<p>{html.escape(case['team_query'])} · status {case['status']} · screenshots {case['screenshot_count']} · {html.escape(marker)}</p>"
            f"{img}"
            "</article>"
        )

    html_text = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PM99 Full-Corpus Variable Name Proof</title>
<style>
:root {{ --ink:#111827; --muted:#5b6472; --line:#d8dee8; --ok:#0f7b4f; --bad:#b3261e; --pending:#8a5a00; --paper:#f8f5ef; }}
body {{ margin:0; font-family: Georgia, 'Times New Roman', serif; color:var(--ink); background:linear-gradient(135deg,#f8f5ef,#eaf0f7); }}
main {{ max-width:1280px; margin:0 auto; padding:32px 18px 56px; }}
h1 {{ font-size:42px; line-height:1; margin:0 0 10px; }}
h2 {{ margin-top:34px; border-bottom:1px solid var(--line); padding-bottom:8px; }}
p {{ color:var(--muted); }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; margin:22px 0; }}
.card {{ background:white; border:1px solid var(--line); border-radius:14px; padding:16px; box-shadow:0 8px 24px rgba(31,41,55,.08); }}
.label {{ color:var(--muted); font-size:13px; }}
.value {{ font-size:26px; font-weight:700; }}
table {{ width:100%; border-collapse:collapse; background:white; border:1px solid var(--line); }}
th,td {{ padding:8px 10px; border-bottom:1px solid var(--line); text-align:left; font-size:14px; }}
th {{ background:#edf2f7; }}
.ok {{ color:var(--ok); font-weight:700; }}
.bad {{ color:var(--bad); font-weight:700; }}
.pending {{ color:var(--pending); font-weight:700; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:14px; }}
.case {{ background:white; border:1px solid var(--line); border-radius:12px; overflow:hidden; box-shadow:0 8px 22px rgba(31,41,55,.07); }}
.case h3 {{ margin:12px 12px 4px; font-size:16px; }}
.case p {{ margin:0 12px 10px; font-size:13px; }}
.case img {{ width:100%; display:block; border-top:1px solid var(--line); image-rendering:auto; }}
.badcase {{ outline:3px solid rgba(179,38,30,.25); }}
code {{ background:rgba(17,24,39,.08); padding:2px 5px; border-radius:5px; }}
</style>
</head>
<body>
<main>
<h1>PM99 Full-Corpus Variable Name Proof</h1>
<p>DB-only full-corpus variable-name rewrite plus PM99 runner proof-carrier waves. The milestone is closed only when every generated runner batch is green and every expected club case has an in-game squad screenshot that is not the PM99 crash modal.</p>
<section class="cards">{''.join(cards)}</section>
<p>Proof root: <code>{html.escape(str(proof_root))}</code></p>
<p>Machine summary: <code>{html.escape(str(summary_path))}</code></p>
<h2>Patch Families</h2>
<table><thead><tr><th>Family</th><th>Records</th></tr></thead><tbody>{''.join(family_rows)}</tbody></table>
<h2>DB Wave Gates</h2>
<table><thead><tr><th>Wave</th><th>Players</th><th>Clubs</th><th>Proof index</th><th>Linked readback</th><th>Warnings</th></tr></thead><tbody>{''.join(wave_rows)}</tbody></table>
<h2>Runner Batches</h2>
<table><thead><tr><th>Wave</th><th>Batch</th><th>Run tag</th><th>Status</th><th>Cases</th></tr></thead><tbody>{''.join(batch_table_rows)}</tbody></table>
<h2>In-Game Squad Screenshots</h2>
<div class="grid">{''.join(case_cards)}</div>
</main>
</body>
</html>
"""
    output.write_text(html_text, encoding="utf-8")
    return evidence_summary


def main() -> int:
    args = _parse_args()
    proof_root = Path(args.proof_root).expanduser().resolve()
    output = Path(args.output).expanduser().resolve() if args.output else proof_root / "evidence" / "full_corpus_variable_name_evidence.html"
    summary = build(
        proof_root=proof_root,
        runner_artifact_root=Path(args.runner_artifact_root).expanduser().resolve(),
        output=output,
        rescan_images=bool(args.rescan_images),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
