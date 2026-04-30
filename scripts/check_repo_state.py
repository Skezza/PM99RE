#!/usr/bin/env python3
"""Check PM99RE checkout/submodule state for reproducible handoff."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def _run(repo_root: Path, args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd or repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _split_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def _submodule_paths(repo_root: Path) -> list[str]:
    result = _run(repo_root, ["git", "config", "--file", ".gitmodules", "--get-regexp", r"\.path$"])
    if result.returncode != 0:
        return []
    paths: list[str] = []
    for line in _split_lines(result.stdout):
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            paths.append(parts[1])
    return paths


def check_status(repo_root: Path) -> list[str]:
    result = _run(repo_root, ["git", "status", "--porcelain", "--ignore-submodules=none"])
    if result.returncode != 0:
        return [result.stderr.strip() or "git status failed"]
    lines = _split_lines(result.stdout)
    if not lines:
        return []
    return ["working tree is not clean:"] + [f"  {line}" for line in lines]


def check_submodule_pointers(repo_root: Path) -> list[str]:
    result = _run(repo_root, ["git", "submodule", "status", "--recursive"])
    if result.returncode != 0:
        return [result.stderr.strip() or "git submodule status failed"]
    bad = [line for line in _split_lines(result.stdout) if line[0] in "+-U"]
    if not bad:
        return []
    return ["submodule pointers are not synchronized:"] + [f"  {line}" for line in bad]


def check_submodule_worktrees(repo_root: Path) -> list[str]:
    problems: list[str] = []
    for rel in _submodule_paths(repo_root):
        path = repo_root / rel
        if not path.exists():
            problems.append(f"{rel}: path missing")
            continue
        result = _run(repo_root, ["git", "status", "--porcelain", "--untracked-files=all"], cwd=path)
        if result.returncode != 0:
            problems.append(f"{rel}: {result.stderr.strip() or 'git status failed'}")
            continue
        lines = _split_lines(result.stdout)
        if lines:
            problems.append(f"{rel}: dirty worktree")
            problems.extend(f"  {line}" for line in lines)
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-root-status",
        action="store_true",
        help="check submodule synchronization only; useful while preparing a commit",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    failures: list[str] = []
    if not args.skip_root_status:
        failures.extend(check_status(repo_root))
    failures.extend(check_submodule_pointers(repo_root))
    failures.extend(check_submodule_worktrees(repo_root))

    if failures:
        print("Repo state check FAILED:")
        for line in failures:
            print(line)
        return 1

    print("Repo state check OK: root and submodules are synchronized and clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
