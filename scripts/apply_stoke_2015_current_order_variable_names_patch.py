#!/usr/bin/env python3
"""Apply natural variable name fields to the runner-proven Stoke 2015 order.

This keeps the EQ roster references from the successful fixed-name proof and
only rebuilds each compact JUG name window with natural surname/full-name length
bytes. The compact payload length and markerless metadata anchor stay stable.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EDITOR_ROOT = REPO_ROOT / "upstream" / "pm99-skezmod-db-editor"
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.editor_actions import _IndexedRawStageRecord, write_player_staged_records  # noqa: E402
from app.eq_jug_linked import load_eq_linked_team_rosters  # noqa: E402
from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from assert_pm99_isolated_input import sha256  # noqa: E402
from apply_stoke_2015_role_preserved_roster_reference_patch import _patch_compact_payload  # noqa: E402
from apply_stoke_2015_semantic_runtime_patch import _extract_nationality_codes, _source_rows  # noqa: E402


def _parse_args() -> argparse.Namespace:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-game",
        default=str(REPO_ROOT / ".local" / "stoke_2015_stats_backfill_20260501T065744Z"),
        help="Runner-proven fixed-name Stoke 2015 game root.",
    )
    parser.add_argument(
        "--out-game",
        default=str(REPO_ROOT / ".local" / f"stoke_2015_current_order_variable_names_{stamp}"),
        help="Output game root to create.",
    )
    parser.add_argument("--team-query", default="Stoke")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _resolve_roster(team_file: Path, player_file: Path, team_query: str) -> list[dict[str, object]]:
    needle = team_query.casefold()
    for roster in load_eq_linked_team_rosters(team_file=str(team_file), player_file=str(player_file)):
        names = [
            str(getattr(roster, "short_name", "") or "").casefold(),
            str(getattr(roster, "full_club_name", "") or "").casefold(),
        ]
        if not any(needle in item for item in names):
            continue
        rows = sorted(list(getattr(roster, "rows", []) or []), key=lambda row: int(getattr(row, "slot_index", 0)))
        return [
            {
                "slot": int(getattr(row, "slot_index", 0)) + 1,
                "pid": int(getattr(row, "player_record_id", 0) or 0),
                "player_name": str(getattr(row, "player_name", "") or ""),
            }
            for row in rows[:20]
        ]
    raise RuntimeError(f"Could not resolve roster for {team_query!r}")


def _norm(text: str) -> str:
    return "".join(ch for ch in str(text).casefold() if ch.isalnum())


def main() -> int:
    args = _parse_args()
    base_game = Path(args.base_game).expanduser().resolve()
    out_game = Path(args.out_game).expanduser().resolve()
    if out_game.exists():
        if not args.force:
            raise SystemExit(f"Output exists: {out_game}")
        shutil.rmtree(out_game)
    shutil.copytree(base_game, out_game, symlinks=True)
    artifact_dir = out_game / "artifacts" / "current_order_variable_names"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    dbdat = out_game / "DBDAT"
    team_file = dbdat / "EQ98030.FDI"
    player_file = dbdat / "JUG98030.FDI"
    coach_file = dbdat / "ENT98030.FDI"
    roster_rows = _resolve_roster(team_file, player_file, args.team_query)
    source_by_name = {_norm(row["game_name"]): row for row in _source_rows(_extract_nationality_codes(dbdat / "TEXTOS.PKF"))}

    file_data = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(file_data)
    entries_by_id = {int(entry.record_id): entry for entry in indexed.entries}
    stages: list[tuple[int, _IndexedRawStageRecord]] = []
    patch_rows: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    for roster_row in roster_rows:
        source_row = source_by_name.get(_norm(str(roster_row["player_name"])))
        if source_row is None:
            failures.append({"slot": roster_row["slot"], "player_name": roster_row["player_name"], "reason": "missing_source_row"})
            continue
        entry = entries_by_id[int(roster_row["pid"])]
        decoded = entry.decode_payload(file_data)
        patched, meta = _patch_compact_payload(decoded, source_row, template_name=str(roster_row["player_name"]))
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
        patch_rows.append({"slot": roster_row["slot"], "pid": roster_row["pid"], "target_name": roster_row["player_name"], **meta})

    backup_path = write_player_staged_records(str(player_file), stages, create_backup_before_write=True)
    (artifact_dir / "current_order_variable_patches.json").write_text(json.dumps(patch_rows, indent=2), encoding="utf-8")
    (artifact_dir / "team_roster.json").write_text(json.dumps(roster_rows, indent=2), encoding="utf-8")
    manifest = {
        "schema": "pm99-stoke-2015-current-order-variable-names-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "base_game": str(base_game),
        "out_game": str(out_game),
        "ok": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "contract": "Runner-proven Stoke current-squad order preserved; natural variable-length name fields inside stable 80-byte compact payloads.",
        "jug_backup_path": str(backup_path) if backup_path else None,
        "patches_json": str(artifact_dir / "current_order_variable_patches.json"),
        "team_roster_json": str(artifact_dir / "team_roster.json"),
        "hashes": {
            "EQ98030.FDI": sha256(team_file),
            "JUG98030.FDI": sha256(player_file),
            "ENT98030.FDI": sha256(coach_file),
        },
    }
    (artifact_dir / "current_order_variable_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"ok": manifest["ok"], "out_game": str(out_game), "manifest": str(artifact_dir / "current_order_variable_manifest.json")}, indent=2))
    return 0 if manifest["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
