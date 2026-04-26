#!/usr/bin/env python3
"""Shared validation helpers for hermetic PM99 game inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
LEGACY_LOCAL_GAME_ROOT = (REPO_ROOT / ".local" / "premier-manager-ninety-nine").resolve()
DEFAULT_FIXTURE_ROOT = (REPO_ROOT / "work" / "fixtures" / "premier-manager-ninety-nine-pristine").resolve()
DEFAULT_FIXTURE_MANIFEST = DEFAULT_FIXTURE_ROOT.parent / "premier-manager-ninety-nine-pristine.manifest.json"

CORE_GAME_RELATIVE_PATHS: tuple[str, ...] = (
    "MANAGPRE.EXE",
    "DBDAT/JUG98030.FDI",
    "DBDAT/EQ98030.FDI",
    "DBDAT/MINIFOTO.PKF",
)
CORE_DBDAT_FILES: tuple[str, ...] = (
    "JUG98030.FDI",
    "EQ98030.FDI",
    "MINIFOTO.PKF",
)


def _candidate_first_existing(paths: Iterable[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path.resolve()
    return None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mode_has_any_write_bits(path: Path) -> bool:
    return bool(path.stat().st_mode & 0o222)


def _writable_targets(paths: Iterable[Path]) -> list[str]:
    writable: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        if _mode_has_any_write_bits(path):
            writable.append(str(path))
    return writable


def _ensure_not_legacy_local(path: Path, *, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if resolved == LEGACY_LOCAL_GAME_ROOT or resolved.is_relative_to(LEGACY_LOCAL_GAME_ROOT):
        raise ValueError(
            f"{label} points into legacy shared state: {resolved}. "
            "Create an isolated run under work/pm99/ and use that path instead."
        )
    return resolved


def ensure_not_legacy_path(path: str | Path, *, label: str) -> Path:
    return _ensure_not_legacy_local(Path(path), label=label)


def _ensure_required_paths(root: Path, relative_paths: Iterable[str], *, label: str) -> None:
    missing = [str(root / relative) for relative in relative_paths if not (root / relative).is_file()]
    if missing:
        raise FileNotFoundError(f"{label} is missing required PM99 files: {', '.join(missing)}")


def _ensure_read_only(root: Path, relative_paths: Iterable[str], *, label: str) -> None:
    targets = [root, *(root / relative for relative in relative_paths)]
    writable = _writable_targets(targets)
    if writable:
        raise PermissionError(
            f"{label} must be read-only, but write bits are still set on: {', '.join(writable)}"
        )


def _ensure_writable(path: Path, *, label: str) -> None:
    if not os.access(path, os.W_OK):
        raise PermissionError(f"{label} is not writable: {path}")


def fixture_manifest_path(fixture_root: Path | None = None) -> Path:
    fixture = (fixture_root or DEFAULT_FIXTURE_ROOT).expanduser().resolve()
    if fixture == DEFAULT_FIXTURE_ROOT:
        return DEFAULT_FIXTURE_MANIFEST
    return fixture.parent / f"{fixture.name}.manifest.json"


def resolve_fixture_root(path: str | Path | None = None) -> Path:
    fixture_root = _ensure_not_legacy_local(Path(path) if path is not None else DEFAULT_FIXTURE_ROOT, label="fixture root")
    _ensure_required_paths(fixture_root, CORE_GAME_RELATIVE_PATHS, label="Fixture root")
    _ensure_read_only(fixture_root, CORE_GAME_RELATIVE_PATHS, label="Fixture root")
    return fixture_root


def resolve_game_root(
    path: str | Path | None = None,
    *,
    required: bool = True,
    require_writable: bool = False,
    default_to_fixture: bool = False,
) -> Path | None:
    if path is None or not str(path).strip():
        if not default_to_fixture:
            if required:
                raise ValueError("A PM99 game root is required")
            return None
        root = resolve_fixture_root()
    else:
        root = _ensure_not_legacy_local(Path(path), label="game root")

    _ensure_required_paths(root, CORE_GAME_RELATIVE_PATHS, label="Game root")
    if require_writable:
        _ensure_writable(root, label="Game root")
    return root


def resolve_dbdat_dir(
    *,
    dbdat_dir: str | Path | None = None,
    game_root: str | Path | None = None,
    required_files: Iterable[str] = CORE_DBDAT_FILES,
    require_writable: bool = False,
    default_to_fixture: bool = False,
) -> Path:
    if dbdat_dir is not None and str(dbdat_dir).strip():
        path = _ensure_not_legacy_local(Path(dbdat_dir), label="DBDAT directory")
    else:
        root = resolve_game_root(
            game_root,
            required=not default_to_fixture,
            require_writable=require_writable,
            default_to_fixture=default_to_fixture,
        )
        if root is None:
            raise ValueError("A DBDAT directory or PM99 game root is required")
        path = root / "DBDAT"

    if not path.is_dir():
        raise NotADirectoryError(f"DBDAT directory not found: {path}")
    missing = [str(path / file_name) for file_name in required_files if not (path / file_name).is_file()]
    if missing:
        raise FileNotFoundError(f"DBDAT directory is missing required files: {', '.join(missing)}")
    if require_writable:
        _ensure_writable(path, label="DBDAT directory")
    return path.resolve()


def default_fixture_dbdat_dir(*, required_files: Iterable[str] = CORE_DBDAT_FILES) -> Path:
    return resolve_dbdat_dir(required_files=required_files, default_to_fixture=True)


def default_fixture_file(relative_path: str) -> Path:
    fixture = resolve_fixture_root()
    path = fixture / relative_path
    if not path.is_file():
        raise FileNotFoundError(f"Fixture file not found: {path}")
    return path


def choose_preferred_game_root(
    *,
    allow_repo_dbdat: bool = True,
    allow_repo_fdi_pkf: bool = True,
) -> Path:
    candidates = [DEFAULT_FIXTURE_ROOT]
    if allow_repo_dbdat:
        candidates.append(REPO_ROOT)
    if allow_repo_fdi_pkf:
        candidates.append(REPO_ROOT / "FDI-PKF")

    chosen = _candidate_first_existing(candidates)
    if chosen is None:
        raise FileNotFoundError(
            "Could not locate a PM99 fixture or compatible repo-local data root. "
            "Run ./scripts/create_pm99_isolated_run.sh first."
        )

    if chosen == DEFAULT_FIXTURE_ROOT:
        return resolve_fixture_root(chosen)

    dbdat_root = chosen / "DBDAT"
    if not dbdat_root.is_dir():
        raise FileNotFoundError(f"Expected DBDAT/ under {chosen}")
    for relative in CORE_DBDAT_FILES:
        if not (dbdat_root / relative).is_file():
            raise FileNotFoundError(f"Expected {(dbdat_root / relative)}")
    return chosen.resolve()


def core_file_hashes(root: Path) -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}
    for relative_path in CORE_GAME_RELATIVE_PATHS:
        file_path = root / relative_path
        out[relative_path] = {
            "path": str(file_path),
            "sha256": sha256(file_path),
            "size": int(file_path.stat().st_size),
        }
    return out


def load_manifest(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _build_cli_summary(args: argparse.Namespace) -> dict[str, object]:
    if args.fixture_root:
        fixture = resolve_fixture_root(args.fixture_root)
        return {
            "mode": "fixture",
            "fixture_root": str(fixture),
            "fixture_manifest_path": str(fixture_manifest_path(fixture)),
            "core_files": core_file_hashes(fixture),
        }
    if args.game_root:
        game_root = resolve_game_root(
            args.game_root,
            require_writable=bool(args.require_writable),
        )
        return {
            "mode": "game-root",
            "game_root": str(game_root),
            "core_files": core_file_hashes(game_root),
        }
    if args.dbdat_dir:
        required_files = tuple(args.required_dbdat_file or CORE_DBDAT_FILES)
        dbdat_dir = resolve_dbdat_dir(
            dbdat_dir=args.dbdat_dir,
            required_files=required_files,
            require_writable=bool(args.require_writable),
        )
        return {
            "mode": "dbdat-dir",
            "dbdat_dir": str(dbdat_dir),
            "required_files": list(required_files),
            "files": {
                file_name: {
                    "path": str(dbdat_dir / file_name),
                    "sha256": sha256(dbdat_dir / file_name),
                    "size": int((dbdat_dir / file_name).stat().st_size),
                }
                for file_name in required_files
            },
        }
    raise ValueError("Provide --fixture-root, --game-root, or --dbdat-dir")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate PM99 inputs against hermetic isolation rules.")
    parser.add_argument("--fixture-root", default="", help="Path to the read-only pristine fixture root")
    parser.add_argument("--game-root", default="", help="Path to a PM99 game root")
    parser.add_argument("--dbdat-dir", default="", help="Path to a DBDAT directory")
    parser.add_argument(
        "--required-dbdat-file",
        action="append",
        default=[],
        help="Additional or replacement required DBDAT file name (repeatable)",
    )
    parser.add_argument(
        "--require-writable",
        action="store_true",
        help="Require the supplied game root or DBDAT directory to be writable",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a JSON summary instead of a short text confirmation",
    )
    args = parser.parse_args()

    summary = _build_cli_summary(args)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        mode = str(summary.get("mode") or "")
        if mode == "fixture":
            print(f"Validated fixture root: {summary['fixture_root']}")
        elif mode == "game-root":
            print(f"Validated game root: {summary['game_root']}")
        else:
            print(f"Validated DBDAT directory: {summary['dbdat_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
