#!/usr/bin/env python3
"""Probe PM99 SIMULDAT PKF offset tables and embedded asset starts.

The script is read-only. It records table offsets, payload offsets, sizes,
type guesses, and hashes without extracting proprietary payloads.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import struct
import sys
import time
from typing import Iterable


DEFAULT_FIELD_OFFSET = 0x107
DEFAULT_FIELD_STRIDE = 0x26
DEFAULT_DESCRIPTOR_SIZE = 0x1A
DEFAULT_MIN_RUN = 4
FLAG_BYTES = b"\x01\x00\x00\x00"


@dataclass(frozen=True)
class PayloadInfo:
    kind: str
    prefix_hex: str
    sha256_16: str
    bmp_size: int | None = None
    bmp_width: int | None = None
    bmp_height: int | None = None
    bmp_bpp: int | None = None
    bmp_size_matches_record: bool | None = None
    riff_type: str | None = None
    riff_total_size: int | None = None
    riff_size_matches_record: bool | None = None
    gif_width: int | None = None
    gif_height: int | None = None


@dataclass(frozen=True)
class Record:
    field_offset: int
    field_offset_hex: str
    payload_offset: int
    payload_offset_hex: str
    length: int
    length_hex: str
    end_offset: int
    end_offset_hex: str
    flag: int
    descriptor_offset: int
    descriptor_offset_hex: str
    descriptor_size: int
    descriptor_status: str
    descriptor_hex: str | None
    payload: PayloadInfo


@dataclass(frozen=True)
class Table:
    table_index: int
    field_start_offset: int
    field_start_offset_hex: str
    entry_count: int
    first_payload_offset: int
    first_payload_offset_hex: str
    last_payload_end: int
    last_payload_end_hex: str
    summed_payload_bytes: int
    payload_kind_counts: dict[str, int]
    records: list[Record]


@dataclass(frozen=True)
class LooseAssetHit:
    offset: int
    offset_hex: str
    kind: str
    status: str
    containing_record: str | None
    size_hint: int | None
    width: int | None
    height: int | None
    bpp: int | None


@dataclass(frozen=True)
class OrphanRecordCandidate:
    field_offset: int
    field_offset_hex: str
    payload_offset: int
    payload_offset_hex: str
    length: int
    length_hex: str
    kind: str
    prefix_hex: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Survey SIMULDAT PKF offset tables and embedded asset starts."
    )
    parser.add_argument(
        "roots",
        nargs="+",
        type=Path,
        help="SIMULDAT directories or individual PKF files to scan.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON output path for the full report.",
    )
    parser.add_argument(
        "--field-offset",
        type=lambda value: int(value, 0),
        default=DEFAULT_FIELD_OFFSET,
        help="Known first record field offset, default 0x107.",
    )
    parser.add_argument(
        "--field-stride",
        type=lambda value: int(value, 0),
        default=DEFAULT_FIELD_STRIDE,
        help="Distance between record offset fields, default 0x26.",
    )
    parser.add_argument(
        "--descriptor-size",
        type=lambda value: int(value, 0),
        default=DEFAULT_DESCRIPTOR_SIZE,
        help="Bytes after offset/length/flag before the next field, default 0x1a.",
    )
    parser.add_argument(
        "--min-run",
        type=int,
        default=DEFAULT_MIN_RUN,
        help="Minimum consecutive candidate records needed for an auto-discovered table.",
    )
    parser.add_argument(
        "--max-loose-hits-per-file",
        type=int,
        default=80,
        help="Maximum loose BMP/RIFF/GIF hits retained per file in JSON.",
    )
    parser.add_argument(
        "--max-orphans-per-file",
        type=int,
        default=80,
        help="Maximum single-record asset candidates retained per file in JSON.",
    )
    return parser.parse_args()


def hex_int(value: int) -> str:
    return f"0x{value:x}"


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def iter_pkf_files(roots: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            print(f"warning: missing root: {root}", file=sys.stderr)
            continue
        if root.is_file():
            if root.suffix.lower() == ".pkf":
                files.append(root)
            continue
        files.extend(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() == ".pkf")
    return sorted(dict.fromkeys(files))


def classify_payload(data: bytes, offset: int, length: int) -> PayloadInfo:
    payload = data[offset : offset + length]
    prefix = payload[:16]
    digest = hashlib.sha256(payload).hexdigest()[:16]
    if len(payload) >= 54 and payload.startswith(b"BM"):
        bmp_size = struct.unpack_from("<I", payload, 2)[0]
        dib_size = struct.unpack_from("<I", payload, 14)[0]
        width: int | None = None
        height: int | None = None
        bpp: int | None = None
        if dib_size == 40 and len(payload) >= 30:
            width, height = struct.unpack_from("<ii", payload, 18)
            bpp = struct.unpack_from("<H", payload, 28)[0]
        return PayloadInfo(
            kind="BMP",
            prefix_hex=prefix.hex(" "),
            sha256_16=digest,
            bmp_size=bmp_size,
            bmp_width=width,
            bmp_height=height,
            bmp_bpp=bpp,
            bmp_size_matches_record=bmp_size == length,
        )
    if len(payload) >= 12 and payload.startswith(b"RIFF"):
        riff_size = struct.unpack_from("<I", payload, 4)[0]
        riff_total = riff_size + 8
        riff_type = payload[8:12].decode("ascii", "replace")
        riff_kind = riff_type.rstrip() or riff_type
        return PayloadInfo(
            kind=f"RIFF/{riff_kind}",
            prefix_hex=prefix.hex(" "),
            sha256_16=digest,
            riff_type=riff_type,
            riff_total_size=riff_total,
            riff_size_matches_record=riff_total == length,
        )
    if len(payload) >= 10 and (payload.startswith(b"GIF87a") or payload.startswith(b"GIF89a")):
        width, height = struct.unpack_from("<HH", payload, 6)
        return PayloadInfo(
            kind="GIF",
            prefix_hex=prefix.hex(" "),
            sha256_16=digest,
            gif_width=width,
            gif_height=height,
        )
    if payload.startswith(b"\xfd\xff\x7f\xff") or payload.startswith(b"\xfe\xff\x7f\xff"):
        return PayloadInfo(kind="P3D-like binary", prefix_hex=prefix.hex(" "), sha256_16=digest)
    printable = sum(1 for byte in payload[:64] if byte in b"\t\r\n" or 32 <= byte <= 126)
    if payload and printable / min(len(payload), 64) >= 0.85:
        return PayloadInfo(kind="mostly-ascii", prefix_hex=prefix.hex(" "), sha256_16=digest)
    return PayloadInfo(kind="binary", prefix_hex=prefix.hex(" "), sha256_16=digest)


def parse_candidate_field(data: bytes, field_offset: int) -> tuple[int, int, int] | None:
    if field_offset < 0 or field_offset + 12 > len(data):
        return None
    payload_offset, length, flag = struct.unpack_from("<III", data, field_offset)
    if flag != 1:
        return None
    if payload_offset < 0x40 or length <= 0:
        return None
    if payload_offset <= field_offset:
        return None
    if payload_offset + length > len(data):
        return None
    return payload_offset, length, flag


def find_candidate_fields(data: bytes) -> dict[int, tuple[int, int, int]]:
    candidates: dict[int, tuple[int, int, int]] = {}
    pos = 0
    while True:
        pos = data.find(FLAG_BYTES, pos)
        if pos < 0:
            break
        field_offset = pos - 8
        parsed = parse_candidate_field(data, field_offset)
        if parsed is not None:
            candidates[field_offset] = parsed
        pos += 1
    return candidates


def run_from(
    candidates: dict[int, tuple[int, int, int]],
    start: int,
    *,
    stride: int,
) -> list[int]:
    run: list[int] = []
    previous_payload = -1
    current = start
    while current in candidates:
        payload_offset, _, _ = candidates[current]
        if payload_offset < previous_payload:
            break
        run.append(current)
        previous_payload = payload_offset
        current += stride
    return run


def select_table_runs(
    candidates: dict[int, tuple[int, int, int]],
    *,
    known_field_offset: int,
    stride: int,
    min_run: int,
) -> list[list[int]]:
    possible: list[list[int]] = []
    for field_offset in sorted(candidates):
        run = run_from(candidates, field_offset, stride=stride)
        if len(run) >= min_run:
            possible.append(run)

    known = run_from(candidates, known_field_offset, stride=stride)
    if known and len(known) < min_run:
        possible.append(known)

    selected: list[list[int]] = []
    used_fields: set[int] = set()
    for run in sorted(possible, key=lambda values: (-len(values), values[0])):
        if any(field in used_fields for field in run):
            continue
        selected.append(run)
        used_fields.update(run)
    return sorted(selected, key=lambda values: values[0])


def merge_ranges(ranges: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if start >= end:
            continue
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        previous_start, previous_end = merged[-1]
        merged[-1] = (previous_start, max(previous_end, end))
    return merged


def range_contains(ranges: list[tuple[int, int]], offset: int) -> tuple[int, int] | None:
    for start, end in ranges:
        if start <= offset < end:
            return start, end
    return None


def build_record(
    data: bytes,
    field_offset: int,
    *,
    descriptor_size: int,
    table_payload_floor: int,
) -> Record:
    parsed = parse_candidate_field(data, field_offset)
    if parsed is None:  # pragma: no cover - guarded by caller
        raise ValueError(f"not a candidate field: {field_offset:#x}")
    payload_offset, length, flag = parsed
    end_offset = payload_offset + length
    descriptor_offset = field_offset + 12
    descriptor_end = descriptor_offset + descriptor_size
    descriptor_hex: str | None
    if descriptor_end <= len(data) and descriptor_end <= table_payload_floor:
        descriptor_status = "available"
        descriptor_hex = data[descriptor_offset:descriptor_end].hex(" ")
    elif descriptor_offset < len(data):
        descriptor_status = "overlaps_payload_or_eof"
        descriptor_hex = None
    else:
        descriptor_status = "missing"
        descriptor_hex = None
    return Record(
        field_offset=field_offset,
        field_offset_hex=hex_int(field_offset),
        payload_offset=payload_offset,
        payload_offset_hex=hex_int(payload_offset),
        length=length,
        length_hex=hex_int(length),
        end_offset=end_offset,
        end_offset_hex=hex_int(end_offset),
        flag=flag,
        descriptor_offset=descriptor_offset,
        descriptor_offset_hex=hex_int(descriptor_offset),
        descriptor_size=descriptor_size,
        descriptor_status=descriptor_status,
        descriptor_hex=descriptor_hex,
        payload=classify_payload(data, payload_offset, length),
    )


def build_tables(
    data: bytes,
    runs: list[list[int]],
    *,
    descriptor_size: int,
) -> list[Table]:
    tables: list[Table] = []
    for table_index, run in enumerate(runs):
        parsed_records = [parse_candidate_field(data, field_offset) for field_offset in run]
        payload_floor = min(record[0] for record in parsed_records if record is not None)
        records = [
            build_record(
                data,
                field_offset,
                descriptor_size=descriptor_size,
                table_payload_floor=payload_floor,
            )
            for field_offset in run
        ]
        kind_counts = Counter(record.payload.kind for record in records)
        first_payload = min(record.payload_offset for record in records)
        last_payload_end = max(record.end_offset for record in records)
        tables.append(
            Table(
                table_index=table_index,
                field_start_offset=run[0],
                field_start_offset_hex=hex_int(run[0]),
                entry_count=len(records),
                first_payload_offset=first_payload,
                first_payload_offset_hex=hex_int(first_payload),
                last_payload_end=last_payload_end,
                last_payload_end_hex=hex_int(last_payload_end),
                summed_payload_bytes=sum(record.length for record in records),
                payload_kind_counts=dict(sorted(kind_counts.items())),
                records=records,
            )
        )
    return tables


def scan_asset_starts(data: bytes) -> list[tuple[int, str, int | None, int | None, int | None, int | None]]:
    hits: list[tuple[int, str, int | None, int | None, int | None, int | None]] = []
    for needle, base_kind in (
        (b"BM", "BMP"),
        (b"RIFF", "RIFF"),
        (b"GIF87a", "GIF"),
        (b"GIF89a", "GIF"),
    ):
        offset = 0
        seen_offsets = {hit[0] for hit in hits}
        while True:
            offset = data.find(needle, offset)
            if offset < 0:
                break
            if offset in seen_offsets:
                offset += 1
                continue
            size_hint: int | None = None
            width: int | None = None
            height: int | None = None
            bpp: int | None = None
            valid = False
            hit_kind = base_kind
            if base_kind == "BMP" and offset + 54 <= len(data):
                size_hint = struct.unpack_from("<I", data, offset + 2)[0]
                data_offset = struct.unpack_from("<I", data, offset + 10)[0]
                dib_size = struct.unpack_from("<I", data, offset + 14)[0]
                valid = 0 < size_hint <= len(data) - offset and 14 <= data_offset <= size_hint
                valid = valid and dib_size in {12, 40, 108, 124}
                if valid and dib_size == 40:
                    width, height = struct.unpack_from("<ii", data, offset + 18)
                    bpp = struct.unpack_from("<H", data, offset + 28)[0]
            elif base_kind == "RIFF" and offset + 12 <= len(data):
                riff_size = struct.unpack_from("<I", data, offset + 4)[0]
                riff_type = data[offset + 8 : offset + 12]
                size_hint = riff_size + 8
                valid = 0 < size_hint <= len(data) - offset and riff_type.rstrip(b" ").isalpha()
                if valid:
                    riff_label = riff_type.decode("ascii", "replace").rstrip()
                    hit_kind = f"RIFF/{riff_label or riff_type.decode('ascii', 'replace')}"
            elif base_kind == "GIF" and offset + 10 <= len(data):
                width, height = struct.unpack_from("<HH", data, offset + 6)
                valid = 0 < width <= 4096 and 0 < height <= 4096
            if valid:
                hits.append((offset, hit_kind, size_hint, width, height, bpp))
                seen_offsets.add(offset)
            offset += 1
    return sorted(hits)


def summarize_loose_assets(
    asset_hits: list[tuple[int, str, int | None, int | None, int | None, int | None]],
    record_by_payload_offset: dict[int, tuple[int, int, str]],
    indexed_ranges: list[tuple[int, int]],
    *,
    limit: int,
) -> tuple[Counter[str], list[LooseAssetHit]]:
    counts: Counter[str] = Counter()
    retained: list[LooseAssetHit] = []
    for offset, kind, size_hint, width, height, bpp in asset_hits:
        if offset in record_by_payload_offset:
            _, _, record_id = record_by_payload_offset[offset]
            status = "indexed_payload_start"
            containing_record = record_id
        else:
            containing = range_contains(indexed_ranges, offset)
            if containing is None:
                status = "outside_indexed_payloads"
                containing_record = None
            else:
                status = "inside_indexed_payload"
                containing_record = f"{hex_int(containing[0])}..{hex_int(containing[1])}"
        counts[status] += 1
        if len(retained) < limit:
            retained.append(
                LooseAssetHit(
                    offset=offset,
                    offset_hex=hex_int(offset),
                    kind=kind,
                    status=status,
                    containing_record=containing_record,
                    size_hint=size_hint,
                    width=width,
                    height=height,
                    bpp=bpp,
                )
            )
    return counts, retained


def find_orphan_asset_records(
    data: bytes,
    candidates: dict[int, tuple[int, int, int]],
    selected_fields: set[int],
    *,
    limit: int,
) -> tuple[int, list[OrphanRecordCandidate]]:
    retained: list[OrphanRecordCandidate] = []
    count = 0
    for field_offset in sorted(candidates):
        if field_offset in selected_fields:
            continue
        payload_offset, length, _ = candidates[field_offset]
        info = classify_payload(data, payload_offset, min(length, len(data) - payload_offset))
        if info.kind not in {"BMP", "GIF", "RIFF/PAL"} and not info.kind.startswith("RIFF/"):
            continue
        count += 1
        if len(retained) >= limit:
            continue
        retained.append(
            OrphanRecordCandidate(
                field_offset=field_offset,
                field_offset_hex=hex_int(field_offset),
                payload_offset=payload_offset,
                payload_offset_hex=hex_int(payload_offset),
                length=length,
                length_hex=hex_int(length),
                kind=info.kind,
                prefix_hex=info.prefix_hex,
            )
        )
    return count, retained


def scan_file(
    path: Path,
    *,
    field_offset: int,
    field_stride: int,
    descriptor_size: int,
    min_run: int,
    max_loose_hits: int,
    max_orphans: int,
) -> dict[str, object]:
    data = path.read_bytes()
    candidates = find_candidate_fields(data)
    runs = select_table_runs(
        candidates,
        known_field_offset=field_offset,
        stride=field_stride,
        min_run=min_run,
    )
    tables = build_tables(data, runs, descriptor_size=descriptor_size)
    records = [record for table in tables for record in table.records]
    ranges = merge_ranges((record.payload_offset, record.end_offset) for record in records)
    indexed_payload_bytes = sum(end - start for start, end in ranges)
    selected_fields = {record.field_offset for record in records}
    record_by_payload_offset: dict[int, tuple[int, int, str]] = {}
    for table in tables:
        for slot_index, record in enumerate(table.records):
            record_by_payload_offset[record.payload_offset] = (
                record.length,
                table.table_index,
                f"table{table.table_index}:slot{slot_index}",
            )

    asset_hits = scan_asset_starts(data)
    loose_counts, loose_retained = summarize_loose_assets(
        asset_hits,
        record_by_payload_offset,
        ranges,
        limit=max_loose_hits,
    )
    orphan_count, orphan_retained = find_orphan_asset_records(
        data,
        candidates,
        selected_fields,
        limit=max_orphans,
    )

    kind_counts = Counter(record.payload.kind for record in records)
    bmp_dimension_counts: Counter[str] = Counter()
    for record in records:
        payload = record.payload
        if payload.kind == "BMP" and payload.bmp_width is not None and payload.bmp_height is not None:
            bmp_dimension_counts[
                f"{payload.bmp_width}x{payload.bmp_height}x{payload.bmp_bpp}"
            ] += 1

    tail_unindexed_bytes = 0
    if ranges:
        tail_unindexed_bytes = max(0, len(data) - max(end for _, end in ranges))

    return {
        "path": display_path(path),
        "size": len(data),
        "size_hex": hex_int(len(data)),
        "sha256_16": hashlib.sha256(data).hexdigest()[:16],
        "head32_hex": data[:32].hex(" "),
        "candidate_record_fields": len(candidates),
        "selected_table_count": len(tables),
        "selected_entry_count": len(records),
        "indexed_payload_bytes_union": indexed_payload_bytes,
        "indexed_payload_coverage_ratio": round(indexed_payload_bytes / len(data), 6)
        if data
        else 0,
        "tail_unindexed_bytes_after_last_indexed_payload": tail_unindexed_bytes,
        "payload_kind_counts": dict(sorted(kind_counts.items())),
        "bmp_dimension_counts": dict(sorted(bmp_dimension_counts.items())),
        "loose_asset_hit_counts": dict(sorted(loose_counts.items())),
        "loose_asset_hits_total": len(asset_hits),
        "loose_asset_hits_retained": [asdict(hit) for hit in loose_retained],
        "orphan_asset_record_candidate_count": orphan_count,
        "orphan_asset_record_candidates_retained": [
            asdict(candidate) for candidate in orphan_retained
        ],
        "tables": [asdict(table) for table in tables],
    }


def main() -> int:
    args = parse_args()
    start_time = time.monotonic()
    pkf_files = iter_pkf_files(args.roots)

    reports: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []
    for path in pkf_files:
        try:
            reports.append(
                scan_file(
                    path,
                    field_offset=args.field_offset,
                    field_stride=args.field_stride,
                    descriptor_size=args.descriptor_size,
                    min_run=args.min_run,
                    max_loose_hits=args.max_loose_hits_per_file,
                    max_orphans=args.max_orphans_per_file,
                )
            )
        except Exception as exc:  # pragma: no cover - defensive research probe
            failures.append({"path": str(path), "error": str(exc)})

    table_count = sum(int(report["selected_table_count"]) for report in reports)
    entry_count = sum(int(report["selected_entry_count"]) for report in reports)
    candidate_fields = sum(int(report["candidate_record_fields"]) for report in reports)
    indexed_bytes = sum(int(report["indexed_payload_bytes_union"]) for report in reports)
    scanned_bytes = sum(int(report["size"]) for report in reports)
    kind_counts: Counter[str] = Counter()
    loose_counts: Counter[str] = Counter()
    for report in reports:
        kind_counts.update(report["payload_kind_counts"])  # type: ignore[arg-type]
        loose_counts.update(report["loose_asset_hit_counts"])  # type: ignore[arg-type]

    summary = {
        "schema": "pm99_simuldat_pkf_layout_probe_v1",
        "elapsed_seconds": round(time.monotonic() - start_time, 3),
        "roots": [str(root) for root in args.roots],
        "field_offset": hex_int(args.field_offset),
        "field_stride": hex_int(args.field_stride),
        "descriptor_size": hex_int(args.descriptor_size),
        "min_run": args.min_run,
        "pkf_files_scanned": len(reports),
        "bytes_scanned": scanned_bytes,
        "candidate_record_fields": candidate_fields,
        "selected_table_count": table_count,
        "selected_entry_count": entry_count,
        "indexed_payload_bytes_union": indexed_bytes,
        "indexed_payload_coverage_ratio": round(indexed_bytes / scanned_bytes, 6)
        if scanned_bytes
        else 0,
        "payload_kind_counts": dict(sorted(kind_counts.items())),
        "loose_asset_hit_counts": dict(sorted(loose_counts.items())),
        "orphan_asset_record_candidate_count": sum(
            int(report["orphan_asset_record_candidate_count"]) for report in reports
        ),
        "failures": failures,
    }
    report = {**summary, "files": reports}

    print(json.dumps(summary, indent=2, sort_keys=True))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(f"\nwrote {args.output}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
