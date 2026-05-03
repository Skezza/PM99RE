#!/usr/bin/env python3
"""Patch reference-backed English-80 home kit approximations.

This is a research artifact generator. It preserves PM99 bitmap dimensions,
transparency, and payload lengths, then recolours the existing kit silhouettes
using manually encoded 2025/26-style home kit patterns.
"""

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


ROOT = Path(__file__).resolve().parents[1]
EDITOR_DIR = ROOT / "upstream" / "pm99-skezmod-db-editor"
if str(EDITOR_DIR) not in sys.path:
    sys.path.insert(0, str(EDITOR_DIR))

from app.minifoto_bitmap_archive import iter_obfuscated_bmp_records, parse_riff_palette  # noqa: E402


ARCHIVES = ("BIGCAMP.PKF", "BIGESC.PKF", "MINIESC.PKF", "NANOESC.PKF", "RIDIESC.PKF")
PALETTE_OFFSET = 0x225B2

SOURCE_URLS = {
    "premier_league": "https://www.premierleague.com/en/news/4309019/premier-league-club-kits-for-the-202526-season",
    "championship": "https://www.footballkitarchive.com/championship-kits-2025-26-l61/",
    "league_one": "https://www.footballkitarchive.com/league-one-kits-2025-26-l156/",
    "league_two": "https://www.footballkitarchive.com/league-two-kits-2025-26-l157/",
}

COLORS: dict[str, tuple[int, int, int]] = {
    "amber": (236, 174, 25),
    "black": (18, 18, 18),
    "blue": (0, 66, 168),
    "brown": (88, 50, 36),
    "claret": (116, 26, 54),
    "cream": (236, 228, 202),
    "dark_blue": (0, 38, 120),
    "deep_red": (165, 0, 24),
    "gold": (225, 154, 35),
    "green": (0, 126, 72),
    "light_blue": (86, 186, 226),
    "navy": (5, 20, 72),
    "orange": (235, 92, 24),
    "pink": (235, 92, 116),
    "purple": (66, 43, 128),
    "red": (212, 0, 30),
    "royal": (0, 82, 184),
    "sky": (112, 196, 230),
    "teal": (0, 128, 142),
    "tangerine": (244, 106, 28),
    "white": (246, 246, 238),
    "yellow": (246, 210, 35),
}


def style(
    name: str,
    division_source: str,
    pattern: str,
    colors: tuple[str, ...],
    *,
    shorts: str = "white",
    trim: str | None = "white",
    sleeves: str | None = None,
    stripe_count: int | None = None,
    band_count: int | None = None,
    accent: str | None = None,
    side_panel: str | None = None,
    yoke: str | None = None,
    notes: str = "",
) -> dict[str, Any]:
    return {
        "name": name,
        "source_url": SOURCE_URLS[division_source],
        "reference_basis": "manual PM99-scale approximation from 2025/26 home-kit reference pages",
        "pattern": pattern,
        "colors": colors,
        "shorts": shorts,
        "trim": trim,
        "sleeves": sleeves,
        "stripe_count": stripe_count,
        "band_count": band_count,
        "accent": accent,
        "side_panel": side_panel,
        "yoke": yoke,
        "notes": notes,
    }


