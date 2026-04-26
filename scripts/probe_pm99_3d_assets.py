#!/usr/bin/env python3
"""Probe PM99 executable and SIMULDAT assets for 3D-engine evidence.

The script is intentionally read-only. It reports facts from a local game/ISO
copy without extracting or writing proprietary payloads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
from pathlib import Path
from typing import Any


TERMS = (
    b"DirectDraw",
    b"Direct3D",
    b"d3d",
    b"OpenGL",
    b"Glide",
    b"3D ENGINE",
    b"HARDWARE OPTIONS",
    b"BILINEAR FILTER",
    b"GOURAUD SHADING",
    b"TEXTURES",
    b"GRAPHICS QUALITY",
    b"PLAYERS",
    b"BACK NUMBERS",
    b"ANIMATIONS",
    b"SHADOWS",
    b"GRASS",
    b"CAMERAS",
    b"DURATION OF MATCH",
    b"RESOLUTION",
    b"simuldat",
    b"Modelos",
    b"Estadios",
)


def sha1_short(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:12]


def entropy(sample: bytes) -> float:
    if not sample:
        return 0.0
    counts = [0] * 256
    for byte in sample:
        counts[byte] += 1
    total = len(sample)
    return -sum((count / total) * math.log2(count / total) for count in counts if count)


class PEImage:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = path.read_bytes()
        e_lfanew = struct.unpack_from("<I", self.data, 0x3C)[0]
        section_count = struct.unpack_from("<H", self.data, e_lfanew + 6)[0]
        optional_size = struct.unpack_from("<H", self.data, e_lfanew + 20)[0]
        optional_off = e_lfanew + 24
        self.image_base = struct.unpack_from("<I", self.data, optional_off + 28)[0]
        section_off = optional_off + optional_size
        self.sections: list[dict[str, Any]] = []
        for index in range(section_count):
            off = section_off + index * 40
            name = self.data[off : off + 8].split(b"\0")[0].decode("ascii", "replace")
            virtual_size, virtual_address, raw_size, raw_pointer = struct.unpack_from(
                "<IIII", self.data, off + 8
            )
            self.sections.append(
                {
                    "name": name,
                    "virtual_address": virtual_address,
                    "virtual_size": virtual_size,
                    "raw_size": raw_size,
                    "raw_pointer": raw_pointer,
                }
            )

    def offset_to_va(self, file_offset: int) -> int | None:
        for section in self.sections:
            raw_pointer = section["raw_pointer"]
            raw_size = section["raw_size"]
            if raw_pointer <= file_offset < raw_pointer + raw_size:
                return (
                    self.image_base
                    + section["virtual_address"]
                    + (file_offset - raw_pointer)
                )
        return None

    def search_terms(self) -> dict[str, list[int]]:
        results: dict[str, list[int]] = {}
        for term in TERMS:
            hits: list[int] = []
            flags = re.IGNORECASE if term.isalpha() else 0
            for match in re.finditer(re.escape(term), self.data, flags):
                va = self.offset_to_va(match.start())
                if va is not None:
                    hits.append(va)
            results[term.decode("latin1")] = hits[:50]
        return results


def scan_bmps(data: bytes, *, limit: int = 50) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    offset = 0
    while True:
        offset = data.find(b"BM", offset)
        if offset < 0:
            break
        if offset + 54 <= len(data):
            size = struct.unpack_from("<I", data, offset + 2)[0]
            data_offset = struct.unpack_from("<I", data, offset + 10)[0]
            dib_size = struct.unpack_from("<I", data, offset + 14)[0]
            if 0 < size <= len(data) - offset and 14 <= data_offset <= size and dib_size in (
                12,
                40,
                108,
                124,
            ):
                entry: dict[str, Any] = {
                    "offset": offset,
                    "size": size,
                    "data_offset": data_offset,
                    "dib_size": dib_size,
                }
                if dib_size == 40 and offset + 30 <= len(data):
                    width, height = struct.unpack_from("<ii", data, offset + 18)
                    bpp = struct.unpack_from("<H", data, offset + 28)[0]
                    entry.update({"width": width, "height": height, "bpp": bpp})
                hits.append(entry)
                if len(hits) >= limit:
                    break
        offset += 2
    return hits


def scan_riff(data: bytes, *, limit: int = 50) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    offset = 0
    while True:
        offset = data.find(b"RIFF", offset)
        if offset < 0:
            break
        if offset + 12 <= len(data):
            size = struct.unpack_from("<I", data, offset + 4)[0]
            riff_type = data[offset + 8 : offset + 12]
            if 0 < size <= len(data) - offset:
                hits.append(
                    {
                        "offset": offset,
                        "size": size,
                        "type": riff_type.decode("latin1", "replace"),
                    }
                )
                if len(hits) >= limit:
                    break
        offset += 4
    return hits


def file_summary(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    sample = data[: min(len(data), 1024 * 1024)]
    return {
        "path": str(path),
        "size": len(data),
        "sha1": sha1_short(data),
        "head16": data[:16].hex(),
        "entropy_first_1m": round(entropy(sample), 3),
        "zero_ratio_first_1m": round(sample.count(0) / len(sample), 5) if sample else 0,
        "bmp_hits": scan_bmps(data, limit=20),
        "riff_hits": scan_riff(data, limit=20),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--game-root",
        type=Path,
        default=Path(".local/iso"),
        help="Local PM99 game/ISO root to inspect.",
    )
    args = parser.parse_args()

    root = args.game_root
    exe_path = root / "MANAGPRE.EXE"
    simuldat = root / "Simuldat"
    if not exe_path.exists():
        raise SystemExit(f"MANAGPRE.EXE not found under {root}")
    if not simuldat.exists():
        raise SystemExit(f"Simuldat directory not found under {root}")

    pe = PEImage(exe_path)
    simuldat_files = sorted(path for path in simuldat.rglob("*") if path.is_file())
    key_files = [
        simuldat / "Modelos.pkf",
        simuldat / "Camaras.pkf",
        simuldat / "Cespedes.pkf",
        simuldat / "Texturas" / "OTROS.pkf",
        simuldat / "Texturas" / "CARAS.pkf",
        simuldat / "SIMULPCF6.PAL",
    ]
    report = {
        "game_root": str(root),
        "exe": {
            "path": str(exe_path),
            "size": exe_path.stat().st_size,
            "sha1": sha1_short(exe_path.read_bytes()),
            "image_base": pe.image_base,
            "sections": pe.sections,
            "term_hits": pe.search_terms(),
        },
        "simuldat": {
            "file_count": len(simuldat_files),
            "total_bytes": sum(path.stat().st_size for path in simuldat_files),
            "extension_counts": {
                suffix or "<none>": sum(
                    1 for path in simuldat_files if (path.suffix.lower() or "<none>") == suffix
                )
                for suffix in sorted({path.suffix.lower() or "<none>" for path in simuldat_files})
            },
            "key_files": [file_summary(path) for path in key_files if path.exists()],
        },
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
