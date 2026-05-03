from __future__ import annotations

import json
import os
from pathlib import Path
import struct

from backend import server


def write_summary(root: Path, run_tag: str, label: str, image_hash: str) -> Path:
    run_dir = root / run_tag
    screens_dir = run_dir / "screens"
    screens_dir.mkdir(parents=True)
    screenshot = screens_dir / f"{label}.png"
    screenshot.write_bytes(b"not-a-real-png")
    summary_path = run_dir / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "mode": "stoke-route-capture",
                "steps": [
                    {
                        "step": {"label": label, "action": "native_inspect", "value": "ignored"},
                        "screenshot": f"screens/{label}.png",
                        "screen_classification": {
                            "screen": f"{label}_screen",
                            "confidence": 0.9,
                            "reason": "test",
                            "image_hash": image_hash,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return summary_path


def test_latest_runtime_screens_keeps_multiple_runs_with_same_mode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    older = write_summary(tmp_path, "older_route_run", "results", "hash-results")
    newer = write_summary(tmp_path, "newer_route_run", "fixtures", "hash-fixtures")
    os.utime(older, (100, 100))
    os.utime(newer, (200, 200))
    monkeypatch.setattr(server, "RUNLOG_ROOT", tmp_path)

    records = server.latest_runtime_screens(limit=10)

    assert [record["run_tag"] for record in records] == ["newer_route_run", "older_route_run"]
    assert [record["label"] for record in records] == ["fixtures", "results"]


def test_latest_runtime_screens_prioritizes_menu_discovery_runs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    menu = write_summary(tmp_path, "menu_discovery_routes", "dashboard_select_results", "hash-menu")
    unrelated = write_summary(tmp_path, "stability_probe", "dashboard_select_fixtures", "hash-stability")
    os.utime(menu, (100, 100))
    os.utime(unrelated, (200, 200))
    monkeypatch.setattr(server, "RUNLOG_ROOT", tmp_path)

    records = server.latest_runtime_screens(limit=10)

    assert [record["run_tag"] for record in records] == ["menu_discovery_routes", "stability_probe"]


def test_latest_runtime_screens_filters_non_menu_steps(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "menu_discovery_routes"
    screens_dir = run_dir / "screens"
    screens_dir.mkdir(parents=True)
    for label in ("manager_name_01_a", "dashboard_select_results"):
        (screens_dir / f"{label}.png").write_bytes(b"not-a-real-png")
    (run_dir / "summary.json").write_text(
        json.dumps(
            {
                "mode": "stoke-route-capture",
                "steps": [
                    {
                        "step": {"label": "manager_name_01_a", "action": "native_key", "value": "a"},
                        "screenshot": "screens/manager_name_01_a.png",
                        "screen_classification": {"screen": "unknown", "image_hash": "hash-name"},
                    },
                    {
                        "step": {"label": "dashboard_select_results", "action": "native_input_click", "value": "214,140,1"},
                        "screenshot": "screens/dashboard_select_results.png",
                        "screen_classification": {"screen": "club_dashboard_screen", "image_hash": "hash-dashboard"},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "RUNLOG_ROOT", tmp_path)

    records = server.latest_runtime_screens(limit=10)

    assert [record["label"] for record in records] == ["dashboard_select_results"]


def os2_indexed_bmp_without_palette() -> bytes:
    width = 4
    height = 2
    stride = 4
    pixels = bytes([0, 1, 2, 3]) * height
    size = 14 + 12 + stride * height
    header = bytearray()
    header += b"BM"
    header += struct.pack("<I", size)
    header += b"\x00\x00\x00\x00"
    header += struct.pack("<I", 14 + 12)
    header += struct.pack("<IHHHH", 12, width, height, 1, 8)
    return bytes(header) + pixels


def riff_palette_256() -> bytes:
    colors = bytearray()
    for index in range(256):
        colors.extend((index, 0, 255 - index, 0))
    data = struct.pack("<HH", 0x0300, 256) + colors
    return b"RIFF" + struct.pack("<I", 4 + 8 + len(data)) + b"PAL " + b"data" + struct.pack("<I", len(data)) + data


def test_palette_less_indexed_bmp_gets_preview_palette(
    tmp_path: Path,
    monkeypatch,
) -> None:
    simuldat = tmp_path / "Simuldat"
    simuldat.mkdir()
    (simuldat / "SIMULPCF6.PAL").write_bytes(riff_palette_256())
    monkeypatch.setattr(server.repository, "root", tmp_path)

    payload = os2_indexed_bmp_without_palette()
    repaired, palette_source = server.bmp_with_fallback_palette(payload)

    assert palette_source == "Simuldat/SIMULPCF6.PAL"
    assert struct.unpack_from("<I", repaired, 10)[0] == 14 + 12 + 256 * 3
    assert len(repaired) == len(payload) + 256 * 3
    assert repaired[26:29] == bytes([255, 0, 0])
    assert repaired[29:32] == bytes([254, 0, 1])

    profile, profile_palette_source = server.image_visual_profile(payload, "BMP")
    assert profile_palette_source == "Simuldat/SIMULPCF6.PAL"
    assert profile is not None
    assert profile["unique_color_count"] == 4
