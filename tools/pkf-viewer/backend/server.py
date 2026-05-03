"""Local API for the standalone SIMULDAT PKF viewer."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import struct
from threading import Lock
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from .pkf_parser import PkfFile, palette_colors, parse_pkf_file, record_payload_bytes


REPO_ROOT = Path(__file__).resolve().parents[3]
RUNLOG_ROOT = Path(
    os.environ.get("PM99_RUNLOG_ROOT", REPO_ROOT / ".local" / "runlogs" / "pm99_runner")
).expanduser().resolve()
MENU_ASSET_SOURCES: tuple[dict[str, str], ...] = (
    {
        "path": "RC_DBASE.PKF",
        "title": "Resource Database UI",
        "description": "Large resource archive with full-screen backgrounds, loading art, trophies, media panels, and interface sprites.",
    },
    {
        "path": "Recursos.pkf",
        "title": "Root UI Backgrounds",
        "description": "Full-screen management backgrounds and wide interface strips loaded from the root resources archive.",
    },
    {
        "path": "Simuldat/menus.pkf",
        "title": "SIMULDAT Menu Controls",
        "description": "Menu strips, button states, progress widgets, and small control graphics used by in-game screens.",
    },
    {
        "path": "Img.pkf",
        "title": "Root Icons",
        "description": "Small root-level interface icons and pointer-sized controls.",
    },
    {
        "path": "Simuldat/Iconos.pkf",
        "title": "SIMULDAT Icons",
        "description": "Small repeated interface icon records from SIMULDAT.",
    },
    {
        "path": "Simuldat/Texturas/OTROS.pkf",
        "title": "Misc UI Texture Candidates",
        "description": "Miscellaneous 2D texture records seen in menu/contact-sheet review; useful for separating interface art from match textures.",
    },
    {
        "path": "dat.pkf",
        "title": "Root Layout Strips",
        "description": "Root-level layout panels and strip graphics that are not in the named menu archives.",
    },
)

RUNTIME_MENU_LABEL_KEYWORDS: tuple[str, ...] = (
    "dashboard",
    "results",
    "league",
    "fixtures",
    "transfers",
    "staff",
    "squad",
    "line_up",
    "tactics",
    "opponent",
    "finance",
    "board_room",
    "ground",
    "match",
    "lineup_warning",
    "halftime",
    "fulltime",
    "startseason",
    "championship",
    "draw",
    "competition",
    "pmshield",
    "managers",
    "players",
    "manager_league",
    "manager_double",
    "continue_visible",
    "select_division",
    "pick_stoke",
    "continue_team",
    "continue_after_rivals",
    "preseason",
)

RUNTIME_MENU_SCREEN_NAMES: tuple[str, ...] = (
    "club_dashboard_screen",
    "results_screen",
    "league_tables_screen",
    "fixtures_screen",
    "transfer_market_screen",
    "staff_screen",
    "squad_management_screen",
    "lineup_screen",
    "tactics_screen",
    "opponent_screen",
    "finance_screen",
    "board_room_screen",
    "ground_screen",
    "match_options_screen",
    "match_intro_screen",
    "match_halftime_screen",
    "full_time_screen",
    "lineup_warning_modal",
    "championships_info_screen",
    "draw_screen",
    "competition_round_screen",
    "start_of_season_screen",
    "pm_shield_champion_modal",
    "managers_of_month_modal",
    "players_of_month_modal",
)
INDEXED_PALETTE_CACHE: dict[str, tuple[str, list[tuple[int, int, int]]]] = {}
EMBEDDED_BMP_PALETTE_CACHE: dict[tuple[str, int, int], list[tuple[int, int, int]] | None] = {}
INFERRED_BMP_PALETTE_CACHE: dict[tuple[str, int, int], tuple[str, list[tuple[int, int, int]]] | None] = {}


def annotate_duplicate_payloads(files: list[PkfFile]) -> list[PkfFile]:
    counts: Counter[str] = Counter()
    for file in files:
        for table in file.tables:
            for record in table.records:
                counts[record.payload.sha256_16] += 1

    annotated: list[PkfFile] = []
    for file in files:
        tables = []
        for table in file.tables:
            records = []
            for record in table.records:
                duplicate_count = counts[record.payload.sha256_16]
                payload = replace(
                    record.payload,
                    duplicate_payload_count=duplicate_count if duplicate_count > 1 else None,
                )
                records.append(replace(record, payload=payload))
            tables.append(replace(table, records=records))
        annotated.append(replace(file, tables=tables))
    return annotated


def default_simuldat_root() -> Path:
    env_root = os.environ.get("PM99_SIMULDAT_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    return (REPO_ROOT / ".local" / "iso" / "Simuldat").resolve()


class PkfRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = Lock()
        self._files: list[PkfFile] = []
        self._paths: list[Path] = []
        self._loaded = False
        self._last_error: str | None = None

    def refresh(self) -> None:
        with self._lock:
            INDEXED_PALETTE_CACHE.clear()
            EMBEDDED_BMP_PALETTE_CACHE.clear()
            INFERRED_BMP_PALETTE_CACHE.clear()
            self._files = []
            self._paths = []
            self._last_error = None
            if not self.root.exists():
                self._loaded = True
                self._last_error = f"SIMULDAT root not found: {self.root}"
                return
            paths = sorted(path for path in self.root.rglob("*") if path.is_file() and path.suffix.lower() == ".pkf")
            for path in paths:
                self._files.append(parse_pkf_file(path, root=self.root))
                self._paths.append(path)
            self._files = annotate_duplicate_payloads(self._files)
            self._loaded = True

    def ensure_loaded(self) -> None:
        if not self._loaded:
            self.refresh()

    def summary(self) -> dict[str, object]:
        self.ensure_loaded()
        payload_kind_counts: dict[str, int] = {}
        p3d_family_counts: dict[str, int] = {}
        for file in self._files:
            for kind, count in file.payload_kind_counts.items():
                payload_kind_counts[kind] = payload_kind_counts.get(kind, 0) + count
            for family, count in file.p3d_family_counts.items():
                p3d_family_counts[family] = p3d_family_counts.get(family, 0) + count
        return {
            "root": str(self.root),
            "exists": self.root.exists(),
            "error": self._last_error,
            "pkf_count": len(self._files),
            "total_bytes": sum(file.size for file in self._files),
            "table_count": sum(file.selected_table_count for file in self._files),
            "entry_count": sum(file.selected_entry_count for file in self._files),
            "payload_kind_counts": dict(sorted(payload_kind_counts.items())),
            "p3d_family_counts": dict(sorted(p3d_family_counts.items())),
        }

    def list_files(self) -> list[dict[str, object]]:
        self.ensure_loaded()
        return [
            {
                "id": index,
                "relative_path": file.relative_path,
                "size": file.size,
                "size_hex": file.size_hex,
                "selected_table_count": file.selected_table_count,
                "selected_entry_count": file.selected_entry_count,
                "indexed_payload_coverage_ratio": file.indexed_payload_coverage_ratio,
                "payload_kind_counts": file.payload_kind_counts,
                "bmp_dimension_counts": file.bmp_dimension_counts,
                "p3d_family_counts": file.p3d_family_counts,
            }
            for index, file in enumerate(self._files)
        ]

    def get_file(self, pkf_id: int) -> PkfFile:
        self.ensure_loaded()
        if pkf_id < 0 or pkf_id >= len(self._files):
            raise HTTPException(status_code=404, detail="Unknown PKF id")
        return self._files[pkf_id]

    def get_path(self, pkf_id: int) -> Path:
        self.ensure_loaded()
        if pkf_id < 0 or pkf_id >= len(self._paths):
            raise HTTPException(status_code=404, detail="Unknown PKF id")
        return self._paths[pkf_id]


repository = PkfRepository(default_simuldat_root())
app = FastAPI(title="PM99 SIMULDAT PKF Viewer", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def record_for(file: PkfFile, table_index: int, slot_index: int):
    if table_index < 0 or table_index >= len(file.tables):
        raise HTTPException(status_code=404, detail="Unknown table")
    table = file.tables[table_index]
    if slot_index < 0 or slot_index >= len(table.records):
        raise HTTPException(status_code=404, detail="Unknown record")
    return table.records[slot_index]


def image_dimensions(record) -> tuple[int | None, int | None, int | None]:
    payload = record.payload
    if payload.kind == "BMP":
        return payload.bmp_width, payload.bmp_height, payload.bmp_bpp
    if payload.kind == "GIF":
        return payload.gif_width, payload.gif_height, None
    return None, None, None


def rgb_luminance(r: int, g: int, b: int) -> float:
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def visual_profile_from_rgb(rgb_values: list[tuple[int, int, int]]) -> dict[str, object] | None:
    if not rgb_values:
        return None
    luminance_sum = 0.0
    near_black = 0
    unique_colors: set[tuple[int, int, int]] = set()
    for r, g, b in rgb_values:
        luminance = rgb_luminance(r, g, b)
        luminance_sum += luminance
        if luminance <= 10 or max(r, g, b) <= 12:
            near_black += 1
        unique_colors.add((r, g, b))
    total = len(rgb_values)
    return {
        "mean_luminance": round(luminance_sum / total, 1),
        "near_black_ratio": round(near_black / total, 4),
        "unique_color_count": len(unique_colors),
    }


def read_bmp_palette(
    payload: bytes,
    *,
    header_end: int,
    pixel_offset: int,
    entry_size: int,
    palette_count: int,
) -> list[tuple[int, int, int]]:
    available = max(0, (pixel_offset - header_end) // entry_size)
    count = min(palette_count, available)
    colors = []
    for index in range(count):
        offset = header_end + index * entry_size
        if offset + 3 > len(payload):
            break
        b, g, r = payload[offset : offset + 3]
        colors.append((r, g, b))
    return colors


def bmp_palette_bytes(
    colors: list[tuple[int, int, int]],
    *,
    entry_size: int,
) -> bytes:
    palette_bytes = bytearray()
    for r, g, b in colors:
        palette_bytes.extend((b, g, r) if entry_size == 3 else (b, g, r, 0))
    return bytes(palette_bytes)


def bmp_palette_layout(payload: bytes) -> dict[str, int] | None:
    if len(payload) < 26 or not payload.startswith(b"BM"):
        return None
    try:
        pixel_offset = struct.unpack_from("<I", payload, 10)[0]
        dib_size = struct.unpack_from("<I", payload, 14)[0]
    except struct.error:
        return None
    if dib_size == 12:
        if len(payload) < 26:
            return None
        _width, _height = struct.unpack_from("<HH", payload, 18)
        _planes, bpp = struct.unpack_from("<HH", payload, 22)
        header_end = 14 + dib_size
        entry_size = 3
    elif dib_size >= 40:
        if len(payload) < 54:
            return None
        _width, _signed_height = struct.unpack_from("<ii", payload, 18)
        _planes, bpp = struct.unpack_from("<HH", payload, 26)
        header_end = 14 + dib_size
        entry_size = 4
    else:
        return None
    if bpp not in {1, 4, 8}:
        return None
    available_colors = max(0, (pixel_offset - header_end) // entry_size)
    return {
        "pixel_offset": pixel_offset,
        "header_end": header_end,
        "entry_size": entry_size,
        "required_colors": 1 << bpp,
        "available_colors": available_colors,
    }


def grayscale_palette() -> list[tuple[int, int, int]]:
    return [(index, index, index) for index in range(256)]


def default_indexed_palette() -> tuple[str, list[tuple[int, int, int]]]:
    cache_key = str(repository.root)
    if cache_key in INDEXED_PALETTE_CACHE:
        return INDEXED_PALETTE_CACHE[cache_key]
    candidates = [
        repository.root / "Simuldat" / "SIMULPCF6.PAL",
        repository.root / "SIMULPCF6.PAL",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        colors = palette_colors(path.read_bytes())
        if len(colors) >= 256:
            palette = (
                path.relative_to(repository.root).as_posix(),
                [(color["r"], color["g"], color["b"]) for color in colors[:256]],
            )
            INDEXED_PALETTE_CACHE[cache_key] = palette
            return palette
    palette = ("generated grayscale", grayscale_palette())
    INDEXED_PALETTE_CACHE[cache_key] = palette
    return palette


def embedded_bmp_palette(payload: bytes) -> list[tuple[int, int, int]] | None:
    layout = bmp_palette_layout(payload)
    if layout is None:
        return None
    required_colors = layout["required_colors"]
    if layout["available_colors"] < required_colors:
        return None
    return read_bmp_palette(
        payload,
        header_end=layout["header_end"],
        pixel_offset=layout["pixel_offset"],
        entry_size=layout["entry_size"],
        palette_count=required_colors,
    )


def record_embedded_bmp_palette(pkf_path: Path, record) -> list[tuple[int, int, int]] | None:
    key = (str(pkf_path), record.table_index, record.slot_index)
    if key not in EMBEDDED_BMP_PALETTE_CACHE:
        if record.payload.kind != "BMP":
            EMBEDDED_BMP_PALETTE_CACHE[key] = None
        else:
            EMBEDDED_BMP_PALETTE_CACHE[key] = embedded_bmp_palette(record_payload_bytes(pkf_path, record))
    return EMBEDDED_BMP_PALETTE_CACHE[key]


def nearest_embedded_palette_in_file(file: PkfFile, pkf_path: Path, record) -> tuple[str, list[tuple[int, int, int]]] | None:
    candidates = []
    for table in file.tables:
        for other in table.records:
            if other.payload.kind != "BMP" or (other.table_index == record.table_index and other.slot_index == record.slot_index):
                continue
            palette = record_embedded_bmp_palette(pkf_path, other)
            if not palette:
                continue
            same_table = other.table_index == record.table_index
            candidates.append(
                (
                    0 if same_table else 1,
                    abs(other.slot_index - record.slot_index) if same_table else abs(other.payload_offset - record.payload_offset),
                    0 if other.payload_offset < record.payload_offset else 1,
                    f"inferred from {file.relative_path} table {other.table_index} slot {other.slot_index}",
                    palette,
                )
            )
    if not candidates:
        return None
    _scope, _distance, _direction, label, palette = min(candidates, key=lambda item: item[:3])
    return label, palette


def canonical_resource_palette() -> tuple[str, list[tuple[int, int, int]]] | None:
    repository.ensure_loaded()
    for index, file in enumerate(repository._files):
        if file.relative_path.lower() != "rc_dbase.pkf":
            continue
        pkf_path = repository.get_path(index)
        for table in file.tables:
            for record in table.records:
                palette = record_embedded_bmp_palette(pkf_path, record)
                if palette:
                    return (
                        f"inferred from {file.relative_path} table {record.table_index} slot {record.slot_index}",
                        palette,
                    )
    return None


def inferred_palette_for_record(
    file: PkfFile,
    pkf_path: Path,
    record,
) -> tuple[str, list[tuple[int, int, int]]] | None:
    key = (str(pkf_path), record.table_index, record.slot_index)
    if key in INFERRED_BMP_PALETTE_CACHE:
        return INFERRED_BMP_PALETTE_CACHE[key]
    palette = nearest_embedded_palette_in_file(file, pkf_path, record)
    if palette is None:
        palette = canonical_resource_palette()
    INFERRED_BMP_PALETTE_CACHE[key] = palette
    return palette


def bmp_with_fallback_palette(
    payload: bytes,
    palette_candidate: tuple[str, list[tuple[int, int, int]]] | None = None,
) -> tuple[bytes, str | None]:
    layout = bmp_palette_layout(payload)
    if layout is None:
        return payload, None
    required_colors = layout["required_colors"]
    if layout["available_colors"] >= required_colors:
        return payload, "embedded BMP palette"

    if palette_candidate is None:
        palette_candidate = default_indexed_palette()
    palette_source, fallback_colors = palette_candidate
    header_end = layout["header_end"]
    entry_size = layout["entry_size"]

    embedded_colors = read_bmp_palette(
        payload,
        header_end=header_end,
        pixel_offset=layout["pixel_offset"],
        entry_size=entry_size,
        palette_count=layout["available_colors"],
    )
    colors = list(embedded_colors)
    for index in range(required_colors):
        if index < len(colors):
            continue
        colors.append(fallback_colors[index] if index < len(fallback_colors) else (index, index, index))
    palette_bytes = bmp_palette_bytes(colors[:required_colors], entry_size=entry_size)

    old_pixel_offset = layout["pixel_offset"]
    new_pixel_offset = header_end + len(palette_bytes)
    repaired = bytearray(payload[:header_end])
    repaired.extend(palette_bytes)
    repaired.extend(payload[old_pixel_offset:])
    struct.pack_into("<I", repaired, 2, len(repaired))
    struct.pack_into("<I", repaired, 10, new_pixel_offset)
    if embedded_colors:
        palette_source = f"embedded BMP palette + {palette_source}"
    return bytes(repaired), palette_source


def bmp_visual_profile(payload: bytes) -> dict[str, object] | None:
    if len(payload) < 26 or not payload.startswith(b"BM"):
        return None
    try:
        pixel_offset = struct.unpack_from("<I", payload, 10)[0]
        dib_size = struct.unpack_from("<I", payload, 14)[0]
    except struct.error:
        return None

    if dib_size == 12:
        if len(payload) < 26:
            return None
        width, height = struct.unpack_from("<HH", payload, 18)
        _planes, bpp = struct.unpack_from("<HH", payload, 22)
        header_end = 14 + dib_size
        palette_entry_size = 3
        palette_count = 1 << bpp if bpp <= 8 else 0
    elif dib_size >= 40:
        if len(payload) < 54:
            return None
        width, signed_height = struct.unpack_from("<ii", payload, 18)
        _planes, bpp = struct.unpack_from("<HH", payload, 26)
        compression = struct.unpack_from("<I", payload, 30)[0]
        if compression != 0:
            return None
        height = abs(signed_height)
        header_end = 14 + dib_size
        palette_entry_size = 4
        colors_used = struct.unpack_from("<I", payload, 46)[0] if len(payload) >= 50 else 0
        palette_count = colors_used or (1 << bpp if bpp <= 8 else 0)
    else:
        return None

    if width <= 0 or height <= 0 or pixel_offset >= len(payload) or bpp not in {1, 4, 8, 24, 32}:
        return None

    row_stride = ((width * bpp + 31) // 32) * 4
    rows_end = pixel_offset + row_stride * height
    if rows_end > len(payload):
        return None

    palette = read_bmp_palette(
        payload,
        header_end=header_end,
        pixel_offset=pixel_offset,
        entry_size=palette_entry_size,
        palette_count=palette_count,
    )
    if bpp <= 8 and len(palette) < min(1 << bpp, palette_count):
        return None

    pixels: list[tuple[int, int, int]] = []
    for row_index in range(height):
        row = payload[pixel_offset + row_index * row_stride : pixel_offset + (row_index + 1) * row_stride]
        if bpp == 1:
            for x in range(width):
                palette_index = (row[x // 8] >> (7 - (x % 8))) & 1
                pixels.append(palette[palette_index])
        elif bpp == 4:
            for x in range(width):
                byte = row[x // 2]
                palette_index = byte >> 4 if x % 2 == 0 else byte & 0x0F
                pixels.append(palette[palette_index])
        elif bpp == 8:
            for palette_index in row[:width]:
                pixels.append(palette[palette_index])
        elif bpp == 24:
            for x in range(width):
                b, g, r = row[x * 3 : x * 3 + 3]
                pixels.append((r, g, b))
        elif bpp == 32:
            for x in range(width):
                b, g, r = row[x * 4 : x * 4 + 3]
                pixels.append((r, g, b))
    return visual_profile_from_rgb(pixels)


def read_gif_color_table(payload: bytes, offset: int, color_count: int) -> tuple[list[tuple[int, int, int]], int] | None:
    byte_count = color_count * 3
    if offset + byte_count > len(payload):
        return None
    colors = [
        tuple(payload[offset + index * 3 : offset + index * 3 + 3])
        for index in range(color_count)
    ]
    return colors, offset + byte_count


def read_gif_sub_blocks(payload: bytes, offset: int) -> tuple[bytes, int] | None:
    chunks = bytearray()
    while offset < len(payload):
        size = payload[offset]
        offset += 1
        if size == 0:
            return bytes(chunks), offset
        if offset + size > len(payload):
            return None
        chunks.extend(payload[offset : offset + size])
        offset += size
    return None


def gif_lzw_indices(data: bytes, min_code_size: int, pixel_limit: int) -> list[int]:
    clear_code = 1 << min_code_size
    end_code = clear_code + 1
    bit_offset = 0

    def read_code(code_size: int) -> int | None:
        nonlocal bit_offset
        if bit_offset + code_size > len(data) * 8:
            return None
        code = 0
        for bit_index in range(code_size):
            absolute_bit = bit_offset + bit_index
            if data[absolute_bit // 8] & (1 << (absolute_bit % 8)):
                code |= 1 << bit_index
        bit_offset += code_size
        return code

    def reset_dictionary() -> tuple[dict[int, bytes], int, int]:
        dictionary = {index: bytes([index]) for index in range(clear_code)}
        return dictionary, end_code + 1, min_code_size + 1

    dictionary, next_code, code_size = reset_dictionary()
    output = bytearray()
    previous: bytes | None = None
    while len(output) < pixel_limit:
        code = read_code(code_size)
        if code is None:
            break
        if code == clear_code:
            dictionary, next_code, code_size = reset_dictionary()
            previous = None
            continue
        if code == end_code:
            break
        if code in dictionary:
            entry = dictionary[code]
        elif code == next_code and previous is not None:
            entry = previous + previous[:1]
        else:
            break
        output.extend(entry)
        if previous is not None and next_code < 4096:
            dictionary[next_code] = previous + entry[:1]
            next_code += 1
            if next_code == (1 << code_size) and code_size < 12:
                code_size += 1
        previous = entry
    return list(output[:pixel_limit])


def gif_visual_profile(payload: bytes) -> dict[str, object] | None:
    if len(payload) < 13 or payload[:3] != b"GIF":
        return None
    width, height = struct.unpack_from("<HH", payload, 6)
    packed = payload[10]
    offset = 13
    global_palette: list[tuple[int, int, int]] = []
    if packed & 0x80:
        table_size = 2 << (packed & 0x07)
        table = read_gif_color_table(payload, offset, table_size)
        if table is None:
            return None
        global_palette, offset = table

    transparent_index: int | None = None
    while offset < len(payload):
        marker = payload[offset]
        offset += 1
        if marker == 0x3B:
            return None
        if marker == 0x21:
            if offset >= len(payload):
                return None
            label = payload[offset]
            offset += 1
            if label == 0xF9 and offset < len(payload):
                block_size = payload[offset]
                offset += 1
                if offset + block_size > len(payload):
                    return None
                block = payload[offset : offset + block_size]
                offset += block_size
                if block_size >= 4 and block[0] & 0x01:
                    transparent_index = block[3]
                if offset < len(payload) and payload[offset] == 0:
                    offset += 1
                continue
            skipped = read_gif_sub_blocks(payload, offset)
            if skipped is None:
                return None
            _data, offset = skipped
            continue
        if marker != 0x2C or offset + 9 > len(payload):
            return None

        _left, _top, frame_width, frame_height, image_packed = struct.unpack_from("<HHHHB", payload, offset)
        offset += 9
        palette = global_palette
        if image_packed & 0x80:
            table_size = 2 << (image_packed & 0x07)
            table = read_gif_color_table(payload, offset, table_size)
            if table is None:
                return None
            palette, offset = table
        if not palette or offset >= len(payload):
            return None
        min_code_size = payload[offset]
        offset += 1
        blocks = read_gif_sub_blocks(payload, offset)
        if blocks is None:
            return None
        data, _offset = blocks
        indices = gif_lzw_indices(data, min_code_size, frame_width * frame_height)
        if not indices and width * height:
            return None
        pixels = [
            palette[index]
            for index in indices
            if index != transparent_index and index < len(palette)
        ]
        if not pixels and indices:
            pixels = [(0, 0, 0)] * len(indices)
        return visual_profile_from_rgb(pixels)
    return None


def image_visual_profile(
    payload: bytes,
    kind: str,
    palette_candidate: tuple[str, list[tuple[int, int, int]]] | None = None,
) -> tuple[dict[str, object] | None, str | None]:
    if kind == "BMP":
        repaired, palette_source = bmp_with_fallback_palette(payload, palette_candidate)
        return bmp_visual_profile(repaired), palette_source
    if kind == "GIF":
        return gif_visual_profile(payload), "embedded GIF palette"
    return None, None


def visual_quality(profile: dict[str, object] | None) -> str:
    if profile is None:
        return "unknown"
    mean_luminance = float(profile["mean_luminance"])
    near_black_ratio = float(profile["near_black_ratio"])
    unique_color_count = int(profile["unique_color_count"])
    if near_black_ratio >= 0.98:
        return "low-information"
    if mean_luminance < 8:
        return "low-information"
    if unique_color_count <= 2 and mean_luminance < 35:
        return "low-information"
    if mean_luminance < 35 or near_black_ratio >= 0.70:
        return "dark-control"
    return "visible"


def menu_asset_role(source_path: str, width: int | None, height: int | None) -> str:
    if width == 640 and height == 480:
        return "screen background"
    if source_path.endswith("RC_DBASE.PKF"):
        return "resource database UI sprite"
    if source_path.endswith("dat.pkf"):
        return "layout strip or panel"
    if width is not None and height is not None and width >= 600 and height <= 100:
        return "wide panel or title strip"
    if source_path.endswith("menus.pkf") and width is not None and height is not None and width >= 120:
        return "button or menu strip"
    if width is not None and height is not None and width <= 64 and height <= 64:
        return "icon or small control"
    return "menu asset"


def menu_record_label(record) -> str:
    width, height, bpp = image_dimensions(record)
    if width is None or height is None:
        return record.payload.kind
    if bpp is None:
        return f"{record.payload.kind} {width}x{height}"
    return f"{record.payload.kind} {width}x{height}x{bpp}"


def menu_source_path(source_path: str, by_path: dict[str, tuple[int, PkfFile]]) -> str | None:
    if source_path in by_path:
        return source_path
    if source_path.startswith("Simuldat/"):
        fallback = source_path.split("/", 1)[1]
        if fallback in by_path:
            return fallback
    return None


ROLE_SORT_ORDER = {
    "screen background": 0,
    "wide panel or title strip": 1,
    "button or menu strip": 2,
    "layout strip or panel": 3,
    "menu asset": 4,
    "resource database UI sprite": 5,
    "icon or small control": 6,
}


def menu_asset_sort_key(asset: dict[str, object]) -> tuple[int, int, int, int, int, int]:
    quality = str(asset.get("visual_quality") or "unknown")
    width = int(asset.get("width") or 0)
    height = int(asset.get("height") or 0)
    area = width * height
    return (
        1 if quality == "low-information" else 0,
        ROLE_SORT_ORDER.get(str(asset.get("role")), 99),
        1 if quality == "dark-control" else 0,
        -area,
        int(asset["table_index"]),
        int(asset["slot_index"]),
    )


def build_menu_asset_groups() -> list[dict[str, object]]:
    repository.ensure_loaded()
    by_path = {file.relative_path: (index, file) for index, file in enumerate(repository._files)}
    groups: list[dict[str, object]] = []
    for source in MENU_ASSET_SOURCES:
        source_path = source["path"]
        resolved_source_path = menu_source_path(source_path, by_path)
        if resolved_source_path is None:
            groups.append({**source, "missing": True, "records": []})
            continue
        indexed = by_path[resolved_source_path]
        pkf_id, file = indexed
        pkf_path = repository.get_path(pkf_id)
        records = []
        for table in file.tables:
            for record in table.records:
                if record.payload.kind not in {"BMP", "GIF"}:
                    continue
                width, height, bpp = image_dimensions(record)
                content = record_payload_bytes(pkf_path, record)
                palette_candidate = (
                    inferred_palette_for_record(file, pkf_path, record)
                    if record.payload.kind == "BMP" and embedded_bmp_palette(content) is None
                    else None
                )
                profile, palette_source = image_visual_profile(
                    content,
                    record.payload.kind,
                    palette_candidate,
                )
                records.append(
                    {
                        "pkf_id": pkf_id,
                        "pkf_path": file.relative_path,
                        "table_index": record.table_index,
                        "slot_index": record.slot_index,
                        "kind": record.payload.kind,
                        "width": width,
                        "height": height,
                        "bpp": bpp,
                        "length": record.length,
                        "length_hex": record.length_hex,
                        "payload_offset_hex": record.payload_offset_hex,
                        "sha256_16": record.payload.sha256_16,
                        "role": menu_asset_role(source_path, width, height),
                        "label": menu_record_label(record),
                        "mean_luminance": profile["mean_luminance"] if profile else None,
                        "near_black_ratio": profile["near_black_ratio"] if profile else None,
                        "unique_color_count": profile["unique_color_count"] if profile else None,
                        "visual_quality": visual_quality(profile),
                        "palette_source": palette_source,
                    }
                )
        records.sort(key=menu_asset_sort_key)
        groups.append({**source, "missing": False, "records": records})
    return groups


def local_runtime_screenshot(summary_path: Path, screenshot: str | None) -> Path | None:
    if not screenshot:
        return None
    screenshot_path = Path(screenshot)
    if screenshot_path.is_absolute() and str(screenshot_path).startswith("/workspace/artifacts/"):
        screenshot_path = summary_path.parent / screenshot_path.relative_to("/workspace/artifacts")
    elif not screenshot_path.is_absolute():
        screenshot_path = summary_path.parent / screenshot_path
    if not screenshot_path.is_file():
        return None
    try:
        screenshot_path.resolve().relative_to(RUNLOG_ROOT)
    except ValueError:
        return None
    return screenshot_path


def runtime_screen_url(path: Path) -> str:
    relative = path.resolve().relative_to(RUNLOG_ROOT)
    return f"/api/menu-atlas/runtime-screen?path={quote(str(relative))}"


def runtime_run_tag(summary_path: Path) -> str:
    return summary_path.parent.name if summary_path.parent.parent == RUNLOG_ROOT else summary_path.parent.parent.name


def runtime_record_from_step(summary_path: Path, step: dict[str, object], *, source: str) -> dict[str, object] | None:
    screenshot_path = local_runtime_screenshot(summary_path, str(step.get("screenshot") or ""))
    if screenshot_path is None:
        return None
    classification = dict(step.get("screen_classification") or {})
    step_spec = dict(step.get("step") or {})
    return {
        "source": source,
        "run_tag": runtime_run_tag(summary_path),
        "label": step_spec.get("label") or screenshot_path.stem,
        "action": step_spec.get("action"),
        "value": step_spec.get("value"),
        "screen": classification.get("screen"),
        "confidence": classification.get("confidence"),
        "reason": classification.get("reason"),
        "image_hash": classification.get("image_hash"),
        "screenshot_url": runtime_screen_url(screenshot_path),
    }


def runtime_record_from_image(
    source_path: Path,
    screenshot: str | None,
    *,
    source: str,
    label: str,
    screen: str | None = None,
) -> dict[str, object] | None:
    screenshot_path = local_runtime_screenshot(source_path, screenshot)
    if screenshot_path is None:
        return None
    return {
        "source": source,
        "run_tag": source_path.parent.name,
        "label": label,
        "action": None,
        "value": None,
        "screen": screen,
        "confidence": None,
        "reason": None,
        "image_hash": None,
        "screenshot_url": runtime_screen_url(screenshot_path),
    }


def is_runtime_menu_record(record: dict[str, object]) -> bool:
    label = str(record.get("label") or "").lower()
    screen = str(record.get("screen") or "").lower()
    if screen in RUNTIME_MENU_SCREEN_NAMES:
        return True
    return any(keyword in label for keyword in RUNTIME_MENU_LABEL_KEYWORDS)


def latest_runtime_screens(limit: int = 240) -> list[dict[str, object]]:
    if not RUNLOG_ROOT.exists():
        return []

    def discovery_sort_key(path: Path) -> tuple[int, float]:
        run_tag = runtime_run_tag(path)
        return (1 if run_tag.startswith("menu_discovery") else 0, path.stat().st_mtime)

    discovery_paths = sorted(
        [*RUNLOG_ROOT.glob("**/summary.json"), *RUNLOG_ROOT.glob("**/selector_discovery.json")],
        key=discovery_sort_key,
        reverse=True,
    )
    screens: list[dict[str, object]] = []
    seen_hashes: set[str] = set()
    for summary_path in discovery_paths:
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        mode = str(summary.get("mode") or summary.get("schema") or summary_path.parent.name)
        if summary_path.name == "selector_discovery.json":
            mode = "selector-discovery"
        step_records = list(summary.get("steps") or []) + list(summary.get("setup_steps") or [])
        for step in step_records:
            if not isinstance(step, dict):
                continue
            record = runtime_record_from_step(summary_path, step, source=mode)
            if record is None:
                continue
            if not is_runtime_menu_record(record):
                continue
            dedupe_key = str(record.get("image_hash") or record.get("screenshot_url"))
            if dedupe_key in seen_hashes:
                continue
            seen_hashes.add(dedupe_key)
            screens.append(record)
            if len(screens) >= limit:
                return screens
        for division in list(summary.get("divisions") or []):
            if not isinstance(division, dict):
                continue
            division_key = str(division.get("division_key") or "division")
            selection_record = runtime_record_from_image(
                summary_path,
                str(division.get("selection_screenshot") or ""),
                source=mode,
                label=f"{division_key} selected",
                screen="name_team_screen",
            )
            if selection_record is not None:
                if not is_runtime_menu_record(selection_record):
                    continue
                dedupe_key = str(selection_record.get("screenshot_url"))
                if dedupe_key not in seen_hashes:
                    seen_hashes.add(dedupe_key)
                    screens.append(selection_record)
                    if len(screens) >= limit:
                        return screens
            for team in list(division.get("teams") or []):
                if not isinstance(team, dict):
                    continue
                team_label = str(team.get("ocr_normalized") or team.get("text") or "team").strip()
                record = runtime_record_from_image(
                    summary_path,
                    str(team.get("screenshot") or ""),
                    source=mode,
                    label=f"{division_key} team {team.get('row_index')}: {team_label}",
                    screen="name_team_screen",
                )
                if record is None:
                    continue
                if not is_runtime_menu_record(record):
                    continue
                dedupe_key = str(record.get("screenshot_url"))
                if dedupe_key in seen_hashes:
                    continue
                seen_hashes.add(dedupe_key)
                screens.append(record)
                if len(screens) >= limit:
                    return screens
    return screens


@app.get("/api/summary")
def get_summary() -> dict[str, object]:
    return repository.summary()


@app.post("/api/refresh")
def refresh() -> dict[str, object]:
    repository.refresh()
    return repository.summary()


@app.get("/api/pkfs")
def list_pkfs() -> list[dict[str, object]]:
    return repository.list_files()


@app.get("/api/pkfs/{pkf_id}")
def get_pkf(pkf_id: int) -> dict[str, object]:
    payload = asdict(repository.get_file(pkf_id))
    payload.pop("path", None)
    return payload


@app.get("/api/pkfs/{pkf_id}/records/{table_index}/{slot_index}/preview")
def preview_record(pkf_id: int, table_index: int, slot_index: int) -> Response:
    file = repository.get_file(pkf_id)
    record = record_for(file, table_index, slot_index)
    content = record_payload_bytes(repository.get_path(pkf_id), record)
    headers: dict[str, str] = {}
    if record.payload.kind == "BMP":
        media_type = "image/bmp"
        pkf_path = repository.get_path(pkf_id)
        palette_candidate = (
            inferred_palette_for_record(file, pkf_path, record)
            if embedded_bmp_palette(content) is None
            else None
        )
        content, palette_source = bmp_with_fallback_palette(content, palette_candidate)
        if palette_source:
            headers["X-PM99-Palette-Source"] = palette_source
    elif record.payload.kind == "GIF":
        media_type = "image/gif"
    else:
        raise HTTPException(status_code=404, detail="Record is not a previewable image")
    return Response(content=content, media_type=media_type, headers=headers)


@app.get("/api/pkfs/{pkf_id}/records/{table_index}/{slot_index}/palette")
def get_palette(pkf_id: int, table_index: int, slot_index: int) -> dict[str, object]:
    file = repository.get_file(pkf_id)
    record = record_for(file, table_index, slot_index)
    if record.payload.kind != "RIFF/PAL":
        raise HTTPException(status_code=404, detail="Record is not a RIFF/PAL palette")
    payload = record_payload_bytes(repository.get_path(pkf_id), record)
    return {"colors": palette_colors(payload)}


@app.get("/api/menu-atlas")
def get_menu_atlas(include_runtime: bool = False) -> dict[str, object]:
    groups = build_menu_asset_groups()
    return {
        "asset_groups": groups,
        "asset_count": sum(len(group["records"]) for group in groups),
        "runtime_root": str(RUNLOG_ROOT),
        "runtime_screens": latest_runtime_screens(limit=360) if include_runtime else [],
    }


@app.get("/api/menu-atlas/runtime-screen")
def get_runtime_screen(path: str) -> Response:
    try:
        screen_path = (RUNLOG_ROOT / path).resolve()
        screen_path.relative_to(RUNLOG_ROOT)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Unknown runtime screen") from exc
    if not screen_path.is_file() or screen_path.suffix.lower() != ".png":
        raise HTTPException(status_code=404, detail="Unknown runtime screen")
    return Response(content=screen_path.read_bytes(), media_type="image/png")
