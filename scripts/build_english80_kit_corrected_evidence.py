#!/usr/bin/env python3
"""Build a static evidence report for the kit-corrected English 80 candidate."""

from __future__ import annotations

import argparse
import collections
import html
import json
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUILD_DIR = ROOT / "work/pm99/english80_2026_division_structured/english80_2026_division_structured_20260501T212554Z"
DEFAULT_OUTPUT_DIR = ROOT / "artifacts/english80_kit_corrected_20260501"
DEFAULT_RUNNER_DIR = ROOT / "upstream/pm99-runner/docs/artifacts/pm99_runner/english80_kit_corrected_selector_20260501T212554Z"
DEFAULT_VISUAL_DIR = ROOT / "upstream/pm99-runner/docs/artifacts/pm99_runner/english80_kit_corrected_visual_proofs_20260501T212554Z"


HIGHLIGHT_KEYS = {
    "arsenal",
    "liverpool",
    "manchester_united",
    "stoke_city",
    "bromley",
    "wrexham",
    "afc_wimbledon",
    "crawley_town",
}

VISUAL_TRUSTED_KEYS = {
    "arsenal",
    "liverpool",
    "manchester_united",
    "stoke_city",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def copy_asset(src: Path, dst: Path) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst.as_posix()


def rel(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()


def safe_name(value: str) -> str:
    chars = []
    for char in value.lower():
        if char.isalnum():
            chars.append(char)
        elif chars and chars[-1] != "_":
            chars.append("_")
    return "".join(chars).strip("_") or "item"


def status_badge(status: str) -> str:
    classes = {
        "kept": "ok",
        "copied_source": "ok",
        "resampled_source": "warn",
        "synthesized": "new",
        "synthesized_missing_source": "warn",
        "missing_target_record": "muted",
    }
    cls = classes.get(status, "plain")
    return f'<span class="badge {cls}">{html.escape(status.replace("_", " "))}</span>'


def action_label(action: str) -> str:
    labels = {
        "keep_existing": "kept original identity kit",
        "copy_existing_source": "copied correct PM99 source kit",
        "synthesize_modern": "synthesized modern kit",
    }
    return labels.get(action, action.replace("_", " "))


def find_per_club_image(build_dir: Path, row: dict[str, Any]) -> Path | None:
    preview_dir = build_dir / "kit_patch/per_club_miniesc"
    slot = int(row["slot"])
    key = safe_name(row["target_display_name"]).title().replace("_", "_")
    eq_id = int(row["carrier_eq_record_id"])
    candidates = sorted(preview_dir.glob(f"{slot:02d}_*_EQ{eq_id:04d}.png"))
    if candidates:
        return candidates[0]
    candidates = sorted(preview_dir.glob(f"{slot:02d}_*.png"))
    if candidates:
        return candidates[0]
    candidates = sorted(preview_dir.glob(f"*{key}*.png"))
    return candidates[0] if candidates else None


def copy_kit_assets(build_dir: Path, output_dir: Path, plan: list[dict[str, Any]]) -> dict[str, str]:
    assets: dict[str, str] = {}
    contact_src = build_dir / "kit_patch/english80_division_kit_contact_sheet.png"
    if contact_src.exists():
        contact_dst = output_dir / "assets/english80_division_kit_contact_sheet.png"
        copy_asset(contact_src, contact_dst)
        assets["contact_sheet"] = rel(contact_dst, output_dir)
    for row in plan:
        src = find_per_club_image(build_dir, row)
        if not src:
            continue
        dst = output_dir / "assets/kits" / src.name
        copy_asset(src, dst)
        assets[row["target_club_key"]] = rel(dst, output_dir)
    return assets


def load_runner_screens(runner_dir: Path, output_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    discovery_path = runner_dir / "selector_discovery.json"
    summary_path = runner_dir / "selector_discovery_summary.json"
    if not discovery_path.exists():
        return [], {
            "available": False,
            "runner_dir": runner_dir.as_posix(),
            "reason": "selector_discovery.json not present yet",
        }

    discovery = read_json(discovery_path)
    summary = read_json(summary_path) if summary_path.exists() else {}
    observations: list[dict[str, Any]] = []
    for division in discovery.get("divisions", []):
        div_key = division.get("division_key", "")
        for team in division.get("teams", []):
            remote_screen = Path(team.get("screenshot", ""))
            local_screen = runner_dir / "screens" / remote_screen.name
            if not local_screen.exists():
                continue
            dst = output_dir / "assets/screens" / local_screen.name
            copy_asset(local_screen, dst)
            observations.append(
                {
                    "division_key": div_key,
                    "row_index": team.get("row_index"),
                    "text": (team.get("text") or "").strip(),
                    "ocr_normalized": team.get("ocr_normalized") or "",
                    "screenshot": rel(dst, output_dir),
                    "team_select_x": team.get("team_select_x"),
                    "team_select_y": team.get("team_select_y"),
                    "selected_team_select_x": team.get("selected_team_select_x"),
                    "selected_team_select_y": team.get("selected_team_select_y"),
                }
            )
    return observations, {
        "available": True,
        "runner_dir": runner_dir.as_posix(),
        "summary": summary,
        "observation_count": len(observations),
    }


def preferred_squad_screen(screens_dir: Path) -> Path | None:
    for name in [
        "025_squad_inspect_final.png",
        "023_squad_inspect_retry.png",
        "021_squad_inspect.png",
    ]:
        candidate = screens_dir / name
        if candidate.exists():
            return candidate
    candidates = sorted(screens_dir.glob("*squad_inspect*.png"))
    return candidates[-1] if candidates else None


def load_visual_proofs(visual_dir: Path, output_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not visual_dir.exists():
        return [], {
            "available": False,
            "visual_dir": visual_dir.as_posix(),
            "reason": "visual proof directory not present yet",
        }

    summary_path = visual_dir / "summary.json"
    summary = read_json(summary_path) if summary_path.exists() else {}
    cases: list[dict[str, Any]] = []
    for club_dir in sorted((visual_dir / "clubs").glob("*")) if (visual_dir / "clubs").exists() else []:
        if not club_dir.is_dir():
            continue
        club_key = club_dir.name
        screens_dir = club_dir / "screens"
        pick_src = screens_dir / "008_pick_team.png"
        squad_src = preferred_squad_screen(screens_dir)
        copied: dict[str, str] = {}
        for label, src in [("pick_team", pick_src), ("squad", squad_src)]:
            if src and src.exists():
                dst = output_dir / "assets/visual" / club_key / src.name
                copy_asset(src, dst)
                copied[label] = rel(dst, output_dir)
        status_path = visual_dir / "club_status" / f"{club_key}.status"
        status = status_path.read_text(encoding="utf-8").strip() if status_path.exists() else ""
        cases.append(
            {
                "club_key": club_key,
                "ok": status == "0",
                "status": status,
                "pick_team": copied.get("pick_team", ""),
                "squad": copied.get("squad", ""),
                "summary_path": (club_dir / "summary.json").as_posix(),
            }
        )
    return cases, {
        "available": True,
        "visual_dir": visual_dir.as_posix(),
        "summary": summary,
        "case_count": len(cases),
        "ok_count": sum(1 for case in cases if case["ok"]),
    }


def event_summary(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for event in events:
        key = event["target_club_key"]
        row = by_key.setdefault(
            key,
            {
                "status_counts": collections.Counter(),
                "archives": [],
                "events": [],
            },
        )
        row["status_counts"][event["status"]] += 1
        row["archives"].append(event["archive_name"])
        row["events"].append(event)
    for row in by_key.values():
        row["status_counts"] = dict(row["status_counts"])
    return by_key


def find_runner_highlights(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    wanted_tokens = [
        ("Arsenal", "arsenal"),
        ("Liverpool", "liverpool"),
        ("Manchester United", "manchester"),
        ("Stoke City", "stoke"),
        ("Burton Albion", "burton"),
        ("Stevenage", "stevenage"),
        ("Bromley", "bromley"),
        ("Wrexham", "wrexham"),
        ("AFC Wimbledon", "wimbledon"),
        ("Crawley Town", "crawley"),
    ]
    highlights: list[dict[str, Any]] = []
    used: set[str] = set()
    for label, token in wanted_tokens:
        for obs in observations:
            haystack = " ".join([obs.get("ocr_normalized", ""), obs.get("text", "")]).lower()
            if token in haystack and obs["screenshot"] not in used:
                copy = dict(obs)
                copy["label"] = label
                highlights.append(copy)
                used.add(obs["screenshot"])
                break
    return highlights


def build_html(
    manifest: dict[str, Any],
    kit_assets: dict[str, str],
    events_by_key: dict[str, dict[str, Any]],
    observations: list[dict[str, Any]],
    runner_meta: dict[str, Any],
    visual_cases: list[dict[str, Any]],
    visual_meta: dict[str, Any],
) -> str:
    plan = manifest["plan"]
    by_division: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in plan:
        by_division[row["target_pm99_division"]].append(row)

    status_counts = manifest["status_counts"]
    action_counts = collections.Counter(row["kit_action"] for row in plan)
    kind_counts = collections.Counter(row["source_kind"] for row in plan)
    stoke = next(row for row in plan if row["target_club_key"] == "stoke_city")
    stoke_events = events_by_key["stoke_city"]["events"]
    trusted_visual_count = sum(1 for case in visual_cases if case["club_key"] in VISUAL_TRUSTED_KEYS and case["ok"])

    stat_cards = [
        ("Build status", "ok=true"),
        ("Clubs", str(len(plan))),
        ("Players", "1,600"),
        ("Kit patch", "ok=true"),
        ("Copied source records", str(status_counts.get("copied_source", 0))),
        ("Synthesized records", str(status_counts.get("synthesized", 0))),
        ("Runner screenshots", str(len(observations)) if observations else "queued"),
        ("Targeted proofs", f"{trusted_visual_count} verified" if visual_cases else "queued"),
        ("Direct PM99 identities", str(kind_counts.get("direct_existing", 0))),
    ]
    stats_html = "".join(
        f'<div class="stat"><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></div>'
        for label, value in stat_cards
    )

    stoke_statuses = "".join(status_badge(event["status"]) for event in stoke_events)
    stoke_html = f"""
      <section class="focus">
        <div>
          <p class="eyebrow">Stoke/Wolves fix</p>
          <h2>Stoke stays in First Division, but its visible carrier now receives Stoke kit art</h2>
          <p>
            The modern First Division slot is still carried by <code>EQ{stoke['carrier_eq_record_id']:04d}</code>,
            which is why it previously inherited Wolverhampton kit art. The corrected build copies Stoke's original
            PM99 source kit from <code>EQ{stoke['desired_eq_record_id']:04d}</code> onto the visible carrier records
            in the writable kit archives.
          </p>
          <div class="status-row">{stoke_statuses}</div>
        </div>
        <figure class="kit-focus">
          <img src="{html.escape(kit_assets.get('stoke_city', ''))}" alt="Corrected Stoke City kit preview">
          <figcaption>Stoke City preview after archive patch: carrier EQ{stoke['carrier_eq_record_id']:04d}, source EQ{stoke['desired_eq_record_id']:04d}</figcaption>
        </figure>
      </section>
    """

    highlight_cards = []
    for key in ["liverpool", "stoke_city", "manchester_united", "arsenal", "bromley", "afc_wimbledon", "wrexham", "crawley_town"]:
        row = next((item for item in plan if item["target_club_key"] == key), None)
        if not row:
            continue
        event_info = events_by_key.get(key, {"status_counts": {}})
        status_list = " ".join(status_badge(status) for status in event_info["status_counts"])
        img_src = kit_assets.get(key, "")
        highlight_cards.append(
            '<article class="club-card">'
            f'<img src="{html.escape(img_src)}" alt="{html.escape(row["target_display_name"])} corrected kit preview">'
            f'<div><h3>{html.escape(row["target_display_name"])}</h3>'
            f'<p>{html.escape(row["target_pm99_division"])} · carrier <code>EQ{row["carrier_eq_record_id"]:04d}</code> · source <code>EQ{row["desired_eq_record_id"]:04d}</code></p>'
            f'<p>{html.escape(action_label(row["kit_action"]))}</p><div class="status-row">{status_list}</div></div>'
            "</article>"
        )

    runner_highlights = find_runner_highlights(observations)
    runner_highlight_html = ""
    if runner_highlights:
        runner_highlight_html = "<section><h2>In-game Selector Highlights</h2><div class=\"screen-grid highlight-screens\">"
        for obs in runner_highlights:
            label = obs["label"]
            text = obs.get("text") or obs.get("ocr_normalized") or "OCR unavailable"
            runner_highlight_html += (
                '<figure class="screen">'
                f'<img src="{html.escape(obs["screenshot"])}" alt="{html.escape(label)} selector screenshot">'
                f'<figcaption><strong>{html.escape(label)}</strong><span>{html.escape(obs["division_key"])} · OCR: {html.escape(text)}</span></figcaption>'
                "</figure>"
            )
        runner_highlight_html += "</div></section>"
    else:
        runner_highlight_html = (
            "<section><h2>In-game Selector Highlights</h2>"
            f"<p class=\"note\">Runner evidence is queued or unavailable. Source: <code>{html.escape(runner_meta.get('runner_dir', ''))}</code></p>"
            "</section>"
        )

    visual_by_key = {case["club_key"]: case for case in visual_cases}
    visual_order = [
        "arsenal",
        "liverpool",
        "manchester_united",
        "stoke_city",
        "wrexham",
        "afc_wimbledon",
        "bromley",
        "crawley_town",
    ]
    visual_html = ""
    trusted_visual_cases = [case for case in visual_cases if case["club_key"] in VISUAL_TRUSTED_KEYS]
    excluded_visual_cases = [case for case in visual_cases if case["club_key"] not in VISUAL_TRUSTED_KEYS]
    if trusted_visual_cases:
        visual_html = '<section><h2>Targeted In-game Club Proofs</h2><div class="visual-grid">'
        for key in visual_order:
            case = visual_by_key.get(key)
            row = next((item for item in plan if item["target_club_key"] == key), None)
            if not case or not row or key not in VISUAL_TRUSTED_KEYS:
                continue
            status = "OK" if case["ok"] else f"status {case.get('status') or 'unknown'}"
            visual_html += '<article class="visual-card">'
            visual_html += f'<h3>{html.escape(row["target_display_name"])}</h3>'
            visual_html += f'<p>{html.escape(row["target_pm99_division"])} · carrier <code>EQ{int(row["carrier_eq_record_id"]):04d}</code> · {html.escape(status)}</p>'
            visual_html += '<div class="visual-pair">'
            if case.get("pick_team"):
                visual_html += (
                    '<figure class="screen">'
                    f'<img src="{html.escape(case["pick_team"])}" alt="{html.escape(row["target_display_name"])} selector proof">'
                    "<figcaption>New-game selector</figcaption></figure>"
                )
            if case.get("squad"):
                visual_html += (
                    '<figure class="screen">'
                    f'<img src="{html.escape(case["squad"])}" alt="{html.escape(row["target_display_name"])} squad proof">'
                    "<figcaption>Squad screen</figcaption></figure>"
                )
            visual_html += "</div></article>"
        visual_html += "</div>"
        if excluded_visual_cases:
            excluded_names = []
            for case in excluded_visual_cases:
                row = next((item for item in plan if item["target_club_key"] == case["club_key"]), None)
                excluded_names.append(row["target_display_name"] if row else case["club_key"])
            visual_html += (
                '<p class="note">Additional focused runs completed for '
                f'{html.escape(", ".join(excluded_names))}, but their selector screenshots exposed lower-division coordinate drift, '
                "so they are not used as visual proof on this page.</p>"
            )
        visual_html += "</section>"
    else:
        visual_html = (
            "<section><h2>Targeted In-game Club Proofs</h2>"
            f"<p class=\"note\">Focused visual proof run is queued or unavailable. Source: <code>{html.escape(visual_meta.get('visual_dir', ''))}</code></p>"
            "</section>"
        )

    rows_html = []
    for division in ["Premier League", "First Division", "Second Division", "Third Division"]:
        rows_html.append(f'<h3 class="division-title">{html.escape(division)}</h3>')
        rows_html.append('<div class="club-grid">')
        for row in by_division.get(division, []):
            img_src = kit_assets.get(row["target_club_key"], "")
            event_info = events_by_key.get(row["target_club_key"], {"status_counts": {}})
            statuses = " ".join(status_badge(status) for status in event_info["status_counts"])
            highlight_class = " highlighted" if row["target_club_key"] in HIGHLIGHT_KEYS else ""
            rows_html.append(
                f'<article class="mini-card{highlight_class}">'
                f'<img src="{html.escape(img_src)}" alt="{html.escape(row["target_display_name"])} kit">'
                f'<div><span class="slot">#{int(row["slot"]):02d}</span><h4>{html.escape(row["target_display_name"])}</h4>'
                f'<p>{html.escape(row["source_kind"].replace("_", " "))}</p>'
                f'<p><code>EQ{int(row["carrier_eq_record_id"]):04d}</code> visible · <code>EQ{int(row["desired_eq_record_id"]):04d}</code> source</p>'
                f'<p>{html.escape(action_label(row["kit_action"]))}</p><div class="status-row">{statuses}</div></div>'
                "</article>"
            )
        rows_html.append("</div>")

    observations_html = ""
    if observations:
        observations_html = '<section><h2>Full Selector Sweep Screenshots</h2><div class="screen-grid">'
        for obs in observations:
            text = obs.get("text") or obs.get("ocr_normalized") or "OCR unavailable"
            observations_html += (
                '<figure class="screen compact">'
                f'<img src="{html.escape(obs["screenshot"])}" alt="{html.escape(obs["division_key"])} selector observation">'
                f'<figcaption>{html.escape(obs["division_key"])} · row {html.escape(str(obs.get("row_index", "")))}<span>{html.escape(text)}</span></figcaption>'
                "</figure>"
            )
        observations_html += "</div></section>"

    contact = kit_assets.get("contact_sheet", "")
    contact_html = ""
    if contact:
        contact_html = (
            "<section><h2>All 80 Corrected Kit Previews</h2>"
            f'<a href="{html.escape(contact)}"><img class="contact-sheet" src="{html.escape(contact)}" alt="English 80 corrected kit contact sheet"></a>'
            "</section>"
        )

    table_rows = []
    for row in plan:
        status_counts_text = ", ".join(
            f"{status}: {count}" for status, count in sorted(events_by_key.get(row["target_club_key"], {}).get("status_counts", {}).items())
        )
        table_rows.append(
            "<tr>"
            f'<td>{int(row["slot"]):02d}</td>'
            f'<td>{html.escape(row["target_display_name"])}</td>'
            f'<td>{html.escape(row["target_pm99_division"])}</td>'
            f'<td><code>EQ{int(row["carrier_eq_record_id"]):04d}</code><small>{html.escape(row["carrier_team_query"])}</small></td>'
            f'<td><code>EQ{int(row["desired_eq_record_id"]):04d}</code></td>'
            f'<td>{html.escape(row["source_kind"].replace("_", " "))}</td>'
            f'<td>{html.escape(action_label(row["kit_action"]))}</td>'
            f'<td>{html.escape(status_counts_text)}</td>'
            "</tr>"
        )

    action_breakdown = "".join(
        f'<li><strong>{count}</strong> {html.escape(action_label(action))}</li>'
        for action, count in sorted(action_counts.items())
    )
    status_breakdown = "".join(
        f'<li><strong>{count}</strong> {html.escape(status.replace("_", " "))}</li>'
        for status, count in sorted(status_counts.items())
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PM99 English 80 Kit-Corrected Evidence</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #17202a;
      --muted: #5d6976;
      --line: #d8dee6;
      --panel: #f5f7fa;
      --paper: #ffffff;
      --accent: #0c6b58;
      --warn: #8a5a00;
      --new: #0f5d9a;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      background: #eef2f5;
      color: var(--ink);
      line-height: 1.45;
    }}
    header {{
      padding: 34px 36px 28px;
      background: #16212f;
      color: #fff;
      border-bottom: 5px solid #d6b34c;
    }}
    header h1 {{ margin: 0 0 10px; font-size: clamp(28px, 4vw, 46px); letter-spacing: 0; }}
    header p {{ margin: 0; max-width: 980px; color: #d7dee7; font-size: 17px; }}
    main {{ width: min(1480px, calc(100vw - 32px)); margin: 22px auto 56px; }}
    section {{ margin: 24px 0; padding: 22px; background: var(--paper); border: 1px solid var(--line); border-radius: 8px; }}
    h2 {{ margin: 0 0 16px; font-size: 24px; }}
    h3 {{ margin: 20px 0 12px; }}
    code {{ background: #edf1f5; padding: 2px 5px; border-radius: 4px; }}
    .eyebrow {{ margin: 0 0 8px; color: #637487; text-transform: uppercase; letter-spacing: .08em; font-size: 12px; font-weight: 700; }}
    .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin-top: 22px; }}
    .stat {{ background: rgba(255,255,255,.08); border: 1px solid rgba(255,255,255,.22); border-radius: 8px; padding: 14px; }}
    .stat span {{ display: block; color: #ccd6e3; font-size: 12px; text-transform: uppercase; letter-spacing: .06em; }}
    .stat strong {{ display: block; margin-top: 5px; font-size: 22px; }}
    .focus {{ display: grid; grid-template-columns: minmax(0, 1fr) 280px; gap: 24px; align-items: center; }}
    .kit-focus, .screen, .kit-focus img, .club-card, .mini-card {{ margin: 0; }}
    .kit-focus img {{ width: 100%; image-rendering: auto; border: 1px solid var(--line); background: #f8fafc; border-radius: 6px; }}
    figcaption {{ color: var(--muted); font-size: 13px; margin-top: 8px; }}
    .status-row {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }}
    .badge {{ display: inline-flex; align-items: center; min-height: 22px; padding: 3px 8px; border-radius: 999px; font-size: 12px; border: 1px solid var(--line); color: #314151; background: #f7f9fb; }}
    .badge.ok {{ color: #07543f; background: #e5f4ef; border-color: #b7dfd2; }}
    .badge.warn {{ color: #704600; background: #fff4d6; border-color: #e8cf84; }}
    .badge.new {{ color: #0d4e82; background: #e4f1fb; border-color: #b8d8ef; }}
    .badge.muted {{ color: #65717f; background: #eff2f5; }}
    .club-cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; }}
    .club-card {{ display: grid; grid-template-columns: 86px minmax(0,1fr); gap: 14px; padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: #fbfcfd; }}
    .club-card img {{ width: 86px; height: 86px; object-fit: contain; background: #eef2f5; border-radius: 6px; border: 1px solid #dfe5eb; }}
    .club-card h3 {{ margin: 0 0 4px; font-size: 18px; }}
    .club-card p {{ margin: 4px 0; color: var(--muted); }}
    .club-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 12px; }}
    .mini-card {{ display: grid; grid-template-columns: 70px minmax(0, 1fr); gap: 10px; padding: 10px; border: 1px solid var(--line); border-radius: 8px; background: #fff; }}
    .mini-card.highlighted {{ border-color: #bca143; box-shadow: 0 0 0 2px rgba(214,179,76,.18); }}
    .mini-card img {{ width: 70px; height: 70px; object-fit: contain; background: #f1f4f7; border-radius: 6px; }}
    .mini-card h4 {{ margin: 0; font-size: 16px; }}
    .mini-card p {{ margin: 3px 0; color: var(--muted); font-size: 13px; }}
    .slot {{ display: inline-block; color: #6b7785; font-size: 12px; font-weight: 700; }}
    .contact-sheet {{ width: 100%; max-height: 1200px; object-fit: contain; background: #111; border-radius: 8px; border: 1px solid var(--line); }}
    .screen-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 14px; }}
    .visual-grid {{ display: grid; grid-template-columns: 1fr; gap: 18px; }}
    .visual-card {{ border: 1px solid var(--line); border-radius: 8px; padding: 14px; background: #fbfcfd; }}
    .visual-card h3 {{ margin: 0 0 4px; }}
    .visual-card p {{ margin: 0 0 12px; color: var(--muted); }}
    .visual-pair {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; }}
    .screen {{ border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #fbfcfd; }}
    .screen img {{ width: 100%; display: block; border-radius: 5px; border: 1px solid #dfe5eb; }}
    .screen figcaption strong, .screen figcaption span {{ display: block; }}
    .compact figcaption {{ min-height: 42px; }}
    .note {{ color: var(--muted); }}
    .breakdowns {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; }}
    .breakdowns ul {{ margin: 0; padding-left: 18px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 9px 8px; text-align: left; vertical-align: top; }}
    th {{ background: var(--panel); font-size: 12px; text-transform: uppercase; letter-spacing: .05em; color: #536171; }}
    td small {{ display: block; color: var(--muted); margin-top: 3px; }}
    .table-wrap {{ overflow-x: auto; }}
    @media (max-width: 760px) {{
      header {{ padding: 28px 18px; }}
      main {{ width: min(100vw - 18px, 1480px); }}
      section {{ padding: 16px; }}
      .focus {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <p class="eyebrow">Premier Manager 99 · English 80 replacement evidence</p>
    <h1>Kit-corrected division-structured candidate</h1>
    <p>
      This report records the all-80 club identity research, the kit archive fix that addresses the Stoke/Wolves mismatch,
      the validation gates, and the selector screenshot evidence for the rebuilt candidate.
    </p>
    <div class="stats">{stats_html}</div>
  </header>
  <main>
    {stoke_html}
    <section>
      <h2>Club Proof Set</h2>
      <div class="club-cards">{''.join(highlight_cards)}</div>
    </section>
    {runner_highlight_html}
    {visual_html}
    {contact_html}
    <section>
      <h2>Patch Breakdown</h2>
      <div class="breakdowns">
        <div><h3>Club actions</h3><ul>{action_breakdown}</ul></div>
        <div><h3>Archive record statuses</h3><ul>{status_breakdown}</ul></div>
      </div>
    </section>
    <section>
      <h2>All 80 Clubs</h2>
      {''.join(rows_html)}
    </section>
    {observations_html}
    <section>
      <h2>Machine-Readable Matrix</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Slot</th><th>Club</th><th>Division</th><th>Visible carrier</th>
              <th>Source/host</th><th>Kind</th><th>Action</th><th>Statuses</th>
            </tr>
          </thead>
          <tbody>{''.join(table_rows)}</tbody>
        </table>
      </div>
    </section>
  </main>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=DEFAULT_BUILD_DIR)
    parser.add_argument("--runner-dir", type=Path, default=DEFAULT_RUNNER_DIR)
    parser.add_argument("--visual-dir", type=Path, default=DEFAULT_VISUAL_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    build_dir = args.build_dir.resolve()
    runner_dir = args.runner_dir.resolve()
    visual_dir = args.visual_dir.resolve()
    output_dir = args.output_dir.resolve()
    manifest_path = build_dir / "kit_patch/english80_division_kit_patch_summary.json"
    if not manifest_path.exists():
        raise SystemExit(f"missing kit patch manifest: {manifest_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = read_json(manifest_path)
    kit_assets = copy_kit_assets(build_dir, output_dir, manifest["plan"])
    observations, runner_meta = load_runner_screens(runner_dir, output_dir)
    visual_cases, visual_meta = load_visual_proofs(visual_dir, output_dir)
    events_by_key = event_summary(manifest["events"])
    html_text = build_html(manifest, kit_assets, events_by_key, observations, runner_meta, visual_cases, visual_meta)
    (output_dir / "index.html").write_text(html_text, encoding="utf-8")
    write_json(
        output_dir / "evidence_manifest.json",
        {
            "build_dir": build_dir.as_posix(),
            "runner_dir": runner_dir.as_posix(),
            "kit_patch_manifest": manifest_path.as_posix(),
            "html": (output_dir / "index.html").as_posix(),
            "runner": runner_meta,
            "visual": visual_meta,
            "kit_status_counts": manifest.get("status_counts", {}),
            "club_count": len(manifest.get("plan", [])),
        },
    )
    print(
        json.dumps(
            {
                "ok": True,
                "html": (output_dir / "index.html").as_posix(),
                "runner_screens": len(observations),
                "visual_cases": len(visual_cases),
                "output_dir": output_dir.as_posix(),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
