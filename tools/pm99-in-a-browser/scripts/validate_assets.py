#!/usr/bin/env python3
"""Validate local PM99 browser assets and optionally write a manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


REQUIRED_PM99_FILES = (
    "MANAGPRE.EXE",
    "MIDAS11.DLL",
    "DBDAT/JUG98030.FDI",
    "DBDAT/EQ98030.FDI",
    "DBDAT/ENT98030.FDI",
    "DBDAT/MINIFOTO.PKF",
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_entry(root: Path, rel: str) -> dict[str, object]:
    path = root / rel
    if not path.is_file():
        return {"path": rel, "present": False}
    return {
        "path": rel,
        "present": True,
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def build_manifest(pm99_root: Path) -> dict[str, object]:
    entries = [file_entry(pm99_root, rel) for rel in REQUIRED_PM99_FILES]
    missing = [str(entry["path"]) for entry in entries if not entry["present"]]
    return {
        "schema": "pm99-in-a-browser-assets-v1",
        "pm99_root": str(pm99_root),
        "required": {
            "total": len(entries),
            "present": len(entries) - len(missing),
            "missing": missing,
            "files": entries,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pm99-root", type=Path, required=True, help="PM99 fixture/root directory")
    parser.add_argument("--write-manifest", type=Path, help="Write manifest JSON to this path")
    args = parser.parse_args()

    pm99_root = args.pm99_root.resolve()
    manifest = build_manifest(pm99_root)

    if args.write_manifest:
        args.write_manifest.parent.mkdir(parents=True, exist_ok=True)
        args.write_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(manifest, indent=2))
    return 0 if not manifest["required"]["missing"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
