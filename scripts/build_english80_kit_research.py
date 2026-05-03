#!/usr/bin/env python3
"""Build an English-80 PM99 identity and kit linkage audit."""

from __future__ import annotations

import argparse
import collections
import csv
import html
import json
import re
from pathlib import Path
from typing import Any


MANUAL_DIRECT_EQ = {
    # PM99 data typo is "West Bronwich Albion", so exact normalization misses it.
    "West Bromwich Albion": 343,
}

HERITAGE_HOST_EQ = {
    # AFC Wimbledon did not exist in PM99; Wimbledon is the closest legacy host.
    "AFC Wimbledon": 314,
}

SYNTHETIC_HOST_EQ = {
    # Clubs with no PM99 English league identity. These are unused legacy hosts
    # chosen for unique clean carriers and full MINIESC/BIGESC/BIGCAMP coverage.
    "Burton Albion": 324,       # Southend Utd.
    "Stevenage": 327,           # Grimsby T.
    "Accrington Stanley": 330,  # Swindon
    "Barrow": 335,              # Oldham Ath.
    "Bromley": 351,             # Bury
    "Cheltenham Town": 354,     # Gillingham
    "Crawley Town": 357,        # Notts C.
    "Fleetwood Town": 364,      # Walsall
}

FOOTBALL_WORDS = [
    "footballandathleticcompany",
    "footballclub",
    "fc",
]


def normalize_name(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "", value.lower().replace("&", "and"))
    for word in FOOTBALL_WORDS:
        text = text.replace(word, "")
    return text


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def team_name(team: dict[str, Any] | None) -> str:
    if not team:
        return "missing"
    ident = team["team_identifier"]
    short_name = ident.get("short_name") or ""
    full_name = ident.get("full_club_name") or ""
    if full_name and full_name != short_name:
        return f"{short_name} / {full_name}"
    return short_name or full_name or "unknown"


def build_original_name_index(kit_rows: list[dict[str, Any]]) -> dict[str, list[int]]:
    index: dict[str, list[int]] = collections.defaultdict(list)
    for row in kit_rows:
        eq_id = row["team_identifier"]["eq_record_id"]
        if not (300 <= eq_id <= 400 or eq_id == 3311):
            continue
        ident = row["team_identifier"]
        for field in ("short_name", "full_club_name"):
            value = ident.get(field) or ""
            if not value:
                continue
            normalized = normalize_name(value)
            if normalized and eq_id not in index[normalized]:
                index[normalized].append(eq_id)
    return index


def resolve_desired_eq_id(
    target_name: str,
    original_name_index: dict[str, list[int]],
) -> tuple[int, str, str]:
    if target_name in MANUAL_DIRECT_EQ:
        return MANUAL_DIRECT_EQ[target_name], "direct_existing", "manual alias to PM99 original identity"
    if target_name in HERITAGE_HOST_EQ:
        return HERITAGE_HOST_EQ[target_name], "heritage_successor", "modern successor uses nearest legacy host"
    if target_name in SYNTHETIC_HOST_EQ:
        return SYNTHETIC_HOST_EQ[target_name], "synthetic_new", "no PM99 league identity; use unused host and synthesize kit"

    matches = original_name_index.get(normalize_name(target_name), [])
    unique_matches = sorted(set(matches))
    if len(unique_matches) == 1:
        return unique_matches[0], "direct_existing", "exact PM99 original identity match"
    if not unique_matches:
        raise KeyError(f"No PM99 identity mapping for {target_name!r}")
    raise ValueError(f"Ambiguous PM99 identity mapping for {target_name!r}: {unique_matches}")


def kit_asset_summary(team: dict[str, Any] | None) -> str:
    if not team:
        return ""
    assets = team.get("kit_payload_source", {}).get("kit_assets", [])
    names = [asset["archive_name"] for asset in assets]
    return ", ".join(names)


