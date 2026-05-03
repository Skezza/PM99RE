#!/usr/bin/env python3
"""Build a native-English-club variable-name runtime probe.

This PM99RE research helper intentionally avoids Stoke surrogate roster
repointing. It patches one existing linked JUG player in each selected English
club and writes a lean hardlink-based full game root for PM99 runner proof.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import os
import re
import shutil
import sys
from dataclasses import asdict, dataclass
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
    _indexed_variable_name_prefix,
    write_player_staged_records,
)
from app.editor_helpers import _player_display_name  # noqa: E402
from app.eq_jug_linked import EQLinkedTeamRoster, load_eq_linked_team_rosters  # noqa: E402
from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from app.models import PlayerRecord  # noqa: E402
from assert_pm99_isolated_input import sha256  # noqa: E402
from probe_full_game_variable_name_windows import (  # noqa: E402
    PlayerWindow,
    _load_windows,
    _norm,
    _patch_dd6360_move_cursor,
    _patch_dd6361_static,
)


DEFAULT_BASE_GAME = REPO_ROOT / ".local" / "record33_vanilla_control_20260502T_clean"
DEFAULT_WORLD_STATE = REPO_ROOT / ".local" / "selector_maps" / "pm99_vanilla_english_80_world_stub.json"
DEFAULT_SELECTOR_MAP = REPO_ROOT / ".local" / "selector_maps" / "pm99_vanilla_english_80_selector_map.json"
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT
    / ".local"
    / f"full_game_variable_name_native_english30_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
)

_SKIP_DIR_NAMES = {"PM99.rep", "__pycache__"}
_SKIP_FILE_SUBSTRINGS = (
    ".bak",
    "bak_",
    "backup",
    ".original",
    ".pre_",
    ".stable_",
    "pm99.lock",
)


@dataclass(frozen=True)
class NativeClubSelection:
    club_index: int
    club_key: str
    team_query: str
    selector_team_query: str
    roster_eq_record_id: int
    roster_short_name: str
    roster_full_club_name: str
    roster_match_score: float
    source_slot: int
    row_flag: int
    record_id: int
    old_name: str
    target_name: str
    head_hex: str
    family: str
    max_prefix_bytes: int
    payload_length: int
    encoded_prefix_bytes: int


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-game", default=str(DEFAULT_BASE_GAME))
    parser.add_argument("--world-state", default=str(DEFAULT_WORLD_STATE))
    parser.add_argument("--selector-map", default=str(DEFAULT_SELECTOR_MAP))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--club-count", type=int, default=30)
    parser.add_argument("--runner-batch-size", type=int, default=10)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _normalized(value: str) -> str:
    return _norm(value)


def _should_skip_file(path: Path) -> bool:
    lowered = path.name.casefold()
    return any(token in lowered for token in _SKIP_FILE_SUBSTRINGS)


def _copy_or_link_file(source: Path, destination: Path, *, copy: bool) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    if copy:
        shutil.copy2(source, destination)
        return
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _copy_lean_game_root(base_game: Path, output_game: Path) -> None:
    if output_game.exists():
        shutil.rmtree(output_game)
    output_game.mkdir(parents=True)
    for dirpath, dirnames, filenames in os.walk(base_game):
        src_dir = Path(dirpath)
        relative_dir = src_dir.relative_to(base_game)
        dirnames[:] = [
            name
            for name in dirnames
            if name not in _SKIP_DIR_NAMES and not name.casefold().endswith(".rep")
        ]
        (output_game / relative_dir).mkdir(parents=True, exist_ok=True)
        for filename in filenames:
            source = src_dir / filename
            if _should_skip_file(source):
                continue
            relative = source.relative_to(base_game)
            destination = output_game / relative
            _copy_or_link_file(
                source,
                destination,
                copy=relative.as_posix().casefold() == "dbdat/jug98030.fdi",
            )


def _score_roster_match(club: dict[str, Any], roster: EQLinkedTeamRoster) -> float:
    probes = [
        str(club.get("team_query") or ""),
        *(str(alias) for alias in list(club.get("aliases") or [])),
        str(club.get("club_key") or "").replace("_", " "),
    ]
    roster_names = [str(roster.short_name or ""), str(roster.full_club_name or "")]
    best = 0.0
    for probe in probes:
        nprobe = _normalized(probe)
        if not nprobe:
            continue
        for roster_name in roster_names:
            nroster = _normalized(roster_name)
            if not nroster:
                continue
            if nprobe == nroster:
                best = max(best, 100.0)
            elif nprobe in nroster or nroster in nprobe:
                best = max(best, 86.0)
            ratio = difflib.SequenceMatcher(None, nprobe, nroster).ratio()
            best = max(best, ratio * 82.0)
    return best


def _match_rosters_to_clubs(
    *,
    clubs: list[dict[str, Any]],
    rosters: list[EQLinkedTeamRoster],
) -> dict[str, tuple[EQLinkedTeamRoster, float]]:
    matches: dict[str, tuple[EQLinkedTeamRoster, float]] = {}
    used_eq_ids: set[int] = set()
    for club in clubs:
        scored = sorted(
            (
                (_score_roster_match(club, roster), roster)
                for roster in rosters
                if int(roster.eq_record_id) not in used_eq_ids
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        if not scored:
            continue
        score, roster = scored[0]
        if score < 70.0:
            continue
        club_key = str(club.get("club_key") or "")
        if not club_key:
            continue
        matches[club_key] = (roster, score)
        used_eq_ids.add(int(roster.eq_record_id))
    return matches


def _target_name(index: int) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    first = alphabet[(index // len(alphabet)) % len(alphabet)]
    second = alphabet[index % len(alphabet)]
    surname = alphabet[(index * 7) % len(alphabet)]
    return f"{first}{second} {surname}"


def _player_name(decoded: bytes, payload_offset: int) -> str:
    parsed = PlayerRecord.from_bytes(decoded, payload_offset)
    return " ".join(str(_player_display_name(parsed) or "").split())


def _select_native_clubs(
    *,
    clubs: list[dict[str, Any]],
    selectors: dict[str, dict[str, Any]],
    matches: dict[str, tuple[EQLinkedTeamRoster, float]],
    windows_by_id: dict[int, PlayerWindow],
    club_count: int,
) -> list[NativeClubSelection]:
    selected: list[NativeClubSelection] = []
    used_pids: set[int] = set()
    accepted_prefix_len = len(_indexed_variable_name_prefix("AB Z"))
    for club in clubs:
        if len(selected) >= club_count:
            break
        club_key = str(club.get("club_key") or "")
        selector = selectors.get(club_key)
        match = matches.get(club_key)
        if selector is None or match is None:
            continue
        roster, score = match
        candidates: list[tuple[int, int, Any, PlayerWindow]] = []
        for row in list(getattr(roster, "rows", []) or []):
            pid = int(getattr(row, "player_record_id", 0) or 0)
            if pid in used_pids:
                continue
            window = windows_by_id.get(pid)
            if not window:
                continue
            is_supported_dd6360 = (
                window.head_hex == "dd6360"
                and window.shortest_accept_status == "accepted"
                and window.max_accept_status == "accepted"
                and window.too_long_status == "rejected"
                and int(window.payload_length or 0) >= 80
                and int(window.max_prefix_bytes or 0) >= accepted_prefix_len
            )
            is_supported_dd6361 = (
                window.head_hex == "dd6361"
                and window.shortest_accept_status == "accepted"
                and window.max_accept_status == "accepted"
                and int(window.max_prefix_bytes or 0) >= accepted_prefix_len
            )
            if is_supported_dd6360 or is_supported_dd6361:
                flag = int(getattr(row, "flag", 0) or 0)
                slot = int(getattr(row, "slot_index", 0) or 0) + 1
                candidates.append((0 if flag == 0 else 1, slot, row, window))
        if not candidates:
            continue
        _, _, row, window = sorted(candidates, key=lambda item: (item[0], item[1], int(item[3].record_id)))[0]
        target_name = _target_name(len(selected))
        used_pids.add(int(window.record_id))
        selected.append(
            NativeClubSelection(
                club_index=len(selected) + 1,
                club_key=club_key,
                team_query=str(club.get("team_query") or ""),
                selector_team_query=str(selector.get("team_query") or club.get("team_query") or ""),
                roster_eq_record_id=int(roster.eq_record_id),
                roster_short_name=str(roster.short_name or ""),
                roster_full_club_name=str(roster.full_club_name or ""),
                roster_match_score=round(float(score), 2),
                source_slot=int(getattr(row, "slot_index", 0) or 0) + 1,
                row_flag=int(getattr(row, "flag", 0) or 0),
                record_id=int(window.record_id),
                old_name=str(window.player_name),
                target_name=target_name,
                head_hex=str(window.head_hex),
                family=str(window.family),
                max_prefix_bytes=int(window.max_prefix_bytes or 0),
                payload_length=int(window.payload_length or 0),
                encoded_prefix_bytes=len(_indexed_variable_name_prefix(target_name)),
            )
        )
    if len(selected) < club_count:
        raise RuntimeError(f"Only selected {len(selected)} native clubs; requested {club_count}")
    return selected


def _patch_selected_names(player_file: Path, selections: list[NativeClubSelection]) -> list[dict[str, Any]]:
    file_data = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(file_data)
    entries_by_id = {int(entry.record_id): entry for entry in indexed.entries}
    stages: list[tuple[int, _IndexedRawStageRecord]] = []
    patch_rows: list[dict[str, Any]] = []
    for selection in selections:
        entry = entries_by_id[int(selection.record_id)]
        decoded = entry.decode_payload(file_data)
        if selection.head_hex == "dd6360":
            patched, meta = _patch_dd6360_move_cursor(decoded, selection.old_name, selection.target_name)
        elif selection.head_hex == "dd6361":
            patched, meta = _patch_dd6361_static(decoded, selection.old_name, selection.target_name)
        else:
            raise RuntimeError(f"Unsupported selected player family {selection.head_hex!r} for {selection.old_name!r}")
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
        patch_rows.append({**asdict(selection), **meta, "payload_offset": int(entry.payload_offset)})
    write_player_staged_records(str(player_file), stages, create_backup_before_write=False)
    return patch_rows


def _readback_selected_names(
    *,
    game_dir: Path,
    selections: list[NativeClubSelection],
) -> list[dict[str, Any]]:
    player_file = game_dir / "DBDAT" / "JUG98030.FDI"
    team_file = game_dir / "DBDAT" / "EQ98030.FDI"
    file_data = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(file_data)
    entries_by_id = {int(entry.record_id): entry for entry in indexed.entries}
    rosters = list(load_eq_linked_team_rosters(team_file=str(team_file), player_file=str(player_file)))
    roster_by_eq = {int(roster.eq_record_id): roster for roster in rosters}
    rows: list[dict[str, Any]] = []
    for selection in selections:
        entry = entries_by_id[int(selection.record_id)]
        decoded = entry.decode_payload(file_data)
        parsed_name = _player_name(decoded, int(entry.payload_offset))
        roster = roster_by_eq[int(selection.roster_eq_record_id)]
        roster_name = ""
        for row in list(getattr(roster, "rows", []) or []):
            if int(getattr(row, "player_record_id", 0) or 0) == int(selection.record_id):
                roster_name = " ".join(str(getattr(row, "player_name", "") or "").split())
                break
        ok = _normalized(parsed_name) == _normalized(selection.target_name) and _normalized(roster_name) == _normalized(
            selection.target_name
        )
        rows.append(
            {
                **asdict(selection),
                "parsed_name": parsed_name,
                "linked_roster_name": roster_name,
                "readback_ok": ok,
            }
        )
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_runner_batches(
    *,
    output_dir: Path,
    game_dir: Path,
    world_state: Path,
    selector_map: Path,
    selections: list[NativeClubSelection],
    batch_size: int,
) -> list[dict[str, Any]]:
    batches: list[dict[str, Any]] = []
    for index in range(0, len(selections), batch_size):
        batch_no = (index // batch_size) + 1
        batch = selections[index : index + batch_size]
        tag = f"fullgame_varwin_native_english30_b{batch_no:02d}_20260503T_runtime"
        command = [
            "./scripts/run_2025_roster_visual_sample.sh",
            "--game-root",
            str(game_dir),
            "--world-state",
            str(world_state),
            "--selector-map",
            str(selector_map),
            "--run-tag",
            tag,
            "--capture-route",
            "squad",
            "--profile-count",
            "0",
            "--squad-enable-status-filters",
            "--squad-scroll-proof-pages",
            "1",
            "--squad-scroll-clicks",
            "6",
            "--skip-setup",
            "--skip-build",
            "--cleanup-on-failure",
        ]
        for selection in batch:
            command.extend(["--club-key", selection.club_key])
        payload = {
            "batch_no": batch_no,
            "run_tag": tag,
            "club_keys": [selection.club_key for selection in batch],
            "expected_names": {selection.club_key: selection.target_name for selection in batch},
            "command": command,
        }
        batches.append(payload)
        script_path = output_dir / f"run_native_batch_{batch_no:02d}.sh"
        script_path.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "cd \"$(dirname \"$0\")/../..\"\n"
            "PM99_RUNNER_WORKER_LANE_COUNT=${PM99_RUNNER_WORKER_LANE_COUNT:-2} \\\n"
            "PM99_RUNNER_DOCKER_TIMEOUT_SECONDS=${PM99_RUNNER_DOCKER_TIMEOUT_SECONDS:-1800} \\\n"
            + " ".join(_shell_quote(part) for part in command)
            + "\n",
            encoding="utf-8",
        )
        script_path.chmod(0o755)
    return batches


def _shell_quote(value: object) -> str:
    text = str(value)
    if re.fullmatch(r"[A-Za-z0-9_./:=+-]+", text):
        return text
    return "'" + text.replace("'", "'\"'\"'") + "'"


def build(args: argparse.Namespace) -> dict[str, Any]:
    base_game = Path(args.base_game).expanduser().resolve()
    world_state = Path(args.world_state).expanduser().resolve()
    selector_map = Path(args.selector_map).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    if output_dir.exists():
        if not args.force:
            raise FileExistsError(output_dir)
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    world = json.loads(world_state.read_text(encoding="utf-8"))
    selector_payload = json.loads(selector_map.read_text(encoding="utf-8"))
    clubs = [item for item in list(world.get("clubs") or []) if isinstance(item, dict)]
    selectors = {
        str(item.get("club_key") or ""): item
        for item in list(selector_payload.get("selectors") or [])
        if isinstance(item, dict) and str(item.get("club_key") or "")
    }

    player_file = base_game / "DBDAT" / "JUG98030.FDI"
    team_file = base_game / "DBDAT" / "EQ98030.FDI"
    windows, _, _, _ = _load_windows(player_file)
    windows_by_id = {int(window.record_id): window for window in windows}
    rosters = list(load_eq_linked_team_rosters(team_file=str(team_file), player_file=str(player_file)))
    matches = _match_rosters_to_clubs(clubs=clubs, rosters=rosters)
    selections = _select_native_clubs(
        clubs=clubs,
        selectors=selectors,
        matches=matches,
        windows_by_id=windows_by_id,
        club_count=int(args.club_count),
    )

    game_dir = output_dir / "game"
    _copy_lean_game_root(base_game, game_dir)
    patches = _patch_selected_names(game_dir / "DBDAT" / "JUG98030.FDI", selections)
    readback_rows = _readback_selected_names(game_dir=game_dir, selections=selections)
    if not all(bool(row["readback_ok"]) for row in readback_rows):
        _json_dump(output_dir / "readback_failures.json", [row for row in readback_rows if not row["readback_ok"]])
        raise RuntimeError(f"Native linked readback failed; see {output_dir / 'readback_failures.json'}")

    batches = _write_runner_batches(
        output_dir=output_dir,
        game_dir=game_dir,
        world_state=world_state,
        selector_map=selector_map,
        selections=selections,
        batch_size=int(args.runner_batch_size),
    )
    summary = {
        "success": True,
        "scope": "native_english_club_variable_name_runtime_probe",
        "base_game": str(base_game),
        "game_dir": str(game_dir),
        "world_state": str(world_state),
        "selector_map": str(selector_map),
        "club_count": len(selections),
        "runner_batch_count": len(batches),
        "selected_clubs": [asdict(selection) for selection in selections],
        "runner_batches": batches,
        "core_hashes": {
            "MANAGPRE.EXE": sha256(game_dir / "MANAGPRE.EXE"),
            "DBDAT/JUG98030.FDI": sha256(game_dir / "DBDAT" / "JUG98030.FDI"),
            "DBDAT/EQ98030.FDI": sha256(game_dir / "DBDAT" / "EQ98030.FDI"),
            "DBDAT/MINIFOTO.PKF": sha256(game_dir / "DBDAT" / "MINIFOTO.PKF"),
        },
    }
    _json_dump(output_dir / "summary.json", summary)
    _json_dump(output_dir / "selected_native_clubs.json", [asdict(selection) for selection in selections])
    _json_dump(output_dir / "name_patches.json", patches)
    _json_dump(output_dir / "native_linked_readback.json", readback_rows)
    _json_dump(output_dir / "runner_batches.json", batches)
    _write_csv(output_dir / "selected_native_clubs.csv", [asdict(selection) for selection in selections])
    _write_csv(output_dir / "native_linked_readback.csv", readback_rows)
    return summary


def main() -> int:
    summary = build(_parse_args())
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
