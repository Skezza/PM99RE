#!/usr/bin/env python3
"""
Educational patcher for the PM99 No-CD byte-level changes in MANAGPRE.EXE.

Patch set (ISO original -> clean No-CD):
  - 0x0080F6: 8A 44 24 10 -> 66 B8 2E 00
  - 0x008119: 75 12       -> 90 90
  - 0x32A97D: 3A 5C       -> 5C 00
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


EXPECTED_SIZE = 3_442_176


@dataclass(frozen=True)
class BytePatch:
    offset: int
    original: bytes
    patched: bytes
    description: str


PATCHES = (
    BytePatch(
        offset=0x0080F6,
        original=bytes.fromhex("8A 44 24 10"),
        patched=bytes.fromhex("66 B8 2E 00"),
        description="CD check path seed overwrite",
    ),
    BytePatch(
        offset=0x008119,
        original=bytes.fromhex("75 12"),
        patched=bytes.fromhex("90 90"),
        description="Bypass CD-ROM drive type branch",
    ),
    BytePatch(
        offset=0x32A97D,
        original=bytes.fromhex("3A 5C"),
        patched=bytes.fromhex("5C 00"),
        description="Disk path template tweak",
    ),
)


def sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def hex_bytes(value: bytes) -> str:
    return value.hex().upper()


def check_patch_state(blob: bytes, patch: BytePatch, target_is_patched: bool) -> tuple[bool, bytes]:
    expected = patch.patched if target_is_patched else patch.original
    current = blob[patch.offset : patch.offset + len(expected)]
    return current == expected, current


def apply_patches(blob: bytearray, *, to_patched: bool) -> None:
    for p in PATCHES:
        src = p.original if to_patched else p.patched
        dst = p.patched if to_patched else p.original
        blob[p.offset : p.offset + len(src)] = dst


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply or revert the educational PM99 No-CD byte patch."
    )
    parser.add_argument("input", type=Path, help="Path to MANAGPRE.EXE (or copy).")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output path. If omitted, a sibling file with suffix is created.",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Modify input file directly (creates backup unless --no-backup).",
    )
    parser.add_argument(
        "--revert",
        action="store_true",
        help="Revert patched bytes back to original values.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report what would change; do not write output.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip expected-byte checks and write target bytes anyway.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="When using --in-place, do not create .bak timestamp backup.",
    )
    return parser.parse_args()


def default_output_path(input_path: Path, revert: bool) -> Path:
    suffix = ".reverted.exe" if revert else ".nocd_patched.exe"
    return input_path.with_name(f"{input_path.stem}{suffix}")


def main() -> int:
    args = parse_args()
    in_path = args.input

    if not in_path.exists():
        print(f"[error] input file not found: {in_path}", file=sys.stderr)
        return 1

    blob = in_path.read_bytes()
    before_hash = sha256_bytes(blob)
    print(f"[info] input: {in_path}")
    print(f"[info] size: {len(blob)} bytes")
    print(f"[info] sha256(before): {before_hash}")

    if len(blob) != EXPECTED_SIZE:
        print(
            f"[warn] file size differs from expected {EXPECTED_SIZE}. "
            "Proceeding anyway."
        )

    target_is_patched = not args.revert
    action = "patch" if target_is_patched else "revert"
    print(f"[info] action: {action}")

    mismatches = 0
    already_target = 0
    for p in PATCHES:
        ok, current = check_patch_state(blob, p, target_is_patched=target_is_patched)
        if ok:
            already_target += 1
            print(
                f"[ok] 0x{p.offset:06X}: already target bytes "
                f"({hex_bytes(current)}) [{p.description}]"
            )
            continue

        source = p.original if target_is_patched else p.patched
        current_src = blob[p.offset : p.offset + len(source)]
        if current_src != source:
            mismatches += 1
            print(
                f"[mismatch] 0x{p.offset:06X}: expected source {hex_bytes(source)}, "
                f"found {hex_bytes(current_src)} [{p.description}]"
            )
        else:
            print(
                f"[change] 0x{p.offset:06X}: {hex_bytes(source)} -> "
                f"{hex_bytes(p.patched if target_is_patched else p.original)} "
                f"[{p.description}]"
            )

    if already_target == len(PATCHES):
        print("[info] file is already in requested state; nothing to do.")
        return 0

    if mismatches and not args.force:
        print(
            "[error] source-byte mismatch detected. Use --force only if you "
            "fully understand the risk.",
            file=sys.stderr,
        )
        return 2

    out_path = in_path if args.in_place else (args.output or default_output_path(in_path, args.revert))

    out_blob = bytearray(blob)
    apply_patches(out_blob, to_patched=target_is_patched)
    after_hash = sha256_bytes(out_blob)

    print(f"[info] sha256(after):  {after_hash}")

    if args.dry_run:
        print("[info] dry-run mode, no file written.")
        return 0

    if args.in_place and not args.no_backup:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = in_path.with_name(f"{in_path.name}.bak_{stamp}")
        shutil.copy2(in_path, backup)
        print(f"[info] backup: {backup}")

    out_path.write_bytes(out_blob)
    print(f"[done] wrote: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
