#!/usr/bin/env python3
"""Scan PM99 data files for embedded zlib/DMZ1 compressed streams.

This is intentionally read-only. It records metadata about candidate streams
without writing or dumping decompressed proprietary payloads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
import sys
import time
from typing import Iterable
import zlib


DEFAULT_SUFFIXES = {
    ".fdi",
    ".gbf",
    ".grf",
    ".pkf",
    ".ps",
    ".tbl",
    ".dat",
    ".pal",
    ".bmp",
    ".p3d",
}

STRICT_ZLIB_HEADERS = {
    (0x78, 0x01),
    (0x78, 0x5E),
    (0x78, 0x9C),
    (0x78, 0xDA),
}


@dataclass(frozen=True)
class StreamHit:
    path: str
    family: str
    file_size: int
    offset: int
    offset_hex: str
    header: str
    compressed_consumed: int | None
    unused_after_stream: int | None
    output_size: int
    output_truncated: bool
    input_window_size: int
    output_sha256_16: str
    output_kind: str
    output_prefix_hex: str


@dataclass(frozen=True)
class DMZ1Hit:
    path: str
    family: str
    file_size: int
    offset: int
    offset_hex: str
    declared_output_size: int
    compressed_consumed: int
    unused_after_stream: int
    output_sha256_16: str
    output_kind: str
    output_prefix_hex: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan PM99 data trees for zlib-wrapped and DMZ1 raw-deflate streams."
    )
    parser.add_argument(
        "roots",
        nargs="+",
        type=Path,
        help="Files or directories to scan.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON output path for the full metadata report.",
    )
    parser.add_argument(
        "--suffix",
        action="append",
        default=[],
        help=(
            "File suffix to include, repeatable. Defaults to common PM99 data "
            "suffixes. Use --all-files to ignore suffix filtering."
        ),
    )
    parser.add_argument(
        "--all-files",
        action="store_true",
        help="Scan every regular file under the supplied roots.",
    )
    parser.add_argument(
        "--header-mode",
        choices=("strict", "valid"),
        default="strict",
        help=(
            "strict scans common zlib headers 78 01/5e/9c/da. valid scans any "
            "RFC1950-looking header and is much slower on noisy binary blobs."
        ),
    )
    parser.add_argument(
        "--min-output-size",
        type=int,
        default=16,
        help="Minimum decompressed byte count for a successful stream hit.",
    )
    parser.add_argument(
        "--max-output-size",
        type=int,
        default=128 * 1024 * 1024,
        help="Maximum bytes to inflate per stream before marking it truncated.",
    )
    parser.add_argument(
        "--max-input-size",
        type=int,
        default=256 * 1024,
        help=(
            "Maximum compressed bytes to feed per candidate. This keeps false "
            "zlib headers inside large binary blobs from making the scan hang."
        ),
    )
    parser.add_argument(
        "--max-streams-per-file",
        type=int,
        default=128,
        help="Stop scanning a file after this many successful streams.",
    )
    parser.add_argument(
        "--no-dmz1",
        action="store_true",
        help="Do not scan PM99's custom DMZ1 raw-deflate wrapper.",
    )
    return parser.parse_args()


def normalize_suffixes(values: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for value in values:
        suffix = value.strip().lower()
        if not suffix:
            continue
        if not suffix.startswith("."):
            suffix = "." + suffix
        out.add(suffix)
    return out or set(DEFAULT_SUFFIXES)


def iter_files(roots: Iterable[Path], *, suffixes: set[str], all_files: bool) -> list[Path]:
    paths: list[Path] = []
    for root in roots:
        if not root.exists():
            print(f"warning: missing root: {root}", file=sys.stderr)
            continue
        if root.is_file():
            candidates = [root]
        else:
            candidates = sorted(path for path in root.rglob("*") if path.is_file())
        for path in candidates:
            if all_files or path.suffix.lower() in suffixes:
                paths.append(path)
    return sorted(dict.fromkeys(paths))


def is_valid_zlib_header(data: bytes, offset: int, *, mode: str) -> bool:
    if offset + 2 > len(data):
        return False
    cmf = data[offset]
    flg = data[offset + 1]
    if mode == "strict":
        return (cmf, flg) in STRICT_ZLIB_HEADERS
    if (cmf & 0x0F) != 8:
        return False
    if (cmf >> 4) > 7:
        return False
    return ((cmf << 8) + flg) % 31 == 0


def iter_candidate_offsets(data: bytes, *, mode: str) -> Iterable[int]:
    if mode == "strict":
        seen: set[int] = set()
        for cmf, flg in STRICT_ZLIB_HEADERS:
            needle = bytes((cmf, flg))
            start = 0
            while True:
                offset = data.find(needle, start)
                if offset < 0:
                    break
                if offset not in seen:
                    seen.add(offset)
                    yield offset
                start = offset + 1
        return

    for offset in range(0, max(0, len(data) - 1)):
        if is_valid_zlib_header(data, offset, mode=mode):
            yield offset


def classify_family(path: Path) -> str:
    lowered_parts = [part.lower() for part in path.parts]
    if "dbdat" in lowered_parts or "dbdat" in "".join(lowered_parts):
        return "DBDAT"
    if "simuldat" in lowered_parts:
        if "estadios" in lowered_parts:
            return "SIMULDAT/Estadios"
        if "texturas" in lowered_parts:
            return "SIMULDAT/Texturas"
        return "SIMULDAT"
    if "tactics" in lowered_parts:
        return "Tactics"
    return "Other"


def classify_output(blob: bytes) -> str:
    if blob.startswith(b"BM"):
        return "BMP"
    if blob.startswith(b"RIFF") and len(blob) >= 12:
        return f"RIFF/{blob[8:12].decode('ascii', errors='replace')}"
    if blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if blob.startswith(b"GIF87a") or blob.startswith(b"GIF89a"):
        return "GIF"
    if blob.startswith(b"DDS "):
        return "DDS"
    if blob.startswith(b"MThd"):
        return "MIDI"
    if blob[:4] == b"\x00\x00\x01\x00":
        return "ICO"
    printable = sum(1 for byte in blob[:64] if byte in b"\t\r\n" or 32 <= byte <= 126)
    if blob and printable / min(len(blob), 64) >= 0.85:
        return "mostly-ascii"
    return "binary"


def try_inflate(
    data: bytes,
    offset: int,
    *,
    min_output_size: int,
    max_output_size: int,
    max_input_size: int,
) -> tuple[bytes, bool, int | None, int | None] | None:
    obj = zlib.decompressobj()
    input_blob = data[offset : offset + max_input_size]
    try:
        out = obj.decompress(input_blob, max_output_size + 1)
    except zlib.error:
        return None
    if len(out) < min_output_size:
        return None

    truncated = len(out) > max_output_size
    if truncated:
        out = out[:max_output_size]

    if not obj.eof and not truncated:
        return None

    consumed: int | None = None
    unused_after_stream: int | None = None
    if obj.eof:
        consumed = len(input_blob) - len(obj.unused_data)
        unused_after_stream = max(0, len(data) - offset - consumed)

    return out, truncated, consumed, unused_after_stream


def try_inflate_dmz1(
    data: bytes,
    offset: int,
    *,
    declared_output_size: int,
    max_input_size: int,
) -> tuple[bytes, int, int] | None:
    compressed_start = offset + 8
    if compressed_start >= len(data):
        return None
    obj = zlib.decompressobj(wbits=-15)
    input_blob = data[compressed_start : compressed_start + max_input_size]
    try:
        out = obj.decompress(input_blob, declared_output_size + 1)
    except zlib.error:
        return None
    if not obj.eof:
        return None
    if len(out) != declared_output_size:
        return None
    consumed = len(input_blob) - len(obj.unused_data)
    unused_after_stream = max(0, len(data) - compressed_start - consumed)
    return out, consumed, unused_after_stream


def scan_dmz1_blocks(
    path: Path,
    data: bytes,
    *,
    max_output_size: int,
    max_input_size: int,
    max_streams_per_file: int,
) -> tuple[int, list[DMZ1Hit]]:
    family = classify_family(path)
    try:
        display_path = str(path.relative_to(Path.cwd()))
    except ValueError:
        display_path = str(path)

    candidate_count = 0
    hits: list[DMZ1Hit] = []
    start = 0
    while True:
        offset = data.find(b"DMZ1", start)
        if offset < 0:
            break
        start = offset + 1
        candidate_count += 1
        if offset + 8 > len(data):
            continue
        declared_output_size = int.from_bytes(data[offset + 4 : offset + 8], "little")
        if declared_output_size <= 0 or declared_output_size > max_output_size:
            continue
        inflated = try_inflate_dmz1(
            data,
            offset,
            declared_output_size=declared_output_size,
            max_input_size=max_input_size,
        )
        if inflated is None:
            continue
        out, consumed, unused_after_stream = inflated
        hits.append(
            DMZ1Hit(
                path=display_path,
                family=family,
                file_size=len(data),
                offset=offset,
                offset_hex=f"0x{offset:x}",
                declared_output_size=declared_output_size,
                compressed_consumed=consumed,
                unused_after_stream=unused_after_stream,
                output_sha256_16=hashlib.sha256(out).hexdigest()[:16],
                output_kind=classify_output(out),
                output_prefix_hex=out[:16].hex(" "),
            )
        )
        if len(hits) >= max_streams_per_file:
            break
    return candidate_count, hits


def scan_file(
    path: Path,
    *,
    header_mode: str,
    min_output_size: int,
    max_output_size: int,
    max_input_size: int,
    max_streams_per_file: int,
    scan_dmz1: bool,
) -> tuple[int, list[StreamHit], int, list[DMZ1Hit]]:
    data = path.read_bytes()
    candidate_count = 0
    hits: list[StreamHit] = []
    dmz1_candidate_count = 0
    dmz1_hits: list[DMZ1Hit] = []
    skip_until = -1
    family = classify_family(path)
    try:
        display_path = str(path.relative_to(Path.cwd()))
    except ValueError:
        display_path = str(path)

    for offset in sorted(iter_candidate_offsets(data, mode=header_mode)):
        if offset < skip_until:
            continue
        candidate_count += 1
        inflated = try_inflate(
            data,
            offset,
            min_output_size=min_output_size,
            max_output_size=max_output_size,
            max_input_size=max_input_size,
        )
        if inflated is None:
            continue

        out, truncated, consumed, unused_after_stream = inflated
        hit = StreamHit(
            path=display_path,
            family=family,
            file_size=len(data),
            offset=offset,
            offset_hex=f"0x{offset:x}",
            header=data[offset : offset + 2].hex(" "),
            compressed_consumed=consumed,
            unused_after_stream=unused_after_stream,
            output_size=len(out),
            output_truncated=truncated,
            input_window_size=min(max_input_size, len(data) - offset),
            output_sha256_16=hashlib.sha256(out).hexdigest()[:16],
            output_kind=classify_output(out),
            output_prefix_hex=out[:16].hex(" "),
        )
        hits.append(hit)
        if consumed:
            skip_until = max(skip_until, offset + consumed)
        if len(hits) >= max_streams_per_file:
            break
    if scan_dmz1:
        dmz1_candidate_count, dmz1_hits = scan_dmz1_blocks(
            path,
            data,
            max_output_size=max_output_size,
            max_input_size=max_input_size,
            max_streams_per_file=max_streams_per_file,
        )
    return candidate_count, hits, dmz1_candidate_count, dmz1_hits


def main() -> int:
    args = parse_args()
    suffixes = normalize_suffixes(args.suffix)
    paths = iter_files(args.roots, suffixes=suffixes, all_files=args.all_files)
    start_time = time.monotonic()

    candidate_total = 0
    dmz1_candidate_total = 0
    scanned_bytes = 0
    failures: list[dict[str, str]] = []
    hits: list[StreamHit] = []
    dmz1_hits: list[DMZ1Hit] = []
    files_by_family: Counter[str] = Counter()
    bytes_by_family: Counter[str] = Counter()
    candidates_by_family: Counter[str] = Counter()
    dmz1_candidates_by_family: Counter[str] = Counter()

    for path in paths:
        family = classify_family(path)
        files_by_family[family] += 1
        try:
            file_size = path.stat().st_size
            scanned_bytes += file_size
            bytes_by_family[family] += file_size
            candidate_count, file_hits, dmz1_candidate_count, file_dmz1_hits = scan_file(
                path,
                header_mode=args.header_mode,
                min_output_size=args.min_output_size,
                max_output_size=args.max_output_size,
                max_input_size=args.max_input_size,
                max_streams_per_file=args.max_streams_per_file,
                scan_dmz1=not args.no_dmz1,
            )
        except Exception as exc:  # pragma: no cover - defensive probe
            failures.append({"path": str(path), "error": str(exc)})
            continue
        candidate_total += candidate_count
        dmz1_candidate_total += dmz1_candidate_count
        candidates_by_family[family] += candidate_count
        dmz1_candidates_by_family[family] += dmz1_candidate_count
        hits.extend(file_hits)
        dmz1_hits.extend(file_dmz1_hits)

    hits_by_family: dict[str, int] = defaultdict(int)
    hits_by_kind: dict[str, int] = defaultdict(int)
    for hit in hits:
        hits_by_family[hit.family] += 1
        hits_by_kind[hit.output_kind] += 1
    dmz1_hits_by_family: dict[str, int] = defaultdict(int)
    dmz1_hits_by_kind: dict[str, int] = defaultdict(int)
    for hit in dmz1_hits:
        dmz1_hits_by_family[hit.family] += 1
        dmz1_hits_by_kind[hit.output_kind] += 1

    report = {
        "schema": "pm99_zlib_stream_probe_v1",
        "elapsed_seconds": round(time.monotonic() - start_time, 3),
        "header_mode": args.header_mode,
        "roots": [str(root) for root in args.roots],
        "suffixes": sorted(suffixes) if not args.all_files else ["*"],
        "files_scanned": len(paths),
        "bytes_scanned": scanned_bytes,
        "candidate_headers": candidate_total,
        "valid_streams": len(hits),
        "dmz1_candidate_headers": dmz1_candidate_total,
        "valid_dmz1_streams": len(dmz1_hits),
        "files_by_family": dict(sorted(files_by_family.items())),
        "bytes_by_family": dict(sorted(bytes_by_family.items())),
        "candidate_headers_by_family": dict(sorted(candidates_by_family.items())),
        "valid_streams_by_family": dict(sorted(hits_by_family.items())),
        "valid_streams_by_output_kind": dict(sorted(hits_by_kind.items())),
        "dmz1_candidate_headers_by_family": dict(sorted(dmz1_candidates_by_family.items())),
        "valid_dmz1_streams_by_family": dict(sorted(dmz1_hits_by_family.items())),
        "valid_dmz1_streams_by_output_kind": dict(sorted(dmz1_hits_by_kind.items())),
        "hits": [asdict(hit) for hit in hits],
        "dmz1_hits": [asdict(hit) for hit in dmz1_hits],
        "failures": failures,
    }

    print(
        json.dumps(
            {key: value for key, value in report.items() if key not in {"hits", "dmz1_hits"}},
            indent=2,
        )
    )
    if hits:
        print("\nTop stream hits:")
        for hit in hits[:25]:
            print(
                f"{hit.path}: offset {hit.offset_hex}, header {hit.header}, "
                f"out={hit.output_size} bytes, kind={hit.output_kind}"
            )
        if len(hits) > 25:
            print(f"... {len(hits) - 25} more hit(s) in JSON report")
    if dmz1_hits:
        print("\nTop DMZ1 raw-deflate hits:")
        for hit in dmz1_hits[:25]:
            print(
                f"{hit.path}: offset {hit.offset_hex}, declared={hit.declared_output_size} bytes, "
                f"kind={hit.output_kind}"
            )
        if len(dmz1_hits) > 25:
            print(f"... {len(dmz1_hits) - 25} more DMZ1 hit(s) in JSON report")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"\nWrote {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