STYLE_BY_CLUB: dict[str, dict[str, Any]] = {
    # Premier League
    "Arsenal": style("Arsenal", "premier_league", "sleeves", ("red",), sleeves="white", shorts="white", trim="white", accent="gold"),
    "Aston Villa": style("Aston Villa", "premier_league", "sleeves", ("claret",), sleeves="sky", shorts="white", trim="sky"),
    "Bournemouth": style("Bournemouth", "premier_league", "vertical_stripes", ("red", "black"), shorts="black", trim="black", stripe_count=5),
    "Brentford": style("Brentford", "premier_league", "vertical_stripes", ("red", "white"), shorts="black", trim="black", stripe_count=5),
    "Brighton & Hove Albion": style("Brighton & Hove Albion", "premier_league", "vertical_stripes", ("blue", "white"), shorts="blue", trim="white", stripe_count=5),
    "Burnley": style("Burnley", "premier_league", "sleeves", ("claret",), sleeves="sky", shorts="white", trim="sky"),
    "Chelsea": style("Chelsea", "premier_league", "solid", ("blue",), shorts="blue", trim="white", accent="white"),
    "Crystal Palace": style("Crystal Palace", "premier_league", "vertical_stripes", ("blue", "red"), shorts="blue", trim="white", stripe_count=5),
    "Everton": style("Everton", "premier_league", "solid", ("royal",), shorts="white", trim="white"),
    "Fulham": style("Fulham", "premier_league", "solid", ("white",), shorts="black", trim="black", side_panel="black"),
    "Leeds United": style("Leeds United", "premier_league", "solid", ("white",), shorts="white", trim="blue", accent="yellow"),
    "Liverpool": style("Liverpool", "premier_league", "solid", ("deep_red",), shorts="deep_red", trim="white"),
    "Manchester City": style("Manchester City", "premier_league", "diagonal_sash", ("sky", "white"), shorts="white", trim="white"),
    "Manchester United": style("Manchester United", "premier_league", "solid", ("red",), shorts="white", trim="black"),
    "Newcastle United": style("Newcastle United", "premier_league", "vertical_stripes", ("black", "white"), shorts="black", trim="white", stripe_count=5),
    "Nottingham Forest": style("Nottingham Forest", "premier_league", "solid", ("red",), shorts="white", trim="white"),
    "Sunderland": style("Sunderland", "premier_league", "vertical_stripes", ("red", "white"), shorts="black", trim="black", stripe_count=5),
    "Tottenham Hotspur": style("Tottenham Hotspur", "premier_league", "solid", ("white",), shorts="navy", trim="navy"),
    "West Ham United": style("West Ham United", "premier_league", "sleeves", ("claret",), sleeves="sky", shorts="white", trim="sky"),
    "Wolverhampton Wanderers": style("Wolverhampton Wanderers", "premier_league", "solid", ("gold",), shorts="black", trim="black"),
    # Championship
    "Birmingham City": style("Birmingham City", "championship", "solid", ("royal",), shorts="royal", trim="white"),
    "Blackburn Rovers": style("Blackburn Rovers", "championship", "halves", ("blue", "white"), shorts="white", trim="black"),
    "Bristol City": style("Bristol City", "championship", "solid", ("red",), shorts="white", trim="white"),
    "Charlton Athletic": style("Charlton Athletic", "championship", "solid", ("red",), shorts="white", trim="white"),
    "Coventry City": style("Coventry City", "championship", "solid", ("sky",), shorts="sky", trim="white"),
    "Derby County": style("Derby County", "championship", "solid", ("white",), shorts="black", trim="black"),
    "Hull City": style("Hull City", "championship", "vertical_stripes", ("amber", "black"), shorts="black", trim="black", stripe_count=5),
    "Ipswich Town": style("Ipswich Town", "championship", "solid", ("blue",), shorts="white", trim="white"),
    "Leicester City": style("Leicester City", "championship", "solid", ("royal",), shorts="white", trim="white"),
    "Middlesbrough": style("Middlesbrough", "championship", "chest_band", ("red", "white"), shorts="red", trim="white"),
    "Millwall": style("Millwall", "championship", "solid", ("navy",), shorts="white", trim="white"),
    "Norwich City": style("Norwich City", "championship", "solid", ("yellow",), shorts="green", trim="green"),
    "Oxford United": style("Oxford United", "championship", "solid", ("yellow",), shorts="navy", trim="navy"),
    "Portsmouth": style("Portsmouth", "championship", "solid", ("blue",), shorts="white", trim="red"),
    "Preston North End": style("Preston North End", "championship", "solid", ("white",), shorts="navy", trim="navy"),
    "Queens Park Rangers": style("Queens Park Rangers", "championship", "hoops", ("white", "royal"), shorts="white", trim="blue", band_count=6),
    "Sheffield United": style("Sheffield United", "championship", "vertical_stripes", ("red", "white"), shorts="black", trim="black", stripe_count=5),
    "Sheffield Wednesday": style("Sheffield Wednesday", "championship", "vertical_stripes", ("royal", "white"), shorts="black", trim="white", stripe_count=5),
    "Southampton": style("Southampton", "championship", "vertical_stripes", ("red", "white"), shorts="black", trim="black", stripe_count=5),
    "Stoke City": style("Stoke City", "championship", "vertical_stripes", ("red", "white"), shorts="white", trim="black", stripe_count=5, notes="mapped to the modern assignment carrier, not the old Stoke EQ id"),
    "Swansea City": style("Swansea City", "championship", "solid", ("white",), shorts="white", trim="black"),
    "Watford": style("Watford", "championship", "solid", ("yellow",), shorts="black", trim="black"),
    "West Bromwich Albion": style("West Bromwich Albion", "championship", "vertical_stripes", ("navy", "white"), shorts="white", trim="navy", stripe_count=5),
    "Wrexham": style("Wrexham", "championship", "solid", ("red",), shorts="white", trim="white"),
    # League One
    "AFC Wimbledon": style("AFC Wimbledon", "league_one", "solid", ("blue",), shorts="blue", trim="yellow"),
    "Barnsley": style("Barnsley", "league_one", "solid", ("red",), shorts="white", trim="white"),
    "Blackpool": style("Blackpool", "league_one", "solid", ("tangerine",), shorts="white", trim="white"),
    "Bolton Wanderers": style("Bolton Wanderers", "league_one", "solid", ("white",), shorts="navy", trim="navy"),
    "Bradford City": style("Bradford City", "league_one", "vertical_stripes", ("amber", "claret"), shorts="black", trim="black", stripe_count=5),
    "Burton Albion": style("Burton Albion", "league_one", "solid", ("yellow",), shorts="black", trim="black"),
    "Cardiff City": style("Cardiff City", "league_one", "solid", ("blue",), shorts="blue", trim="white"),
    "Doncaster Rovers": style("Doncaster Rovers", "league_one", "hoops", ("red", "white"), shorts="black", trim="black", band_count=5),
    "Exeter City": style("Exeter City", "league_one", "vertical_stripes", ("red", "white"), shorts="black", trim="black", stripe_count=5),
    "Huddersfield Town": style("Huddersfield Town", "league_one", "vertical_stripes", ("royal", "white"), shorts="white", trim="white", stripe_count=5),
    "Leyton Orient": style("Leyton Orient", "league_one", "solid", ("red",), shorts="red", trim="white"),
    "Lincoln City": style("Lincoln City", "league_one", "vertical_stripes", ("red", "white"), shorts="black", trim="black", stripe_count=5),
    "Luton Town": style("Luton Town", "league_one", "solid", ("orange",), shorts="navy", trim="navy"),
    "Mansfield Town": style("Mansfield Town", "league_one", "solid", ("amber",), shorts="blue", trim="blue"),
    "Northampton Town": style("Northampton Town", "league_one", "solid", ("claret",), shorts="white", trim="white"),
    "Peterborough United": style("Peterborough United", "league_one", "solid", ("blue",), shorts="white", trim="white"),
    # League Two / lower modern assignment
    "Plymouth Argyle": style("Plymouth Argyle", "league_one", "solid", ("green",), shorts="white", trim="white"),
    "Port Vale": style("Port Vale", "league_one", "solid", ("white",), shorts="black", trim="black"),
    "Reading": style("Reading", "league_one", "hoops", ("royal", "white"), shorts="white", trim="blue", band_count=6),
    "Rotherham United": style("Rotherham United", "league_one", "sleeves", ("red",), sleeves="white", shorts="white", trim="white"),
    "Stevenage": style("Stevenage", "league_one", "sleeves", ("red",), sleeves="white", shorts="red", trim="white"),
    "Stockport County": style("Stockport County", "league_one", "halves", ("blue", "white"), shorts="white", trim="blue"),
    "Wigan Athletic": style("Wigan Athletic", "league_one", "vertical_stripes", ("royal", "white"), shorts="blue", trim="white", stripe_count=5),
    "Wycombe Wanderers": style("Wycombe Wanderers", "league_one", "quarters", ("navy", "light_blue"), shorts="navy", trim="light_blue"),
    "Accrington Stanley": style("Accrington Stanley", "league_two", "solid", ("red",), shorts="red", trim="white"),
    "Barnet": style("Barnet", "league_two", "vertical_stripes", ("black", "amber"), shorts="black", trim="amber", stripe_count=5),
    "Barrow": style("Barrow", "league_two", "halves", ("blue", "white"), shorts="blue", trim="white"),
    "Bristol Rovers": style("Bristol Rovers", "league_two", "quarters", ("royal", "white"), shorts="white", trim="blue"),
    "Bromley": style("Bromley", "league_two", "solid", ("white",), shorts="black", trim="black"),
    "Cambridge United": style("Cambridge United", "league_two", "solid", ("amber",), shorts="black", trim="black"),
    "Cheltenham Town": style("Cheltenham Town", "league_two", "sleeves", ("red",), sleeves="white", shorts="white", trim="white"),
    "Chesterfield": style("Chesterfield", "league_two", "solid", ("blue",), shorts="white", trim="white"),
    "Colchester United": style("Colchester United", "league_two", "vertical_stripes", ("royal", "white"), shorts="blue", trim="white", stripe_count=5),
    "Crawley Town": style("Crawley Town", "league_two", "solid", ("red",), shorts="red", trim="white"),
    "Crewe Alexandra": style("Crewe Alexandra", "league_two", "solid", ("red",), shorts="white", trim="white"),
    "Fleetwood Town": style("Fleetwood Town", "league_two", "sleeves", ("red",), sleeves="white", shorts="white", trim="white"),
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
        raise RuntimeError(f"expected RIFF palette at {palette_path}:{PALETTE_OFFSET:#x}")
    chunk_size = int.from_bytes(data[PALETTE_OFFSET + 4 : PALETTE_OFFSET + 8], "little")
    blob = data[PALETTE_OFFSET : PALETTE_OFFSET + 8 + chunk_size]
    return parse_riff_palette(blob)


def record_to_top_down_indices(record: Any) -> list[list[int]]:
    width = int(record.width)
    height = int(record.height)
    pixels = record.raw_bitmap[record.pixel_offset : record.pixel_offset + width * height]
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
            image.putpixel((x, y), (r, g, b, 255) if mask_zero else (r, g, b))
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


def color_rgb(name: str | None, fallback: str = "white") -> tuple[int, int, int]:
    return COLORS[name or fallback]


def luminance(rgb: tuple[int, int, int]) -> float:
    return (0.299 * rgb[0]) + (0.587 * rgb[1]) + (0.114 * rgb[2])


def shade_rgb(rgb: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(round(channel * factor)))) for channel in rgb)


