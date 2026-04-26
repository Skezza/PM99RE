#!/usr/bin/env python3
"""Apply small research compatibility patches to PM99 MANAGPRE.EXE.

The patches here target old runtime assumptions, not local ripped/missing data:

- windowed:
  Force the game's own FULL SCREEN setting off, default missing manager.ini to
  windowed mode, and stop Alt+Enter from entering exclusive fullscreen.
  This is a rejected experiment, not a shipping compatibility fix. Runner
  validation proved it does not make PM99 playable in a larger Wine desktop.

- no-display-mode-mutation:
  No-op the legacy ChangeDisplaySettingsA call used by the "switch desktop to
  256 colors" path. This is not needed on normal modern desktops, so it is
  opt-in rather than part of the default set.

No proprietary executable is included in this repository. This script only
patches a user-supplied local copy.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import struct
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


IMAGE_BASE = 0x00400000
EXPECTED_SIZE = 3_442_176


@dataclass(frozen=True)
class BytePatch:
    name: str
    patch_set: str
    va: int
    original: bytes
    patched: bytes
    description: str


PATCHES = (
    BytePatch(
        name="force_parsed_fullscreen_off",
        patch_set="windowed",
        va=0x0040B806,
        original=bytes.fromhex("F7 D8 1B C0 40"),
        patched=bytes.fromhex("31 C0 90 90 90"),
        description="Store 0 for parsed FULL SCREEN instead of accepting ON from manager.ini.",
    ),
    BytePatch(
        name="missing_manager_ini_defaults_windowed",
        patch_set="windowed",
        va=0x0040B89F,
        original=bytes.fromhex("01"),
        patched=bytes.fromhex("00"),
        description="When manager.ini is missing, default FULL SCREEN to OFF.",
    ),
    BytePatch(
        name="alt_enter_never_enters_fullscreen",
        patch_set="windowed",
        va=0x00677A49,
        original=bytes.fromhex("0F 94 C0"),
        patched=bytes.fromhex("30 C0 90"),
        description="Keep Alt+Enter able to request windowed mode, but never request fullscreen.",
    ),
    BytePatch(
        name="no_op_legacy_change_display_settings",
        patch_set="no-display-mode-mutation",
        va=0x006AAD86,
        original=bytes.fromhex("FF 15 84 65 6E 00"),
        patched=bytes.fromhex("31 C0 90 90 90 90"),
        description=(
            "Pretend ChangeDisplaySettingsA succeeded without changing the desktop color mode."
        ),
    ),
)


def sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def hex_bytes(value: bytes) -> str:
    return value.hex(" ").upper()


def read_sections(pe_bytes: bytes) -> list[dict[str, int]]:
    if pe_bytes[:2] != b"MZ":
        raise ValueError("input is not an MZ executable")
    pe_off = struct.unpack_from("<I", pe_bytes, 0x3C)[0]
    if pe_bytes[pe_off : pe_off + 4] != b"PE\x00\x00":
        raise ValueError("input does not contain a PE header")

    section_count = struct.unpack_from("<H", pe_bytes, pe_off + 6)[0]
    opt_size = struct.unpack_from("<H", pe_bytes, pe_off + 20)[0]
    section_off = pe_off + 24 + opt_size
    sections: list[dict[str, int]] = []
    for i in range(section_count):
        off = section_off + i * 40
        virtual_size, virtual_address, raw_size, raw_ptr = struct.unpack_from("<IIII", pe_bytes, off + 8)
        sections.append(
            {
                "virtual_address": virtual_address,
                "virtual_size": virtual_size,
                "raw_size": raw_size,
                "raw_ptr": raw_ptr,
            }
        )
    return sections


def va_to_file_offset(pe_bytes: bytes, va: int) -> int:
    rva = va - IMAGE_BASE
    for section in read_sections(pe_bytes):
        start = section["virtual_address"]
        size = max(section["virtual_size"], section["raw_size"])
        if start <= rva < start + size:
            return section["raw_ptr"] + (rva - start)
    raise ValueError(f"VA 0x{va:08X} does not map to a file-backed section")


def selected_patches(names: list[str] | None) -> list[BytePatch]:
    selected = set(names or [])
    if "all" in selected:
        selected = {p.patch_set for p in PATCHES}
    return [p for p in PATCHES if p.patch_set in selected]


def default_output_path(input_path: Path, revert: bool) -> Path:
    suffix = ".compat_reverted.exe" if revert else ".compat_patched.exe"
    return input_path.with_name(f"{input_path.stem}{suffix}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply/revert transferable PM99 MANAGPRE.EXE compatibility byte patches."
    )
    parser.add_argument("input", type=Path, help="Path to MANAGPRE.EXE or a copy.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output path. If omitted, a sibling file with a compatibility suffix is created.",
    )
    parser.add_argument(
        "--patch-set",
        action="append",
        choices=["windowed", "no-display-mode-mutation", "all"],
        help="Patch set to apply. May be repeated. No default; windowed is rejected research-only.",
    )
    parser.add_argument(
        "--ack-windowed-rejected-experiment",
        action="store_true",
        help="Required to write the rejected windowed patch set.",
    )
    parser.add_argument("--revert", action="store_true", help="Revert selected patches.")
    parser.add_argument("--dry-run", action="store_true", help="Validate only; do not write output.")
    parser.add_argument("--in-place", action="store_true", help="Patch input directly.")
    parser.add_argument("--no-backup", action="store_true", help="Do not create an in-place backup.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Write target bytes despite source-byte mismatches. Use only after manual review.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path: Path = args.input
    if not input_path.exists():
        print(f"[error] input not found: {input_path}", file=sys.stderr)
        return 1

    blob = input_path.read_bytes()
    if len(blob) != EXPECTED_SIZE:
        print(f"[warn] size is {len(blob)} bytes; expected {EXPECTED_SIZE}", file=sys.stderr)

    patches = selected_patches(args.patch_set)
    if not patches:
        print("[error] no patches selected; pass --patch-set explicitly", file=sys.stderr)
        return 1

    includes_windowed = any(p.patch_set == "windowed" for p in patches)
    if includes_windowed and not args.revert and not args.dry_run and not args.ack_windowed_rejected_experiment:
        print(
            "[error] the windowed patch set is a rejected experiment; pass "
            "--ack-windowed-rejected-experiment to write it intentionally",
            file=sys.stderr,
        )
        return 2

    print(f"[info] input: {input_path}")
    print(f"[info] sha256(before): {sha256_bytes(blob)}")
    print(f"[info] action: {'revert' if args.revert else 'apply'}")
    print(f"[info] patch sets: {', '.join(sorted({p.patch_set for p in patches}))}")

    out_blob = bytearray(blob)
    mismatches = 0
    already_target = 0
    for patch in patches:
        offset = va_to_file_offset(blob, patch.va)
        source = patch.patched if args.revert else patch.original
        target = patch.original if args.revert else patch.patched
        current = bytes(blob[offset : offset + len(source)])

        if current == target:
            already_target += 1
            print(
                f"[ok] 0x{patch.va:08X} file+0x{offset:06X}: already target "
                f"{hex_bytes(current)} [{patch.name}]"
            )
            continue

        if current != source:
            mismatches += 1
            print(
                f"[mismatch] 0x{patch.va:08X} file+0x{offset:06X}: expected "
                f"{hex_bytes(source)}, found {hex_bytes(current)} [{patch.name}]",
                file=sys.stderr,
            )
            if not args.force:
                continue

        print(
            f"[change] 0x{patch.va:08X} file+0x{offset:06X}: "
            f"{hex_bytes(current)} -> {hex_bytes(target)} [{patch.description}]"
        )
        out_blob[offset : offset + len(target)] = target

    if mismatches and not args.force:
        print("[error] source-byte mismatch detected; no file written.", file=sys.stderr)
        return 2

    if already_target == len(patches):
        print("[info] all selected patches are already in the requested state.")
        return 0

    out_bytes = bytes(out_blob)
    print(f"[info] sha256(after):  {sha256_bytes(out_bytes)}")

    if args.dry_run:
        print("[info] dry-run mode, no file written.")
        return 0

    output_path = input_path if args.in_place else (args.output or default_output_path(input_path, args.revert))
    if args.in_place and not args.no_backup:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = input_path.with_name(f"{input_path.name}.bak_compat_{stamp}")
        shutil.copy2(input_path, backup)
        print(f"[info] backup: {backup}")

    output_path.write_bytes(out_bytes)
    print(f"[done] wrote: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
