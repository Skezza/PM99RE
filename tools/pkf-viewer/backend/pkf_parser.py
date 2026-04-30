"""Read-only SIMULDAT PKF table parser.

The parser intentionally returns metadata and record byte slices only. Callers
decide whether to stream those bytes; this module never writes extracted assets.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import math
from pathlib import Path
import struct
from typing import Iterable


FIELD_OFFSET = 0x107
FIELD_STRIDE = 0x26
DESCRIPTOR_SIZE = 0x1A
FLAG_BYTES = b"\x01\x00\x00\x00"
MIN_TABLE_RUN = 4


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
    duplicate_payload_count: int | None = None
    p3d_magic_hex: str | None = None
    p3d_magic_class: str | None = None
    p3d_marker_field_count: int | None = None
    p3d_family: str | None = None
    p3d_label: str | None = None
    p3d_first_ascii_offset: int | None = None
    p3d_record_start_offset: int | None = None
    p3d_optional_header_flag: int | None = None
    p3d_optional_header_dwords_hex: list[str] | None = None
    p3d_optional_header_floats: list[float] | None = None
    p3d_printable_runs: list[str] | None = None
    p3d_ascii_run_count: int | None = None
    p3d_longest_ascii_run_length: int | None = None
    p3d_first_dwords_hex: list[str] | None = None
    p3d_first_inner_marker_hex: str | None = None
    p3d_first_inner_marker_field_count: int | None = None
    p3d_stream_bytes_after_header: int | None = None
    p3d_chunk128_floor_count: int | None = None
    p3d_chunk128_trailing_bytes: int | None = None
    p3d_chunk128_loader_iterations: int | None = None
    p3d_chunk_name_samples: list[dict[str, object]] | None = None
    p3d_float32_finite_sample_count: int | None = None
    p3d_float32_plausible_sample_count: int | None = None
    p3d_zero16_block_count: int | None = None
    p3d_size_bucket: str | None = None


@dataclass(frozen=True)
class PkfRecord:
    table_index: int
    slot_index: int
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
class PkfTable:
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
    records: list[PkfRecord]


@dataclass(frozen=True)
class PkfFile:
    path: str
    relative_path: str
    size: int
    size_hex: str
    sha256_16: str
    head32_hex: str
    candidate_record_fields: int
    selected_table_count: int
    selected_entry_count: int
    indexed_payload_bytes_union: int
    indexed_payload_coverage_ratio: float
    tail_unindexed_bytes_after_last_indexed_payload: int
    payload_kind_counts: dict[str, int]
    bmp_dimension_counts: dict[str, int]
    p3d_family_counts: dict[str, int]
    tables: list[PkfTable]


def hex_int(value: int) -> str:
    return f"0x{value:x}"


def file_sha256_16(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def printable_runs_with_offsets(
    payload: bytes,
    *,
    max_scan: int = 256,
    min_run: int = 3,
) -> list[tuple[int, str]]:
    runs: list[tuple[int, str]] = []
    current = bytearray()
    current_start: int | None = None
    for offset, byte in enumerate(payload[:max_scan]):
        if 32 <= byte <= 126:
            if current_start is None:
                current_start = offset
            current.append(byte)
            continue
        if len(current) >= min_run:
            runs.append((current_start or 0, current.decode("ascii", "replace")))
        current.clear()
        current_start = None
    if len(current) >= min_run:
        runs.append((current_start or 0, current.decode("ascii", "replace")))
    return runs


def p3d_float_profile(payload: bytes, *, max_scan: int = 4096) -> tuple[int, int]:
    finite = 0
    plausible = 0
    scan_size = min(len(payload), max_scan)
    scan_size -= scan_size % 4
    for offset in range(0, scan_size, 4):
        value = struct.unpack_from("<f", payload, offset)[0]
        if not math.isfinite(value):
            continue
        finite += 1
        if abs(value) <= 100_000 and abs(value) >= 1e-7:
            plausible += 1
    return finite, plausible


def p3d_size_bucket(length: int) -> str:
    if length < 1024:
        return "<1 KiB"
    if length < 64 * 1024:
        return "1-64 KiB"
    if length < 1024 * 1024:
        return "64 KiB-1 MiB"
    if length < 10 * 1024 * 1024:
        return "1-10 MiB"
    return "10 MiB+"


def p3d_layout(payload: bytes) -> tuple[str, int]:
    if payload.startswith(b"\xfe\xff\x7f\xff"):
        return "fe...records@4", 4
    control = struct.unpack_from("<I", payload, 4)[0] if len(payload) >= 8 else 0
    if control == 0:
        return "fd...00-records@8", 8
    if control == 1:
        return "fd...01-records@32", 32
    return f"fd...{control:08x}-records@8", 8


def p3d_marker_field_count(marker: int) -> int:
    return (-marker) & 0x7FFFFF


def zero16_block_count(payload: bytes) -> int:
    zero = b"\x00" * 16
    return sum(1 for offset in range(0, len(payload) - 15, 16) if payload[offset : offset + 16] == zero)


def chunk_name_at(payload: bytes, offset: int) -> str | None:
    chunk = payload[offset : offset + 0x80]
    name = bytearray()
    for byte in chunk:
        if byte == 0:
            break
        if not (32 <= byte <= 126):
            return None
        name.append(byte)
    if len(name) < 3:
        return None
    return name.decode("ascii", "replace")


def p3d_chunk_name_samples(
    payload: bytes,
    *,
    record_start: int,
    chunk_count: int,
    limit: int = 24,
) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for index in range(min(chunk_count, limit)):
        offset = record_start + index * 0x80
        name = chunk_name_at(payload, offset)
        if name is None:
            continue
        samples.append(
            {
                "index": index,
                "offset": offset,
                "offset_hex": hex_int(offset),
                "name": name,
            }
        )
    return samples


def p3d_profile(payload: bytes) -> dict[str, object] | None:
    if payload.startswith(b"\xfe\xff\x7f\xff"):
        magic_class = "P3D named resource"
    elif payload.startswith(b"\xfd\xff\x7f\xff"):
        magic_class = "P3D scene/bundle"
    else:
        return None

    magic = struct.unpack_from("<I", payload, 0)[0]
    marker_field_count = p3d_marker_field_count(magic)
    optional_flag = None
    optional_dwords = None
    optional_floats = None
    dword_scan = min(len(payload), 32)
    dword_scan -= dword_scan % 4
    first_dwords = [
        f"0x{struct.unpack_from('<I', payload, offset)[0]:08x}"
        for offset in range(0, dword_scan, 4)
    ]
    if marker_field_count > 2 and len(payload) >= 8:
        optional_flag = struct.unpack_from("<I", payload, 4)[0]
        if optional_flag != 0 and len(payload) >= 32:
            optional_dwords = first_dwords[2:8]
            optional_floats = [struct.unpack_from("<f", payload, offset)[0] for offset in range(8, 32, 4)]
    runs_with_offsets = printable_runs_with_offsets(payload)
    runs = [text for _, text in runs_with_offsets]
    family, record_start = p3d_layout(payload)
    label_run = next(
        ((offset, text) for offset, text in runs_with_offsets if offset >= record_start),
        None,
    )
    stream_bytes = max(0, len(payload) - record_start)
    chunk_floor = stream_bytes // 0x80
    chunk_trailing = stream_bytes % 0x80
    chunk_iterations = chunk_floor + (1 if chunk_trailing else 0)
    inner_marker_offset = record_start + 0x80
    inner_marker = None
    if inner_marker_offset + 4 <= len(payload):
        inner_marker = struct.unpack_from("<I", payload, inner_marker_offset)[0]
    finite, plausible = p3d_float_profile(payload)
    return {
        "p3d_magic_hex": f"0x{magic:08x}",
        "p3d_magic_class": magic_class,
        "p3d_marker_field_count": marker_field_count,
        "p3d_family": family,
        "p3d_label": label_run[1] if label_run else None,
        "p3d_first_ascii_offset": label_run[0] if label_run else None,
        "p3d_record_start_offset": record_start,
        "p3d_optional_header_flag": optional_flag,
        "p3d_optional_header_dwords_hex": optional_dwords,
        "p3d_optional_header_floats": optional_floats,
        "p3d_printable_runs": runs[:8],
        "p3d_ascii_run_count": len(runs),
        "p3d_longest_ascii_run_length": max((len(run) for run in runs), default=0),
        "p3d_first_dwords_hex": first_dwords,
        "p3d_first_inner_marker_hex": f"0x{inner_marker:08x}" if inner_marker is not None else None,
        "p3d_first_inner_marker_field_count": p3d_marker_field_count(inner_marker)
        if inner_marker is not None
        else None,
        "p3d_stream_bytes_after_header": stream_bytes,
        "p3d_chunk128_floor_count": chunk_floor,
        "p3d_chunk128_trailing_bytes": chunk_trailing,
        "p3d_chunk128_loader_iterations": chunk_iterations,
        "p3d_chunk_name_samples": p3d_chunk_name_samples(
            payload,
            record_start=record_start,
            chunk_count=chunk_floor,
        ),
        "p3d_float32_finite_sample_count": finite,
        "p3d_float32_plausible_sample_count": plausible,
        "p3d_zero16_block_count": zero16_block_count(payload),
        "p3d_size_bucket": p3d_size_bucket(len(payload)),
    }


def classify_payload(data: bytes, offset: int, length: int) -> PayloadInfo:
    payload = data[offset : offset + length]
    prefix = payload[:16]
    digest = file_sha256_16(payload)

    if len(payload) >= 26 and payload.startswith(b"BM"):
        bmp_size = struct.unpack_from("<I", payload, 2)[0]
        dib_size = struct.unpack_from("<I", payload, 14)[0]
        width: int | None = None
        height: int | None = None
        bpp: int | None = None
        if dib_size == 12 and len(payload) >= 26:
            width, height = struct.unpack_from("<HH", payload, 18)
            bpp = struct.unpack_from("<H", payload, 24)[0]
        elif dib_size == 40 and len(payload) >= 30:
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

    if len(payload) >= 10 and (
        payload.startswith(b"GIF87a") or payload.startswith(b"GIF89a")
    ):
        width, height = struct.unpack_from("<HH", payload, 6)
        return PayloadInfo(
            kind="GIF",
            prefix_hex=prefix.hex(" "),
            sha256_16=digest,
            gif_width=width,
            gif_height=height,
        )

    profile = p3d_profile(payload)
    if profile is not None:
        return PayloadInfo(
            kind="P3D-like binary",
            prefix_hex=prefix.hex(" "),
            sha256_16=digest,
            **profile,
        )

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
    position = 0
    while True:
        position = data.find(FLAG_BYTES, position)
        if position < 0:
            break
        field_offset = position - 8
        parsed = parse_candidate_field(data, field_offset)
        if parsed is not None:
            candidates[field_offset] = parsed
        position += 1
    return candidates


def run_from(
    candidates: dict[int, tuple[int, int, int]],
    start: int,
    *,
    stride: int = FIELD_STRIDE,
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
    known_field_offset: int = FIELD_OFFSET,
    stride: int = FIELD_STRIDE,
    min_run: int = MIN_TABLE_RUN,
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


def build_record(
    data: bytes,
    field_offset: int,
    *,
    table_index: int,
    slot_index: int,
    table_payload_floor: int,
) -> PkfRecord:
    parsed = parse_candidate_field(data, field_offset)
    if parsed is None:  # pragma: no cover - caller only passes candidates
        raise ValueError(f"not a candidate field: {field_offset:#x}")
    payload_offset, length, flag = parsed
    end_offset = payload_offset + length
    descriptor_offset = field_offset + 12
    descriptor_end = descriptor_offset + DESCRIPTOR_SIZE
    if descriptor_end <= len(data) and descriptor_end <= table_payload_floor:
        descriptor_status = "available"
        descriptor_hex = data[descriptor_offset:descriptor_end].hex(" ")
    elif descriptor_offset < len(data):
        descriptor_status = "overlaps_payload_or_eof"
        descriptor_hex = None
    else:
        descriptor_status = "missing"
        descriptor_hex = None

    return PkfRecord(
        table_index=table_index,
        slot_index=slot_index,
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
        descriptor_size=DESCRIPTOR_SIZE,
        descriptor_status=descriptor_status,
        descriptor_hex=descriptor_hex,
        payload=classify_payload(data, payload_offset, length),
    )


def build_tables(data: bytes, runs: list[list[int]]) -> list[PkfTable]:
    tables: list[PkfTable] = []
    for table_index, run in enumerate(runs):
        parsed_records = [parse_candidate_field(data, field_offset) for field_offset in run]
        payload_floor = min(record[0] for record in parsed_records if record is not None)
        records = [
            build_record(
                data,
                field_offset,
                table_index=table_index,
                slot_index=slot_index,
                table_payload_floor=payload_floor,
            )
            for slot_index, field_offset in enumerate(run)
        ]
        kind_counts = Counter(record.payload.kind for record in records)
        first_payload = min(record.payload_offset for record in records)
        last_payload_end = max(record.end_offset for record in records)
        tables.append(
            PkfTable(
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


def parse_pkf_file(path: Path, *, root: Path | None = None) -> PkfFile:
    data = path.read_bytes()
    candidates = find_candidate_fields(data)
    runs = select_table_runs(candidates)
    tables = build_tables(data, runs)
    records = [record for table in tables for record in table.records]
    ranges = merge_ranges((record.payload_offset, record.end_offset) for record in records)
    indexed_payload_bytes = sum(end - start for start, end in ranges)
    kind_counts = Counter(record.payload.kind for record in records)
    bmp_dimension_counts: Counter[str] = Counter()
    p3d_family_counts: Counter[str] = Counter()
    for record in records:
        payload = record.payload
        if payload.kind == "BMP" and payload.bmp_width is not None and payload.bmp_height is not None:
            bmp_dimension_counts[
                f"{payload.bmp_width}x{payload.bmp_height}x{payload.bmp_bpp}"
            ] += 1
        if payload.p3d_family is not None:
            p3d_family_counts[payload.p3d_family] += 1

    tail_unindexed_bytes = 0
    if ranges:
        tail_unindexed_bytes = max(0, len(data) - max(end for _, end in ranges))

    if root is not None:
        try:
            relative_path = str(path.relative_to(root))
        except ValueError:
            relative_path = path.name
    else:
        relative_path = path.name

    return PkfFile(
        path=str(path),
        relative_path=relative_path,
        size=len(data),
        size_hex=hex_int(len(data)),
        sha256_16=file_sha256_16(data),
        head32_hex=data[:32].hex(" "),
        candidate_record_fields=len(candidates),
        selected_table_count=len(tables),
        selected_entry_count=len(records),
        indexed_payload_bytes_union=indexed_payload_bytes,
        indexed_payload_coverage_ratio=round(indexed_payload_bytes / len(data), 6)
        if data
        else 0,
        tail_unindexed_bytes_after_last_indexed_payload=tail_unindexed_bytes,
        payload_kind_counts=dict(sorted(kind_counts.items())),
        bmp_dimension_counts=dict(sorted(bmp_dimension_counts.items())),
        p3d_family_counts=dict(sorted(p3d_family_counts.items())),
        tables=tables,
    )


def record_payload_bytes(path: Path, record: PkfRecord) -> bytes:
    with path.open("rb") as handle:
        handle.seek(record.payload_offset)
        return handle.read(record.length)


def palette_colors(payload: bytes) -> list[dict[str, int]]:
    if not (payload.startswith(b"RIFF") and len(payload) >= 12 and payload[8:12].rstrip() == b"PAL"):
        return []

    offset = 12
    while offset + 8 <= len(payload):
        chunk_id = payload[offset : offset + 4]
        chunk_size = struct.unpack_from("<I", payload, offset + 4)[0]
        chunk_start = offset + 8
        chunk_end = chunk_start + chunk_size
        if chunk_end > len(payload):
            return []
        if chunk_id == b"data" and chunk_size >= 4:
            version, count = struct.unpack_from("<HH", payload, chunk_start)
            if version not in {0x0300, 0x300}:
                return []
            colors: list[dict[str, int]] = []
            entry_offset = chunk_start + 4
            for index in range(count):
                if entry_offset + 4 > chunk_end:
                    break
                red, green, blue, flags = payload[entry_offset : entry_offset + 4]
                colors.append({"index": index, "r": red, "g": green, "b": blue, "flags": flags})
                entry_offset += 4
            return colors
        offset = chunk_end + (chunk_size % 2)
    return []


def to_dict(value: object) -> dict[str, object]:
    return asdict(value)