def style_color(
    style_row: dict[str, Any],
    x: int,
    y: int,
    row_min: int,
    row_max: int,
    shirt_top: int,
    shirt_bottom: int,
) -> tuple[int, int, int]:
    pattern = str(style_row.get("pattern", "solid"))
    colors = tuple(color_rgb(str(item)) for item in style_row.get("colors", ("white",)))
    row_width = max(1, row_max - row_min + 1)
    row_center = (row_min + row_max) / 2.0
    shirt_height = max(1, shirt_bottom - shirt_top + 1)
    x_norm = (x - row_min) / row_width
    y_norm = (y - shirt_top) / shirt_height

    if pattern == "vertical_stripes":
        stripe_count = int(style_row.get("stripe_count") or max(4, len(colors) * 3))
        stripe = int(math.floor(x_norm * stripe_count))
        return colors[stripe % len(colors)]
    if pattern == "hoops":
        band_count = int(style_row.get("band_count") or 6)
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
        sleeve_rgb = color_rgb(style_row.get("sleeves"), str(style_row.get("colors", ("white",))[0]))
        sleeve_width = max(2, int(row_width * 0.23))
        if y_norm <= 0.82 and (x <= row_min + sleeve_width or x >= row_max - sleeve_width):
            return sleeve_rgb
        return colors[0]
    if pattern == "chest_band":
        band_rgb = colors[min(1, len(colors) - 1)]
        band_mid = shirt_top + int(shirt_height * 0.38)
        band_half = max(1, int(shirt_height * 0.08))
        return band_rgb if abs(y - band_mid) <= band_half else colors[0]
    if pattern == "diagonal_sash":
        sash_rgb = colors[min(1, len(colors) - 1)]
        diagonal_center = row_min + row_width * (0.12 + y_norm * 0.82)
        sash_half = max(2, int(row_width * 0.10))
        return sash_rgb if abs(x - diagonal_center) <= sash_half else colors[0]
    return colors[0]


