#!/usr/bin/env python3
"""Build the role-preserved Stoke 2015 proof with physical variable names.

This is the strict closeout target:

* every original Stoke roster slot keeps its coarse playing role;
* the EQ roster row points at a 2015 Stoke player for that role;
* each target JUG compact linked-player payload uses a physically variable
  name block, with role/metadata moved to the natural cursor position; and
* each linked-player payload remains at the runner-proven 80-byte length.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
EDITOR_ROOT = REPO_ROOT / "upstream" / "pm99-skezmod-db-editor"
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.editor_actions import _IndexedRawStageRecord, edit_team_roster_eq_jug_linked, write_player_staged_records  # noqa: E402
from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from assert_pm99_isolated_input import sha256  # noqa: E402
from apply_stoke_2015_current_order_physical_variable_names_patch import (  # noqa: E402
    _patch_physical_variable_payload,
    _resolve_roster,
)
from apply_stoke_2015_role_preserved_compact_variable_patch import _norm  # noqa: E402
from apply_stoke_2015_variable_names_runtime_patch import _extract_nationality_codes, _target_source_rows  # noqa: E402


DROPPED_FORWARD_PID_FOR_SHAY_GIVEN = 10001
BUTLAND_TEMPLATE_NAME = "Jack Butland"

ROLE_PRESERVED_TARGETS: list[dict[str, Any]] = [
    {"slot": 1, "original_name": "Bryan SMALL", "original_role": "D", "target_name": "Phil Bardsley"},
    {"slot": 2, "original_name": "Peter THORNE", "original_role": "F", "target_name": "Marko Arnautovic"},
    {"slot": 3, "original_name": "Larus SIGURDSSON", "original_role": "D", "target_name": "Erik Pieters"},
    {"slot": 4, "original_name": "Ray WALLACE", "original_role": "D", "target_name": "Marc Muniesa"},
    {"slot": 5, "original_name": "Carl MUGGLETON", "original_role": "G", "target_name": "Jack Butland"},
    {"slot": 6, "original_name": "Richard FORSYTH", "original_role": "M", "target_name": "Glenn Whelan"},
    {"slot": 7, "original_name": "Kevin KEEN", "original_role": "M", "target_name": "Stephen Ireland"},
    {"slot": 8, "original_name": "Simon STURRIDGE", "original_role": "F", "target_name": "Joselu Mato"},
    {"slot": 9, "original_name": "Phillip ROBINSON", "original_role": "M", "target_name": "Ibrahim Afellay"},
    {"slot": 10, "original_name": "David Charles OLDFIELD", "original_role": "M", "target_name": "Marco van Ginkel"},
    {"slot": 11, "original_name": "Kyle LIGHTBOURNE", "original_role": "F", "target_name": "Mame Diouf"},
    {"slot": 12, "original_name": "Chris SHORT", "original_role": "D", "target_name": "Glen Johnson"},
    {"slot": 13, "original_name": "Graham KAVANAGH", "original_role": "M", "target_name": "Charlie Adam"},
    {"slot": 14, "original_name": "Clive CLARKE", "original_role": "D", "target_name": "Marc Wilson"},
    {"slot": 15, "original_name": "Stuart FRASER", "original_role": "G", "target_name": "Shay Given"},
    {"slot": 16, "original_name": "Stephen John WOODS", "original_role": "D", "target_name": "Ryan Shawcross"},
    {"slot": 17, "original_name": "Neil David McKENZIE", "original_role": "M", "target_name": "Giannelli Imbula"},
    {"slot": 18, "original_name": "Dean Anthony CROWE", "original_role": "F", "target_name": "Jonathan Walters"},
    {"slot": 19, "original_name": "Ben PETTY", "original_role": "D", "target_name": "Geoff Cameron"},
    {"slot": 20, "original_name": "Robert HEATH", "original_role": "M", "target_name": "Steve Sidwell"},
]


def _parse_args() -> argparse.Namespace:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-game",
        default=str(REPO_ROOT / ".local" / "stoke_2015_stats_backfill_20260501T065744Z"),
        help="Runner-proven fixed-name compact Stoke 2015 game root.",
    )
    parser.add_argument(
        "--out-game",
        default=str(REPO_ROOT / ".local" / f"stoke_2015_role_preserved_physical_variable_names_{stamp}"),
        help="Output game root to create.",
    )
    parser.add_argument("--team-query", default="Stoke")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _target_pid_map(roster_rows: list[dict[str, object]]) -> dict[str, int]:
    pid_by_name = {_norm(str(row["player_name"])): int(row["pid"]) for row in roster_rows}
    out: dict[str, int] = {}
    for assignment in ROLE_PRESERVED_TARGETS:
        target_name = str(assignment["target_name"])
        if target_name == "Shay Given":
            out[target_name] = DROPPED_FORWARD_PID_FOR_SHAY_GIVEN
            continue
        key = _norm(target_name)
        if key not in pid_by_name:
            raise RuntimeError(f"Target {target_name!r} is not present in the fixed proof roster")
        out[target_name] = pid_by_name[key]
    return out


def _write_static_artifacts(out_game: Path, artifact_dir: Path) -> None:
    # The caller runs the canonical CLI validation after generation; these
    # placeholders keep artifact naming consistent with the current-order proof
    # and are overwritten by the validation commands in the orchestration step.
    (artifact_dir / "team_roster.json").write_text(
        json.dumps({"game": str(out_game), "note": "Run team-roster-linked for parsed roster output."}, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    args = _parse_args()
    base_game = Path(args.base_game).expanduser().resolve()
    out_game = Path(args.out_game).expanduser().resolve()
    if out_game.exists():
        if not args.force:
            raise SystemExit(f"Output exists: {out_game}")
        shutil.rmtree(out_game)
    shutil.copytree(base_game, out_game, symlinks=True)
    artifact_dir = out_game / "artifacts" / "role_preserved_physical_variable_names"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    dbdat = out_game / "DBDAT"
    team_file = dbdat / "EQ98030.FDI"
    player_file = dbdat / "JUG98030.FDI"
    coach_file = dbdat / "ENT98030.FDI"
    country_codes = _extract_nationality_codes(dbdat / "TEXTOS.PKF")
    source_by_name = _target_source_rows(country_codes)
    roster_rows = _resolve_roster(team_file, player_file, args.team_query)
    target_pid_by_name = _target_pid_map(roster_rows)

    file_data = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(file_data)
    entries_by_id = {int(entry.record_id): entry for entry in indexed.entries}
    butland_pid = target_pid_by_name[BUTLAND_TEMPLATE_NAME]
    butland_entry = entries_by_id[butland_pid]

    stages: list[tuple[int, _IndexedRawStageRecord]] = []
    patch_by_name: dict[str, dict[str, Any]] = {}
    for target_name, target_pid in sorted(target_pid_by_name.items(), key=lambda item: item[1]):
        source_row = source_by_name[target_name]
        template_entry = butland_entry if target_name == "Shay Given" else entries_by_id[int(target_pid)]
        decoded = template_entry.decode_payload(file_data)
        patched, meta = _patch_physical_variable_payload(decoded, source_row)
        target_entry = entries_by_id[int(target_pid)]
        if len(patched) != int(target_entry.payload_length):
            raise RuntimeError(
                f"Patched payload for {target_name!r} length {len(patched)} does not match "
                f"target container length {target_entry.payload_length}"
            )
        stages.append(
            (
                int(target_entry.payload_offset),
                _IndexedRawStageRecord(
                    raw_payload=patched,
                    container_offset=int(target_entry.payload_offset),
                    container_length=int(target_entry.payload_length),
                ),
            )
        )
        patch_by_name[target_name] = {
            "target_name": target_name,
            "pid": int(target_pid),
            "template_name": BUTLAND_TEMPLATE_NAME if target_name == "Shay Given" else target_name,
            **meta,
        }

    backup_path = write_player_staged_records(str(player_file), stages, create_backup_before_write=True)

    assignment_rows: list[dict[str, Any]] = []
    patch_rows: list[dict[str, Any]] = []
    for assignment in ROLE_PRESERVED_TARGETS:
        target_name = str(assignment["target_name"])
        target_pid = int(target_pid_by_name[target_name])
        result = edit_team_roster_eq_jug_linked(
            team_file=str(team_file),
            player_file=str(player_file),
            team_query=args.team_query,
            slot_number=int(assignment["slot"]),
            player_record_id=target_pid,
            flag=0,
            write_changes=True,
        )
        changes = [
            {
                "slot_number": int(change.slot_number),
                "old_player_record_id": int(change.old_player_record_id),
                "new_player_record_id": int(change.new_player_record_id),
                "old_player_name": str(change.old_player_name),
                "new_player_name": str(change.new_player_name),
            }
            for change in list(getattr(result, "changes", []) or [])
        ]
        assignment_row = {
            **assignment,
            "target_pid": target_pid,
            "changes": changes,
        }
        assignment_rows.append(assignment_row)
        patch_rows.append(
            {
                "slot": int(assignment["slot"]),
                "original_name": str(assignment["original_name"]),
                "original_role": str(assignment["original_role"]),
                "target_role": str(assignment["original_role"]),
                **patch_by_name[target_name],
                "assignment": assignment_row,
            }
        )

    final_rows = _resolve_roster(team_file, player_file, args.team_query)
    final_by_slot = {int(row["slot"]): row for row in final_rows}
    failures: list[dict[str, Any]] = []
    for assignment in ROLE_PRESERVED_TARGETS:
        slot = int(assignment["slot"])
        actual_name = str(final_by_slot[slot]["player_name"])
        if _norm(actual_name) != _norm(str(assignment["target_name"])):
            failures.append({"slot": slot, "expected": assignment["target_name"], "actual": actual_name})

    (artifact_dir / "role_preserved_assignments.json").write_text(
        json.dumps(assignment_rows, indent=2),
        encoding="utf-8",
    )
    (artifact_dir / "physical_variable_patches.json").write_text(
        json.dumps(patch_rows, indent=2),
        encoding="utf-8",
    )
    (artifact_dir / "team_roster_final.json").write_text(json.dumps(final_rows, indent=2), encoding="utf-8")
    _write_static_artifacts(out_game, artifact_dir)

    manifest = {
        "schema": "pm99-stoke-2015-role-preserved-physical-variable-names-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "base_game": str(base_game),
        "out_game": str(out_game),
        "ok": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "contract": (
            "Each original Stoke slot keeps its coarse role; EQ references point to the closest 2015 player; "
            "JUG compact dd6360 payloads use physically variable name blocks with role/metadata immediately "
            "after the natural name prefix and tail padding moved out of the parse path."
        ),
        "dropped_forward_reused_for_shay_given_pid": DROPPED_FORWARD_PID_FOR_SHAY_GIVEN,
        "butland_template_pid": int(butland_pid),
        "jug_backup_path": str(backup_path) if backup_path else None,
        "assignment_json": str(artifact_dir / "role_preserved_assignments.json"),
        "patches_json": str(artifact_dir / "physical_variable_patches.json"),
        "final_roster_json": str(artifact_dir / "team_roster_final.json"),
        "hashes": {
            "EQ98030.FDI": sha256(team_file),
            "JUG98030.FDI": sha256(player_file),
            "ENT98030.FDI": sha256(coach_file),
        },
    }
    (artifact_dir / "physical_variable_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": manifest["ok"],
                "out_game": str(out_game),
                "manifest": str(artifact_dir / "physical_variable_manifest.json"),
                "patch_rows": len(patch_rows),
                "failure_count": len(failures),
            },
            indent=2,
        )
    )
    return 0 if manifest["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
