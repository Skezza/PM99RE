#!/usr/bin/env python3
"""Probe DB-only variable-length player-name rewrites across an indexed JUG file.

This is a research proof, not a product import path. It rewrites a copy of
JUG98030.FDI with deterministic synthetic longer names to prove which player
record families can be moved with database-only changes and which still need
separate reverse engineering.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
import unicodedata
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

from app.editor_actions import _IndexedRawStageRecord, _split_display_name_for_linked_payload, write_player_staged_records  # noqa: E402
from app.editor_helpers import _player_display_name  # noqa: E402
from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from app.models import PlayerRecord  # noqa: E402
from app.xor import xor_encode  # noqa: E402
from assert_pm99_isolated_input import sha256  # noqa: E402


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _ascii(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _ascii(value).casefold())


def _cp1252_bytes(value: str) -> bytes:
    return str(value or "").encode("cp1252", errors="replace")


def _display_name(record: PlayerRecord) -> str:
    return " ".join(str(_player_display_name(record) or "").split())


def _encode_byte(value: int) -> int:
    if not 0 <= int(value) <= 255:
        raise ValueError(f"Byte value out of range: {value}")
    return int(value) ^ 0x61


def _name_prefix(name: str) -> bytes:
    given, surname = _split_display_name_for_linked_payload(name)
    given = " ".join(str(given or "").split())
    surname = " ".join(str(surname or "").split())
    if not given or not surname:
        raise ValueError(f"Name must include given and surname: {name!r}")
    surname_bytes = _cp1252_bytes(surname)
    display = f"{given} {surname.upper()}".strip()
    display_bytes = _cp1252_bytes(display)
    if len(surname_bytes) > 255 or len(display_bytes) > 255:
        raise ValueError(f"Name segment too long for PM99 linked payload: {name!r}")
    return (
        bytes([len(surname_bytes) ^ 0x61, 0x61])
        + surname_bytes
        + bytes([len(display_bytes) ^ 0x61, 0x61])
        + display_bytes
    )


def _probe_target_names(current: str, suffix: str, *, record_id: int, mode: str) -> list[str]:
    normalized = " ".join(str(current or "").split())
    if not normalized or normalized in {"Unknown Player", "Parse Error"}:
        raise ValueError("No parser-backed display name")
    suffix = " ".join(str(suffix or "VX").split()) or "VX"
    if mode == "synthetic":
        targets = [
            f"Alexanderson Variablelength{suffix}",
            f"Alex Variable{suffix}",
            f"Al Var{suffix}",
        ]
    elif mode == "append-suffix":
        given, surname = _split_display_name_for_linked_payload(normalized)
        given = given or "Player"
        surname = surname or normalized
        targets = [f"{given} {surname} {suffix}".strip()]
    else:
        raise ValueError(f"Unsupported target mode: {mode}")
    # Keep the probe under the single-byte segment contracts. The real import
    # path can reject overlong source names before building payloads.
    for target in targets:
        _name_prefix(target)
    return targets


def _compact_segments(payload: bytes) -> dict[str, int] | None:
    name_end = PlayerRecord._find_name_end(payload)
    if name_end is None:
        return None
    candidates: list[dict[str, int]] = []
    for first_len_offset in range(5, min(len(payload), 24)):
        surname_width = int(payload[first_len_offset] ^ 0x61)
        surname_start = first_len_offset + 2
        surname_end = surname_start + surname_width
        if not (1 <= surname_width <= 48):
            continue
        if first_len_offset + 1 >= len(payload) or payload[first_len_offset + 1] != 0x61:
            continue
        full_len_offset = surname_end
        if full_len_offset + 1 >= len(payload) or payload[full_len_offset + 1] != 0x61:
            continue
        full_width = int(payload[full_len_offset] ^ 0x61)
        full_start = full_len_offset + 2
        full_end = full_start + full_width
        if not (1 <= full_width <= 160 and full_end <= len(payload)):
            continue
        pre_marker_gap = int(name_end) - int(full_end)
        if pre_marker_gap in {3, 4}:
            candidates.append(
                {
                    "first_len_offset": first_len_offset,
                    "surname_start": surname_start,
                    "surname_end": surname_end,
                    "surname_width": surname_width,
                    "full_len_offset": full_len_offset,
                    "full_name_start": full_start,
                    "full_name_end": full_end,
                    "full_name_width": full_width,
                    "name_end": int(name_end),
                    "pre_marker_gap_bytes": int(pre_marker_gap),
                }
            )
    if not candidates:
        return None
    candidates.sort(key=lambda item: (0 if item["pre_marker_gap_bytes"] == 3 else 1, item["first_len_offset"]))
    return candidates[0]


def _patch_dd6360(decoded: bytes, current_name: str, target_name: str) -> tuple[bytes, dict[str, Any]]:
    segments = _compact_segments(decoded)
    if segments is None:
        raise RuntimeError("Could not resolve dd6360 compact name segments")
    old_name_end = int(segments["name_end"])
    gap = int(segments["pre_marker_gap_bytes"])
    old_role_start = old_name_end - gap
    old_tail_start = old_role_start + 8
    if old_role_start < 0 or old_tail_start > len(decoded):
        raise RuntimeError("dd6360 role/tail block outside payload")

    prefix = _name_prefix(target_name)
    first_len_offset = int(segments["first_len_offset"])
    new_role_start = first_len_offset + len(prefix)
    new_name_end = new_role_start + gap
    role_block = decoded[old_role_start:old_tail_start]
    tail = decoded[old_tail_start:]

    patched = bytearray()
    patched.extend(decoded[:first_len_offset])
    patched.extend(prefix)
    patched.extend(role_block)
    patched.extend(tail)
    natural_length = len(patched)
    if len(patched) < len(decoded):
        patched.extend(b"\x61" * (len(decoded) - len(patched)))

    parsed = PlayerRecord.from_bytes(bytes(patched), 0)
    applied = _display_name(parsed)
    reparsed_name_end = PlayerRecord._find_name_end(bytes(patched))
    if _norm(applied) != _norm(target_name):
        raise RuntimeError(f"Patched dd6360 reparsed as {applied!r}, expected {target_name!r}")
    if bytes(patched)[2:5] != decoded[2:5]:
        raise RuntimeError("Patched dd6360 signature changed")
    if reparsed_name_end is None:
        anchor_status = "missing_after_rewrite"
    elif int(reparsed_name_end) == new_name_end:
        anchor_status = "exact"
    else:
        anchor_status = "drift"
    return bytes(patched), {
        "family": f"dd6360_gap{gap}",
        "old_name": current_name,
        "target_name": target_name,
        "applied_name": applied,
        "old_name_end": old_name_end,
        "new_name_end": new_name_end,
        "old_payload_length": len(decoded),
        "new_payload_length": len(patched),
        "natural_payload_length": natural_length,
        "payload_length_delta": len(patched) - len(decoded),
        "name_end_delta": new_name_end - old_name_end,
        "anchor_status": anchor_status,
        "reparsed_name_end": reparsed_name_end,
        "first_len_offset": first_len_offset,
        "pre_marker_gap_bytes": gap,
    }


def _runtime_name_segments(payload: bytes) -> dict[str, int]:
    for first_len_offset in range(5, min(len(payload), 24)):
        surname_width = int(payload[first_len_offset] ^ 0x61)
        surname_start = first_len_offset + 2
        surname_end = surname_start + surname_width
        if not (1 <= surname_width <= 64):
            continue
        if first_len_offset + 1 >= len(payload) or payload[first_len_offset + 1] != 0x61:
            continue
        if surname_end >= len(payload):
            continue
        full_len_offset = surname_end
        if full_len_offset + 1 >= len(payload) or payload[full_len_offset + 1] != 0x61:
            continue
        full_width = int(payload[full_len_offset] ^ 0x61)
        full_start = full_len_offset + 2
        full_end = full_start + full_width
        if not (1 <= full_width <= 192 and full_end <= len(payload)):
            continue
        return {
            "first_len_offset": first_len_offset,
            "surname_start": surname_start,
            "surname_end": surname_end,
            "surname_width": surname_width,
            "full_len_offset": full_len_offset,
            "full_name_start": full_start,
            "full_name_end": full_end,
            "full_name_width": full_width,
        }
    raise RuntimeError("Could not resolve runtime surname/full-name segments")


def _patch_dd6361(decoded: bytes, current_name: str, target_name: str) -> tuple[bytes, dict[str, Any]]:
    old_anchor = PlayerRecord._find_indexed_suffix_anchor(decoded, current_name)
    if old_anchor is None:
        raise RuntimeError("Could not resolve dd6361 indexed suffix anchor")
    segments = _runtime_name_segments(decoded)
    if int(segments["full_name_end"]) != int(old_anchor):
        raise RuntimeError(f"dd6361 full-name end {segments['full_name_end']} != suffix anchor {old_anchor}")
    prefix = _name_prefix(target_name)
    first_len_offset = int(segments["first_len_offset"])
    patched = bytearray()
    patched.extend(decoded[:first_len_offset])
    patched.extend(prefix)
    patched.extend(decoded[old_anchor:])
    new_anchor = first_len_offset + len(prefix)

    parsed = PlayerRecord.from_bytes(bytes(patched), 0)
    applied = _display_name(parsed)
    reparsed_anchor = PlayerRecord._find_indexed_suffix_anchor(bytes(patched), applied)
    if _norm(applied) != _norm(target_name):
        raise RuntimeError(f"Patched dd6361 reparsed as {applied!r}, expected {target_name!r}")
    if bytes(patched)[2:5] != decoded[2:5]:
        raise RuntimeError("Patched dd6361 signature changed")
    if reparsed_anchor is None:
        anchor_status = "missing_after_rewrite"
    elif int(reparsed_anchor) == new_anchor:
        anchor_status = "exact"
    else:
        anchor_status = "drift"
    return bytes(patched), {
        "family": "dd6361_indexed_suffix",
        "old_name": current_name,
        "target_name": target_name,
        "applied_name": applied,
        "old_name_end": old_anchor,
        "new_name_end": new_anchor,
        "old_payload_length": len(decoded),
        "new_payload_length": len(patched),
        "natural_payload_length": len(patched),
        "payload_length_delta": len(patched) - len(decoded),
        "name_end_delta": new_anchor - old_anchor,
        "anchor_status": anchor_status,
        "reparsed_name_end": reparsed_anchor,
        "first_len_offset": first_len_offset,
        "pre_marker_gap_bytes": None,
    }


@dataclass
class ProbeRow:
    record_id: int
    key: str
    payload_offset: int
    old_payload_length: int
    new_payload_length: int | None
    payload_length_delta: int | None
    name_end_delta: int | None
    head_hex: str
    family: str
    anchor_status: str
    status: str
    old_name: str
    target_name: str
    applied_name: str
    failure: str


def _write_csv(path: Path, rows: list[ProbeRow]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ProbeRow.__dataclass_fields__.keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def _patch_payload(decoded: bytes, current_name: str, target_name: str) -> tuple[bytes, dict[str, Any]]:
    head = decoded[2:5]
    if head == b"\xdd\x63\x60":
        return _patch_dd6360(decoded, current_name, target_name)
    if head == b"\xdd\x63\x61":
        return _patch_dd6361(decoded, current_name, target_name)
    raise RuntimeError(f"Unsupported player payload family: {head.hex()}")


def _verify_written_copy(path: Path, expected_by_id: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    data = path.read_bytes()
    indexed = IndexedFDIFile.from_bytes(data)
    entries = {int(entry.record_id): entry for entry in indexed.entries}
    failures: list[dict[str, Any]] = []
    for record_id, expected in sorted(expected_by_id.items()):
        entry = entries.get(record_id)
        if entry is None:
            failures.append({"record_id": record_id, "failure": "missing_post_entry"})
            continue
        try:
            decoded = entry.decode_payload(data)
            parsed = PlayerRecord.from_bytes(decoded, int(entry.payload_offset))
            applied = _display_name(parsed)
            if _norm(applied) != _norm(str(expected["target_name"])):
                failures.append(
                    {
                        "record_id": record_id,
                        "failure": "post_name_mismatch",
                        "expected": expected["target_name"],
                        "actual": applied,
                    }
                )
            if int(entry.payload_length) != int(expected["new_payload_length"]):
                failures.append(
                    {
                        "record_id": record_id,
                        "failure": "post_payload_length_mismatch",
                        "expected": expected["new_payload_length"],
                        "actual": int(entry.payload_length),
                    }
                )
        except Exception as exc:
            failures.append({"record_id": record_id, "failure": f"post_exception:{exc}"})
    return failures


def run(args: argparse.Namespace) -> dict[str, Any]:
    player_file = Path(args.player_file).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    data = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(data)

    rows: list[ProbeRow] = []
    stages: list[tuple[int, _IndexedRawStageRecord]] = []
    expected_by_id: dict[int, dict[str, Any]] = {}
    status_counts: Counter[str] = Counter()
    family_counts: Counter[str] = Counter()
    anchor_counts: Counter[str] = Counter()
    delta_counts: Counter[int] = Counter()

    for entry in indexed.entries:
        decoded = entry.decode_payload(data)
        head_hex = decoded[2:5].hex() if len(decoded) >= 5 else ""
        old_name = ""
        target_name = ""
        try:
            parsed = PlayerRecord.from_bytes(decoded, int(entry.payload_offset))
            old_name = _display_name(parsed)
            if not old_name or old_name in {"Unknown Player", "Parse Error"}:
                raise RuntimeError("opaque_or_non_player_payload")
            last_error = ""
            for candidate_target in _probe_target_names(
                old_name,
                args.suffix,
                record_id=int(entry.record_id),
                mode=args.target_mode,
            ):
                target_name = candidate_target
                try:
                    patched, meta = _patch_payload(decoded, old_name, target_name)
                    break
                except Exception as exc:
                    patched = b""
                    meta = {}
                    last_error = str(exc)
            else:
                raise RuntimeError(last_error or "No probe target succeeded")
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
            expected_by_id[int(entry.record_id)] = meta
            status = "rewrite_probe_ok"
            family = str(meta["family"])
            delta = int(meta["payload_length_delta"])
            anchor_status = str(meta.get("anchor_status") or "")
            delta_counts[delta] += 1
            anchor_counts[anchor_status] += 1
            rows.append(
                ProbeRow(
                    record_id=int(entry.record_id),
                    key=str(entry.key),
                    payload_offset=int(entry.payload_offset),
                    old_payload_length=int(entry.payload_length),
                    new_payload_length=int(meta["new_payload_length"]),
                    payload_length_delta=delta,
                    name_end_delta=int(meta["name_end_delta"]),
                    head_hex=head_hex,
                    family=family,
                    anchor_status=anchor_status,
                    status=status,
                    old_name=old_name,
                    target_name=target_name,
                    applied_name=str(meta["applied_name"]),
                    failure="",
                )
            )
        except Exception as exc:
            reason = str(exc)
            status = "preserve_only" if reason == "opaque_or_non_player_payload" else "rewrite_probe_failed"
            family = "opaque_or_non_player_payload" if status == "preserve_only" else f"{head_hex or 'unknown'}_unresolved"
            rows.append(
                ProbeRow(
                    record_id=int(entry.record_id),
                    key=str(entry.key),
                    payload_offset=int(entry.payload_offset),
                    old_payload_length=int(entry.payload_length),
                    new_payload_length=None,
                    payload_length_delta=None,
                    name_end_delta=None,
                    head_hex=head_hex,
                    family=family,
                    anchor_status="",
                    status=status,
                    old_name=old_name,
                    target_name=target_name,
                    applied_name="",
                    failure=reason,
                )
            )
        status_counts[status] += 1
        family_counts[family] += 1

    output_player_file = output_dir / "JUG98030.variable_name_db_only_probe.FDI"
    backup_path = None
    post_failures: list[dict[str, Any]] = []
    if args.write_copy:
        shutil.copy2(player_file, output_player_file)
        backup_path = write_player_staged_records(str(output_player_file), stages, create_backup_before_write=True)
        post_failures = _verify_written_copy(output_player_file, expected_by_id)

    csv_path = output_dir / "full_jug_variable_name_db_only_probe.csv"
    json_path = output_dir / "full_jug_variable_name_db_only_probe.json"
    _write_csv(csv_path, rows)
    summary = {
        "schema": "pm99-full-jug-variable-name-db-only-probe-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "player_file": str(player_file),
        "output_dir": str(output_dir),
        "output_player_file": str(output_player_file) if args.write_copy else None,
        "backup_path": str(backup_path) if backup_path else None,
        "write_copy": bool(args.write_copy),
        "record_count": len(indexed.entries),
        "rewrite_probe_ok_count": int(status_counts["rewrite_probe_ok"]),
        "preserve_only_count": int(status_counts["preserve_only"]),
        "rewrite_probe_failed_count": int(status_counts["rewrite_probe_failed"]),
        "post_write_failure_count": len(post_failures),
        "status_counts": dict(status_counts),
        "family_counts": dict(family_counts),
        "anchor_status_counts": dict(anchor_counts),
        "payload_length_delta_counts": {str(k): int(v) for k, v in sorted(delta_counts.items())},
        "payload_grew_count": sum(1 for row in rows if row.payload_length_delta is not None and row.payload_length_delta > 0),
        "payload_same_count": sum(1 for row in rows if row.payload_length_delta == 0),
        "payload_shrank_count": sum(1 for row in rows if row.payload_length_delta is not None and row.payload_length_delta < 0),
        "max_payload_length_delta": max((int(row.payload_length_delta) for row in rows if row.payload_length_delta is not None), default=0),
        "max_name_end_delta": max((int(row.name_end_delta) for row in rows if row.name_end_delta is not None), default=0),
        "ok": bool(status_counts["rewrite_probe_failed"] == 0 and len(post_failures) == 0),
        "hashes": {
            "input_JUG98030.FDI": sha256(player_file),
            "output_JUG98030.FDI": sha256(output_player_file) if args.write_copy and output_player_file.is_file() else None,
        },
        "artifacts": {
            "json": str(json_path),
            "csv": str(csv_path),
        },
        "post_write_failures_sample": post_failures[:100],
        "failure_samples": [asdict(row) for row in rows if row.status == "rewrite_probe_failed"][:100],
        "preserve_only_samples": [asdict(row) for row in rows if row.status == "preserve_only"][:100],
    }
    _json_dump(json_path, {"summary": summary, "rows": [asdict(row) for row in rows]})
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--player-file", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--suffix", default="VX", help="Synthetic suffix used in generated probe names")
    parser.add_argument("--target-mode", choices=["synthetic", "append-suffix"], default="synthetic")
    parser.add_argument("--write-copy", action="store_true", help="Write and reopen a rebuilt JUG copy")
    return parser.parse_args()


def main() -> int:
    summary = run(parse_args())
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
