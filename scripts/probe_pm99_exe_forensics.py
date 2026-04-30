#!/usr/bin/env python3
"""Read-only forensic survey for PM99 MANAGPRE.EXE variants.

The probe intentionally does not patch or copy proprietary executables. It
emits structural metadata, byte coverage, imports, import references, strings,
and variant byte-diff summaries so follow-up experiments can be based on
repeatable evidence instead of one-off `strings`/`objdump` output.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import math
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


IMAGE_DIRECTORY_NAMES = [
    "export",
    "import",
    "resource",
    "exception",
    "security",
    "basereloc",
    "debug",
    "architecture",
    "globalptr",
    "tls",
    "load_config",
    "bound_import",
    "iat",
    "delay_import",
    "clr",
    "reserved",
]

SECTION_CHARACTERISTICS = {
    0x00000020: "code",
    0x00000040: "initialized_data",
    0x00000080: "uninitialized_data",
    0x02000000: "discardable",
    0x04000000: "not_cached",
    0x08000000: "not_paged",
    0x10000000: "shared",
    0x20000000: "execute",
    0x40000000: "read",
    0x80000000: "write",
}

INTERESTING_STRING_PATTERNS = {
    "install_registry": re.compile(r"(Software\\Gremlin|DISK\.ID|PREMIER6|PM99\.EXE|PCF5)", re.I),
    "config": re.compile(r"(manager\.ini|sip\.ini|FULL SCREEN|SCREEN POSITION|MUSIC|SOUND|TRANSITIONS|PIS LEVEL)", re.I),
    "save_data": re.compile(r"(save\\|main\.dat|dbdat\\|eq98%03u|jug98%03u|\.fdi|TACTIC|partido\.dat)", re.I),
    "assets": re.compile(r"(recursos\\|simuldat\\|\.bmp|\.gif|\.pal|\.pkf|\.p3d|\.wav|\.avi|\.s3m)", re.I),
    "legacy_api_risk": re.compile(r"(free space|hard drive|CDROM|DirectX|16 colors|Out of Memory|reinstall|Application cannot)", re.I),
    "debug_or_demo": re.compile(r"(debug|assert|testeo|test|demo|not available in ects demo)", re.I),
    "compression": re.compile(r"(incorrect data check|incompatible version|buffer error|stream error|zlib|inflate|deflate)", re.I),
    "graphics_options": re.compile(r"(resolution|hardware options|graphics quality|gouraud|bilinear|textures|shadow|grass|cameras)", re.I),
}


@dataclass(frozen=True)
class Section:
    name: str
    virtual_size: int
    virtual_address: int
    raw_size: int
    raw_pointer: int
    characteristics: int

    def raw_end(self) -> int:
        return self.raw_pointer + self.raw_size

    def va_start(self, image_base: int) -> int:
        return image_base + self.virtual_address

    def va_end(self, image_base: int) -> int:
        return image_base + self.virtual_address + max(self.virtual_size, self.raw_size)

    def contains_rva(self, rva: int) -> bool:
        size = max(self.virtual_size, self.raw_size)
        return self.virtual_address <= rva < self.virtual_address + size

    def rva_to_offset(self, rva: int) -> int:
        return self.raw_pointer + (rva - self.virtual_address)


class PEImage:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.e_lfanew = self._u32(0x3C)
        if data[:2] != b"MZ":
            raise ValueError("missing MZ header")
        if data[self.e_lfanew : self.e_lfanew + 4] != b"PE\0\0":
            raise ValueError("missing PE signature")

        coff = self.e_lfanew + 4
        (
            self.machine,
            self.number_of_sections,
            self.timestamp,
            self.pointer_to_symbol_table,
            self.number_of_symbols,
            self.size_of_optional_header,
            self.characteristics,
        ) = struct.unpack_from("<HHIIIHH", data, coff)

        optional = coff + 20
        self.optional_header_offset = optional
        self.magic = self._u16(optional)
        if self.magic != 0x10B:
            raise ValueError(f"unsupported optional header magic 0x{self.magic:04x}")
        self.major_linker_version = data[optional + 2]
        self.minor_linker_version = data[optional + 3]
        self.size_of_code = self._u32(optional + 4)
        self.size_of_initialized_data = self._u32(optional + 8)
        self.size_of_uninitialized_data = self._u32(optional + 12)
        self.address_of_entry_point = self._u32(optional + 16)
        self.base_of_code = self._u32(optional + 20)
        self.base_of_data = self._u32(optional + 24)
        self.image_base = self._u32(optional + 28)
        self.section_alignment = self._u32(optional + 32)
        self.file_alignment = self._u32(optional + 36)
        self.major_os_version = self._u16(optional + 40)
        self.minor_os_version = self._u16(optional + 42)
        self.major_subsystem_version = self._u16(optional + 48)
        self.minor_subsystem_version = self._u16(optional + 50)
        self.size_of_image = self._u32(optional + 56)
        self.size_of_headers = self._u32(optional + 60)
        self.checksum = self._u32(optional + 64)
        self.subsystem = self._u16(optional + 68)
        self.dll_characteristics = self._u16(optional + 70)
        self.size_of_stack_reserve = self._u32(optional + 72)
        self.size_of_heap_reserve = self._u32(optional + 80)
        self.number_of_rva_and_sizes = self._u32(optional + 92)

        self.data_directories: list[dict[str, Any]] = []
        dd_off = optional + 96
        for index in range(min(self.number_of_rva_and_sizes, len(IMAGE_DIRECTORY_NAMES))):
            rva, size = struct.unpack_from("<II", data, dd_off + index * 8)
            self.data_directories.append(
                {"index": index, "name": IMAGE_DIRECTORY_NAMES[index], "rva": rva, "size": size}
            )

        sections_off = optional + self.size_of_optional_header
        self.sections: list[Section] = []
        for index in range(self.number_of_sections):
            off = sections_off + index * 40
            raw_name = data[off : off + 8].split(b"\0", 1)[0]
            name = raw_name.decode("ascii", errors="replace")
            virtual_size, virtual_address, raw_size, raw_pointer = struct.unpack_from("<IIII", data, off + 8)
            characteristics = self._u32(off + 36)
            self.sections.append(
                Section(
                    name=name,
                    virtual_size=virtual_size,
                    virtual_address=virtual_address,
                    raw_size=raw_size,
                    raw_pointer=raw_pointer,
                    characteristics=characteristics,
                )
            )

    def _u16(self, offset: int) -> int:
        return struct.unpack_from("<H", self.data, offset)[0]

    def _u32(self, offset: int) -> int:
        return struct.unpack_from("<I", self.data, offset)[0]

    def rva_to_offset(self, rva: int) -> int | None:
        if 0 <= rva < self.size_of_headers:
            return rva
        for section in self.sections:
            if section.contains_rva(rva):
                off = section.rva_to_offset(rva)
                if 0 <= off < len(self.data):
                    return off
        return None

    def va_to_offset(self, va: int) -> int | None:
        return self.rva_to_offset(va - self.image_base)

    def offset_to_va(self, offset: int) -> int | None:
        if 0 <= offset < self.size_of_headers:
            return self.image_base + offset
        for section in self.sections:
            if section.raw_pointer <= offset < section.raw_end():
                return self.image_base + section.virtual_address + (offset - section.raw_pointer)
        return None

    def section_for_offset(self, offset: int) -> str:
        if 0 <= offset < self.size_of_headers:
            return "headers"
        for section in self.sections:
            if section.raw_pointer <= offset < section.raw_end():
                return section.name
        return "unmapped"

    def section_for_va(self, va: int) -> str:
        rva = va - self.image_base
        for section in self.sections:
            if section.contains_rva(rva):
                return section.name
        if 0 <= rva < self.size_of_headers:
            return "headers"
        return "unmapped"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = [0] * 256
    for byte in data:
        counts[byte] += 1
    total = len(data)
    return -sum((count / total) * math.log2(count / total) for count in counts if count)


def run_lengths(data: bytes, needle: int, *, min_len: int) -> list[dict[str, int]]:
    out: list[dict[str, int]] = []
    start: int | None = None
    for index, byte in enumerate(data):
        if byte == needle:
            if start is None:
                start = index
        elif start is not None:
            if index - start >= min_len:
                out.append({"offset": start, "length": index - start})
            start = None
    if start is not None and len(data) - start >= min_len:
        out.append({"offset": start, "length": len(data) - start})
    return out


def section_flags(value: int) -> list[str]:
    return [name for bit, name in SECTION_CHARACTERISTICS.items() if value & bit]


def parse_imports(pe: PEImage) -> list[dict[str, Any]]:
    import_dir = next((d for d in pe.data_directories if d["name"] == "import"), None)
    if not import_dir or not import_dir["rva"]:
        return []

    off = pe.rva_to_offset(import_dir["rva"])
    if off is None:
        return []

    imports: list[dict[str, Any]] = []
    descriptor_index = 0
    while off + descriptor_index * 20 + 20 <= len(pe.data):
        desc_off = off + descriptor_index * 20
        original_first_thunk, timestamp, forwarder_chain, name_rva, first_thunk = struct.unpack_from(
            "<IIIII", pe.data, desc_off
        )
        if not any((original_first_thunk, timestamp, forwarder_chain, name_rva, first_thunk)):
            break
        name_off = pe.rva_to_offset(name_rva)
        dll = read_c_string(pe.data, name_off) if name_off is not None else f"<bad-rva-0x{name_rva:x}>"
        thunk_rva = original_first_thunk or first_thunk
        thunk_off = pe.rva_to_offset(thunk_rva)
        entries: list[dict[str, Any]] = []
        thunk_index = 0
        if thunk_off is not None:
            while thunk_off + thunk_index * 4 + 4 <= len(pe.data):
                thunk = pe._u32(thunk_off + thunk_index * 4)
                if thunk == 0:
                    break
                iat_rva = first_thunk + thunk_index * 4
                iat_va = pe.image_base + iat_rva
                if thunk & 0x80000000:
                    entries.append(
                        {
                            "kind": "ordinal",
                            "ordinal": thunk & 0xFFFF,
                            "iat_rva": iat_rva,
                            "iat_va": iat_va,
                        }
                    )
                else:
                    hint_name_off = pe.rva_to_offset(thunk)
                    if hint_name_off is None:
                        name = f"<bad-rva-0x{thunk:x}>"
                        hint = None
                    else:
                        hint = pe._u16(hint_name_off)
                        name = read_c_string(pe.data, hint_name_off + 2)
                    entries.append(
                        {
                            "kind": "name",
                            "name": name,
                            "hint": hint,
                            "iat_rva": iat_rva,
                            "iat_va": iat_va,
                        }
                    )
                thunk_index += 1
        imports.append(
            {
                "dll": dll,
                "descriptor_rva": import_dir["rva"] + descriptor_index * 20,
                "first_thunk_rva": first_thunk,
                "entries": entries,
            }
        )
        descriptor_index += 1
    return imports


def read_c_string(data: bytes, offset: int | None, *, limit: int = 4096) -> str:
    if offset is None or offset < 0 or offset >= len(data):
        return ""
    end = offset
    max_end = min(len(data), offset + limit)
    while end < max_end and data[end] != 0:
        end += 1
    return data[offset:end].decode("cp1252", errors="replace")


def extract_ascii_strings(data: bytes, *, min_len: int = 4) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    start: int | None = None
    for index, byte in enumerate(data + b"\0"):
        is_printable = 32 <= byte <= 126
        if is_printable:
            if start is None:
                start = index
        elif start is not None:
            if index - start >= min_len:
                text = data[start:index].decode("ascii", errors="replace")
                out.append({"offset": start, "length": index - start, "text": text, "encoding": "ascii"})
            start = None
    return out


def extract_utf16le_strings(data: bytes, *, min_chars: int = 4) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for parity in (0, 1):
        start: int | None = None
        chars: list[int] = []
        index = parity
        while index + 1 < len(data):
            lo, hi = data[index], data[index + 1]
            is_printable = hi == 0 and 32 <= lo <= 126
            if is_printable:
                if start is None:
                    start = index
                    chars = []
                chars.append(lo)
            else:
                if start is not None and len(chars) >= min_chars:
                    out.append(
                        {
                            "offset": start,
                            "length": len(chars) * 2,
                            "text": bytes(chars).decode("ascii", errors="replace"),
                            "encoding": "utf16le_ascii",
                        }
                    )
                start = None
                chars = []
            index += 2
        if start is not None and len(chars) >= min_chars:
            out.append(
                {
                    "offset": start,
                    "length": len(chars) * 2,
                    "text": bytes(chars).decode("ascii", errors="replace"),
                    "encoding": "utf16le_ascii",
                }
            )
    return sorted(out, key=lambda item: item["offset"])


def classify_strings(pe: PEImage, strings: list[dict[str, Any]], *, sample_limit: int) -> dict[str, Any]:
    categories: dict[str, dict[str, Any]] = {
        key: {"count": 0, "samples": []} for key in INTERESTING_STRING_PATTERNS
    }
    for item in strings:
        text = item["text"]
        for key, pattern in INTERESTING_STRING_PATTERNS.items():
            if not pattern.search(text):
                continue
            categories[key]["count"] += 1
            if len(categories[key]["samples"]) < sample_limit:
                off = int(item["offset"])
                categories[key]["samples"].append(
                    {
                        "offset": off,
                        "va": pe.offset_to_va(off),
                        "section": pe.section_for_offset(off),
                        "encoding": item["encoding"],
                        "text": text,
                    }
                )
    return categories


def import_reference_summary(pe: PEImage, imports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    text_sections = [
        section
        for section in pe.sections
        if section.characteristics & 0x20000000 and section.raw_size and section.raw_pointer < len(pe.data)
    ]
    text_chunks = [(section, pe.data[section.raw_pointer : min(section.raw_end(), len(pe.data))]) for section in text_sections]

    all_entries: list[tuple[str, dict[str, Any]]] = []
    for dll in imports:
        for entry in dll["entries"]:
            all_entries.append((dll["dll"], entry))

    stub_by_iat: dict[int, list[int]] = {}
    for section, chunk in text_chunks:
        base_va = section.va_start(pe.image_base)
        for dll, entry in all_entries:
            iat_va = int(entry["iat_va"])
            pattern = b"\xff\x25" + struct.pack("<I", iat_va)
            start = 0
            while True:
                found = chunk.find(pattern, start)
                if found < 0:
                    break
                stub_by_iat.setdefault(iat_va, []).append(base_va + found)
                start = found + 1

    summary: list[dict[str, Any]] = []
    for dll, entry in all_entries:
        iat_va = int(entry["iat_va"])
        direct_refs: list[int] = []
        direct_calls: list[int] = []
        stub_calls: list[int] = []
        imm = struct.pack("<I", iat_va)
        call_abs = b"\xff\x15" + imm

        for section, chunk in text_chunks:
            base_va = section.va_start(pe.image_base)
            start = 0
            while True:
                found = chunk.find(imm, start)
                if found < 0:
                    break
                direct_refs.append(base_va + found)
                start = found + 1

            start = 0
            while True:
                found = chunk.find(call_abs, start)
                if found < 0:
                    break
                direct_calls.append(base_va + found)
                start = found + 1

            for stub_va in stub_by_iat.get(iat_va, []):
                # Relative CALL rel32 target = next instruction + rel32.
                for found in find_rel32_calls_to(chunk, base_va, stub_va):
                    stub_calls.append(found)

        name = entry.get("name") if entry["kind"] == "name" else f"#{entry['ordinal']}"
        summary.append(
            {
                "dll": dll,
                "name": name,
                "iat_va": iat_va,
                "direct_reference_count": len(direct_refs),
                "direct_call_count": len(direct_calls),
                "stub_vas": sorted(stub_by_iat.get(iat_va, []))[:16],
                "stub_call_count": len(set(stub_calls)),
                "sample_direct_references": sorted(direct_refs)[:12],
                "sample_direct_calls": sorted(direct_calls)[:12],
                "sample_stub_calls": sorted(set(stub_calls))[:12],
            }
        )
    return summary


def find_rel32_calls_to(chunk: bytes, base_va: int, target_va: int) -> Iterable[int]:
    start = 0
    while True:
        found = chunk.find(b"\xe8", start)
        if found < 0 or found + 5 > len(chunk):
            break
        rel = struct.unpack_from("<i", chunk, found + 1)[0]
        next_va = base_va + found + 5
        if next_va + rel == target_va:
            yield base_va + found
        start = found + 1


def diff_summary(reference: bytes, other: bytes, pe: PEImage, *, sample_limit: int) -> dict[str, Any]:
    max_len = max(len(reference), len(other))
    regions: list[dict[str, Any]] = []
    count = 0
    start: int | None = None
    for index in range(max_len):
        a = reference[index] if index < len(reference) else None
        b = other[index] if index < len(other) else None
        if a != b:
            count += 1
            if start is None:
                start = index
        elif start is not None:
            regions.append(diff_region(reference, other, pe, start, index))
            start = None
    if start is not None:
        regions.append(diff_region(reference, other, pe, start, max_len))

    by_section: dict[str, int] = {}
    for region in regions:
        by_section[region["section"]] = by_section.get(region["section"], 0) + region["length"]

    return {
        "same_size": len(reference) == len(other),
        "reference_size": len(reference),
        "other_size": len(other),
        "diff_byte_count": count,
        "diff_region_count": len(regions),
        "diff_bytes_by_section": by_section,
        "sample_regions": regions[:sample_limit],
    }


def diff_region(reference: bytes, other: bytes, pe: PEImage, start: int, end: int) -> dict[str, Any]:
    ref_slice = reference[start:end]
    other_slice = other[start:end]
    return {
        "offset": start,
        "va": pe.offset_to_va(start),
        "section": pe.section_for_offset(start),
        "length": end - start,
        "reference_hex": ref_slice[:24].hex(" "),
        "other_hex": other_slice[:24].hex(" "),
    }


def byte_coverage(pe: PEImage) -> dict[str, Any]:
    intervals: list[tuple[int, int, str]] = [(0, min(pe.size_of_headers, len(pe.data)), "headers")]
    for section in pe.sections:
        start = section.raw_pointer
        end = min(section.raw_end(), len(pe.data))
        if end > start:
            intervals.append((start, end, section.name))
    intervals.sort()

    gaps: list[dict[str, Any]] = []
    cursor = 0
    for start, end, name in intervals:
        if start > cursor:
            gaps.append({"offset": cursor, "length": start - cursor, "kind": "gap"})
        cursor = max(cursor, end)
    if cursor < len(pe.data):
        gaps.append({"offset": cursor, "length": len(pe.data) - cursor, "kind": "overlay_or_trailing_gap"})

    covered = sum(end - start for start, end, _name in intervals)
    return {
        "covered_bytes": covered,
        "uncovered_bytes": len(pe.data) - covered,
        "coverage_percent": round(covered * 100 / len(pe.data), 3) if pe.data else 0,
        "gaps": gaps,
    }


def pe_summary(pe: PEImage, path: Path) -> dict[str, Any]:
    section_items: list[dict[str, Any]] = []
    for section in pe.sections:
        raw = pe.data[section.raw_pointer : min(section.raw_end(), len(pe.data))]
        zero_runs = run_lengths(raw, 0x00, min_len=32)
        nop_runs = run_lengths(raw, 0x90, min_len=16)
        int3_runs = run_lengths(raw, 0xCC, min_len=16)
        section_items.append(
            {
                "name": section.name,
                "virtual_address": section.virtual_address,
                "virtual_size": section.virtual_size,
                "va_start": section.va_start(pe.image_base),
                "va_end": section.va_end(pe.image_base),
                "raw_pointer": section.raw_pointer,
                "raw_size": section.raw_size,
                "raw_end": section.raw_end(),
                "characteristics": section.characteristics,
                "flags": section_flags(section.characteristics),
                "entropy": round(entropy(raw), 4),
                "zero_run_count_ge_32": len(zero_runs),
                "largest_zero_runs": sorted(
                    (
                        {"offset": section.raw_pointer + item["offset"], "length": item["length"]}
                        for item in zero_runs
                    ),
                    key=lambda item: item["length"],
                    reverse=True,
                )[:8],
                "nop_run_count_ge_16": len(nop_runs),
                "largest_nop_runs": sorted(
                    (
                        {"offset": section.raw_pointer + item["offset"], "length": item["length"]}
                        for item in nop_runs
                    ),
                    key=lambda item: item["length"],
                    reverse=True,
                )[:8],
                "int3_run_count_ge_16": len(int3_runs),
            }
        )

    return {
        "path": str(path),
        "size": len(pe.data),
        "sha256": sha256(pe.data),
        "timestamp_raw": pe.timestamp,
        "timestamp_utc": _dt.datetime.fromtimestamp(pe.timestamp, _dt.UTC).isoformat()
        if pe.timestamp
        else None,
        "machine": pe.machine,
        "number_of_sections": pe.number_of_sections,
        "characteristics": pe.characteristics,
        "magic": pe.magic,
        "linker_version": f"{pe.major_linker_version}.{pe.minor_linker_version}",
        "image_base": pe.image_base,
        "entry_point_rva": pe.address_of_entry_point,
        "entry_point_va": pe.image_base + pe.address_of_entry_point,
        "base_of_code": pe.base_of_code,
        "base_of_data": pe.base_of_data,
        "size_of_code": pe.size_of_code,
        "size_of_initialized_data": pe.size_of_initialized_data,
        "size_of_uninitialized_data": pe.size_of_uninitialized_data,
        "section_alignment": pe.section_alignment,
        "file_alignment": pe.file_alignment,
        "os_version": f"{pe.major_os_version}.{pe.minor_os_version}",
        "subsystem_version": f"{pe.major_subsystem_version}.{pe.minor_subsystem_version}",
        "size_of_image": pe.size_of_image,
        "size_of_headers": pe.size_of_headers,
        "checksum": pe.checksum,
        "subsystem": pe.subsystem,
        "dll_characteristics": pe.dll_characteristics,
        "size_of_stack_reserve": pe.size_of_stack_reserve,
        "size_of_heap_reserve": pe.size_of_heap_reserve,
        "data_directories": pe.data_directories,
        "sections": section_items,
        "byte_coverage": byte_coverage(pe),
    }


def constant_hits(pe: PEImage, values: list[int], *, sample_limit: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for value in values:
        needle = struct.pack("<I", value)
        hits: list[dict[str, Any]] = []
        start = 0
        while True:
            found = pe.data.find(needle, start)
            if found < 0:
                break
            if len(hits) < sample_limit:
                hits.append(
                    {
                        "offset": found,
                        "va": pe.offset_to_va(found),
                        "section": pe.section_for_offset(found),
                    }
                )
            start = found + 1
        out[str(value)] = {"count": count_bytes(pe.data, needle), "samples": hits}
    return out


def count_bytes(data: bytes, needle: bytes) -> int:
    count = 0
    start = 0
    while True:
        found = data.find(needle, start)
        if found < 0:
            return count
        count += 1
        start = found + 1


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    reference_path = args.reference.expanduser().resolve()
    reference = reference_path.read_bytes()
    pe = PEImage(reference)
    imports = parse_imports(pe)
    strings = extract_ascii_strings(reference) + extract_utf16le_strings(reference)
    strings.sort(key=lambda item: item["offset"])

    report: dict[str, Any] = {
        "tool": "probe_pm99_exe_forensics.py",
        "generated_at_utc": _dt.datetime.now(_dt.UTC).isoformat(),
        "reference": pe_summary(pe, reference_path),
        "imports": imports,
        "import_reference_summary": import_reference_summary(pe, imports),
        "strings": {
            "total_ascii_and_utf16le": len(strings),
            "categories": classify_strings(pe, strings, sample_limit=args.sample_limit),
        },
        "constants": constant_hits(
            pe,
            [
                3 * 1024 * 1024,
                200 * 1024 * 1024,
                640,
                480,
                800,
                600,
                1024,
                768,
                0x100,
                0x104,
                0x1F0003,
            ],
            sample_limit=args.sample_limit,
        ),
        "comparisons": [],
    }

    for other_path in args.compare:
        path = other_path.expanduser().resolve()
        if not path.exists():
            report["comparisons"].append({"path": str(path), "error": "missing"})
            continue
        other = path.read_bytes()
        report["comparisons"].append(
            {
                "path": str(path),
                "sha256": sha256(other),
                **diff_summary(reference, other, pe, sample_limit=args.sample_limit),
            }
        )

    if args.compact:
        report["imports"] = compact_imports(imports)
        report["import_reference_summary"] = compact_import_references(report["import_reference_summary"])
    return report


def compact_imports(imports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "dll": item["dll"],
            "entry_count": len(item["entries"]),
            "entries": [
                {
                    "name": entry.get("name") if entry["kind"] == "name" else f"#{entry['ordinal']}",
                    "iat_va": entry["iat_va"],
                }
                for entry in item["entries"]
            ],
        }
        for item in imports
    ]


def compact_import_references(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item
        for item in items
        if item["direct_reference_count"] or item["direct_call_count"] or item["stub_call_count"]
    ]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reference",
        type=Path,
        default=Path(".local/iso/MANAGPRE.original.exe"),
        help="Reference MANAGPRE.EXE to survey.",
    )
    parser.add_argument(
        "--compare",
        type=Path,
        action="append",
        default=[],
        help="Additional MANAGPRE.EXE variant to byte-compare against the reference. Repeatable.",
    )
    parser.add_argument("--output", type=Path, help="Write JSON report to this path instead of stdout.")
    parser.add_argument("--sample-limit", type=int, default=12, help="Maximum samples per category.")
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Trim empty import-reference entries and ordinal-heavy import detail.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report = build_report(args)
    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
