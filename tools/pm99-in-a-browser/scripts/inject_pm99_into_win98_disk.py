#!/usr/bin/env python3
"""Copy the staged PM99 tree into an installed Windows 98 FAT disk image.

This expects a raw IDE disk image with a FAT16/FAT32 partition, as produced by
Windows 98 setup. It does not create or download Windows.
"""

from __future__ import annotations

import argparse
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DISK = ROOT / "v86" / "assets" / "disks" / "win98-pm99.img"
DEFAULT_PM99 = ROOT / "assets" / "pm99"
FAT_PARTITION_TYPES = {0x01, 0x04, 0x06, 0x0B, 0x0C, 0x0E}
REQUIRED_PM99_FILES = (
    "MANAGPRE.EXE",
    "MIDAS11.DLL",
    "DBDAT/JUG98030.FDI",
    "DBDAT/EQ98030.FDI",
    "DBDAT/ENT98030.FDI",
    "DBDAT/MINIFOTO.PKF",
)


def run(args: list[str], *, dry_run: bool = False) -> None:
    if dry_run:
        print("+ " + " ".join(args))
        return
    subprocess.run(args, check=True)


def mtool_image_arg(disk: Path, offset: int) -> str:
    return f"{disk}@@{offset}" if offset else str(disk)


def detect_fat_offset(disk: Path) -> int:
    with disk.open("rb") as fh:
        sector = fh.read(512)
    if len(sector) != 512:
        raise RuntimeError(f"{disk} is too small to be a disk image")

    if sector[510:512] != b"\x55\xaa":
        return 0

    candidates: list[tuple[int, int, int]] = []
    for index in range(4):
        entry = sector[446 + index * 16 : 446 + (index + 1) * 16]
        part_type = entry[4]
        start_lba = struct.unpack_from("<I", entry, 8)[0]
        sectors = struct.unpack_from("<I", entry, 12)[0]
        if part_type in FAT_PARTITION_TYPES and start_lba and sectors:
            candidates.append((index + 1, part_type, start_lba * 512))

    if not candidates:
        return 0

    number, part_type, offset = candidates[0]
    print(f"Using FAT partition {number} type 0x{part_type:02x} at byte offset {offset}")
    return offset


def validate_pm99_root(root: Path) -> None:
    missing = [rel for rel in REQUIRED_PM99_FILES if not (root / rel).is_file()]
    if missing:
        raise RuntimeError(f"PM99 root is missing required files: {', '.join(missing)}")


def guest_path(*parts: str) -> str:
    cleaned = [part.strip("/\\") for part in parts if part.strip("/\\")]
    return "::/" + "/".join(cleaned)


def ensure_guest_dir(image: str, path: str, *, dry_run: bool = False) -> None:
    segments = [segment for segment in path.replace("\\", "/").split("/") if segment]
    current: list[str] = []
    for segment in segments:
        current.append(segment)
        target = guest_path(*current)
        result = subprocess.run(["mdir", "-i", image, target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode != 0:
            run(["mmd", "-i", image, target], dry_run=dry_run)


def copy_tree(image: str, source: Path, destination: str, *, dry_run: bool = False) -> tuple[int, int]:
    dirs = 0
    files = 0
    ensure_guest_dir(image, destination, dry_run=dry_run)

    for dirpath, dirnames, filenames in os.walk(source):
        dirnames[:] = sorted(name for name in dirnames if name not in {".git", "__pycache__"})
        filenames = sorted(filenames)
        current = Path(dirpath)
        rel_dir = current.relative_to(source)
        guest_dir = destination if str(rel_dir) == "." else f"{destination}/{rel_dir.as_posix()}"
        ensure_guest_dir(image, guest_dir, dry_run=dry_run)
        dirs += 1

        for filename in filenames:
            src = current / filename
            if src.is_symlink() and not src.exists():
                continue
            if not src.is_file():
                continue
            run(["mcopy", "-o", "-i", image, str(src), guest_path(guest_dir, filename)], dry_run=dry_run)
            files += 1

    return dirs, files


def write_launcher_batch(image: str, destination: str, *, dry_run: bool = False) -> None:
    dos_destination = "\\" + destination.strip("/\\").replace("/", "\\")
    content = f"@ECHO OFF\r\nCD {dos_destination}\r\nMANAGPRE.EXE\r\n"
    with tempfile.TemporaryDirectory(prefix="pm99-win98-") as tmp:
        batch = Path(tmp) / "RUNPM99.BAT"
        batch.write_text(content, encoding="ascii", newline="")
        run(["mcopy", "-o", "-i", image, str(batch), guest_path(destination, "RUNPM99.BAT")], dry_run=dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disk", type=Path, default=DEFAULT_DISK, help="raw Windows 98 disk image")
    parser.add_argument("--pm99-root", type=Path, default=DEFAULT_PM99, help="staged PM99 root directory")
    parser.add_argument("--destination", default="PM99", help="guest directory on C:, default PM99")
    parser.add_argument("--offset", type=int, help="FAT partition byte offset; detected from MBR by default")
    parser.add_argument("--dry-run", action="store_true", help="print mtools commands without copying")
    args = parser.parse_args()

    disk = args.disk.resolve()
    pm99_root = args.pm99_root.resolve()

    for tool in ("mdir", "mmd", "mcopy"):
        if shutil.which(tool) is None:
            print(f"Missing required tool: {tool}", file=sys.stderr)
            return 1

    if not disk.is_file():
        print(f"Disk image not found: {disk}", file=sys.stderr)
        return 1
    if not pm99_root.is_dir():
        print(f"PM99 root not found: {pm99_root}", file=sys.stderr)
        return 1

    validate_pm99_root(pm99_root)
    offset = args.offset if args.offset is not None else detect_fat_offset(disk)
    image = mtool_image_arg(disk, offset)

    probe = subprocess.run(["mdir", "-i", image, "::/"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if probe.returncode != 0:
        print(probe.stderr.strip(), file=sys.stderr)
        print("Could not read a FAT filesystem from the disk image. Install/format Windows 98 first.", file=sys.stderr)
        return 1

    dirs, files = copy_tree(image, pm99_root, args.destination.strip("/\\"), dry_run=args.dry_run)
    write_launcher_batch(image, args.destination.strip("/\\"), dry_run=args.dry_run)
    print(f"Copied PM99 to C:\\{args.destination.strip('/\\')} ({files} files, {dirs} directories)")
    print(f"Launch inside Windows with C:\\{args.destination.strip('/\\')}\\RUNPM99.BAT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
