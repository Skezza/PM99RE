#!/usr/bin/env python3
"""Patch the PM99 title-screen build badge text inside MANAGPRE.EXE."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from dataclasses import dataclass
from pathlib import Path


IMAGE_BASE = 0x400000
TITLE_BADGE_FORMAT_VA = 0x00731C2C
TITLE_BADGE_PUSH_VA = 0x00467028
TITLE_BADGE_STRING_VA = 0x0072BA20
EXPECTED_FORMAT_BYTES = b"F%u.%u\x00"
EXPECTED_PUSH_OPCODE = 0x68


@dataclass(frozen=True)
class Section:
    name: str
    virtual_address: int
    virtual_size: int
    raw_pointer: int
    raw_size: int

    @property
    def va_start(self) -> int:
        return IMAGE_BASE + self.virtual_address

    @property
    def va_end(self) -> int:
        return self.va_start + max(self.virtual_size, self.raw_size)


class PEImage:
    def __init__(self, raw: bytearray) -> None:
        self.raw = raw
        pe_offset = struct.unpack_from("<I", raw, 0x3C)[0]
        section_count = struct.unpack_from("<H", raw, pe_offset + 6)[0]
        optional_header_size = struct.unpack_from("<H", raw, pe_offset + 20)[0]
        section_table_offset = pe_offset + 24 + optional_header_size
        self.sections: list[Section] = []
        for index in range(section_count):
            offset = section_table_offset + 40 * index
            name = bytes(raw[offset : offset + 8]).split(b"\x00", 1)[0].decode("ascii", "replace")
            virtual_size, virtual_address, raw_size, raw_pointer = struct.unpack_from("<IIII", raw, offset + 8)
            self.sections.append(
                Section(
                    name=name,
                    virtual_address=virtual_address,
                    virtual_size=virtual_size,
                    raw_pointer=raw_pointer,
                    raw_size=raw_size,
                )
            )

    def va_to_offset(self, va: int) -> int:
        for section in self.sections:
            if section.va_start <= va < section.va_end:
                return section.raw_pointer + (va - section.va_start)
        raise ValueError(f"virtual address is not mapped in the PE image: 0x{va:08x}")

    def read(self, va: int, size: int) -> bytes:
        offset = self.va_to_offset(va)
        return bytes(self.raw[offset : offset + size])

    def write(self, va: int, payload: bytes) -> None:
        offset = self.va_to_offset(va)
        self.raw[offset : offset + len(payload)] = payload

    def zero_run_length(self, va: int) -> int:
        offset = self.va_to_offset(va)
        length = 0
        while offset + length < len(self.raw) and self.raw[offset + length] == 0:
            length += 1
        return length


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def patch_title_badge(exe_path: Path, badge_text: str) -> dict[str, object]:
    if not badge_text:
        raise ValueError("badge text must not be empty")
    try:
        encoded_text = badge_text.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("badge text must be ASCII-only") from exc
    if b"\x00" in encoded_text:
        raise ValueError("badge text must not contain NUL bytes")

    before_sha256 = sha256_file(exe_path)
    raw = bytearray(exe_path.read_bytes())
    image = PEImage(raw)

    format_bytes = image.read(TITLE_BADGE_FORMAT_VA, len(EXPECTED_FORMAT_BYTES))
    if format_bytes != EXPECTED_FORMAT_BYTES:
        raise ValueError(
            "unexpected title badge format bytes at "
            f"0x{TITLE_BADGE_FORMAT_VA:08x}: {format_bytes!r}"
        )

    push_bytes = image.read(TITLE_BADGE_PUSH_VA, 5)
    if push_bytes[0] != EXPECTED_PUSH_OPCODE:
        raise ValueError(
            f"unexpected instruction opcode at 0x{TITLE_BADGE_PUSH_VA:08x}: "
            f"0x{push_bytes[0]:02x}"
        )

    available_zero_run = image.zero_run_length(TITLE_BADGE_STRING_VA)
    required_length = len(encoded_text) + 1
    if required_length > available_zero_run:
        raise ValueError(
            f"badge text requires {required_length} bytes, but only {available_zero_run} zero bytes "
            f"are available at 0x{TITLE_BADGE_STRING_VA:08x}"
        )

    image.write(TITLE_BADGE_STRING_VA, b"\x00" * available_zero_run)
    image.write(TITLE_BADGE_STRING_VA, encoded_text + b"\x00")
    image.write(TITLE_BADGE_PUSH_VA + 1, struct.pack("<I", TITLE_BADGE_STRING_VA))

    exe_path.write_bytes(raw)
    after_sha256 = sha256_file(exe_path)

    patched_push_bytes = bytes.fromhex(f"{EXPECTED_PUSH_OPCODE:02x}") + struct.pack("<I", TITLE_BADGE_STRING_VA)
    verification = {
        "string_bytes": image.read(TITLE_BADGE_STRING_VA, required_length).hex(),
        "push_bytes": image.read(TITLE_BADGE_PUSH_VA, 5).hex(),
        "string_matches": image.read(TITLE_BADGE_STRING_VA, required_length) == encoded_text + b"\x00",
        "push_matches": image.read(TITLE_BADGE_PUSH_VA, 5) == patched_push_bytes,
    }

    return {
        "exe_path": str(exe_path.resolve()),
        "badge_text": badge_text,
        "before_sha256": before_sha256,
        "after_sha256": after_sha256,
        "title_badge_format_va": f"0x{TITLE_BADGE_FORMAT_VA:08x}",
        "title_badge_push_va": f"0x{TITLE_BADGE_PUSH_VA:08x}",
        "title_badge_string_va": f"0x{TITLE_BADGE_STRING_VA:08x}",
        "title_badge_string_offset": f"0x{image.va_to_offset(TITLE_BADGE_STRING_VA):x}",
        "title_badge_push_offset": f"0x{image.va_to_offset(TITLE_BADGE_PUSH_VA):x}",
        "available_zero_run": available_zero_run,
        "verification": verification,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exe_path", help="Path to MANAGPRE.EXE to patch")
    parser.add_argument("--text", default="SkezMod", help="Replacement title badge text")
    parser.add_argument("--json-out", help="Optional path for a JSON patch summary")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    exe_path = Path(args.exe_path).expanduser().resolve()
    if not exe_path.is_file():
        parser.error(f"missing EXE: {exe_path}")

    try:
        payload = patch_title_badge(exe_path, args.text)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json_out:
        output_path = Path(args.json_out).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
