#!/usr/bin/env python3
"""Smoke tests for upstream PKF parser/searcher helpers (non-GUI)."""
import os
import sys
import traceback
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
_editor_root = Path(os.environ.get("PM99_EDITOR_ROOT", _project_root / "upstream" / "pm99-skezmod-db-editor")).resolve()
if str(_editor_root) not in sys.path:
    sys.path.insert(0, str(_editor_root))

try:
    from app.pkf import PKFFile, PKFDecoderError
    from app.pkf_searcher import PKFSearcher
    from app.xor import xor_decode
except Exception as e:
    print("Import error:", e)
    traceback.print_exc()
    sys.exit(2)


def format_hex_preview(data: bytes, width: int = 16, start_offset: int = 0, max_lines: int = 10):
    if not data:
        return "(empty)", False
    lines = []
    end_offset = min(len(data), start_offset + max_lines * width)
    for offset in range(start_offset, end_offset, width):
        chunk = data[offset:offset + width]
        hex_part = " ".join(f"{b:02X}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{offset:08X}  {hex_part:<{width * 3 - 1}}  {ascii_part}")
    has_more = end_offset < len(data)
    if has_more:
        lines.append(f"… ({len(data) - end_offset} more bytes)")
    return "\n".join(lines), has_more


def find_pkf_candidates():
    candidates = []
    for base in (
        Path(os.environ["PM99_PKF_ROOT"]) if os.environ.get("PM99_PKF_ROOT") else None,
        _project_root / "DBDAT",
        _project_root / ".local",
        _project_root / "work" / "fixtures",
    ):
        if base is None:
            continue
        if not base.exists():
            continue
        for ext in ("*.PKF", "*.pkf"):
            for p in sorted(base.rglob(ext)):
                candidates.append(p)
    return candidates


def main():
    candidates = find_pkf_candidates()
    if not candidates:
        print("No PKF files found for smoke test")
        return 1
    pkf_path = candidates[0]
    print("Using PKF file:", pkf_path)
    try:
        data = pkf_path.read_bytes()
        pkf = PKFFile.from_bytes(pkf_path.name, data)
        print("Parsed PKF:", pkf_path.name, "entries=", len(pkf), "format_hint=", getattr(pkf, "format_hint", None))
    except Exception as e:
        print("Failed to parse PKF:", e)
        traceback.print_exc()
        return 2

    entries = list(pkf.list_entries())[:3]
    for entry in entries:
        print(f"Entry {entry.index}: offset=0x{entry.offset:08X}, length={entry.length}, name={getattr(entry, 'name', None)}")
        snippet, more = format_hex_preview(entry.raw_bytes, max_lines=4)
        print(snippet)
        try:
            decoded = pkf.decode_payload(entry.raw_bytes)
            t = type(decoded)
            ln = len(decoded) if hasattr(decoded, "__len__") else None
            print("decode_payload ->", t, "len=", ln)
        except Exception as e:
            print("decode_payload raised:", repr(e))
        # try XOR transform
        try:
            key = 0x5A
            x = xor_decode(entry.raw_bytes[:64], key)
            print("xor_decode snippet:", x[:32].hex())
        except Exception as e:
            print("xor_decode failed:", e)

    # PKFSearcher test
    search_dir = pkf_path.parent
    try:
        searcher = PKFSearcher(directory=search_dir, recursive=False, file_pattern="*.pkf", max_results=50, context_size=32)
        found = searcher.find_pkf_files()
        print("PKFSearcher find_pkf_files ->", len(found), "files")
        # perform a lightweight text search for a common short token
        try:
            results = searcher.search_text("the", case_sensitive=False, encoding="utf-8", use_parallel=False)
            print("search_text('the') ->", len(results), "results (showing up to 3)")
            for r in results[:3]:
                try:
                    print("  ", r.file_path, r.entry_index, hex(r.absolute_offset))
                except Exception:
                    print("  <result: cannot pretty-print>")
        except Exception as e:
            print("search_text raised:", e)
    except Exception as e:
        print("PKFSearcher failed to initialize:", e)
        traceback.print_exc()

    print("Smoke test finished successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
