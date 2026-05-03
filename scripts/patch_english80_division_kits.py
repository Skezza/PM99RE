#!/usr/bin/env python3
"""Patch English-80 division carrier kits from a structured assignment."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


REPO_ROOT = Path(__file__).resolve().parents[1]
EDITOR_ROOT = REPO_ROOT / "upstream" / "pm99-skezmod-db-editor"
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from app.minifoto_bitmap_archive import iter_obfuscated_bmp_records, parse_riff_palette  # noqa: E402
from build_english80_kit_research import (  # noqa: E402
    build_original_name_index,
    read_json,
    resolve_desired_eq_id,
)


ARCHIVES = ("BIGCAMP.PKF", "BIGESC.PKF", "MINIESC.PKF", "NANOESC.PKF", "RIDIESC.PKF")
PALETTE_OFFSET = 0x225B2

COLORS: dict[str, tuple[int, int, int]] = {
    "amber": (236, 174, 25),
    "black": (18, 18, 18),
    "blue": (0, 66, 168),
    "claret": (116, 26, 54),
    "deep_red": (165, 0, 24),
    "gold": (225, 154, 35),
    "green": (0, 126, 72),
    "light_blue": (86, 186, 226),
    "navy": (5, 20, 72),
    "orange": (235, 92, 24),
    "red": (212, 0, 30),
    "royal": (0, 82, 184),
    "sky": (112, 196, 230),
    "tangerine": (244, 106, 28),
    "white": (246, 246, 238),
    "yellow": (246, 210, 35),
}

SYNTHETIC_KIT_STYLES: dict[str, dict[str, Any]] = {
    "afc_wimbledon": {
        "name": "AFC Wimbledon",
        "pattern": "solid",
        "colors": ("royal",),
        "shorts": "royal",
        "trim": "yellow",
    },
    "burton_albion": {
        "name": "Burton Albion",
        "pattern": "solid",
        "colors": ("yellow",),
        "shorts": "black",
        "trim": "black",
    },
    "stevenage": {
        "name": "Stevenage",
        "pattern": "solid",
        "colors": ("red",),
        "shorts": "white",
        "trim": "black",
    },
    "accrington_stanley": {
        "name": "Accrington Stanley",
        "pattern": "solid",
        "colors": ("red",),
        "shorts": "red",
        "trim": "white",
    },
    "barrow": {
        "name": "Barrow",
        "pattern": "vertical_stripes",
        "colors": ("blue", "white"),
        "shorts": "blue",
        "trim": "white",
        "stripe_count": 5,
    },
    "bromley": {
        "name": "Bromley",
        "pattern": "solid",
        "colors": ("white",),
        "shorts": "black",
        "trim": "black",
    },
    "cheltenham_town": {
        "name": "Cheltenham Town",
        "pattern": "vertical_stripes",
        "colors": ("red", "white"),
        "shorts": "red",
        "trim": "white",
        "stripe_count": 5,
    },
    "crawley_town": {
        "name": "Crawley Town",
        "pattern": "solid",
        "colors": ("red",),
        "shorts": "red",
        "trim": "white",
    },
    "fleetwood_town": {
        "name": "Fleetwood Town",
        "pattern": "solid",
        "colors": ("red",),
        "shorts": "white",
        "trim": "white",
    },
}

SOURCE_STYLE_BY_EQ_ID: dict[int, dict[str, Any]] = {
    315: {"name": "Sheffield Wednesday", "pattern": "vertical_stripes", "colors": ("royal", "white"), "shorts": "black", "trim": "white", "stripe_count": 5},
    317: {"name": "Southampton", "pattern": "vertical_stripes", "colors": ("red", "white"), "shorts": "black", "trim": "black", "stripe_count": 5},
    322: {"name": "Bolton Wanderers", "pattern": "solid", "colors": ("white",), "shorts": "navy", "trim": "navy"},
    333: {"name": "Charlton Athletic", "pattern": "solid", "colors": ("red",), "shorts": "white", "trim": "white"},
    343: {"name": "West Bromwich Albion", "pattern": "vertical_stripes", "colors": ("navy", "white"), "shorts": "white", "trim": "navy", "stripe_count": 5},
    347: {"name": "Brentford", "pattern": "vertical_stripes", "colors": ("red", "white"), "shorts": "black", "trim": "black", "stripe_count": 5},
    349: {"name": "Bristol Rovers", "pattern": "quarters", "colors": ("royal", "white"), "shorts": "white", "trim": "blue"},
    350: {"name": "Burnley", "pattern": "sleeves", "colors": ("claret",), "sleeves": "sky", "shorts": "white", "trim": "sky"},
    353: {"name": "Crewe Alexandra", "pattern": "solid", "colors": ("red",), "shorts": "white", "trim": "white"},
    358: {"name": "Peterborough United", "pattern": "solid", "colors": ("blue",), "shorts": "white", "trim": "white"},
    366: {"name": "Wrexham", "pattern": "solid", "colors": ("red",), "shorts": "white", "trim": "white"},
    372: {"name": "Cardiff City", "pattern": "solid", "colors": ("blue",), "shorts": "blue", "trim": "white"},
    377: {"name": "Doncaster Rovers", "pattern": "hoops", "colors": ("red", "white"), "shorts": "black", "trim": "black", "band_count": 5},
    383: {"name": "Leyton Orient", "pattern": "solid", "colors": ("red",), "shorts": "red", "trim": "white"},
    386: {"name": "Northampton Town", "pattern": "solid", "colors": ("claret",), "shorts": "white", "trim": "white"},
    390: {"name": "Swansea City", "pattern": "solid", "colors": ("white",), "shorts": "white", "trim": "black"},
}


class PaletteMapper:
    def __init__(self, palette: list[tuple[int, int, int]]) -> None:
        self.palette = palette
        self.cache: dict[tuple[int, int, int, bool], int] = {}

    def nearest(self, rgb: tuple[int, int, int], *, avoid_zero: bool = True) -> int:
        quantized = tuple(max(0, min(255, int(round(channel / 8) * 8))) for channel in rgb)
        key = (quantized[0], quantized[1], quantized[2], avoid_zero)
        if key in self.cache:
            return self.cache[key]
        start = 1 if avoid_zero else 0
        best_index = start
        best_distance = float("inf")
        for index, color in enumerate(self.palette[start:], start):
            distance = sum((int(color[channel]) - int(quantized[channel])) ** 2 for channel in range(3))
            if distance < best_distance:
                best_index = index
                best_distance = distance
        self.cache[key] = best_index
        return best_index


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_dat_palette(game_root: Path) -> list[tuple[int, int, int]]:
    palette_path = game_root / "DAT.PKF"
    data = palette_path.read_bytes()
    if data[PALETTE_OFFSET : PALETTE_OFFSET + 4] != b"RIFF":
        raise RuntimeError(f"expected RIFF palette in {palette_path} at {PALETTE_OFFSET:#x}")
    chunk_size = int.from_bytes(data[PALETTE_OFFSET + 4 : PALETTE_OFFSET + 8], "little")
    blob = data[PALETTE_OFFSET : PALETTE_OFFSET + 8 + chunk_size]
    return parse_riff_palette(blob)


def team_id_from_record(record: Any) -> int | None:
    match = re.match(r"^EQ96(?P<team_id>\d{4})\.BMP$", str(record.file_name), re.IGNORECASE)
    if not match:
        return None
    return int(match.group("team_id"))


def record_to_top_down_indices(record: Any, raw_bitmap: bytes | None = None) -> list[list[int]]:
    bitmap = raw_bitmap if raw_bitmap is not None else record.raw_bitmap
    width = int(record.width)
    height = int(record.height)
    pixels = bitmap[int(record.pixel_offset) : int(record.pixel_offset) + width * height]
    rows: list[list[int]] = []
    for y in range(height):
        source_row = (height - 1 - y) * width
        rows.append([int(value) for value in pixels[source_row : source_row + width]])
    return rows


def top_down_indices_to_raw(record: Any, rows: list[list[int]]) -> bytes:
    width = int(record.width)
    height = int(record.height)
    raw = bytearray(record.raw_bitmap)
    for y, row in enumerate(rows):
        if len(row) != width:
            raise ValueError("row width mismatch")
        target_row = (height - 1 - y) * width
        start = int(record.pixel_offset) + target_row
        raw[start : start + width] = bytes(max(0, min(255, int(value))) for value in row)
    return bytes(raw)


def resample_source_bitmap_to_target(source_record: Any, target_record: Any) -> bytes:
    source_rows = record_to_top_down_indices(source_record)
    target_rows = record_to_top_down_indices(target_record)
    source_height = len(source_rows)
    source_width = len(source_rows[0])
    target_height = len(target_rows)
    target_width = len(target_rows[0])

    source_image = Image.new("L", (source_width, source_height), 0)
    source_image.putdata([value for row in source_rows for value in row])
    resized = source_image.resize((target_width, target_height), Image.Resampling.NEAREST)
    resized_values = list(resized.getdata())

    def nearest_nonzero(x: int, y: int) -> int:
        for radius in range(1, 6):
            for ny in range(max(0, y - radius), min(target_height, y + radius + 1)):
                for nx in range(max(0, x - radius), min(target_width, x + radius + 1)):
                    value = int(resized_values[ny * target_width + nx])
                    if value != 0:
                        return value
        return 0

    out = [list(row) for row in target_rows]
    for y, row in enumerate(target_rows):
        for x, target_value in enumerate(row):
            if target_value == 0:
                out[y][x] = 0
                continue
            value = int(resized_values[y * target_width + x])
            if value == 0:
                value = nearest_nonzero(x, y)
            if value != 0:
                out[y][x] = value
    return top_down_indices_to_raw(target_record, out)


def render_rows(
    rows: list[list[int]],
    palette: list[tuple[int, int, int]],
    *,
    scale: int,
    mask_zero: bool,
) -> Image.Image:
    height = len(rows)
    width = len(rows[0]) if height else 0
    mode = "RGBA" if mask_zero else "RGB"
    background = (0, 0, 0, 0) if mask_zero else (236, 236, 236)
    image = Image.new(mode, (width, height), background)
    for y, row in enumerate(rows):
        for x, index in enumerate(row):
            if mask_zero and index == 0:
                continue
            r, g, b = palette[index]
            if mask_zero:
                image.putpixel((x, y), (r, g, b, 255))
            else:
                image.putpixel((x, y), (r, g, b))
    if scale == 1:
        return image
    return image.resize((width * scale, height * scale), Image.Resampling.NEAREST)


def row_bounds(mask: list[list[bool]], y: int) -> tuple[int, int] | None:
    xs = [x for x, value in enumerate(mask[y]) if value]
    if not xs:
        return None
    return min(xs), max(xs)


def edge_pixel(mask: list[list[bool]], x: int, y: int) -> bool:
    height = len(mask)
    width = len(mask[0])
    for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
        if nx < 0 or ny < 0 or nx >= width or ny >= height or not mask[ny][nx]:
            return True
    return False


def color_rgb(name: str) -> tuple[int, int, int]:
    return COLORS[name]


def luminance(rgb: tuple[int, int, int]) -> float:
    return (0.299 * rgb[0]) + (0.587 * rgb[1]) + (0.114 * rgb[2])


def shade_rgb(rgb: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(round(channel * factor)))) for channel in rgb)


def style_color(
    style: dict[str, Any],
    x: int,
    y: int,
    row_min: int,
    row_max: int,
    shirt_top: int,
    shirt_bottom: int,
) -> tuple[int, int, int]:
    pattern = str(style.get("pattern", "solid"))
    color_names = tuple(str(item) for item in style.get("colors", ("white",)))
    colors = tuple(color_rgb(name) for name in color_names)
    row_width = max(1, row_max - row_min + 1)
    row_center = (row_min + row_max) / 2.0
    shirt_height = max(1, shirt_bottom - shirt_top + 1)
    x_norm = (x - row_min) / row_width
    y_norm = (y - shirt_top) / shirt_height

    if pattern == "solid":
        return colors[0]
    if pattern == "vertical_stripes":
        stripe_count = int(style.get("stripe_count") or max(4, len(colors) * 3))
        stripe = int(math.floor(x_norm * stripe_count))
        return colors[stripe % len(colors)]
    if pattern == "hoops":
        band_count = int(style.get("band_count") or 6)
        band = int(math.floor(y_norm * band_count))
        return colors[band % len(colors)]
    if pattern == "halves":
        return colors[0] if x <= row_center else colors[min(1, len(colors) - 1)]
    if pattern == "quarters":
        left = x <= row_center
        top = y_norm < 0.52
        first = (left and top) or ((not left) and (not top))
        return colors[0] if first else colors[min(1, len(colors) - 1)]
    if pattern == "sleeves":
        sleeve_rgb = color_rgb(str(style.get("sleeves") or color_names[0]))
        sleeve_width = max(2, int(row_width * 0.23))
        if y_norm <= 0.82 and (x <= row_min + sleeve_width or x >= row_max - sleeve_width):
            return sleeve_rgb
        return colors[0]
    return colors[0]


def build_updated_kit_rows(
    rows: list[list[int]],
    palette: list[tuple[int, int, int]],
    mapper: PaletteMapper,
    style: dict[str, Any],
) -> list[list[int]]:
    height = len(rows)
    width = len(rows[0])
    mask = [[index != 0 for index in row] for row in rows]
    nonzero_rows = [y for y, row in enumerate(mask) if any(row)]
    if not nonzero_rows:
        return [list(row) for row in rows]

    first_y = min(nonzero_rows)
    last_y = max(nonzero_rows)
    shirt_top = max(first_y, int(height * 0.04))
    shirt_bottom = min(last_y, int(height * 0.58))
    trim_name = style.get("trim")
    trim_rgb = color_rgb(str(trim_name)) if trim_name else None
    shorts_rgb = color_rgb(str(style.get("shorts") or "white"))
    out = [list(row) for row in rows]
    for y in range(height):
        bounds = row_bounds(mask, y)
        if bounds is None:
            continue
        row_min, row_max = bounds
        row_width = max(1, row_max - row_min + 1)
        row_center = (row_min + row_max) / 2.0
        for x in range(width):
            original_index = rows[y][x]
            if original_index == 0:
                out[y][x] = 0
                continue
            original_rgb = palette[original_index]
            source_luma = luminance(original_rgb)
            is_edge = edge_pixel(mask, x, y)
            if y <= shirt_bottom:
                base_rgb = style_color(style, x, y, row_min, row_max, shirt_top, shirt_bottom)
                if trim_rgb is not None:
                    top_band = y <= shirt_top + max(1, height // 19)
                    collar_width = max(2, int(row_width * 0.18))
                    cuff_width = max(1, width // 34)
                    if top_band and abs(x - row_center) <= collar_width:
                        base_rgb = trim_rgb
                    elif x <= row_min + cuff_width or x >= row_max - cuff_width:
                        base_rgb = trim_rgb
            else:
                base_rgb = shorts_rgb
            factor = 0.82 + (max(0.0, min(255.0, source_luma)) / 255.0) * 0.35
            if is_edge:
                factor *= 0.90
            out[y][x] = mapper.nearest(shade_rgb(base_rgb, factor))
    return out


def build_kit_plan(assignment_path: Path, kit_manifest_path: Path) -> list[dict[str, Any]]:
    assignment = read_json(assignment_path)
    kit_rows = read_json(kit_manifest_path)["rows"]
    original_index = build_original_name_index(kit_rows)
    plan: list[dict[str, Any]] = []
    for row in assignment["assignments"]:
        carrier_eq_id = int(row["carrier_eq_record_id"])
        desired_eq_id, source_kind, map_rationale = resolve_desired_eq_id(
            str(row["target_display_name"]),
            original_index,
        )
        if source_kind == "direct_existing":
            if int(desired_eq_id) == carrier_eq_id:
                action = "keep_existing"
            else:
                action = "copy_existing_source"
        else:
            action = "synthesize_modern"
        plan.append(
            {
                "slot": int(row["slot"]),
                "target_club_key": str(row["target_club_key"]),
                "target_display_name": str(row["target_display_name"]),
                "target_pm99_division": str(row["target_pm99_division"]),
                "carrier_eq_record_id": carrier_eq_id,
                "carrier_team_query": str(row["carrier_team_query"]),
                "desired_eq_record_id": int(desired_eq_id),
                "source_kind": source_kind,
                "map_rationale": map_rationale,
                "kit_action": action,
            }
        )
    return plan


def patch_archive(
    archive_path: Path,
    plan: list[dict[str, Any]],
    palette: list[tuple[int, int, int]],
    mapper: PaletteMapper,
) -> list[dict[str, Any]]:
    original_archive = archive_path.read_bytes()
    patched_archive = bytearray(original_archive)
    records = list(iter_obfuscated_bmp_records(archive_path, file_name_pattern=r"^EQ96\d{4}\.BMP$"))
    by_team = {team_id_from_record(record): record for record in records if team_id_from_record(record) is not None}
    events: list[dict[str, Any]] = []

    for item in plan:
        carrier_eq_id = int(item["carrier_eq_record_id"])
        target_record = by_team.get(carrier_eq_id)
        if target_record is None:
            events.append({**item, "archive_name": archive_path.name, "status": "missing_target_record"})
            continue

        action = str(item["kit_action"])
        if action == "keep_existing":
            events.append(
                {
                    **item,
                    "archive_name": archive_path.name,
                    "file_name": target_record.file_name,
                    "status": "kept",
                    "bitmap_sha256_before": sha256_bytes(target_record.raw_bitmap),
                    "bitmap_sha256_after": sha256_bytes(target_record.raw_bitmap),
                }
            )
            continue

        if action == "copy_existing_source":
            source_eq_id = int(item["desired_eq_record_id"])
            source_record = by_team.get(source_eq_id)
            if source_record is None:
                style = SOURCE_STYLE_BY_EQ_ID.get(source_eq_id)
                if style is None:
                    events.append(
                        {
                            **item,
                            "archive_name": archive_path.name,
                            "file_name": target_record.file_name,
                            "status": "failed_missing_source_record",
                        }
                    )
                    continue
                original_rows = record_to_top_down_indices(target_record)
                updated_rows = build_updated_kit_rows(original_rows, palette, mapper, style)
                updated_bitmap = top_down_indices_to_raw(target_record, updated_rows)
                source_file_name = ""
                status = "synthesized_missing_source"
            elif len(source_record.raw_bitmap) != int(target_record.bitmap_length):
                updated_bitmap = resample_source_bitmap_to_target(source_record, target_record)
                source_file_name = source_record.file_name
                status = "resampled_source"
            else:
                updated_bitmap = bytes(source_record.raw_bitmap)
                source_file_name = source_record.file_name
                status = "copied_source"
        else:
            style = SYNTHETIC_KIT_STYLES.get(str(item["target_club_key"]))
            if style is None:
                events.append(
                    {
                        **item,
                        "archive_name": archive_path.name,
                        "file_name": target_record.file_name,
                        "status": "missing_synthetic_style",
                    }
                )
                continue
            original_rows = record_to_top_down_indices(target_record)
            updated_rows = build_updated_kit_rows(original_rows, palette, mapper, style)
            updated_bitmap = top_down_indices_to_raw(target_record, updated_rows)
            source_file_name = ""
            status = "synthesized"

        start = int(target_record.bitmap_offset)
        end = start + int(target_record.bitmap_length)
        patched_archive[start:end] = updated_bitmap
        events.append(
            {
                **item,
                "archive_name": archive_path.name,
                "file_name": target_record.file_name,
                "source_file_name": source_file_name,
                "status": status,
                "record_offset": int(target_record.record_offset),
                "bitmap_offset": int(target_record.bitmap_offset),
                "bitmap_length": int(target_record.bitmap_length),
                "width": int(target_record.width),
                "height": int(target_record.height),
                "bitmap_sha256_before": sha256_bytes(target_record.raw_bitmap),
                "bitmap_sha256_after": sha256_bytes(updated_bitmap),
            }
        )

    archive_path.write_bytes(bytes(patched_archive))
    reread = list(iter_obfuscated_bmp_records(archive_path, file_name_pattern=r"^EQ96\d{4}\.BMP$"))
    reread_by_file = {str(record.file_name).upper(): record for record in reread}
    for event in events:
        if event.get("status") in {"copied_source", "synthesized"}:
            reread_record = reread_by_file.get(str(event["file_name"]).upper())
            if reread_record is None:
                raise RuntimeError(f"{archive_path.name}/{event['file_name']}: missing after write")
            if sha256_bytes(reread_record.raw_bitmap) != event["bitmap_sha256_after"]:
                raise RuntimeError(f"{archive_path.name}/{event['file_name']}: post-write verification failed")
    archive_before = sha256_bytes(original_archive)
    archive_after = sha256_bytes(bytes(patched_archive))
    for event in events:
        event["archive_sha256_before"] = archive_before
        event["archive_sha256_after"] = archive_after
    return events


def render_per_club_previews(
    game_root: Path,
    output_dir: Path,
    plan: list[dict[str, Any]],
    palette: list[tuple[int, int, int]],
) -> None:
    per_club = output_dir / "per_club_miniesc"
    per_club.mkdir(parents=True, exist_ok=True)
    records = list(iter_obfuscated_bmp_records(game_root / "DBDAT" / "MINIESC.PKF", file_name_pattern=r"^EQ96\d{4}\.BMP$"))
    by_team = {team_id_from_record(record): record for record in records if team_id_from_record(record) is not None}
    columns = 8
    cell_width = 188
    cell_height = 228
    sheet = Image.new("RGB", (columns * cell_width, math.ceil(len(plan) / columns) * cell_height), (224, 224, 218))
    draw = ImageDraw.Draw(sheet)
    for index, item in enumerate(plan):
        record = by_team.get(int(item["carrier_eq_record_id"]))
        col = index % columns
        row = index // columns
        x0 = col * cell_width
        y0 = row * cell_height
        draw.rectangle((x0, y0, x0 + cell_width - 1, y0 + cell_height - 1), outline=(184, 184, 176))
        label = f"{item['slot']:02d} {item['target_display_name']}"
        draw.text((x0 + 8, y0 + 8), label[:28], fill=(20, 20, 20))
        draw.text((x0 + 8, y0 + 24), f"EQ{int(item['carrier_eq_record_id']):04d} {item['kit_action']}", fill=(80, 80, 80))
        if record is None:
            draw.text((x0 + 8, y0 + 44), "missing MINIESC", fill=(160, 0, 0))
            continue
        rows = record_to_top_down_indices(record)
        image = render_rows(rows, palette, scale=3, mask_zero=True)
        bg = Image.new("RGB", image.size, (236, 236, 236))
        bg.paste(image, (0, 0), image)
        sheet.paste(bg, (x0 + (cell_width - bg.width) // 2, y0 + 48))
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(item["target_display_name"])).strip("_")
        bg.save(per_club / f"{int(item['slot']):02d}_{safe_name}_EQ{int(item['carrier_eq_record_id']):04d}.png")
    sheet.save(output_dir / "english80_division_kit_contact_sheet.png")


def patch_english80_division_kits(
    *,
    game_root: Path,
    assignment_path: Path,
    output_dir: Path,
    kit_manifest_path: Path,
) -> dict[str, Any]:
    game_root = game_root.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    plan = build_kit_plan(assignment_path, kit_manifest_path)
    palette = load_dat_palette(game_root)
    mapper = PaletteMapper(palette)
    events: list[dict[str, Any]] = []
    for archive_name in ARCHIVES:
        archive_path = game_root / "DBDAT" / archive_name
        if not archive_path.exists():
            raise FileNotFoundError(archive_path)
        events.extend(patch_archive(archive_path, plan, palette, mapper))
    render_per_club_previews(game_root, output_dir, plan, palette)

    counts: dict[str, int] = {}
    for event in events:
        key = str(event.get("status") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    summary = {
        "schema": "pm99-english80-division-kit-patch-v1",
        "ok": not any(str(event.get("status") or "").startswith("failed") for event in events)
        and not any(event.get("status") == "missing_synthetic_style" for event in events),
        "game_root": str(game_root),
        "assignment_path": str(assignment_path),
        "kit_manifest_path": str(kit_manifest_path),
        "output_dir": str(output_dir),
        "plan_count": len(plan),
        "event_count": len(events),
        "status_counts": counts,
        "contact_sheet": str(output_dir / "english80_division_kit_contact_sheet.png"),
        "per_club_preview_dir": str(output_dir / "per_club_miniesc"),
        "plan": plan,
        "events": events,
    }
    (output_dir / "english80_division_kit_patch_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", required=True, type=Path)
    parser.add_argument("--assignment-path", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--kit-manifest-path",
        default=REPO_ROOT / "work" / "parallel_recheck" / "team_kits" / "kit_manifest.json",
        type=Path,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = patch_english80_division_kits(
        game_root=args.game_root,
        assignment_path=args.assignment_path,
        output_dir=args.output_dir,
        kit_manifest_path=args.kit_manifest_path,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