def kit_preview_rel(output_dir: Path, eq_id: int) -> str:
    per_team = output_dir / "base_miniesc_review" / "kits_datpal_per_team"
    candidates = [
        per_team / f"{eq_id:04d}_datpal_mask0.png",
        per_team / f"{eq_id:04d}_datpal.png",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.relative_to(output_dir).as_posix()
    return ""


def action_for(source_kind: str, current_eq_id: int, desired_eq_id: int) -> tuple[str, str]:
    if source_kind == "direct_existing":
        if current_eq_id == desired_eq_id:
            return (
                "keep_existing_identity",
                "Already uses the PM99 original club id; kit filename is aligned.",
            )
        return (
            "relink_to_existing_identity",
            "Move/select the original PM99 club id; do not hide this by copying a kit onto the wrong carrier.",
        )
    if source_kind == "heritage_successor":
        if current_eq_id == desired_eq_id:
            return (
                "use_heritage_host",
                "Uses the legacy host; replace visible identity and synthesize/update the modern kit.",
            )
        return (
            "move_to_heritage_host",
            "Move to the nearest legacy host and synthesize/update the modern kit there.",
        )
    if current_eq_id == desired_eq_id:
        return (
            "synthesize_current_host",
            "Host choice is clean, but the old carrier kit must be replaced with the modern club kit.",
        )
    return (
        "move_to_unused_host_and_synthesize",
        "Current carrier collides with a real PM99 club; use a clean unused host and replace its kit.",
    )


def kit_action_for(source_kind: str, current_eq_id: int, desired_eq_id: int) -> str:
    if source_kind == "direct_existing":
        if current_eq_id == desired_eq_id:
            return "no kit patch required for identity"
        return f"relink club to EQ{desired_eq_id:04d}; fallback only: copy EQ96{desired_eq_id:04d}.BMP kit records"
    if source_kind == "heritage_successor":
        return f"synthesize AFC Wimbledon kit into EQ96{desired_eq_id:04d}.BMP records"
    return f"synthesize modern home kit into EQ96{desired_eq_id:04d}.BMP records"


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "slot",
        "target_display_name",
        "source_league",
        "target_pm99_division",
        "source_kind",
        "current_carrier_eq_record_id",
        "current_carrier_name",
        "current_carrier_desired_by",
        "desired_eq_record_id",
        "desired_host_name",
        "identity_action",
        "kit_action",
        "rationale",
        "current_kit_archives",
        "desired_kit_archives",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def badge(text: str) -> str:
    classes = {
        "keep_existing_identity": "ok",
        "relink_to_existing_identity": "warn",
        "move_to_heritage_host": "new",
        "use_heritage_host": "new",
        "synthesize_current_host": "new",
        "move_to_unused_host_and_synthesize": "bad",
    }
    cls = classes.get(text, "plain")
    return f'<span class="badge {cls}">{html.escape(text.replace("_", " "))}</span>'


def image_cell(label: str, rel_path: str) -> str:
    if not rel_path:
        return f'<div class="kit-missing">{html.escape(label)}<br>No preview</div>'
    return (
        '<figure class="kit">'
        f'<img src="{html.escape(rel_path)}" alt="{html.escape(label)} kit preview">'
        f'<figcaption>{html.escape(label)}</figcaption>'
        "</figure>"
    )


def write_html(path: Path, rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    by_division: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in rows:
        by_division[row["target_pm99_division"]].append(row)

    cards = "".join(
        f'<div class="stat"><strong>{html.escape(str(value))}</strong><span>{html.escape(label)}</span></div>'
        for label, value in [
            ("clubs audited", summary["club_count"]),
            ("current carrier mismatches", summary["mismatch_count"]),
            ("direct PM99 identities", summary["source_kind_counts"].get("direct_existing", 0)),
            ("new/synthetic clubs", summary["source_kind_counts"].get("synthetic_new", 0)),
        ]
    )
    stoke = next(row for row in rows if row["target_display_name"] == "Stoke City")

    sections = []
    for division in ("Premier League", "First Division", "Second Division", "Third Division"):
        body_rows = []
        for row in by_division.get(division, []):
            issue = ""
            if row["current_carrier_desired_by"] and row["current_carrier_desired_by"] != row["target_display_name"]:
                issue = f'<div class="issue">Current carrier belongs to {html.escape(row["current_carrier_desired_by"])}</div>'
            body_rows.append(
                "<tr>"
                f'<td class="slot">{row["slot"]}</td>'
                f'<td><strong>{html.escape(row["target_display_name"])}</strong>'
                f'<small>{html.escape(row["source_league"])}</small></td>'
                f'<td>{image_cell(row["current_carrier_name"], row["current_preview_rel"])}</td>'
                f'<td><code>EQ{row["current_carrier_eq_record_id"]:04d}</code><br>{html.escape(row["current_carrier_name"])}{issue}</td>'
                f'<td>{image_cell(row["desired_host_name"], row["desired_preview_rel"])}</td>'
                f'<td><code>EQ{row["desired_eq_record_id"]:04d}</code><br>{html.escape(row["desired_host_name"])}'
                f'<small>{html.escape(row["source_kind"].replace("_", " "))}</small></td>'
                f'<td>{badge(row["identity_action"])}<p>{html.escape(row["rationale"])}</p>'
                f'<small>{html.escape(row["kit_action"])}</small></td>'
                "</tr>"
            )
        sections.append(
            f"<h2>{html.escape(division)}</h2>"
            '<table><thead><tr><th>#</th><th>Target club</th><th>Current kit</th>'
            '<th>Current carrier</th><th>Correct/host kit</th><th>Correct carrier</th><th>Action</th>'
            "</tr></thead><tbody>"
            + "\n".join(body_rows)
            + "</tbody></table>"
        )

    css = """
:root {
  color-scheme: light;
  --ink: #172026;
  --muted: #5b6670;
  --line: #d7dde2;
  --panel: #f6f8fa;
  --accent: #146c78;
  --warn: #9a5b00;
  --bad: #9a2525;
  --new: #345ca8;
}
body {
  margin: 0;
  font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: var(--ink);
  background: #fff;
}
header {
  padding: 28px 32px 18px;
  border-bottom: 1px solid var(--line);
  background: #f9fafb;
}
h1 { margin: 0 0 8px; font-size: 30px; letter-spacing: 0; }
h2 { margin: 30px 32px 12px; font-size: 21px; }
p { margin: 6px 0 0; max-width: 1080px; color: var(--muted); }
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.stats { display: grid; grid-template-columns: repeat(4, minmax(130px, 1fr)); gap: 12px; margin: 20px 0 8px; max-width: 960px; }
.stat { border: 1px solid var(--line); background: #fff; padding: 12px 14px; }
.stat strong { display: block; font-size: 25px; }
.stat span { color: var(--muted); }
.callout {
  margin-top: 18px;
  padding: 14px 16px;
  border-left: 5px solid var(--warn);
  background: #fff8ec;
  max-width: 1100px;
}
table { width: calc(100% - 64px); margin: 0 32px 24px; border-collapse: collapse; table-layout: fixed; }
th, td { border: 1px solid var(--line); padding: 8px; vertical-align: top; }
th { text-align: left; background: var(--panel); font-size: 12px; text-transform: uppercase; color: #3f4a52; }
td:nth-child(1) { width: 38px; }
td:nth-child(2) { width: 190px; }
td:nth-child(3), td:nth-child(5) { width: 118px; }
td:nth-child(4), td:nth-child(6) { width: 190px; }
small { display: block; color: var(--muted); margin-top: 4px; }
.slot { text-align: right; color: var(--muted); }
.kit { margin: 0; display: grid; justify-items: center; gap: 4px; }
.kit img { width: 64px; height: 86px; object-fit: contain; image-rendering: pixelated; background: #eef1f4; border: 1px solid var(--line); }
.kit figcaption { font-size: 11px; color: var(--muted); text-align: center; overflow-wrap: anywhere; }
.kit-missing { color: var(--muted); font-size: 12px; }
.badge { display: inline-block; padding: 2px 7px; border-radius: 4px; font-size: 12px; font-weight: 700; }
.badge.ok { color: #0f5c34; background: #e7f4ec; }
.badge.warn { color: var(--warn); background: #fff1d6; }
.badge.bad { color: var(--bad); background: #fde7e7; }
.badge.new { color: var(--new); background: #e8eefc; }
.issue { margin-top: 5px; color: var(--bad); font-weight: 700; font-size: 12px; }
@media (max-width: 900px) {
  .stats { grid-template-columns: repeat(2, minmax(130px, 1fr)); }
  table { width: calc(100% - 24px); margin-left: 12px; margin-right: 12px; font-size: 12px; }
  header { padding-left: 16px; padding-right: 16px; }
  h2 { margin-left: 12px; }
}
"""
    html_doc = "".join(
        [
            "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
            "<title>English 80 PM99 Identity and Kit Audit</title>",
            f"<style>{css}</style></head><body>",
            "<header>",
            "<h1>English 80 PM99 Identity and Kit Audit</h1>",
            "<p>This report joins the modern 80-club assignment to PM99 EQ ids and the kit bitmap filename contract. ",
            "A visible club inherits the kit for its carrier id: <code>EQ96&lt;eq_record_id&gt;.BMP</code> in the kit archives.</p>",
            f'<div class="stats">{cards}</div>',
            '<div class="callout">',
            "<strong>Stoke finding:</strong> ",
            f"the current build labels carrier <code>EQ{stoke['current_carrier_eq_record_id']:04d}</code> as Stoke, ",
            f"but that carrier is {html.escape(stoke['current_carrier_name'])}. ",
            f"The correct Stoke identity is <code>EQ{stoke['desired_eq_record_id']:04d}</code> ",
            f"({html.escape(stoke['desired_host_name'])}). That is why Stoke visually picked up a Wolves-style kit.",
            "</div>",
            "</header>",
            "\n".join(sections),
            "</body></html>",
        ]
    )
    path.write_text(html_doc, encoding="utf-8")


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    assignments = read_json(args.assignment_path)["assignments"]
    kit_rows = read_json(args.kit_manifest_path)["rows"]
    by_eq_id = {row["team_identifier"]["eq_record_id"]: row for row in kit_rows}
    original_name_index = build_original_name_index(kit_rows)

    first_pass = []
    for assignment in assignments:
        target_name = assignment["target_display_name"]
        desired_eq_id, source_kind, map_rationale = resolve_desired_eq_id(target_name, original_name_index)
        current_eq_id = assignment["carrier_eq_record_id"]
        identity_action, rationale = action_for(source_kind, current_eq_id, desired_eq_id)
        first_pass.append(
            {
                "slot": assignment["slot"],
                "target_display_name": target_name,
                "target_club_key": assignment["target_club_key"],
                "source_league": assignment["source_league"],
                "target_pm99_division": assignment["target_pm99_division"],
                "source_kind": source_kind,
                "map_rationale": map_rationale,
                "current_carrier_eq_record_id": current_eq_id,
                "desired_eq_record_id": desired_eq_id,
                "identity_action": identity_action,
                "rationale": rationale,
                "kit_action": kit_action_for(source_kind, current_eq_id, desired_eq_id),
            }
        )

    desired_owner = {row["desired_eq_record_id"]: row["target_display_name"] for row in first_pass}
    rows = []
    for row in first_pass:
        current_team = by_eq_id.get(row["current_carrier_eq_record_id"])
        desired_team = by_eq_id.get(row["desired_eq_record_id"])
        current_owner = desired_owner.get(row["current_carrier_eq_record_id"], "")
        expanded = {
            **row,
            "current_carrier_name": team_name(current_team),
            "desired_host_name": team_name(desired_team),
            "current_carrier_desired_by": current_owner,
            "current_kit_archives": kit_asset_summary(current_team),
            "desired_kit_archives": kit_asset_summary(desired_team),
            "current_preview_rel": kit_preview_rel(output_dir, row["current_carrier_eq_record_id"]),
            "desired_preview_rel": kit_preview_rel(output_dir, row["desired_eq_record_id"]),
        }
        rows.append(expanded)

    action_counts = collections.Counter(row["identity_action"] for row in rows)
    kind_counts = collections.Counter(row["source_kind"] for row in rows)
    mismatch_count = sum(
        1 for row in rows if row["current_carrier_eq_record_id"] != row["desired_eq_record_id"]
    )
    summary = {
        "club_count": len(rows),
        "mismatch_count": mismatch_count,
        "keep_count": len(rows) - mismatch_count,
        "identity_action_counts": dict(action_counts),
        "source_kind_counts": dict(kind_counts),
        "assignment_path": str(args.assignment_path),
        "kit_manifest_path": str(args.kit_manifest_path),
        "preview_source": str(output_dir / "base_miniesc_review"),
    }

    matrix = {"summary": summary, "rows": rows}
    (output_dir / "english80_identity_kit_matrix.json").write_text(
        json.dumps(matrix, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    write_csv(output_dir / "english80_identity_kit_matrix.csv", rows)
    write_html(output_dir / "index.html", rows, summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--assignment-path",
        type=Path,
        default=Path(
            "work/pm99/english80_2026_division_structured/"
            "english80_2026_division_structured_20260501T183853Z/"
            "slot_assignment_english80_2026_division_structured.json"
        ),
    )
    parser.add_argument(
        "--kit-manifest-path",
        type=Path,
        default=Path("work/parallel_recheck/team_kits/kit_manifest.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/english80_kit_research_20260501"),
    )
    return parser.parse_args()


def main() -> int:
    summary = build_report(parse_args())
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
