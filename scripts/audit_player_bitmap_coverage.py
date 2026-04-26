#!/usr/bin/env python3
"""Deterministic coverage audit for PM99 player bitmap assets.

This script is research-only in PM99RE. It is designed to be promotable into
upstream editor tooling with minimal changes.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
EDITOR_ROOT = REPO_ROOT / "upstream" / "pm99-skezmod-db-editor"
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from assert_pm99_isolated_input import choose_preferred_game_root, ensure_not_legacy_path
from app.fdi_indexed import IndexedFDIFile
from app.minifoto_bitmap_archive import iter_minifoto_records, iter_obfuscated_bmp_records
from app.player_bitmap_discovery import discover_player_bitmap_payloads

J96_RE = re.compile(r"^J96(?P<player_id>\d{5})\.BMP$", re.IGNORECASE)
EXE_MARKERS = (
    "J96%05u",
    "DBDAT\\MINIFOTO\\%s.bmp",
    "DBDAT\\BIGFOTO\\",
    "%seq96%04d\\%s.bmp",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except Exception:
        return str(path)


def _candidate_first_existing(paths: Iterable[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _default_jug_path() -> Path:
    return choose_preferred_game_root() / "DBDAT" / "JUG98030.FDI"


def _default_minifoto_paths() -> list[Path]:
    default_game_root = choose_preferred_game_root()
    out = []
    for path in [
        default_game_root / "DBDAT" / "MINIFOTO.PKF",
        REPO_ROOT / "DBDAT" / "MINIFOTO.PKF",
        REPO_ROOT / "FDI-PKF" / "DBDAT" / "MINIFOTO.PKF",
        REPO_ROOT / "FDI-PKF" / "FDI-PKF" / "DBDAT" / "MINIFOTO.PKF",
        REPO_ROOT / ".local" / "iso" / "DbDat" / "MINIFOTO.PKF",
    ]:
        if path.exists():
            out.append(path)
    return out


def _default_bigfoto_dir() -> Path | None:
    candidate = REPO_ROOT / ".local" / "iso" / "DbDat" / "BIGFOTO"
    return candidate if candidate.exists() else None


def _default_scan_roots() -> list[Path]:
    default_game_root = choose_preferred_game_root()
    roots = []
    for path in [
        default_game_root / "DBDAT",
        REPO_ROOT / "DBDAT",
        REPO_ROOT / "FDI-PKF" / "DBDAT",
        REPO_ROOT / "FDI-PKF" / "FDI-PKF" / "DBDAT",
        REPO_ROOT / ".local" / "iso" / "DbDat",
    ]:
        if path.exists():
            roots.append(path)
    return roots


def _default_dbasepre_path() -> Path | None:
    return _candidate_first_existing(
        [
            choose_preferred_game_root() / "DBASEPRE.EXE",
            REPO_ROOT / ".local" / "iso" / "Dbasepre.exe",
            REPO_ROOT / ".local" / "iso" / "DBASEPRE.EXE",
        ]
    )


def _collect_jug_ids(jug_file: Path) -> set[int]:
    indexed = IndexedFDIFile.from_path(jug_file)
    return {int(entry.record_id) for entry in indexed.entries if int(entry.record_id) > 0}


def _scan_minifoto(minifoto_paths: list[Path]) -> tuple[list[dict[str, object]], set[int], dict[str, list[str]]]:
    file_rows: list[dict[str, object]] = []
    id_union: set[int] = set()
    sha_groups: dict[str, list[str]] = defaultdict(list)
    for path in minifoto_paths:
        records = iter_minifoto_records(path)
        record_ids = {int(record.player_record_id) for record in records if int(record.player_record_id) > 0}
        id_union.update(record_ids)
        sha = _sha256(path)
        sha_groups[sha].append(_rel(path))
        file_rows.append(
            {
                "path": _rel(path),
                "sha256": sha,
                "records": len(records),
                "unique_ids": len(record_ids),
                "dims": sorted({(int(record.width), int(record.height), int(record.bits_per_pixel)) for record in records}),
                "min_id": min(record_ids) if record_ids else None,
                "max_id": max(record_ids) if record_ids else None,
            }
        )
    file_rows.sort(key=lambda item: str(item["path"]))
    return file_rows, id_union, {key: sorted(value) for key, value in sha_groups.items()}


def _scan_bigfoto(bigfoto_dir: Path | None) -> tuple[list[dict[str, object]], set[int]]:
    if bigfoto_dir is None or not bigfoto_dir.exists():
        return [], set()
    rows: list[dict[str, object]] = []
    id_union: set[int] = set()
    for path in sorted(bigfoto_dir.glob("*.pkf")) + sorted(bigfoto_dir.glob("*.PKF")):
        records = iter_obfuscated_bmp_records(path, file_name_pattern=J96_RE)
        record_ids = set()
        for record in records:
            match = J96_RE.match(record.file_name)
            if match:
                record_ids.add(int(match.group("player_id")))
        if not record_ids:
            continue
        id_union.update(record_ids)
        rows.append(
            {
                "path": _rel(path),
                "sha256": _sha256(path),
                "records": len(records),
                "unique_ids": len(record_ids),
                "dims": sorted({(int(record.width), int(record.height), int(record.bits_per_pixel)) for record in records}),
                "min_id": min(record_ids),
                "max_id": max(record_ids),
            }
        )
    rows.sort(key=lambda item: str(item["path"]))
    return rows, id_union


def _classify_j96_archive(path: Path) -> str:
    upper_parts = [part.upper() for part in path.parts]
    if path.name.upper() == "MINIFOTO.PKF":
        return "MINIFOTO"
    if "BIGFOTO" in upper_parts:
        return "BIGFOTO"
    return "OTHER"


def _scan_j96_archives(scan_roots: list[Path]) -> dict[str, object]:
    pkf_paths: set[Path] = set()
    for root in scan_roots:
        for path in root.rglob("*.pkf"):
            if path.is_file():
                pkf_paths.add(path)
        for path in root.rglob("*.PKF"):
            if path.is_file():
                pkf_paths.add(path)

    archives_with_j96: list[dict[str, object]] = []
    parse_errors: list[dict[str, str]] = []
    source_counts: Counter[str] = Counter()
    for path in sorted(pkf_paths):
        try:
            records = iter_obfuscated_bmp_records(path, file_name_pattern=J96_RE)
        except Exception as exc:  # pragma: no cover - corpus-dependent malformed content
            parse_errors.append({"path": _rel(path), "error": str(exc)})
            continue
        if not records:
            continue
        record_ids = set()
        for record in records:
            match = J96_RE.match(record.file_name)
            if match:
                record_ids.add(int(match.group("player_id")))
        if not record_ids:
            continue
        source = _classify_j96_archive(path)
        source_counts[source] += 1
        archives_with_j96.append(
            {
                "path": _rel(path),
                "source_family": source,
                "sha256": _sha256(path),
                "records": len(records),
                "unique_ids": len(record_ids),
            }
        )

    expected = {"MINIFOTO", "BIGFOTO"}
    detected_sources = set(source_counts.keys())
    unexpected = sorted(detected_sources.difference(expected))
    return {
        "scan_roots": [_rel(root) for root in scan_roots],
        "pkf_files_scanned": len(pkf_paths),
        "archives_with_j96_count": len(archives_with_j96),
        "archives_with_j96": archives_with_j96,
        "source_family_counts": dict(source_counts),
        "only_expected_source_families": len(unexpected) == 0,
        "unexpected_source_families": unexpected,
        "parse_error_count": len(parse_errors),
        "parse_errors": parse_errors[:50],
    }


def _find_ascii_offsets(data: bytes, marker: str) -> list[int]:
    needle = marker.encode("ascii")
    offsets: list[int] = []
    cursor = 0
    while True:
        hit = data.find(needle, cursor)
        if hit < 0:
            break
        offsets.append(hit)
        cursor = hit + 1
    return offsets


def _scan_exe_markers(exe_path: Path | None) -> dict[str, object]:
    if exe_path is None:
        return {"enabled": False, "reason": "No DBASEPRE executable path provided/found"}
    if not exe_path.exists():
        return {"enabled": False, "reason": f"Executable not found: {exe_path}"}

    data = exe_path.read_bytes()
    markers = []
    all_found = True
    for marker in EXE_MARKERS:
        offsets = _find_ascii_offsets(data, marker)
        if not offsets:
            all_found = False
        markers.append(
            {
                "marker": marker,
                "found": bool(offsets),
                "offsets_hex": [f"0x{offset:x}" for offset in offsets[:20]],
                "hit_count": len(offsets),
            }
        )
    return {
        "enabled": True,
        "exe_path": _rel(exe_path),
        "exe_sha256": _sha256(exe_path),
        "all_expected_markers_present": all_found,
        "markers": markers,
    }


def _scan_payload_for_embedded_images(jug_file: Path, *, enabled: bool) -> dict[str, object]:
    if not enabled:
        return {"enabled": False, "reason": "Disabled by caller"}

    report = discover_player_bitmap_payloads(player_file=str(jug_file), include_rows_without_signals=False)
    invalid_reasons: Counter[str] = Counter()
    for row in list(report.rows or []):
        for candidate in list(row.image_candidates or []):
            if bool(candidate.valid):
                continue
            reason = str(candidate.reason or "unknown")
            invalid_reasons[reason] += 1

    return {
        "enabled": True,
        "total_indexed_players": int(report.total_indexed_players),
        "selected_player_count": int(report.selected_player_count),
        "rows_emitted": int(report.emitted_row_count),
        "players_with_image_candidates": int(report.players_with_image_candidates),
        "players_with_validated_images": int(report.players_with_validated_images),
        "total_image_candidates": int(report.total_image_candidates),
        "total_validated_images": int(report.total_validated_images),
        "top_invalid_candidate_reasons": [
            {"reason": reason, "count": int(count)}
            for reason, count in invalid_reasons.most_common(20)
        ],
    }


def _scan_jug_for_18077_presence() -> list[dict[str, object]]:
    results = []
    for path in sorted(REPO_ROOT.rglob("JUG*.FDI")):
        try:
            ids = _collect_jug_ids(path)
            results.append({"path": _rel(path), "players": len(ids), "has_18077": bool(18077 in ids)})
        except Exception as exc:
            results.append({"path": _rel(path), "error": str(exc)})
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit player bitmap coverage and provenance in local PM99 corpora.")
    parser.add_argument("--jug-file", default="", help="Path to JUG*.FDI file")
    parser.add_argument(
        "--minifoto",
        action="append",
        default=[],
        help="Path to MINIFOTO.PKF (repeatable). If omitted, known local defaults are used.",
    )
    parser.add_argument(
        "--bigfoto-dir",
        default="",
        help="Path to BIGFOTO directory",
    )
    parser.add_argument(
        "--scan-root",
        action="append",
        default=[],
        help="Root folder to sweep for J96 archives (repeatable). If omitted, known local defaults are used.",
    )
    parser.add_argument(
        "--dbasepre-exe",
        default="",
        help="Path to DBASEPRE executable for string-marker evidence",
    )
    parser.add_argument(
        "--include-payload-scan",
        action="store_true",
        help="Also run player payload embedded-image discovery over JUG (slower).",
    )
    parser.add_argument("--output", required=True, help="Output JSON artifact path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    jug_file = (
        ensure_not_legacy_path(args.jug_file, label="JUG file")
        if str(args.jug_file or "").strip()
        else _default_jug_path()
    )
    if not jug_file.exists():
        raise SystemExit(f"JUG file not found: {jug_file}")

    minifoto_paths = [
        ensure_not_legacy_path(item, label="MINIFOTO archive")
        for item in list(args.minifoto or [])
        if str(item).strip()
    ]
    if not minifoto_paths:
        minifoto_paths = _default_minifoto_paths()
    minifoto_paths = [path for path in minifoto_paths if path.exists()]

    bigfoto_dir = (
        ensure_not_legacy_path(args.bigfoto_dir, label="BIGFOTO directory")
        if str(args.bigfoto_dir or "").strip()
        else _default_bigfoto_dir()
    )
    scan_roots = [
        ensure_not_legacy_path(item, label="scan root")
        for item in list(args.scan_root or [])
        if str(item).strip()
    ]
    if not scan_roots:
        scan_roots = _default_scan_roots()
    scan_roots = [path for path in scan_roots if path.exists()]

    dbasepre_exe = (
        ensure_not_legacy_path(args.dbasepre_exe, label="DBASEPRE executable")
        if str(args.dbasepre_exe or "").strip()
        else _default_dbasepre_path()
    )

    jug_ids = _collect_jug_ids(jug_file)
    minifoto_files, minifoto_ids, minifoto_sha_groups = _scan_minifoto(minifoto_paths)
    bigfoto_files, bigfoto_ids = _scan_bigfoto(bigfoto_dir)
    j96_archive_scan = _scan_j96_archives(scan_roots)
    exe_markers = _scan_exe_markers(dbasepre_exe)
    payload_scan = _scan_payload_for_embedded_images(jug_file, enabled=bool(args.include_payload_scan))

    combined_ids = set(minifoto_ids).union(bigfoto_ids)
    combined_hits = combined_ids.intersection(jug_ids)
    combined_not_in_jug = sorted(combined_ids.difference(jug_ids))

    output = {
        "scope": "player_bitmap_coverage_audit",
        "status": "completed",
        "inputs": {
            "jug_file": {"path": _rel(jug_file), "sha256": _sha256(jug_file)},
            "minifoto_files": minifoto_files,
            "bigfoto_dir": _rel(bigfoto_dir) if bigfoto_dir is not None else "",
            "scan_roots": [_rel(root) for root in scan_roots],
            "dbasepre_exe": _rel(dbasepre_exe) if dbasepre_exe is not None else "",
        },
        "coverage": {
            "jug_players": len(jug_ids),
            "minifoto_unique_ids": len(minifoto_ids),
            "bigfoto_unique_ids": len(bigfoto_ids),
            "combined_unique_photo_ids": len(combined_ids),
            "players_with_any_photo_in_jug": len(combined_hits),
            "players_without_any_photo_in_jug": len(jug_ids.difference(combined_ids)),
            "coverage_minifoto_pct": round((len(minifoto_ids.intersection(jug_ids)) / len(jug_ids)) * 100, 4)
            if jug_ids
            else 0.0,
            "coverage_combined_pct": round((len(combined_hits) / len(jug_ids)) * 100, 4) if jug_ids else 0.0,
            "big_only_ids": sorted(bigfoto_ids.difference(minifoto_ids)),
            "mini_only_ids_count": len(minifoto_ids.difference(bigfoto_ids)),
            "combined_ids_not_in_jug": combined_not_in_jug,
            "has_18077_in_primary_jug": bool(18077 in jug_ids),
        },
        "archive_provenance": {
            "minifoto_sha_groups": minifoto_sha_groups,
            "bigfoto_files_with_j96_count": len(bigfoto_files),
            "bigfoto_files_with_j96": bigfoto_files,
            "j96_archive_scan": j96_archive_scan,
        },
        "executable_evidence": exe_markers,
        "payload_embedded_image_scan": payload_scan,
        "cross_jug_18077_presence": _scan_jug_for_18077_presence(),
        "upstream_reuse_targets": {
            "archive_parser": "upstream/pm99-skezmod-db-editor/app/minifoto_bitmap_archive.py",
            "indexed_jug_parser": "upstream/pm99-skezmod-db-editor/app/fdi_indexed.py",
            "payload_discovery": "upstream/pm99-skezmod-db-editor/app/player_bitmap_discovery.py",
            "review_builder": "upstream/pm99-skezmod-db-editor/scripts/build_player_bitmap_review.py",
        },
        "conclusion": {
            "missing_player_photos_are_absent_in_corpus": bool(len(jug_ids.difference(combined_ids)) > 0),
            "j96_photo_sources_limited_to_expected_families": bool(
                j96_archive_scan.get("only_expected_source_families", False)
            ),
            "embedded_player_images_validated_in_jug_payloads": bool(
                payload_scan.get("total_validated_images", 0) if payload_scan.get("enabled") else 0
            ),
        },
    }

    output_path = Path(args.output).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("Player Bitmap Coverage Audit")
    print(f"Output: {output_path}")
    print(f"JUG players: {output['coverage']['jug_players']}")
    print(f"Combined photo IDs: {output['coverage']['combined_unique_photo_ids']}")
    print(f"Players without any photo in JUG: {output['coverage']['players_without_any_photo_in_jug']}")
    print(f"Combined coverage: {output['coverage']['coverage_combined_pct']}%")
    print(
        "Sources: "
        f"{output['archive_provenance']['j96_archive_scan']['source_family_counts']}"
    )
    if output["conclusion"]["missing_player_photos_are_absent_in_corpus"]:
        print("Conclusion: Missing players are absent from current photo corpora (not extraction misses).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
