#!/usr/bin/env python3
"""Run full indexed-JUG variable-name coverage across string length classes."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
EDITOR_ROOT = REPO_ROOT / "upstream" / "pm99-skezmod-db-editor"
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))

from app.editor_actions import (  # noqa: E402
    PlayerVariableNameTarget,
    apply_player_variable_names,
    plan_player_variable_names,
)
from app.editor_helpers import _player_display_name  # noqa: E402
from app.fdi_indexed import IndexedFDIFile  # noqa: E402
from app.models import PlayerRecord  # noqa: E402


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _display(record: PlayerRecord) -> str:
    return " ".join(str(_player_display_name(record) or "").split())


def _load_parser_backed_players(player_file: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    data = player_file.read_bytes()
    indexed = IndexedFDIFile.from_bytes(data)
    players: list[dict[str, Any]] = []
    opaque: list[dict[str, Any]] = []
    for entry in indexed.entries:
        decoded = entry.decode_payload(data)
        head_hex = decoded[2:5].hex() if len(decoded) >= 5 else ""
        try:
            parsed = PlayerRecord.from_bytes(decoded, int(entry.payload_offset))
            name = _display(parsed)
        except Exception as exc:
            name = ""
            opaque.append(
                {
                    "record_id": int(entry.record_id),
                    "payload_offset": int(entry.payload_offset),
                    "payload_length": int(entry.payload_length),
                    "head_hex": head_hex,
                    "reason": f"parse_exception:{exc}",
                }
            )
            continue
        if not name or name in {"Unknown Player", "Parse Error"}:
            opaque.append(
                {
                    "record_id": int(entry.record_id),
                    "payload_offset": int(entry.payload_offset),
                    "payload_length": int(entry.payload_length),
                    "head_hex": head_hex,
                    "reason": "opaque_or_non_player_payload",
                }
            )
            continue
        players.append(
            {
                "record_id": int(entry.record_id),
                "payload_offset": int(entry.payload_offset),
                "payload_length": int(entry.payload_length),
                "head_hex": head_hex,
                "current_name": name,
                "current_name_bytes": len(name.encode("cp1252", errors="replace")),
            }
        )
    return players, opaque


def _write_targets_csv(path: Path, players: list[dict[str, Any]], target_name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["record_id", "payload_offset", "current_name", "target_name"],
        )
        writer.writeheader()
        for row in players:
            writer.writerow(
                {
                    "record_id": row["record_id"],
                    "payload_offset": row["payload_offset"],
                    "current_name": row["current_name"],
                    "target_name": target_name,
                }
            )


def _targets(players: list[dict[str, Any]], target_name: str) -> list[PlayerVariableNameTarget]:
    return [
        PlayerVariableNameTarget(
            row_number=index,
            record_id=int(row["record_id"]),
            payload_offset=int(row["payload_offset"]),
            expected_current_name=str(row["current_name"]),
            target_name=target_name,
        )
        for index, row in enumerate(players, start=2)
    ]


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _mode_summary(name: str, source_file: Path, target_name: str, result: Any, output_file: Path) -> dict[str, Any]:
    return {
        "mode": name,
        "source_file": str(source_file),
        "output_file": str(output_file),
        "target_name": target_name,
        "target_name_bytes": len(target_name.encode("cp1252")),
        "ok": bool(getattr(result, "ok", False)),
        "row_count": int(getattr(result, "row_count", 0) or 0),
        "ready_count": int(getattr(result, "ready_count", 0) or 0),
        "noop_count": int(getattr(result, "noop_count", 0) or 0),
        "blocked_count": int(getattr(result, "blocked_count", 0) or 0),
        "applied_count": int(getattr(result, "applied_count", 0) or 0),
        "post_write_failure_count": int(getattr(result, "post_write_failure_count", 0) or 0),
        "payload_grew_count": int(getattr(result, "payload_grew_count", 0) or 0),
        "payload_same_count": int(getattr(result, "payload_same_count", 0) or 0),
        "payload_shrank_count": int(getattr(result, "payload_shrank_count", 0) or 0),
        "max_payload_length_delta": int(getattr(result, "max_payload_length_delta", 0) or 0),
        "status_counts": dict(getattr(result, "status_counts", {}) or {}),
        "family_counts": dict(getattr(result, "family_counts", {}) or {}),
        "anchor_status_counts": dict(getattr(result, "anchor_status_counts", {}) or {}),
        "output_sha256": _sha256(output_file) if output_file.is_file() else None,
        "failure_samples": [
            _jsonable(row)
            for row in list(getattr(result, "rows", []) or [])
            if str(getattr(row, "status", "") or "") not in {"ready", "noop"}
        ][:25],
        "post_write_failures_sample": list(getattr(result, "post_write_failures", []) or [])[:25],
    }


def _render_html(path: Path, summary: dict[str, Any]) -> None:
    rows = []
    for mode in summary["modes"]:
        status = "PASS" if mode["ok"] else "FAIL"
        rows.append(
            "<tr>"
            f"<td>{mode['mode']}</td>"
            f"<td>{status}</td>"
            f"<td>{mode['target_name_bytes']}</td>"
            f"<td>{mode['row_count']}</td>"
            f"<td>{mode['ready_count']}</td>"
            f"<td>{mode['noop_count']}</td>"
            f"<td>{mode['blocked_count']}</td>"
            f"<td>{mode['post_write_failure_count']}</td>"
            f"<td>{mode['payload_grew_count']}</td>"
            f"<td>{mode['payload_same_count']}</td>"
            f"<td>{mode['payload_shrank_count']}</td>"
            f"<td>{mode['max_payload_length_delta']}</td>"
            f"<td><code>{mode['target_name'][:80]}</code></td>"
            "</tr>"
        )

    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>PM99 Player Variable Name Full Matrix</title>
  <style>
    body {{ font-family: sans-serif; margin: 32px; color: #1f2933; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #d8dee9; padding: 6px 8px; text-align: left; }}
    th {{ background: #edf2f7; }}
    code {{ white-space: pre-wrap; word-break: break-all; }}
    .pass {{ color: #096; font-weight: 700; }}
  </style>
</head>
<body>
  <h1>PM99 Player Variable Name Full Matrix</h1>
  <p><strong>Overall:</strong> <span class="pass">{'PASS' if summary['ok'] else 'FAIL'}</span></p>
  <p><strong>Input:</strong> <code>{summary['player_file']}</code></p>
  <p><strong>Indexed entries:</strong> {summary['indexed_entry_count']}</p>
  <p><strong>Parser-backed players targeted:</strong> {summary['parser_backed_player_count']}</p>
  <p><strong>Opaque/non-player preserved:</strong> {summary['opaque_or_non_player_count']}</p>
  <table>
    <thead>
      <tr>
        <th>Mode</th><th>Status</th><th>Target Bytes</th><th>Rows</th><th>Ready</th><th>Noop</th>
        <th>Blocked</th><th>Post Fail</th><th>Grew</th><th>Same</th><th>Shrank</th><th>Max Delta</th><th>Target</th>
      </tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
  <p>Full machine-readable evidence: <code>{summary['artifacts']['json']}</code></p>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    player_file = Path(args.player_file).expanduser().resolve()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else REPO_ROOT / "work" / "pm99" / "player_variable_name_full_matrix" / timestamp
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    players, opaque = _load_parser_backed_players(player_file)
    baseline_json = output_dir / "baseline_players.json"
    _save_json(baseline_json, {"players": players, "opaque_or_non_player": opaque})

    modes = [
        ("noop_current", None),
        ("short_3_bytes", "A B"),
        ("short_5_bytes", "Al Li"),
        ("medium_11_bytes", "Alex Matrix"),
        ("long_44_bytes", "Bob " + ("L" * 40)),
        ("near_max_224_bytes", "Bob " + ("L" * 220)),
    ]

    summaries: list[dict[str, Any]] = []
    long_output: Path | None = None
    for mode_name, target_name in modes:
        source_file = player_file
        mode_dir = output_dir / mode_name
        mode_dir.mkdir(parents=True, exist_ok=True)
        if target_name is None:
            mode_targets = [
                PlayerVariableNameTarget(
                    row_number=index,
                    record_id=int(row["record_id"]),
                    payload_offset=int(row["payload_offset"]),
                    expected_current_name=str(row["current_name"]),
                    target_name=str(row["current_name"]),
                )
                for index, row in enumerate(players, start=2)
            ]
            target_label = "current_name"
        else:
            _write_targets_csv(mode_dir / "targets.csv", players, target_name)
            mode_targets = _targets(players, target_name)
            target_label = target_name

        output_file = mode_dir / "JUG98030.variable_name_matrix.FDI"
        result = apply_player_variable_names(
            str(source_file),
            mode_targets,
            target_path=mode_dir / "targets.csv" if target_name is not None else None,
            output_file=output_file,
            create_backup_before_write=False,
        )
        if mode_name == "noop_current" and not output_file.exists():
            shutil.copy2(source_file, output_file)
        _save_json(mode_dir / "result.json", result)
        mode_summary = _mode_summary(mode_name, source_file, target_label, result, output_file)
        summaries.append(mode_summary)
        if mode_name == "near_max_224_bytes":
            long_output = output_file

    if long_output is not None and long_output.is_file():
        long_players, _long_opaque = _load_parser_backed_players(long_output)
        mode_name = "roundtrip_near_max_to_short_3_bytes"
        mode_dir = output_dir / mode_name
        mode_dir.mkdir(parents=True, exist_ok=True)
        target_name = "A B"
        _write_targets_csv(mode_dir / "targets.csv", long_players, target_name)
        output_file = mode_dir / "JUG98030.variable_name_matrix.FDI"
        result = apply_player_variable_names(
            str(long_output),
            _targets(long_players, target_name),
            target_path=mode_dir / "targets.csv",
            output_file=output_file,
            create_backup_before_write=False,
        )
        _save_json(mode_dir / "result.json", result)
        summaries.append(_mode_summary(mode_name, long_output, target_name, result, output_file))

    summary = {
        "schema": "pm99-player-variable-name-full-matrix-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "player_file": str(player_file),
        "player_file_sha256": _sha256(player_file),
        "output_dir": str(output_dir),
        "indexed_entry_count": len(players) + len(opaque),
        "parser_backed_player_count": len(players),
        "opaque_or_non_player_count": len(opaque),
        "opaque_or_non_player_samples": opaque[:25],
        "modes": summaries,
        "ok": bool(players and all(item["ok"] for item in summaries)),
        "artifacts": {
            "baseline_json": str(baseline_json),
            "json": str(output_dir / "full_matrix_summary.json"),
            "html": str(output_dir / "full_matrix_summary.html"),
        },
    }
    _save_json(output_dir / "full_matrix_summary.json", summary)
    _render_html(output_dir / "full_matrix_summary.html", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--player-file", default=str(REPO_ROOT / "DBDAT" / "JUG98030.FDI"))
    parser.add_argument("--output-dir")
    return parser.parse_args()


def main() -> int:
    summary = run(parse_args())
    print(json.dumps(_jsonable(summary), indent=2, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
