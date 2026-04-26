#!/usr/bin/env python3
"""Build deterministic team-kit review artifacts from MINIESC.PKF + DAT palettes."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import struct
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont


ROOT_DIR = Path(__file__).resolve().parent.parent
EDITOR_DIR = ROOT_DIR / "upstream" / "pm99-skezmod-db-editor"
if str(EDITOR_DIR) not in sys.path:
    sys.path.insert(0, str(EDITOR_DIR))

from app.minifoto_bitmap_archive import (  # noqa: E402
    iter_obfuscated_bmp_records,
    parse_riff_palette,
)


@dataclass(frozen=True)
class PaletteCandidate:
    dat_path: Path
    offset: int
    sha16: str
    palette: list[tuple[int, int, int]]


def _extract_palette_candidates(dat_path: Path) -> list[PaletteCandidate]:
    data = dat_path.read_bytes()
    candidates: list[PaletteCandidate] = []
    cursor = 0
    while True:
        riff_offset = data.find(b"RIFF", cursor)
        if riff_offset < 0:
            break
        cursor = riff_offset + 1
        if riff_offset + 12 > len(data) or data[riff_offset + 8 : riff_offset + 12] != b"PAL ":
            continue
        chunk_size = int(struct.unpack_from("<I", data, riff_offset + 4)[0])
        chunk_end = riff_offset + 8 + chunk_size
        if chunk_end > len(data):
            continue
        blob = data[riff_offset:chunk_end]
        try:
            palette = parse_riff_palette(blob)
        except Exception:
            continue
        candidates.append(
            PaletteCandidate(
                dat_path=dat_path,
                offset=riff_offset,
                sha16=hashlib.sha256(blob).hexdigest()[:16],
                palette=palette,
            )
        )
    return candidates


def _choose_palette(dat_paths: list[Path], preferred_hashes: Iterable[str]) -> PaletteCandidate:
    all_candidates: list[PaletteCandidate] = []
    for dat_path in dat_paths:
        if dat_path.is_file():
            all_candidates.extend(_extract_palette_candidates(dat_path))
    if not all_candidates:
        raise FileNotFoundError("No DAT palette candidates found in provided --dat-archive paths")

    for preferred in preferred_hashes:
        normalized = preferred.strip().lower()
        if not normalized:
            continue
        for candidate in all_candidates:
            if candidate.sha16 == normalized:
                return candidate
    return all_candidates[0]


def _render_record(
    record,
    palette: list[tuple[int, int, int]],
    *,
    scale: int,
    mask_zero: bool,
) -> Image.Image:
    if scale <= 0:
        raise ValueError("scale must be positive")

    width = int(record.width)
    height = int(record.height)
    pixel_count = width * height
    pixel_bytes = record.raw_bitmap[record.pixel_offset : record.pixel_offset + pixel_count]

    if mask_zero:
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    else:
        image = Image.new("RGB", (width, height), (240, 240, 240))

    for y in range(height):
        source_row = (height - 1 - y) * width
        for x in range(width):
            palette_index = pixel_bytes[source_row + x]
            if mask_zero and palette_index == 0:
                continue
            red, green, blue = palette[palette_index]
            if mask_zero:
                image.putpixel((x, y), (int(red), int(green), int(blue), 255))
            else:
                image.putpixel((x, y), (int(red), int(green), int(blue)))

    if scale == 1:
        return image
    return image.resize((width * scale, height * scale), Image.Resampling.NEAREST)


def _load_rows(manifest_path: Path) -> list[dict]:
    payload = json.loads(manifest_path.read_text())
    if isinstance(payload, dict):
        rows = payload.get("rows", [])
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []
    if not isinstance(rows, list):
        raise ValueError("Manifest rows payload is not a list")
    return sorted(rows, key=lambda row: int(row.get("team_identifier", {}).get("eq_record_id") or 0))


def _build_composite(
    rows: list[dict],
    record_by_file_name: dict[str, object],
    palette: list[tuple[int, int, int]],
    output_path: Path,
    *,
    columns: int,
    composite_scale: int,
    palette_label: str,
) -> None:
    if columns <= 0:
        raise ValueError("columns must be positive")

    first_record = next(iter(record_by_file_name.values()))
    sample = _render_record(first_record, palette, scale=composite_scale, mask_zero=True)
    cell_kit_width, cell_kit_height = sample.size
    font = ImageFont.load_default()

    pad = 10
    col_gap = 20
    row_gap = 12
    text_gap = 12
    text_area_width = 300
    cell_width = pad + cell_kit_width + text_gap + text_area_width + pad
    cell_height = pad + max(cell_kit_height, 56) + pad
    header_height = 58

    row_count = math.ceil(len(rows) / columns)
    canvas_width = (columns * cell_width) + ((columns - 1) * col_gap)
    canvas_height = header_height + (row_count * cell_height) + ((row_count - 1) * row_gap) + pad

    sheet = Image.new("RGB", (canvas_width, canvas_height), (248, 248, 248))
    draw = ImageDraw.Draw(sheet)
    draw.rectangle((0, 0, canvas_width, header_height), fill=(34, 34, 34))
    draw.text(
        (12, 10),
        f"PM99 Team Kits (DAT palette {palette_label}, mask0) - {len(rows)} teams",
        font=font,
        fill=(255, 255, 255),
    )
    draw.text((12, 30), "Index 0 rendered as transparent mask.", font=font, fill=(210, 210, 210))

    for index, row in enumerate(rows):
        column = index % columns
        row_index = index // columns
        x0 = column * (cell_width + col_gap)
        y0 = header_height + row_index * (cell_height + row_gap)
        x1 = x0 + cell_width
        y1 = y0 + cell_height
        draw.rectangle((x0, y0, x1, y1), fill=(255, 255, 255), outline=(220, 220, 220), width=1)

        assets = row.get("kit_payload_source", {}).get("kit_assets", [])
        miniesc_asset = next(
            (asset for asset in assets if str(asset.get("archive_name", "")).upper() == "MINIESC.PKF"),
            None,
        )
        record = None
        if miniesc_asset is not None:
            record = record_by_file_name.get(str(miniesc_asset.get("file_name", "")).upper())

        if record is not None:
            kit = _render_record(record, palette, scale=composite_scale, mask_zero=True)
            panel = Image.new("RGB", kit.size, (242, 242, 242))
            panel.paste(kit, (0, 0), kit)
            sheet.paste(panel, (x0 + pad, y0 + pad))

        team_identifier = row.get("team_identifier", {})
        team_id = int(team_identifier.get("eq_record_id") or 0)
        short_name = str(team_identifier.get("short_name") or "").strip()
        full_club_name = str(team_identifier.get("full_club_name") or "").strip()

        text_x = x0 + pad + cell_kit_width + text_gap
        text_y = y0 + pad
        draw.text((text_x, text_y), f"{team_id:04d} | {short_name}", font=font, fill=(20, 20, 20))
        for line in _wrap_text(full_club_name or short_name, width=40, max_lines=4):
            text_y += 14
            draw.text((text_x, text_y), line, font=font, fill=(45, 45, 45))

    sheet.save(output_path)


def _wrap_text(value: str, *, width: int, max_lines: int) -> list[str]:
    if not value:
        return []
    words = value.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for token in words[1:]:
        joined = f"{current} {token}"
        if len(joined) <= width:
            current = joined
        else:
            lines.append(current)
            current = token
            if len(lines) >= max_lines:
                break
    if len(lines) < max_lines:
        lines.append(current)
    return lines[:max_lines]


def _clean_generated_files(per_team_dir: Path) -> None:
    for pattern in ("*_datpal.png", "*_datpal_mask0.png"):
        for file_path in per_team_dir.glob(pattern):
            file_path.unlink(missing_ok=True)


def build_team_kit_review(
    *,
    manifest_path: Path,
    kit_archive_path: Path,
    dat_archives: list[Path],
    output_dir: Path,
    preferred_palette_hashes: list[str],
    columns: int,
    composite_scale: int,
    per_team_scale: int,
) -> dict:
    rows = _load_rows(manifest_path)
    palette_candidate = _choose_palette(dat_archives, preferred_palette_hashes)
    palette = palette_candidate.palette

    records = iter_obfuscated_bmp_records(kit_archive_path)
    record_by_file_name = {str(record.file_name).upper(): record for record in records}

    per_team_dir = output_dir / "kits_datpal_per_team"
    per_team_dir.mkdir(parents=True, exist_ok=True)
    _clean_generated_files(per_team_dir)

    top_rows_html: list[str] = []
    missing_team_ids: list[int] = []
    pixel_counter = Counter()
    total_pixels = 0
    black_nonzero_pixels = 0

    for row in rows:
        team_identifier = row.get("team_identifier", {})
        team_id = int(team_identifier.get("eq_record_id") or 0)
        short_name = str(team_identifier.get("short_name") or "").strip()
        full_club_name = str(team_identifier.get("full_club_name") or "").strip()

        assets = row.get("kit_payload_source", {}).get("kit_assets", [])
        miniesc_asset = next(
            (asset for asset in assets if str(asset.get("archive_name", "")).upper() == "MINIESC.PKF"),
            None,
        )
        record = None
        if miniesc_asset is not None:
            record = record_by_file_name.get(str(miniesc_asset.get("file_name", "")).upper())

        if record is None:
            missing_team_ids.append(team_id)
            continue

        width = int(record.width)
        height = int(record.height)
        pixel_count = width * height
        pixels = record.raw_bitmap[record.pixel_offset : record.pixel_offset + pixel_count]
        pixel_counter.update(pixels)
        total_pixels += len(pixels)
        black_nonzero_pixels += sum(1 for idx in pixels if idx != 0 and palette[idx] == (0, 0, 0))

        plain_image = _render_record(record, palette, scale=per_team_scale, mask_zero=False)
        masked_image = _render_record(record, palette, scale=per_team_scale, mask_zero=True)

        plain_name = f"{team_id:04d}_datpal.png"
        masked_name = f"{team_id:04d}_datpal_mask0.png"
        plain_image.save(per_team_dir / plain_name)

        masked_panel = Image.new("RGB", masked_image.size, (236, 236, 236))
        masked_panel.paste(masked_image, (0, 0), masked_image)
        masked_panel.save(per_team_dir / masked_name)

        top_indices = Counter(pixels).most_common(6)
        top_indices_text = ", ".join(f"{idx}:{count}" for idx, count in top_indices)
        top_rows_html.append(
            "<tr>"
            f"<td>{team_id:04d}</td>"
            f"<td>{html.escape(short_name)}</td>"
            f"<td>{html.escape(full_club_name)}</td>"
            f"<td><img src='kits_datpal_per_team/{plain_name}' loading='lazy' /></td>"
            f"<td><img src='kits_datpal_per_team/{masked_name}' loading='lazy' /></td>"
            f"<td>{html.escape(top_indices_text)}</td>"
            "</tr>"
        )

    composite_path = output_dir / "team_kits_all_labeled_datpal_mask0.png"
    _build_composite(
        rows,
        record_by_file_name,
        palette,
        composite_path,
        columns=columns,
        composite_scale=composite_scale,
        palette_label=palette_candidate.sha16,
    )

    review_path = output_dir / "review_each_team_datpal.html"
    review_path.write_text(
        _build_review_html(
            palette_candidate=palette_candidate,
            rows_count=len(rows),
            missing_team_ids=missing_team_ids,
            composite_name=composite_path.name,
            body_rows="".join(top_rows_html),
        )
    )

    summary = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "manifest_path": str(manifest_path),
        "kit_archive_path": str(kit_archive_path),
        "palette_hash": palette_candidate.sha16,
        "palette_dat_file": str(palette_candidate.dat_path),
        "palette_offset_hex": hex(palette_candidate.offset),
        "total_teams": len(rows),
        "missing_count": len(missing_team_ids),
        "missing_team_ids": missing_team_ids,
        "output_composite": str(composite_path),
        "output_review_each_team_html": str(review_path),
        "output_per_team_dir": str(per_team_dir),
        "index0_share": (pixel_counter[0] / total_pixels) if total_pixels else 0.0,
        "black_share_after_mask0": (black_nonzero_pixels / total_pixels) if total_pixels else 0.0,
    }

    summary_path = output_dir / "dat_palette_review_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    return summary


def _build_review_html(
    *,
    palette_candidate: PaletteCandidate,
    rows_count: int,
    missing_team_ids: list[int],
    composite_name: str,
    body_rows: str,
) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Team Kit Per-Team Review (DAT palette)</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 12px; background: #f5f5f5; }}
    .card {{ background: #fff; border: 1px solid #ddd; padding: 12px; margin-bottom: 12px; }}
    img {{ image-rendering: pixelated; border: 1px solid #bbb; background: #fff; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; }}
    th, td {{ border: 1px solid #ddd; padding: 6px; vertical-align: top; font-size: 12px; }}
    th {{ position: sticky; top: 0; background: #222; color: #fff; }}
    .small {{ color: #555; font-size: 12px; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Per-Team Kit Review (DAT palette {palette_candidate.sha16})</h1>
    <p class="small">Primary composite: <a href="{composite_name}">{composite_name}</a></p>
    <p class="small">
      Rows: {rows_count} | missing: {len(missing_team_ids)} |
      DAT source: {html.escape(str(palette_candidate.dat_path))} @ {hex(palette_candidate.offset)}
    </p>
    <img src="{composite_name}" style="max-width: 100%; height: auto;" />
  </div>
  <div class="card">
    <table>
      <thead>
        <tr>
          <th>ID</th>
          <th>Short</th>
          <th>Club</th>
          <th>DAT palette</th>
          <th>DAT palette + mask0</th>
          <th>Top pixel indices</th>
        </tr>
      </thead>
      <tbody>
        {body_rows}
      </tbody>
    </table>
  </div>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build team-kit review artifacts using DAT palette + mask0 rendering.")
    parser.add_argument(
        "--manifest-path",
        default=str(ROOT_DIR / "work" / "parallel_recheck" / "team_kits" / "kit_manifest.json"),
        help="Path to team kit manifest JSON.",
    )
    parser.add_argument(
        "--kit-archive",
        default=str(ROOT_DIR / "DBDAT" / "MINIESC.PKF"),
        help="Path to MINIESC.PKF kit archive.",
    )
    parser.add_argument(
        "--dat-archive",
        action="append",
        default=None,
        help="Path to DAT.PKF file containing embedded RIFF palettes (repeatable).",
    )
    parser.add_argument(
        "--preferred-palette-hash",
        action="append",
        default=None,
        help="Preferred 16-hex SHA256 prefix for embedded RIFF palette (repeatable).",
    )
    parser.add_argument(
        "--columns",
        type=int,
        default=4,
        help="Composite grid column count (default: 4).",
    )
    parser.add_argument(
        "--composite-scale",
        type=int,
        default=2,
        help="Scale for composite kit thumbnails (default: 2).",
    )
    parser.add_argument(
        "--per-team-scale",
        type=int,
        default=4,
        help="Scale for per-team review images (default: 4).",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Output directory for generated artifacts.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest_path).expanduser().resolve()
    kit_archive_path = Path(args.kit_archive).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    dat_archives = (
        [Path(path).expanduser().resolve() for path in args.dat_archive]
        if args.dat_archive
        else [
            (ROOT_DIR / "FDI-PKF" / "DAT.PKF").resolve(),
            (ROOT_DIR / "DBDAT" / "DAT.PKF").resolve(),
        ]
    )
    preferred_palette_hashes = (
        [value.strip().lower() for value in args.preferred_palette_hash]
        if args.preferred_palette_hash
        else ["ba71c6264fdd9ad0", "2d2bceb5304c1937"]
    )

    if not manifest_path.is_file():
        raise FileNotFoundError(f"Manifest file not found: {manifest_path}")
    if not kit_archive_path.is_file():
        raise FileNotFoundError(f"Kit archive not found: {kit_archive_path}")

    summary = build_team_kit_review(
        manifest_path=manifest_path,
        kit_archive_path=kit_archive_path,
        dat_archives=dat_archives,
        output_dir=output_dir,
        preferred_palette_hashes=preferred_palette_hashes,
        columns=int(args.columns),
        composite_scale=int(args.composite_scale),
        per_team_scale=int(args.per_team_scale),
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

