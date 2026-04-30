#!/usr/bin/env python3
"""Summarize PM99 P3D-like records discovered inside SIMULDAT PKFs."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import argparse
import json
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
PKF_VIEWER_ROOT = REPO_ROOT / "tools" / "pkf-viewer"
sys.path.insert(0, str(PKF_VIEWER_ROOT))

from backend.pkf_parser import parse_pkf_file  # noqa: E402


def summarize(root: Path) -> dict[str, object]:
    family_counts: Counter[str] = Counter()
    label_counts: Counter[str] = Counter()
    optional_flags: Counter[str] = Counter()
    trailing_by_family: dict[str, Counter[int]] = defaultdict(Counter)
    duplicate_hashes: Counter[str] = Counter()
    examples: list[dict[str, object]] = []
    largest: list[dict[str, object]] = []
    total_records = 0
    total_bytes = 0
    pkf_count = 0

    for path in sorted(root.rglob("*.pkf")):
        parsed = parse_pkf_file(path, root=root)
        p3d_records = [
            (table, record)
            for table in parsed.tables
            for record in table.records
            if record.payload.kind == "P3D-like binary"
        ]
        if not p3d_records:
            continue

        pkf_count += 1
        for table, record in p3d_records:
            payload = record.payload
            total_records += 1
            total_bytes += record.length
            family_counts[payload.p3d_family or "unknown"] += 1
            optional_flags[str(payload.p3d_optional_header_flag)] += 1
            duplicate_hashes[payload.sha256_16] += 1
            if payload.p3d_label:
                label_counts[payload.p3d_label] += 1
            if payload.p3d_family is not None and payload.p3d_chunk128_trailing_bytes is not None:
                trailing_by_family[payload.p3d_family][payload.p3d_chunk128_trailing_bytes] += 1
            row = {
                "pkf": parsed.relative_path,
                "table": table.table_index,
                "slot": record.slot_index,
                "length": record.length,
                "family": payload.p3d_family,
                "label": payload.p3d_label,
                "marker_field_count": payload.p3d_marker_field_count,
                "optional_header_flag": payload.p3d_optional_header_flag,
                "optional_header_floats": payload.p3d_optional_header_floats,
                "record_start_offset": payload.p3d_record_start_offset,
                "first_inner_marker_hex": payload.p3d_first_inner_marker_hex,
                "first_inner_marker_field_count": payload.p3d_first_inner_marker_field_count,
                "chunk128_loader_iterations": payload.p3d_chunk128_loader_iterations,
                "chunk128_trailing_bytes": payload.p3d_chunk128_trailing_bytes,
                "chunk_name_samples": payload.p3d_chunk_name_samples,
                "sha256_16": payload.sha256_16,
            }
            if len(examples) < 20:
                examples.append(row)
            largest.append(row)

    duplicate_groups = sum(1 for count in duplicate_hashes.values() if count > 1)
    return {
        "root": str(root),
        "p3d_pkf_count": pkf_count,
        "p3d_record_count": total_records,
        "p3d_total_bytes": total_bytes,
        "family_counts": dict(sorted(family_counts.items())),
        "top_labels": label_counts.most_common(30),
        "optional_header_flags": dict(sorted(optional_flags.items())),
        "duplicate_hash_groups": duplicate_groups,
        "trailing_bytes_by_family": {
            family: counter.most_common(12)
            for family, counter in sorted(trailing_by_family.items())
        },
        "largest_records": sorted(largest, key=lambda row: int(row["length"]), reverse=True)[:20],
        "examples": examples,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root",
        nargs="?",
        default=str(REPO_ROOT / ".local" / "iso" / "Simuldat"),
        help="SIMULDAT root to scan",
    )
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve()
    if not root.exists():
        parser.error(f"SIMULDAT root does not exist: {root}")
    print(json.dumps(summarize(root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
