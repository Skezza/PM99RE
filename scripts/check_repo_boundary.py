#!/usr/bin/env python3
"""Enforce PM99RE boundary: research-only parent, product code in submodules."""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
from pathlib import Path


PRODUCT_PREFIXES = ("app/", "tests/")
LOCAL_ARTIFACT_PREFIXES = (
    ".local/",
    "artifacts/",
    "FDI-PKF/",
    "tbc/",
    "work/",
    "worktrees/",
)
BLOCKED_BASENAMES = ("pm99_database_editor.py", "pytest.ini")
FORBIDDEN_PATTERNS = (
    "*.FDI",
    "*.fdi",
    "*.FDI.*",
    "*.fdi.*",
    "*.PKF",
    "*.pkf",
    "*.PKF.*",
    "*.pkf.*",
    "*.EXE",
    "*.exe",
    "*.DLL",
    "*.dll",
    "*.backup_*",
)
ALLOWED_EXACT = {"DBDAT/.gitkeep"}
LOCAL_PRODUCT_DIRS = ("app", "tests")
LOCAL_ROOT_TOOL_DIRS = ("pm99-in-a-browser",)


def _tracked_files(repo_root: Path) -> list[str]:
    out = subprocess.check_output(
        ["git", "ls-files"],
        cwd=repo_root,
        text=True,
    )
    return [line.strip() for line in out.splitlines() if line.strip()]


def _is_forbidden_binary_or_backup(rel: str) -> bool:
    name = Path(rel).name
    return any(fnmatch.fnmatch(name, pattern) for pattern in FORBIDDEN_PATTERNS)


def _violations(files: list[str]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {
        "product_paths": [],
        "local_artifacts": [],
        "binary_or_backup": [],
    }
    for rel in files:
        if rel in ALLOWED_EXACT:
            continue
        if Path(rel).name in BLOCKED_BASENAMES or rel.startswith(PRODUCT_PREFIXES):
            found["product_paths"].append(rel)
        if rel.startswith(LOCAL_ARTIFACT_PREFIXES):
            found["local_artifacts"].append(rel)
        if _is_forbidden_binary_or_backup(rel):
            found["binary_or_backup"].append(rel)
    return {key: sorted(values) for key, values in found.items() if values}


def _local_dir_violations(repo_root: Path) -> list[str]:
    found: list[str] = []
    for rel in (*LOCAL_PRODUCT_DIRS, *LOCAL_ROOT_TOOL_DIRS):
        path = repo_root / rel
        if path.exists():
            found.append(rel + "/")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-local",
        action="store_true",
        help="also fail if root product-shaped or misplaced tool directories exist on disk",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    files = _tracked_files(repo_root)
    found = _violations(files)
    if args.check_local:
        local_found = _local_dir_violations(repo_root)
        if local_found:
            found["local_root_dirs"] = local_found

    if not found:
        print("Boundary check OK: no product paths, local artifacts, or PM99 binaries tracked in PM99RE.")
        return 0

    print("Boundary check FAILED. Remove these paths from PM99RE tracking or local root workspace:")
    for label, paths in found.items():
        print(f"\n{label}:")
        for rel in paths:
            print(f"- {rel}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
