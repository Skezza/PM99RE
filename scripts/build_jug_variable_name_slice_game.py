#!/usr/bin/env python3
"""Build an isolated PM99 game with a slice of JUG variable-name rewrites."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
EDITOR_ROOT = REPO_ROOT / "upstream" / "pm99-skezmod-db-editor"
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.editor_actions import (  # noqa: E402
    _IndexedRawStageRecord,
    _patch_indexed_player_variable_name_payload,
    write_player_staged_records,
)
from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from build_full_corpus_variable_name_proof_waves import (  # noqa: E402
    DEFAULT_BASE_GAME,
    TargetRow,
    _copy_lean_game_root,
    _load_targets,
    _proof_name,
)
from probe_full_jug_variable_names_db_only import _patch_payload  # noqa: E402


DEFAULT_OUTPUT_ROOT = REPO_ROOT / "work" / "pm99" / "jug_variable_name_slice_bisect"


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-game", default=str(DEFAULT_BASE_GAME))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT / stamp))
    parser.add_argument("--start", type=int, default=0, help="First parser-backed target index to patch.")
    parser.add_argument("--count", type=int, default=0, help="Number of targets to patch. 0 means all after start.")
    parser.add_argument(
        "--allow-unsafe-research-patcher",
        action="store_true",
        help="Use the old research-only patcher that can bypass editor runtime-safety gates.",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _slice_targets(targets: list[TargetRow], start: int, count: int) -> list[TargetRow]:
    if start < 0:
        raise ValueError("--start must be >= 0")
    if count < 0:
        raise ValueError("--count must be >= 0")
    end = len(targets) if count == 0 else min(len(targets), start + count)
    if start > len(targets):
        raise ValueError(f"--start {start} exceeds target count {len(targets)}")
    return targets[start:end]


def build(
    base_game: Path,
    output_dir: Path,
    start: int,
    count: int,
    force: bool,
    *,
    allow_unsafe_research_patcher: bool = False,
) -> dict[str, Any]:
    if output_dir.exists():
        if not force:
            raise SystemExit(f"Output exists; pass --force: {output_dir}")
        shutil.rmtree(output_dir)
    game_dir = output_dir / "game"
    _copy_lean_game_root(base_game, game_dir, copy_db_files={"DBDAT/JUG98030.FDI"})

    player_file = game_dir / "DBDAT" / "JUG98030.FDI"
    targets, preserve_only = _load_targets(player_file)
    selected = _slice_targets(targets, start, count)

    data = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(data)
    entries_by_id = {int(entry.record_id): entry for entry in indexed.entries}
    stages: list[tuple[int, _IndexedRawStageRecord]] = []
    patch_rows: list[dict[str, Any]] = []
    blocked_rows: list[dict[str, Any]] = []

    for target in selected:
        entry = entries_by_id[int(target.record_id)]
        decoded = entry.decode_payload(data)
        try:
            if allow_unsafe_research_patcher:
                patched, meta = _patch_payload(decoded, target.old_name, _proof_name(target.proof_index))
            else:
                patched, meta = _patch_indexed_player_variable_name_payload(
                    decoded,
                    target.old_name,
                    _proof_name(target.proof_index),
                )
        except Exception as exc:
            blocked_rows.append(
                {
                    **asdict(target),
                    "target_name": _proof_name(target.proof_index),
                    "status": "preserve_only",
                    "failure": str(exc),
                    "old_payload_length": int(entry.payload_length),
                }
            )
            continue
        stages.append(
            (
                int(entry.payload_offset),
                _IndexedRawStageRecord(
                    raw_payload=patched,
                    container_offset=int(entry.payload_offset),
                    container_length=int(entry.payload_length),
                ),
            )
        )
        patch_rows.append(
            {
                **asdict(target),
                "target_name": _proof_name(target.proof_index),
                "family": str(meta["family"]),
                "old_payload_length": int(meta["old_payload_length"]),
                "new_payload_length": int(meta["new_payload_length"]),
                "payload_length_delta": int(meta["payload_length_delta"]),
                "name_end_delta": int(meta["name_end_delta"]),
            }
        )

    if stages:
        write_player_staged_records(str(player_file), stages, create_backup_before_write=False)

    summary = {
        "success": True,
        "base_game": str(base_game),
        "output_dir": str(output_dir),
        "game_dir": str(game_dir),
        "start": start,
        "count": len(selected),
        "requested_count": count,
        "patch_count": len(patch_rows),
        "blocked_count": len(blocked_rows),
        "allow_unsafe_research_patcher": bool(allow_unsafe_research_patcher),
        "target_count": len(targets),
        "preserve_only_count": len(preserve_only),
        "first_target": asdict(selected[0]) if selected else None,
        "last_target": asdict(selected[-1]) if selected else None,
        "payload_length_delta_counts": {
            str(delta): sum(1 for row in patch_rows if int(row["payload_length_delta"]) == delta)
            for delta in sorted({int(row["payload_length_delta"]) for row in patch_rows})
        },
        "patch_rows": patch_rows,
        "blocked_rows": blocked_rows,
    }
    _json_dump(output_dir / "summary.json", summary)
    return summary


def main() -> int:
    args = _parse_args()
    summary = build(
        base_game=Path(args.base_game).expanduser().resolve(),
        output_dir=Path(args.output_dir).expanduser().resolve(),
        start=int(args.start),
        count=int(args.count),
        force=bool(args.force),
        allow_unsafe_research_patcher=bool(args.allow_unsafe_research_patcher),
    )
    print(
        json.dumps(
            {
                key: summary[key]
                for key in (
                    "success",
                    "game_dir",
                    "start",
                    "count",
                    "patch_count",
                    "blocked_count",
                    "target_count",
                    "allow_unsafe_research_patcher",
                )
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
