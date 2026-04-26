#!/usr/bin/env python3
"""Build a local HTML gallery for Stoke 2015 face-replacement runner captures."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create an HTML gallery from Stoke face milestone artifacts.")
    parser.add_argument("--prepare-manifest", required=True, help="Path to prepare_manifest.json")
    parser.add_argument("--runner-artifacts-dir", required=True, help="Path to runner artifact directory for the capture run")
    parser.add_argument(
        "--output-html",
        help="Output HTML path (default: <prepare-manifest-dir>/stoke_2015_face_gallery.html)",
    )
    parser.add_argument(
        "--include-skipped",
        action="store_true",
        help="Include slots that were skipped due to missing bitmap/source.",
    )
    return parser.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _rel_path(from_dir: Path, target: Path) -> str:
    return Path(Path(target).resolve().relative_to(Path(from_dir).resolve().anchor)).as_posix()


def _safe_rel(from_dir: Path, target: Path) -> str:
    try:
        return Path(target).resolve().relative_to(from_dir.resolve()).as_posix()
    except Exception:
        try:
            return Path(target).resolve().relative_to(Path.cwd().resolve()).as_posix()
        except Exception:
            return str(target.resolve())


def main() -> int:
    args = _parse_args()
    prepare_manifest_path = Path(args.prepare_manifest).expanduser().resolve()
    runner_artifacts_dir = Path(args.runner_artifacts_dir).expanduser().resolve()
    prepare_manifest = _load_json(prepare_manifest_path)
    runner_summary = _load_json(runner_artifacts_dir / "summary.json")

    output_html = (
        Path(args.output_html).expanduser().resolve()
        if args.output_html
        else prepare_manifest_path.parent / "stoke_2015_face_gallery.html"
    )
    output_html.parent.mkdir(parents=True, exist_ok=True)

    captures_by_slot: dict[int, dict[str, Any]] = {}
    for item in list(runner_summary.get("profile_captures") or []):
        slot = int(item.get("slot") or 0)
        if slot > 0:
            captures_by_slot[slot] = dict(item)

    rows_html: list[str] = []
    patch_results = list(prepare_manifest.get("patch_results") or [])
    for entry in patch_results:
        slot = int(entry.get("slot") or 0)
        status = str(entry.get("status") or "unknown")
        if not args.include_skipped and status != "patched":
            continue

        capture = captures_by_slot.get(slot, {})
        screenshot_path = runner_artifacts_dir / "profiles" / f"{slot:02d}.png"
        screenshot_rel = _safe_rel(output_html.parent, screenshot_path)
        screenshot_exists = screenshot_path.is_file()

        preview_path = Path(str(entry.get("preview_path") or "")).expanduser() if entry.get("preview_path") else None
        preview_rel = _safe_rel(output_html.parent, preview_path) if preview_path and preview_path.exists() else ""
        source_image_path = Path(str(entry.get("source_image_path") or "")).expanduser() if entry.get("source_image_path") else None
        source_image_rel = _safe_rel(output_html.parent, source_image_path) if source_image_path and source_image_path.exists() else ""

        image_lookup = dict(entry.get("image_lookup") or {})
        image_url = str(image_lookup.get("image_url") or "")
        resolved_title = str(image_lookup.get("resolved_title") or "")

        rows_html.append(
            "\n".join(
                [
                    "<section class='card'>",
                    f"<h2>Slot {slot:02d}: {html.escape(str(entry.get('target_name') or 'Unknown'))}</h2>",
                    f"<p><strong>PID:</strong> {int(entry.get('pid') or 0)} | <strong>Status:</strong> {html.escape(status)}</p>",
                    (
                        f"<p><strong>Wikipedia title:</strong> {html.escape(resolved_title)}"
                        f"{' | <a href=\"' + html.escape(image_url) + '\">source</a>' if image_url else ''}</p>"
                    ),
                    "<div class='grid'>",
                    (
                        f"<figure><figcaption>Runner profile screenshot</figcaption>"
                        f"{'<img src=\"' + html.escape(screenshot_rel) + '\" alt=\"slot screenshot\">' if screenshot_exists else '<p>Missing screenshot</p>'}"
                        f"</figure>"
                    ),
                    (
                        f"<figure><figcaption>Generated 32x32 face preview</figcaption>"
                        f"{'<img src=\"' + html.escape(preview_rel) + '\" alt=\"generated face\">' if preview_rel else '<p>Not generated</p>'}"
                        f"</figure>"
                    ),
                    (
                        f"<figure><figcaption>Downloaded source image</figcaption>"
                        f"{'<img src=\"' + html.escape(source_image_rel) + '\" alt=\"source face\">' if source_image_rel else '<p>Not available</p>'}"
                        f"</figure>"
                    ),
                    "</div>",
                    f"<p><strong>OCR profile text:</strong> {html.escape(str(capture.get('profile_combined_text') or '').strip())}</p>",
                    "</section>",
                ]
            )
        )

    success = bool(runner_summary.get("success"))
    counts = dict(prepare_manifest.get("counts") or {})
    html_text = "\n".join(
        [
            "<!doctype html>",
            "<html lang='en'>",
            "<head>",
            "<meta charset='utf-8'>",
            "<meta name='viewport' content='width=device-width, initial-scale=1'>",
            "<title>Stoke 2015 Face Milestone Gallery</title>",
            "<style>",
            "body{font-family:Verdana,Arial,sans-serif;margin:18px;background:#f5f7fb;color:#182028}",
            "h1{margin:0 0 8px 0}",
            ".meta{background:#e9eef7;border:1px solid #cdd9ef;padding:10px 12px;margin:0 0 16px 0}",
            ".card{background:#fff;border:1px solid #d8dde8;padding:12px;margin:0 0 14px 0}",
            ".card h2{margin:0 0 8px 0;font-size:19px}",
            ".grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;align-items:start}",
            "figure{margin:0;padding:0}",
            "figcaption{font-weight:700;font-size:12px;margin:0 0 6px 0}",
            "img{width:100%;height:auto;border:1px solid #bcc6d9;background:#edf2fa}",
            "@media (max-width:1200px){.grid{grid-template-columns:1fr}}",
            "</style>",
            "</head>",
            "<body>",
            "<h1>Stoke 2015 Face Replacement Validation</h1>",
            "<div class='meta'>",
            f"<p><strong>Prepare manifest:</strong> {html.escape(str(prepare_manifest_path))}</p>",
            f"<p><strong>Runner artifacts:</strong> {html.escape(str(runner_artifacts_dir))}</p>",
            f"<p><strong>Runner success:</strong> {str(success)}</p>",
            f"<p><strong>Patched slots:</strong> {int(counts.get('patched') or 0)} / {int(counts.get('slots_total') or 0)}</p>",
            f"<p><strong>Missing bitmap slots:</strong> {int(counts.get('skipped_missing_bitmap') or 0)}</p>",
            f"<p><strong>Missing source-image slots:</strong> {int(counts.get('skipped_missing_source_image') or 0)}</p>",
            "</div>",
            *rows_html,
            "</body>",
            "</html>",
        ]
    )
    output_html.write_text(html_text + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "success": True,
                "output_html": str(output_html),
                "cards": len(rows_html),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
