#!/usr/bin/env python3
"""Full-game variable player-name window probe plus runner batch builder.

This is a PM99RE research probe. It does not claim the product editor can safely
apply all of these contracts yet. It measures every parser-backed indexed JUG
player record, then builds Stoke-surrogate runner batches by placing sampled
players from 30 source teams into Stoke's linked roster so the existing runner
profile route can visually validate those player payloads in-game.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import sys
from collections import Counter
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
    _indexed_variable_name_compact_segments,
    _indexed_variable_name_prefix,
    _indexed_variable_name_runtime_segments,
    batch_edit_team_roster_records,
    write_player_staged_records,
)
from app.editor_helpers import _player_display_name  # noqa: E402
from app.eq_jug_linked import load_eq_linked_team_rosters  # noqa: E402
from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from app.models import PlayerRecord  # noqa: E402
from assert_pm99_isolated_input import sha256  # noqa: E402


SHORT_ACCEPTED_NAME = "AB Z"
SHORT_REJECTED_NAME = "A B"


@dataclass
class PlayerWindow:
    record_id: int
    key: str
    payload_offset: int
    payload_length: int
    head_hex: str
    player_name: str
    family: str
    first_len_offset: int | None = None
    name_end: int | None = None
    pre_marker_gap_bytes: int | None = None
    old_role_start: int | None = None
    max_prefix_bytes: int | None = None
    max_visible_chars_surname1: int | None = None
    current_prefix_bytes: int | None = None
    shortest_accept_status: str = ""
    too_short_status: str = ""
    max_accept_status: str = ""
    too_long_status: str = ""
    failure: str = ""


@dataclass
class SamplePlayer:
    batch_index: int
    batch_slot: int
    source_team_name: str
    source_full_club_name: str
    source_eq_record_id: int
    source_slot: int
    record_id: int
    old_name: str
    target_name: str
    target_case: str
    visible_chars: int
    encoded_prefix_bytes: int
    family: str
    pre_marker_gap_bytes: int
    max_prefix_bytes: int
    payload_length: int


def _parse_args() -> argparse.Namespace:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-game",
        default=str(REPO_ROOT / ".local" / "record33_vanilla_control_20260502T_clean"),
        help="Clean full PM99 game root to probe.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / ".local" / f"full_game_variable_name_windows_{stamp}"),
        help="Output research artifact directory.",
    )
    parser.add_argument("--sample-team-count", type=int, default=30)
    parser.add_argument("--players-per-team", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--target-team-query", default="Stoke")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _display_name(decoded: bytes, payload_offset: int) -> str:
    parsed = PlayerRecord.from_bytes(decoded, payload_offset)
    return " ".join(str(_player_display_name(parsed) or "").split())


def _repeat_letters(length: int, *, seed: int = 0) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if length <= 0:
        return ""
    rotated = alphabet[seed % len(alphabet) :] + alphabet[: seed % len(alphabet)]
    return (rotated * ((length // len(rotated)) + 1))[:length]


def _name_for_visible_length(visible_chars: int, *, seed: int = 0) -> str:
    if visible_chars < 4:
        raise ValueError(f"Need at least 4 visible chars for a two-token PM99 name, got {visible_chars}")
    given_len = int(visible_chars) - 2
    surname = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[seed % 26]
    return f"{_repeat_letters(given_len, seed=seed)} {surname}"


def _patch_dd6360_move_cursor(decoded: bytes, current_name: str, target_name: str) -> tuple[bytes, dict[str, Any]]:
    segments = _indexed_variable_name_compact_segments(decoded)
    if segments is None:
        raise RuntimeError("Could not resolve dd6360 compact name segments")

    gap = int(segments["pre_marker_gap_bytes"])
    old_name_end = int(segments["name_end"])
    old_role_start = old_name_end - gap
    old_tail_start = old_role_start + 8
    if old_role_start < 0 or old_tail_start > len(decoded):
        raise RuntimeError("dd6360 role/tail block outside payload")

    first_len_offset = int(segments["first_len_offset"])
    prefix = _indexed_variable_name_prefix(target_name)
    new_role_start = first_len_offset + len(prefix)
    new_name_end = new_role_start + gap
    if new_role_start > old_role_start:
        raise RuntimeError(
            f"target prefix exceeds compact window: new_role_start={new_role_start}, old_role_start={old_role_start}"
        )

    patched = bytearray()
    patched.extend(decoded[:first_len_offset])
    patched.extend(prefix)
    patched.extend(decoded[old_role_start:old_tail_start])
    patched.extend(decoded[old_tail_start:])
    natural_length = len(patched)
    if len(patched) > len(decoded):
        raise RuntimeError(f"compact rewrite grew payload: {len(patched)} > {len(decoded)}")
    patched.extend(b"\x61" * (len(decoded) - len(patched)))

    patched_bytes = bytes(patched)
    applied = _display_name(patched_bytes, 0)
    parser_name_end = PlayerRecord._find_name_end(patched_bytes)
    if _norm(applied) != _norm(target_name):
        raise RuntimeError(f"patched payload reparsed as {applied!r}, expected {target_name!r}")
    if parser_name_end != new_name_end:
        raise RuntimeError(f"parser name_end mismatch: expected {new_name_end}, got {parser_name_end}")
    return patched_bytes, {
        "old_name": current_name,
        "applied_name": applied,
        "old_name_end": old_name_end,
        "new_name_end": new_name_end,
        "old_role_start": old_role_start,
        "new_role_start": new_role_start,
        "pre_marker_gap_bytes": gap,
        "first_len_offset": first_len_offset,
        "encoded_prefix_bytes": len(prefix),
        "natural_length": natural_length,
        "payload_length": len(decoded),
        "tail_padding_bytes": len(decoded) - natural_length,
    }


def _patch_dd6361_static(decoded: bytes, current_name: str, target_name: str) -> tuple[bytes, dict[str, Any]]:
    old_anchor = PlayerRecord._find_indexed_suffix_anchor(decoded, current_name)
    if old_anchor is None:
        raise RuntimeError("Could not resolve dd6361 indexed suffix anchor")
    segments = _indexed_variable_name_runtime_segments(decoded)
    if int(segments["full_name_end"]) != int(old_anchor):
        raise RuntimeError(f"dd6361 full-name end {segments['full_name_end']} != suffix anchor {old_anchor}")
    first_len_offset = int(segments["first_len_offset"])
    prefix = _indexed_variable_name_prefix(target_name)
    patched = bytes(decoded[:first_len_offset]) + prefix + bytes(decoded[int(old_anchor) :])
    new_anchor = first_len_offset + len(prefix)
    applied = _display_name(patched, 0)
    reparsed_anchor = PlayerRecord._find_indexed_suffix_anchor(patched, applied)
    if _norm(applied) != _norm(target_name):
        raise RuntimeError(f"patched dd6361 reparsed as {applied!r}, expected {target_name!r}")
    if reparsed_anchor != new_anchor:
        raise RuntimeError(f"dd6361 suffix anchor mismatch: expected {new_anchor}, got {reparsed_anchor}")
    return patched, {
        "old_name_end": int(old_anchor),
        "new_name_end": int(new_anchor),
        "first_len_offset": first_len_offset,
        "encoded_prefix_bytes": len(prefix),
        "payload_length": len(patched),
        "payload_length_delta": len(patched) - len(decoded),
    }


def _norm(value: str) -> str:
    import re
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    asciiish = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", asciiish.casefold())


def _status_for_patch(func: Any, decoded: bytes, current_name: str, target_name: str) -> tuple[str, str]:
    try:
        func(decoded, current_name, target_name)
        return "accepted", ""
    except Exception as exc:
        return "rejected", str(exc)


def _load_windows(player_file: Path) -> tuple[list[PlayerWindow], dict[int, bytes], dict[int, Any], bytes]:
    data = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(data)
    decoded_by_id: dict[int, bytes] = {}
    entries_by_id: dict[int, Any] = {}
    windows: list[PlayerWindow] = []

    for entry in indexed.entries:
        record_id = int(entry.record_id)
        entries_by_id[record_id] = entry
        decoded = entry.decode_payload(data)
        decoded_by_id[record_id] = decoded
        head_hex = decoded[2:5].hex() if len(decoded) >= 5 else ""
        try:
            player_name = _display_name(decoded, int(entry.payload_offset))
            if not player_name or player_name in {"Unknown Player", "Parse Error"}:
                raise RuntimeError("opaque_or_non_player_payload")
            if head_hex == "dd6360":
                segments = _indexed_variable_name_compact_segments(decoded)
                if segments is None:
                    raise RuntimeError("Could not resolve dd6360 compact name segments")
                gap = int(segments["pre_marker_gap_bytes"])
                name_end = int(segments["name_end"])
                first_len_offset = int(segments["first_len_offset"])
                role_start = name_end - gap
                max_prefix = role_start - first_len_offset
                max_visible = max_prefix - 5
                max_name = _name_for_visible_length(max_visible, seed=record_id)
                too_long_name = _name_for_visible_length(max_visible + 1, seed=record_id)
                short_status, short_failure = _status_for_patch(
                    _patch_dd6360_move_cursor, decoded, player_name, SHORT_ACCEPTED_NAME
                )
                too_short_status, too_short_failure = _status_for_patch(
                    _patch_dd6360_move_cursor, decoded, player_name, SHORT_REJECTED_NAME
                )
                max_status, max_failure = _status_for_patch(_patch_dd6360_move_cursor, decoded, player_name, max_name)
                too_long_status, too_long_failure = _status_for_patch(
                    _patch_dd6360_move_cursor, decoded, player_name, too_long_name
                )
                failure = "; ".join(
                    item
                    for item in [
                        "" if short_status == "accepted" else f"short:{short_failure}",
                        "" if max_status == "accepted" else f"max:{max_failure}",
                        "" if too_long_status == "rejected" else "too_long_unexpected_accept",
                    ]
                    if item
                )
                windows.append(
                    PlayerWindow(
                        record_id=record_id,
                        key=str(entry.key),
                        payload_offset=int(entry.payload_offset),
                        payload_length=int(entry.payload_length),
                        head_hex=head_hex,
                        player_name=player_name,
                        family=f"dd6360_gap{gap}",
                        first_len_offset=first_len_offset,
                        name_end=name_end,
                        pre_marker_gap_bytes=gap,
                        old_role_start=role_start,
                        max_prefix_bytes=max_prefix,
                        max_visible_chars_surname1=max_visible,
                        current_prefix_bytes=int(segments["full_name_end"]) - first_len_offset,
                        shortest_accept_status=short_status,
                        too_short_status=too_short_status,
                        max_accept_status=max_status,
                        too_long_status=too_long_status,
                        failure=failure,
                    )
                )
            elif head_hex == "dd6361":
                segments = _indexed_variable_name_runtime_segments(decoded)
                short_status, short_failure = _status_for_patch(_patch_dd6361_static, decoded, player_name, SHORT_ACCEPTED_NAME)
                max_name = _name_for_visible_length(255, seed=record_id)
                max_status, max_failure = _status_for_patch(_patch_dd6361_static, decoded, player_name, max_name)
                failure = "; ".join(
                    item
                    for item in [
                        "" if short_status == "accepted" else f"short:{short_failure}",
                        "" if max_status == "accepted" else f"max:{max_failure}",
                    ]
                    if item
                )
                windows.append(
                    PlayerWindow(
                        record_id=record_id,
                        key=str(entry.key),
                        payload_offset=int(entry.payload_offset),
                        payload_length=int(entry.payload_length),
                        head_hex=head_hex,
                        player_name=player_name,
                        family="dd6361_indexed_suffix_static",
                        first_len_offset=int(segments["first_len_offset"]),
                        name_end=int(segments["full_name_end"]),
                        max_prefix_bytes=260,
                        max_visible_chars_surname1=255,
                        current_prefix_bytes=int(segments["full_name_end"]) - int(segments["first_len_offset"]),
                        shortest_accept_status=short_status,
                        too_short_status="not_tested",
                        max_accept_status=max_status,
                        too_long_status="not_tested",
                        failure=failure,
                    )
                )
            else:
                raise RuntimeError(f"unsupported_player_payload_family:{head_hex or 'short'}")
        except Exception as exc:
            windows.append(
                PlayerWindow(
                    record_id=record_id,
                    key=str(entry.key),
                    payload_offset=int(entry.payload_offset),
                    payload_length=int(entry.payload_length),
                    head_hex=head_hex,
                    player_name="",
                    family="opaque_or_unresolved",
                    failure=str(exc),
                )
            )
    return windows, decoded_by_id, entries_by_id, data


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _window_summary(windows: list[PlayerWindow]) -> dict[str, Any]:
    family_counts = Counter(row.family for row in windows)
    parsed = [row for row in windows if row.player_name]
    dd6360 = [row for row in parsed if row.head_hex == "dd6360" and row.max_prefix_bytes is not None]
    dd6361 = [row for row in parsed if row.head_hex == "dd6361"]
    return {
        "record_count": len(windows),
        "parser_backed_count": len(parsed),
        "family_counts": dict(sorted(family_counts.items())),
        "dd6360_count": len(dd6360),
        "dd6360_gap_counts": dict(Counter(int(row.pre_marker_gap_bytes or 0) for row in dd6360)),
        "dd6360_max_prefix_min": min((int(row.max_prefix_bytes or 0) for row in dd6360), default=None),
        "dd6360_max_prefix_max": max((int(row.max_prefix_bytes or 0) for row in dd6360), default=None),
        "dd6360_max_visible_surname1_min": min((int(row.max_visible_chars_surname1 or 0) for row in dd6360), default=None),
        "dd6360_max_visible_surname1_max": max((int(row.max_visible_chars_surname1 or 0) for row in dd6360), default=None),
        "dd6360_short_accept_counts": dict(Counter(row.shortest_accept_status for row in dd6360)),
        "dd6360_too_short_counts": dict(Counter(row.too_short_status for row in dd6360)),
        "dd6360_max_accept_counts": dict(Counter(row.max_accept_status for row in dd6360)),
        "dd6360_too_long_counts": dict(Counter(row.too_long_status for row in dd6360)),
        "dd6361_count": len(dd6361),
        "dd6361_short_accept_counts": dict(Counter(row.shortest_accept_status for row in dd6361)),
        "dd6361_max_accept_counts": dict(Counter(row.max_accept_status for row in dd6361)),
        "unresolved_count": len([row for row in windows if not row.player_name]),
        "failure_count": len([row for row in windows if row.failure and row.player_name]),
        "failure_samples": [asdict(row) for row in windows if row.failure and row.player_name][:25],
    }


def _evenly_spaced(items: list[Any], count: int) -> list[Any]:
    if count >= len(items):
        return list(items)
    if count <= 1:
        return [items[0]]
    indexes = sorted({round(i * (len(items) - 1) / (count - 1)) for i in range(count)})
    return [items[index] for index in indexes[:count]]


def _select_samples(
    *,
    rosters: list[Any],
    windows_by_id: dict[int, PlayerWindow],
    team_count: int,
    players_per_team: int,
    batch_size: int,
) -> list[SamplePlayer]:
    eligible: list[Any] = []
    for roster in rosters:
        candidates = []
        for row in list(getattr(roster, "rows", []) or []):
            pid = int(getattr(row, "player_record_id", 0) or 0)
            window = windows_by_id.get(pid)
            if (
                window
                and window.head_hex == "dd6360"
                and window.shortest_accept_status == "accepted"
                and window.max_accept_status == "accepted"
                and window.too_long_status == "rejected"
                and int(window.payload_length or 0) >= 80
                and int(window.max_prefix_bytes or 0) >= len(_indexed_variable_name_prefix(SHORT_ACCEPTED_NAME))
            ):
                candidates.append((row, window))
        if len(candidates) >= players_per_team:
            eligible.append((roster, candidates))

    selected_teams = _evenly_spaced(eligible, team_count)
    samples: list[SamplePlayer] = []
    used_pids: set[int] = set()
    for team_index, (roster, candidates) in enumerate(selected_teams, start=1):
        candidates = sorted(candidates, key=lambda item: (int(item[1].max_prefix_bytes or 0), int(item[1].record_id)))
        chosen: list[tuple[Any, PlayerWindow, str]] = []
        if players_per_team >= 1:
            chosen.append((*candidates[0], "shortest_accepted"))
        if players_per_team >= 2:
            for item in reversed(candidates):
                if int(item[1].record_id) != int(chosen[0][1].record_id):
                    chosen.append((*item, "record_max_prefix"))
                    break
        for extra in range(max(0, players_per_team - len(chosen))):
            for item in candidates:
                if all(int(item[1].record_id) != int(existing[1].record_id) for existing in chosen):
                    chosen.append((*item, f"additional_{extra + 1}"))
                    break

        for row, window, target_case in chosen[:players_per_team]:
            pid = int(window.record_id)
            if pid in used_pids:
                continue
            used_pids.add(pid)
            if target_case == "shortest_accepted":
                target_name = SHORT_ACCEPTED_NAME
            else:
                target_name = _name_for_visible_length(int(window.max_visible_chars_surname1 or 4), seed=pid)
            batch_index = math.floor(len(samples) / batch_size) + 1
            batch_slot = (len(samples) % batch_size) + 1
            samples.append(
                SamplePlayer(
                    batch_index=batch_index,
                    batch_slot=batch_slot,
                    source_team_name=str(getattr(roster, "short_name", "") or ""),
                    source_full_club_name=str(getattr(roster, "full_club_name", "") or ""),
                    source_eq_record_id=int(getattr(roster, "eq_record_id", 0) or 0),
                    source_slot=int(getattr(row, "slot_index", 0) or 0) + 1,
                    record_id=pid,
                    old_name=str(window.player_name),
                    target_name=target_name,
                    target_case=target_case,
                    visible_chars=len(target_name),
                    encoded_prefix_bytes=len(_indexed_variable_name_prefix(target_name)),
                    family=window.family,
                    pre_marker_gap_bytes=int(window.pre_marker_gap_bytes or 0),
                    max_prefix_bytes=int(window.max_prefix_bytes or 0),
                    payload_length=int(window.payload_length),
                )
            )
    return samples


def _patch_sample_names(player_file: Path, samples: list[SamplePlayer]) -> list[dict[str, Any]]:
    data = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(data)
    entries_by_id = {int(entry.record_id): entry for entry in indexed.entries}
    stages: list[tuple[int, _IndexedRawStageRecord]] = []
    patch_rows: list[dict[str, Any]] = []
    for sample in samples:
        entry = entries_by_id[int(sample.record_id)]
        decoded = entry.decode_payload(data)
        patched, meta = _patch_dd6360_move_cursor(decoded, sample.old_name, sample.target_name)
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
        patch_rows.append({**asdict(sample), **meta, "payload_offset": int(entry.payload_offset)})
    write_player_staged_records(str(player_file), stages, create_backup_before_write=False)
    return patch_rows


def _write_stoke_batch_csv(path: Path, samples: list[SamplePlayer], target_team_query: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["team", "source", "slot", "player_id", "flag"])
        writer.writeheader()
        for sample in samples:
            writer.writerow(
                {
                    "team": target_team_query,
                    "source": "linked",
                    "slot": sample.batch_slot,
                    "player_id": sample.record_id,
                    "flag": 0,
                }
            )


def _build_runner_batches(
    *,
    base_game: Path,
    output_dir: Path,
    samples: list[SamplePlayer],
    batch_size: int,
    target_team_query: str,
) -> list[dict[str, Any]]:
    all_game = output_dir / "all_samples_game"
    if all_game.exists():
        shutil.rmtree(all_game)
    shutil.copytree(base_game, all_game, symlinks=True)
    patch_rows = _patch_sample_names(all_game / "DBDAT" / "JUG98030.FDI", samples)
    _json_dump(output_dir / "sample_name_patches.json", patch_rows)

    batches: list[dict[str, Any]] = []
    for batch_index in sorted({sample.batch_index for sample in samples}):
        batch_samples = [sample for sample in samples if sample.batch_index == batch_index]
        batch_root = output_dir / f"runner_batch_{batch_index:02d}_game"
        if batch_root.exists():
            shutil.rmtree(batch_root)
        shutil.copytree(all_game, batch_root, symlinks=True)
        csv_path = output_dir / f"runner_batch_{batch_index:02d}_stoke_roster.csv"
        _write_stoke_batch_csv(csv_path, batch_samples, target_team_query)
        result = batch_edit_team_roster_records(
            team_file=str(batch_root / "DBDAT" / "EQ98030.FDI"),
            csv_path=str(csv_path),
            player_file=str(batch_root / "DBDAT" / "JUG98030.FDI"),
            write_changes=True,
        )
        batches.append(
            {
                "batch_index": batch_index,
                "batch_root": str(batch_root),
                "csv": str(csv_path),
                "sample_count": len(batch_samples),
                "matched_row_count": int(getattr(result, "matched_row_count", 0) or 0),
                "linked_change_count": len(getattr(result, "linked_changes", []) or []),
                "warnings": [str(getattr(w, "message", w)) for w in list(getattr(result, "warnings", []) or [])],
                "run_tag": f"fullgame_varwin_30teams_b{batch_index:02d}_20260503T_runtime",
                "profile_count": len(batch_samples),
                "samples": [asdict(sample) for sample in batch_samples],
                "hashes": {
                    "JUG98030.FDI": sha256(batch_root / "DBDAT" / "JUG98030.FDI"),
                    "EQ98030.FDI": sha256(batch_root / "DBDAT" / "EQ98030.FDI"),
                    "MANAGPRE.EXE": sha256(batch_root / "MANAGPRE.EXE"),
                },
            }
        )
    return batches


def main() -> int:
    args = _parse_args()
    base_game = Path(args.base_game).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    if output_dir.exists():
        if not args.force:
            raise SystemExit(f"Output exists: {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    dbdat = base_game / "DBDAT"
    player_file = dbdat / "JUG98030.FDI"
    team_file = dbdat / "EQ98030.FDI"
    windows, _decoded_by_id, _entries_by_id, _data = _load_windows(player_file)
    windows_by_id = {row.record_id: row for row in windows}
    rosters = list(load_eq_linked_team_rosters(team_file=str(team_file), player_file=str(player_file)))
    samples = _select_samples(
        rosters=rosters,
        windows_by_id=windows_by_id,
        team_count=int(args.sample_team_count),
        players_per_team=int(args.players_per_team),
        batch_size=int(args.batch_size),
    )
    if len({sample.source_eq_record_id for sample in samples}) < int(args.sample_team_count):
        raise RuntimeError(
            f"Only selected {len({sample.source_eq_record_id for sample in samples})} teams, "
            f"expected {int(args.sample_team_count)}"
        )

    batches = _build_runner_batches(
        base_game=base_game,
        output_dir=output_dir,
        samples=samples,
        batch_size=int(args.batch_size),
        target_team_query=str(args.target_team_query),
    )

    window_rows = [asdict(row) for row in windows]
    sample_rows = [asdict(row) for row in samples]
    _json_dump(output_dir / "player_variable_name_windows.json", {"summary": _window_summary(windows), "rows": window_rows})
    _write_csv(output_dir / "player_variable_name_windows.csv", window_rows)
    _json_dump(output_dir / "runner_spotcheck_samples.json", {"samples": sample_rows, "batches": batches})
    _write_csv(output_dir / "runner_spotcheck_samples.csv", sample_rows)

    summary = {
        "schema": "pm99-full-game-variable-name-window-probe-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "base_game": str(base_game),
        "output_dir": str(output_dir),
        "window_summary": _window_summary(windows),
        "linked_roster_count": len(rosters),
        "linked_roster_row_count": sum(len(getattr(roster, "rows", []) or []) for roster in rosters),
        "sample_team_count": len({sample.source_eq_record_id for sample in samples}),
        "sample_player_count": len(samples),
        "batch_count": len(batches),
        "batches": batches,
        "hashes": {
            "input_JUG98030.FDI": sha256(player_file),
            "input_EQ98030.FDI": sha256(team_file),
            "input_MANAGPRE.EXE": sha256(base_game / "MANAGPRE.EXE"),
        },
        "artifacts": {
            "windows_json": str(output_dir / "player_variable_name_windows.json"),
            "windows_csv": str(output_dir / "player_variable_name_windows.csv"),
            "samples_json": str(output_dir / "runner_spotcheck_samples.json"),
            "samples_csv": str(output_dir / "runner_spotcheck_samples.csv"),
        },
    }
    _json_dump(output_dir / "summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