def apply_detail_overlays(
    base_rgb: tuple[int, int, int],
    style_row: dict[str, Any],
    x: int,
    y: int,
    row_min: int,
    row_max: int,
    row_center: float,
    row_width: int,
    shirt_top: int,
    shirt_bottom: int,
) -> tuple[int, int, int]:
    shirt_height = max(1, shirt_bottom - shirt_top + 1)
    y_norm = (y - shirt_top) / shirt_height
    trim_rgb = color_rgb(style_row.get("trim"), "white") if style_row.get("trim") else None
    accent_rgb = color_rgb(style_row.get("accent"), "white") if style_row.get("accent") else None
    side_panel_rgb = color_rgb(style_row.get("side_panel"), "white") if style_row.get("side_panel") else None
    yoke_rgb = color_rgb(style_row.get("yoke"), "white") if style_row.get("yoke") else None

    if yoke_rgb and y_norm < 0.18:
        return yoke_rgb
    if side_panel_rgb:
        panel_width = max(1, int(row_width * 0.08))
        if x <= row_min + panel_width or x >= row_max - panel_width:
            return side_panel_rgb
    if trim_rgb is not None:
        top_band = y <= shirt_top + max(1, shirt_height // 11)
        collar_width = max(2, int(row_width * 0.18))
        sleeve_band = y <= shirt_top + max(3, int(shirt_height * 0.66))
        cuff_width = max(1, row_width // 16)
        if top_band and abs(x - row_center) <= collar_width:
            return trim_rgb
        if sleeve_band and (x <= row_min + cuff_width or x >= row_max - cuff_width):
            return trim_rgb
    if accent_rgb is not None:
        # A thin center/neck accent is visible in PM99 without pretending to draw sponsors.
        accent_half = max(1, row_width // 30)
        accent_top = shirt_top + int(shirt_height * 0.17)
        accent_bottom = shirt_top + int(shirt_height * 0.45)
        if accent_top <= y <= accent_bottom and abs(x - row_center) <= accent_half:
            return accent_rgb
    return base_rgb


def build_updated_kit_rows(
    rows: list[list[int]],
    palette: list[tuple[int, int, int]],
    mapper: PaletteMapper,
    style_row: dict[str, Any],
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
    shorts_rgb = color_rgb(str(style_row.get("shorts") or "white"))

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
                base_rgb = style_color(style_row, x, y, row_min, row_max, shirt_top, shirt_bottom)
                base_rgb = apply_detail_overlays(
                    base_rgb,
                    style_row,
                    x,
                    y,
                    row_min,
                    row_max,
                    row_center,
                    row_width,
                    shirt_top,
                    shirt_bottom,
                )
            else:
                base_rgb = shorts_rgb

            factor = 0.82 + (max(0.0, min(255.0, source_luma)) / 255.0) * 0.35
            if is_edge:
                factor *= 0.90
            if y > shirt_bottom and y > height * 0.78:
                factor *= 0.96
            out[y][x] = mapper.nearest(shade_rgb(base_rgb, factor))
    return out


def team_id_from_record(record: Any) -> int | None:
    match = re.match(r"^EQ96(?P<team_id>\d{4})\.BMP$", str(record.file_name), re.IGNORECASE)
    if not match:
        return None
    return int(match.group("team_id"))


def load_assignments(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assignments = data.get("assignments", [])
    if len(assignments) != 80:
        raise RuntimeError(f"expected 80 assignments, got {len(assignments)}")
    missing = [row["target_display_name"] for row in assignments if row["target_display_name"] not in STYLE_BY_CLUB]
    if missing:
        raise RuntimeError(f"missing style definitions for: {missing}")
    carrier_ids = [int(row["carrier_eq_record_id"]) for row in assignments]
    duplicate_ids = sorted({team_id for team_id in carrier_ids if carrier_ids.count(team_id) > 1})
    if duplicate_ids:
        raise RuntimeError(f"duplicate carrier ids in assignment: {duplicate_ids}")
    return assignments


def styles_by_carrier(assignments: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for row in assignments:
        club = row["target_display_name"]
        style_row = dict(STYLE_BY_CLUB[club])
        style_row["slot"] = int(row["slot"])
        style_row["target_pm99_division"] = row["target_pm99_division"]
        style_row["target_club_key"] = row["target_club_key"]
        style_row["carrier_eq_record_id"] = int(row["carrier_eq_record_id"])
        result[int(row["carrier_eq_record_id"])] = style_row
    return result


def patch_archive(
    archive_path: Path,
    output_dir: Path,
    palette: list[tuple[int, int, int]],
    mapper: PaletteMapper,
    styles: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    original_archive = archive_path.read_bytes()
    patched_archive = bytearray(original_archive)
    records = iter_obfuscated_bmp_records(archive_path, file_name_pattern=r"^EQ96\d{4}\.BMP$")
    summaries: list[dict[str, Any]] = []

    for record in records:
        team_id = team_id_from_record(record)
        if team_id not in styles:
            continue
        style_row = styles[int(team_id)]
        original_rows = record_to_top_down_indices(record)
        updated_rows = build_updated_kit_rows(original_rows, palette, mapper, style_row)
        updated_bitmap = top_down_indices_to_raw(record, updated_rows)
        if len(updated_bitmap) != int(record.bitmap_length):
            raise RuntimeError(f"{archive_path.name}/{record.file_name}: bitmap length drift")
        start = int(record.bitmap_offset)
        end = start + int(record.bitmap_length)
        patched_archive[start:end] = updated_bitmap

        if archive_path.name == "MINIESC.PKF":
            image = render_rows(updated_rows, palette, scale=4, mask_zero=True)
            bg = Image.new("RGB", image.size, (236, 236, 236))
            bg.paste(image, (0, 0), image)
            safe_name = str(style_row["name"]).replace("/", "_").replace(" ", "_")
            bg.save(output_dir / "per_team_miniesc" / f"{int(team_id):04d}_{safe_name}.png")

        summaries.append(
            {
                "archive": str(archive_path),
                "archive_name": archive_path.name,
                "team_id": int(team_id),
                "target_name": style_row["name"],
                "slot": style_row["slot"],
                "file_name": record.file_name,
                "record_offset": int(record.record_offset),
                "bitmap_offset": int(record.bitmap_offset),
                "bitmap_length": int(record.bitmap_length),
                "width": int(record.width),
                "height": int(record.height),
                "bitmap_sha256_before": sha256_bytes(record.raw_bitmap),
                "bitmap_sha256_after": sha256_bytes(updated_bitmap),
            }
        )

    archive_path.write_bytes(bytes(patched_archive))
    reread = iter_obfuscated_bmp_records(archive_path, file_name_pattern=r"^EQ96\d{4}\.BMP$")
    reread_by_file = {record.file_name.upper(): record for record in reread}
    for summary in summaries:
        reread_record = reread_by_file.get(str(summary["file_name"]).upper())
        if reread_record is None:
            raise RuntimeError(f"{archive_path.name}/{summary['file_name']}: missing after write")
        if sha256_bytes(reread_record.raw_bitmap) != summary["bitmap_sha256_after"]:
            raise RuntimeError(f"{archive_path.name}/{summary['file_name']}: post-write verification failed")

    for summary in summaries:
        summary["archive_sha256_before"] = sha256_bytes(original_archive)
        summary["archive_sha256_after"] = sha256_bytes(bytes(patched_archive))
    return summaries


def build_contact_sheet(
    game_root: Path,
    output_path: Path,
    palette: list[tuple[int, int, int]],
    assignments: list[dict[str, Any]],
    styles: dict[int, dict[str, Any]],
) -> None:
    records = iter_obfuscated_bmp_records(game_root / "DBDAT" / "MINIESC.PKF", file_name_pattern=r"^EQ96\d{4}\.BMP$")
    record_by_team = {team_id_from_record(record): record for record in records}
    columns = 8
    kit_scale = 3
    cell_width = 176
    cell_height = 244
    rows_count = math.ceil(len(assignments) / columns)
    sheet = Image.new("RGB", (columns * cell_width, rows_count * cell_height), (224, 224, 218))
    draw = ImageDraw.Draw(sheet)

    for index, assignment in enumerate(assignments):
        team_id = int(assignment["carrier_eq_record_id"])
        style_row = styles[team_id]
        col = index % columns
        row = index // columns
        x0 = col * cell_width
        y0 = row * cell_height
        draw.rectangle((x0, y0, x0 + cell_width - 1, y0 + cell_height - 1), outline=(184, 184, 176))
        label = f"{int(assignment['slot']):02d} EQ{team_id:04d}"
        draw.text((x0 + 8, y0 + 8), label, fill=(20, 20, 20))
        draw.text((x0 + 8, y0 + 22), str(style_row["name"])[:24], fill=(20, 20, 20))
        record = record_by_team.get(team_id)
        if record is None:
            draw.text((x0 + 8, y0 + 42), "missing MINIESC", fill=(160, 0, 0))
            continue
        kit_rows = record_to_top_down_indices(record)
        kit_image = render_rows(kit_rows, palette, scale=kit_scale, mask_zero=True)
        bg = Image.new("RGB", kit_image.size, (236, 236, 236))
        bg.paste(kit_image, (0, 0), kit_image)
        sheet.paste(bg, (x0 + (cell_width - bg.width) // 2, y0 + 48))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)


def write_gallery(
    output_path: Path,
    assignments: list[dict[str, Any]],
    styles: dict[int, dict[str, Any]],
) -> None:
    cards: list[str] = []
    for row in assignments:
        team_id = int(row["carrier_eq_record_id"])
        style_row = styles[team_id]
        safe_name = str(style_row["name"]).replace("/", "_").replace(" ", "_")
        rel = f"per_team_miniesc/{team_id:04d}_{safe_name}.png"
        cards.append(
            "<figure>"
            f'<img src="{rel}" alt="{style_row["name"]} kit">'
            f"<figcaption><strong>{int(row['slot']):02d}. {style_row['name']}</strong>"
            f"<span>EQ{team_id:04d} - {row['target_pm99_division']}</span></figcaption>"
            "</figure>"
        )
    css = """
body{margin:0;font:14px/1.4 system-ui,sans-serif;color:#1b232a;background:#f7f8f5}
header{padding:24px 28px;background:#fff;border-bottom:1px solid #d8ddd7}
h1{margin:0 0 8px;font-size:26px}
p{margin:0;color:#59636a;max-width:980px}
main{display:grid;grid-template-columns:repeat(auto-fill,minmax(128px,1fr));gap:12px;padding:18px}
figure{margin:0;background:#fff;border:1px solid #d8ddd7;padding:8px;display:grid;justify-items:center;gap:6px}
img{width:96px;height:128px;object-fit:contain;image-rendering:pixelated;background:#ecece8}
figcaption{display:grid;gap:2px;text-align:center;font-size:12px}
span{color:#667078}
"""
    html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>English-80 Reference Kits V2</title><style>{css}</style></head><body>"
        "<header><h1>English-80 Reference Kits V2</h1>"
        "<p>PM99-safe 8-bit kit approximations in modern assignment order. "
        "References are league kit pages; artwork is manually encoded for PM99 scale.</p></header>"
        f"<main>{''.join(cards)}</main></body></html>"
    )
    output_path.write_text(html, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game-root", required=True)
    parser.add_argument("--assignment-path", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    game_root = Path(args.game_root).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "per_team_miniesc").mkdir(parents=True, exist_ok=True)
    assignments = load_assignments(Path(args.assignment_path).resolve())
    styles = styles_by_carrier(assignments)
    palette = load_dat_palette(game_root)
    mapper = PaletteMapper(palette)

    patched: list[dict[str, Any]] = []
    for archive_name in ARCHIVES:
        archive_path = game_root / "DBDAT" / archive_name
        if not archive_path.is_file():
            raise FileNotFoundError(f"missing archive: {archive_path}")
        patched.extend(patch_archive(archive_path, output_dir, palette, mapper, styles))

    contact_sheet = output_dir / "english80_reference_home_kits_v2_contact_sheet.png"
    build_contact_sheet(game_root, contact_sheet, palette, assignments, styles)
    gallery = output_dir / "english80_reference_home_kits_v2_gallery.html"
    write_gallery(gallery, assignments, styles)

    patched_counts: dict[str, int] = {}
    for row in patched:
        archive = str(row["archive_name"])
        patched_counts[archive] = patched_counts.get(archive, 0) + 1

    patched_miniesc_ids = sorted({int(row["team_id"]) for row in patched if row["archive_name"] == "MINIESC.PKF"})
    expected_ids = sorted(styles)
    missing_miniesc_ids = sorted(set(expected_ids) - set(patched_miniesc_ids))
    summary = {
        "schema": "pm99-english80-reference-kits-v2",
        "game_root": str(game_root),
        "assignment_path": str(Path(args.assignment_path).resolve()),
        "palette_path": str(game_root / "DAT.PKF"),
        "palette_offset": hex(PALETTE_OFFSET),
        "scope": "modern English-80 assignment carriers",
        "team_count": len(assignments),
        "carrier_id_count": len(styles),
        "patched_record_count": len(patched),
        "patched_counts_by_archive": patched_counts,
        "missing_miniesc_ids": missing_miniesc_ids,
        "source_urls": SOURCE_URLS,
        "contact_sheet": str(contact_sheet),
        "gallery": str(gallery),
        "styles_by_carrier": {str(team_id): styles[team_id] for team_id in sorted(styles)},
        "patched": patched,
    }
    summary_path = output_dir / "english80_reference_home_kits_v2_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
