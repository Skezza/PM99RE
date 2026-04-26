#!/usr/bin/env python3
"""Summarize PM99 DirectDraw trace artifacts from a runner directory."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


HRESULT_RE = re.compile(r"\bhr=0x([0-9A-Fa-f]{8})\s+(ok|fail)\b")
CALL_RE = re.compile(r"\]\s+(.+?)\s+(?:hr=|enter|input|filter|output|device|callback|path=)")
MODAL_RE = re.compile(r"Application cannot (?:start|continue)[^\r\n]*", re.IGNORECASE)
SURFACE_SIZE_RE = re.compile(r"CreateSurface input .*?\bwidth=(\d+)\s+height=(\d+)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize PM99 DirectDraw trace artifacts.")
    parser.add_argument("artifact_dir", type=Path, help="Runner artifact directory")
    parser.add_argument("--output", type=Path, help="Optional JSON output path")
    return parser.parse_args()


def read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def find_trace_lines(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for index, line in enumerate(text.splitlines(), start=1):
        hr_match = HRESULT_RE.search(line)
        call_match = CALL_RE.search(line)
        event = {
            "line": index,
            "raw": line,
            "call": call_match.group(1).strip() if call_match else "",
            "hresult": None,
            "state": None,
        }
        surface_match = SURFACE_SIZE_RE.search(line)
        if surface_match:
            width = int(surface_match.group(1))
            height = int(surface_match.group(2))
            event["surface_width"] = width
            event["surface_height"] = height
            event["anomaly"] = "huge_surface_dimension" if width > 10000 or height > 10000 else None
        if hr_match:
            event["hresult"] = f"0x{hr_match.group(1).upper()}"
            event["state"] = hr_match.group(2)
        events.append(event)
    return events


def classify_trace(events: list[dict[str, Any]]) -> dict[str, Any]:
    hr_events = [event for event in events if event.get("hresult")]
    failed = [event for event in hr_events if event.get("state") == "fail"]
    ok = [event for event in hr_events if event.get("state") == "ok"]
    anomalies = [event for event in events if event.get("anomaly")]
    return {
        "event_count": len(events),
        "hresult_event_count": len(hr_events),
        "last_success": ok[-1] if ok else None,
        "first_failure": failed[0] if failed else None,
        "first_anomaly": anomalies[0] if anomalies else None,
        "anomaly_count": len(anomalies),
        "last_event": events[-1] if events else None,
    }


def load_runner_summary(artifact_dir: Path) -> dict[str, Any]:
    for name in ("summary.json", "result.json", "native_runner_summary.json"):
        path = artifact_dir / name
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {"unparsed_json": str(path)}
    return {}


def canonical_modal_text(value: str) -> str:
    lowered = " ".join(value.lower().split())
    if "application cannot start" in lowered:
        return "Application cannot start."
    if "application cannot continue" in lowered:
        return "Application cannot continue."
    return " ".join(value.split())


def extract_modal_text_from_runner_summary(summary: dict[str, Any]) -> list[str]:
    found: set[str] = set()
    stack: list[Any] = [summary]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, str):
            for match in MODAL_RE.findall(item):
                found.add(canonical_modal_text(match))
    return sorted(found)


def main() -> int:
    args = parse_args()
    artifact_dir = args.artifact_dir
    trace_path = artifact_dir / "pm99-ddraw.log"
    wine_path = artifact_dir / "wine.log"
    trace_text = read_text(trace_path)
    wine_text = read_text(wine_path)
    trace_events = find_trace_lines(trace_text)
    runner_summary = load_runner_summary(artifact_dir)
    modal_matches = sorted(
        {canonical_modal_text(match) for match in MODAL_RE.findall(wine_text + "\n" + trace_text)}
        | set(extract_modal_text_from_runner_summary(runner_summary))
    )

    summary = {
        "artifact_dir": str(artifact_dir),
        "trace_log": str(trace_path),
        "trace_log_present": trace_path.is_file(),
        "wine_log": str(wine_path),
        "wine_log_present": wine_path.is_file(),
        "modal_text": modal_matches,
        "trace": classify_trace(trace_events),
        "runner_summary": runner_summary,
    }

    rendered = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
