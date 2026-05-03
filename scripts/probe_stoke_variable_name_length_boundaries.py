#!/usr/bin/env python3
"""Build a Stoke-only variable-name length boundary proof.

This is a research probe, not a generic editor feature. It uses the certified
compact Stoke physical-variable writer against a fixed-window Stoke base and
patches two visible squad players:

* shortest certified two-token name: ``AB Z``
* longest fixed-80-byte Stoke compact name that fits the current contract:
  31-byte given name + 1-byte surname, visible length 33

It also attempts the known-too-short ``A B`` cursor case and the one-byte-over
long case, recording both expected static failures without writing them.
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
EDITOR_ROOT = REPO_ROOT / "upstream" / "pm99-skezmod-db-editor"
SCRIPT_DIR = Path(__file__).resolve().parent
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from app.editor_actions import _IndexedRawStageRecord, write_player_staged_records  # noqa: E402
from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from assert_pm99_isolated_input import sha256  # noqa: E402
from apply_stoke_2015_current_order_physical_variable_names_patch import (  # noqa: E402
    _patch_physical_variable_payload,
    _resolve_roster,
)
from apply_stoke_2015_role_preserved_compact_variable_patch import _name_prefix, _norm  # noqa: E402
from apply_stoke_2015_variable_names_runtime_patch import (  # noqa: E402
    _extract_nationality_codes,
    _target_source_rows,
)


# A single-character given + single-character surname (`A B`) is format-encoded
# but is not certified for this compact runtime shape: the native/editor parser
# re-anchors the metadata cursor one byte later. `AB Z` is the shortest two-part
# name found that preserves the expected moved cursor.
TOO_SHORT_NAME = "A B"
SHORTEST_NAME = "AB Z"
LONGEST_FIXED80_NAME = "ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE Z"
ONE_BYTE_TOO_LONG_NAME = "ABCDEFGHIJKLMNOPQRSTUVWXYZABCDEF Z"


def _parse_args() -> argparse.Namespace:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--clean-game-base",
        default=str(REPO_ROOT / ".local" / "record33_vanilla_control_20260502T_clean"),
        help="Full clean PM99 game root with known-good EXE/DLL baseline.",
    )
    parser.add_argument(
        "--fixed-stoke-dbdat",
        default=str(REPO_ROOT / ".local" / "stoke_2015_stats_backfill_20260501T065744Z" / "DBDAT"),
        help="Fixed-window Stoke DBDAT base to copy over the clean game root.",
    )
    parser.add_argument(
        "--out-game",
        default=str(REPO_ROOT / ".local" / f"stoke_variable_name_length_boundaries_{stamp}"),
        help="Output full game root to create.",
    )
    parser.add_argument("--team-query", default="Stoke")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _copy_root(clean_game_base: Path, fixed_stoke_dbdat: Path, out_game: Path, *, force: bool) -> None:
    if out_game.exists():
        if not force:
            raise SystemExit(f"Output exists: {out_game}")
        shutil.rmtree(out_game)
    shutil.copytree(clean_game_base, out_game, symlinks=True)
    out_dbdat = out_game / "DBDAT"
    if out_dbdat.exists():
        shutil.rmtree(out_dbdat)
    shutil.copytree(fixed_stoke_dbdat, out_dbdat, symlinks=True)


def _prefix_info(name: str) -> dict[str, Any]:
    prefix = _name_prefix(name)
    given, surname = name.split(" ", 1)
    return {
        "name": name,
        "visible_chars": len(name),
        "given_chars": len(given),
        "surname_chars": len(surname),
        "encoded_prefix_bytes": len(prefix),
        "encoded_prefix_hex": prefix.hex(),
    }


def _patched_row(
    *,
    file_data: bytes,
    entries_by_id: dict[int, Any],
    roster_by_name: dict[str, dict[str, object]],
    source_by_name: dict[str, dict[str, Any]],
    source_player_name: str,
    target_name: str,
    label: str,
) -> tuple[tuple[int, _IndexedRawStageRecord], dict[str, Any]]:
    roster_row = roster_by_name[_norm(source_player_name)]
    source_row = copy.deepcopy(source_by_name[_norm(source_player_name)])
    source_row["game_name"] = target_name
    entry = entries_by_id[int(roster_row["pid"])]
    decoded = entry.decode_payload(file_data)
    patched, meta = _patch_physical_variable_payload(decoded, source_row)
    stage = (
        int(entry.payload_offset),
        _IndexedRawStageRecord(
            raw_payload=patched,
            container_offset=int(entry.payload_offset),
            container_length=int(entry.payload_length),
        ),
    )
    return stage, {
        "label": label,
        "source_player_name": source_player_name,
        "target_name": target_name,
        "pid": int(roster_row["pid"]),
        "slot": int(roster_row["slot"]),
        "payload_offset": int(entry.payload_offset),
        "payload_length_before": int(entry.payload_length),
        **_prefix_info(target_name),
        **meta,
    }


def main() -> int:
    args = _parse_args()
    clean_game_base = Path(args.clean_game_base).expanduser().resolve()
    fixed_stoke_dbdat = Path(args.fixed_stoke_dbdat).expanduser().resolve()
    out_game = Path(args.out_game).expanduser().resolve()
    _copy_root(clean_game_base, fixed_stoke_dbdat, out_game, force=bool(args.force))

    artifact_dir = out_game / "artifacts" / "name_length_boundaries"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    dbdat = out_game / "DBDAT"
    team_file = dbdat / "EQ98030.FDI"
    player_file = dbdat / "JUG98030.FDI"
    country_codes = _extract_nationality_codes(dbdat / "TEXTOS.PKF")
    source_by_name = {_norm(name): row for name, row in _target_source_rows(country_codes).items()}
    roster_rows = _resolve_roster(team_file, player_file, args.team_query)
    roster_by_name = {_norm(str(row["player_name"])): row for row in roster_rows}

    file_data = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(file_data)
    entries_by_id = {int(entry.record_id): entry for entry in indexed.entries}

    stages: list[tuple[int, _IndexedRawStageRecord]] = []
    patches: list[dict[str, Any]] = []
    for source_player_name, target_name, label in (
        ("Jack Butland", SHORTEST_NAME, "shortest_two_token"),
        ("Phil Bardsley", LONGEST_FIXED80_NAME, "longest_fixed80_prefix38"),
    ):
        stage, patch = _patched_row(
            file_data=file_data,
            entries_by_id=entries_by_id,
            roster_by_name=roster_by_name,
            source_by_name=source_by_name,
            source_player_name=source_player_name,
            target_name=target_name,
            label=label,
        )
        stages.append(stage)
        patches.append(patch)

    under_limit: dict[str, Any] = {
        "label": "one_char_given_one_char_surname_parser_anchor",
        **_prefix_info(TOO_SHORT_NAME),
        "expected_failure": True,
    }
    try:
        _patched_row(
            file_data=file_data,
            entries_by_id=entries_by_id,
            roster_by_name=roster_by_name,
            source_by_name=source_by_name,
            source_player_name="Jack Butland",
            target_name=TOO_SHORT_NAME,
            label="one_char_given_one_char_surname_parser_anchor",
        )
        under_limit["failure"] = None
        under_limit["unexpected_success"] = True
    except Exception as exc:  # Expected: parser re-anchors the compact metadata cursor.
        under_limit["failure"] = str(exc)
        under_limit["unexpected_success"] = False

    over_limit: dict[str, Any] = {
        "label": "one_byte_over_fixed80_contract",
        **_prefix_info(ONE_BYTE_TOO_LONG_NAME),
        "expected_failure": True,
    }
    try:
        _patched_row(
            file_data=file_data,
            entries_by_id=entries_by_id,
            roster_by_name=roster_by_name,
            source_by_name=source_by_name,
            source_player_name="Erik Pieters",
            target_name=ONE_BYTE_TOO_LONG_NAME,
            label="one_byte_over_fixed80_contract",
        )
        over_limit["failure"] = None
        over_limit["unexpected_success"] = True
    except Exception as exc:  # Expected: prefix exceeds fixed compact name window.
        over_limit["failure"] = str(exc)
        over_limit["unexpected_success"] = False

    write_player_staged_records(str(player_file), stages, create_backup_before_write=False)

    final_roster = _resolve_roster(team_file, player_file, args.team_query)
    manifest = {
        "schema": "pm99-stoke-variable-name-length-boundary-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "clean_game_base": str(clean_game_base),
        "fixed_stoke_dbdat": str(fixed_stoke_dbdat),
        "out_game": str(out_game),
        "team_query": args.team_query,
        "contract": (
            "Stoke compact dd6360 fixed-80-byte linked-player payload. Name prefix must fit before "
            "the old role block; removed fixed-window padding is moved to the tail."
        ),
        "accepted_count": len(patches),
        "patches": patches,
        "under_limit": under_limit,
        "over_limit": over_limit,
        "final_roster": final_roster,
        "hashes": {
            "MANAGPRE.EXE": sha256(out_game / "MANAGPRE.EXE"),
            "EQ98030.FDI": sha256(team_file),
            "JUG98030.FDI": sha256(player_file),
            "MINIFOTO.PKF": sha256(dbdat / "MINIFOTO.PKF"),
            "MFC42.DLL": sha256(out_game / "MFC42.DLL"),
            "MIDAS11.DLL": sha256(out_game / "MIDAS11.DLL"),
        },
    }
    (artifact_dir / "boundary_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (artifact_dir / "boundary_patches.json").write_text(json.dumps(patches, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "out_game": str(out_game), "manifest": str(artifact_dir / "boundary_manifest.json")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
