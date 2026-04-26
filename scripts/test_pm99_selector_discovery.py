from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_SCRIPT_DIR = REPO_ROOT / "upstream" / "pm99-runner" / "scripts" / "pm99_runner"
if str(RUNNER_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(RUNNER_SCRIPT_DIR))

import selector_discovery
import selector_discovery_capture


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _world_state(tmp_path: Path) -> Path:
    return _write_json(
        tmp_path / "world.json",
        {
            "schema": "pm99-world-state-v1",
            "clubs": [
                {
                    "club_key": "stoke",
                    "team_query": "Stoke C.",
                    "full_club_name": "Stoke City",
                    "aliases": ["Stoke City"],
                },
                {
                    "club_key": "coventry",
                    "team_query": "Coventry C.",
                    "runtime_routes": ["squad"],
                },
            ],
        },
    )


def test_build_selector_map_matches_alias_and_nested_division_rows(tmp_path: Path) -> None:
    world = _world_state(tmp_path)
    observations = _write_json(
        tmp_path / "observations.json",
        {
            "schema": selector_discovery.DISCOVERY_SCHEMA_ID,
            "divisions": [
                {
                    "division_key": "eng_d2",
                    "division_text": "Second Division",
                    "division_select_x": 559,
                    "division_select_y": 302,
                    "teams": [
                        {
                            "text": "Stoke City",
                            "team_select_x": 327,
                            "team_select_y": 356,
                            "screenshot": "screens/stoke.png",
                        },
                        {
                            "text": "Coventry C",
                            "team_select_x": 327,
                            "team_select_y": 395,
                        },
                    ],
                }
            ],
        },
    )

    selector_map, report = selector_discovery.build_selector_map_from_discovery(
        world_state_path=world,
        observations_path=observations,
    )

    assert report["ok"] is True
    assert report["counts"]["matched_selectors"] == 2
    selectors = {row["club_key"]: row for row in selector_map["selectors"]}
    assert selectors["stoke"]["team_select_y"] == 356
    assert selectors["stoke"]["source"]["discovery_normalized_text"] == "stoke city"
    assert selectors["coventry"]["runtime_routes"] == ["squad"]


def test_duplicate_observations_are_ambiguous_and_excluded(tmp_path: Path) -> None:
    world = _world_state(tmp_path)
    observations = _write_json(
        tmp_path / "observations.json",
        {
            "schema": selector_discovery.DISCOVERY_SCHEMA_ID,
            "observations": [
                {
                    "text": "Stoke C",
                    "division_select_x": 559,
                    "division_select_y": 302,
                    "team_select_x": 327,
                    "team_select_y": 356,
                },
                {
                    "text": "Stoke C.",
                    "division_select_x": 559,
                    "division_select_y": 302,
                    "team_select_x": 327,
                    "team_select_y": 395,
                },
            ],
        },
    )

    selector_map, report = selector_discovery.build_selector_map_from_discovery(
        world_state_path=world,
        observations_path=observations,
    )

    assert report["ok"] is False
    assert selector_map["selectors"] == []
    assert report["counts"]["ambiguous_clubs"] == 1
    assert report["ambiguous_clubs"][0]["club_key"] == "stoke"


def test_selected_kit_center_overrides_probe_coordinate(tmp_path: Path) -> None:
    world = _world_state(tmp_path)
    observations = _write_json(
        tmp_path / "observations.json",
        {
            "schema": selector_discovery.DISCOVERY_SCHEMA_ID,
            "divisions": [
                {
                    "division_key": "eng_d2",
                    "division_select_x": 559,
                    "division_select_y": 302,
                    "teams": [
                        {
                            "text": "Stoke City",
                            "team_select_x": 330,
                            "team_select_y": 360,
                            "selected_team_select_x": 302,
                            "selected_team_select_y": 360,
                        }
                    ],
                }
            ],
        },
    )

    selector_map, report = selector_discovery.build_selector_map_from_discovery(
        world_state_path=world,
        observations_path=observations,
    )

    assert report["ok"] is False
    assert selector_map["selectors"][0]["team_select_x"] == 302
    assert selector_map["selectors"][0]["source"]["probe_team_select_x"] == 330


def test_capture_detects_split_selected_kit_highlight(tmp_path: Path) -> None:
    screenshot = tmp_path / "selector.png"
    image = Image.new("RGB", (640, 480), "black")
    draw = ImageDraw.Draw(image)
    draw.rectangle((167, 307, 190, 316), outline=(255, 220, 0))
    draw.rectangle((167, 323, 190, 340), outline=(255, 220, 0))
    image.save(screenshot)

    selected = selector_discovery_capture.detect_selected_kit_highlight(screenshot)

    assert selected is not None
    assert selected["center_x"] == 178
    assert selected["center_y"] == 323


def test_cli_writes_partial_selector_outputs(tmp_path: Path) -> None:
    world = _world_state(tmp_path)
    observations = _write_json(
        tmp_path / "observations.json",
        {
            "schema": selector_discovery.DISCOVERY_SCHEMA_ID,
            "observations": [
                {
                    "text": "Stoke C",
                    "division_select_x": 559,
                    "division_select_y": 302,
                    "team_select_x": 327,
                    "team_select_y": 356,
                }
            ],
        },
    )
    selectors_path = tmp_path / "selectors.generated.json"
    report_path = tmp_path / "selector_discovery_report.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER_SCRIPT_DIR / "selector_discovery.py"),
            "build-selector-map",
            "--world-state",
            str(world),
            "--observations",
            str(observations),
            "--output-selectors",
            str(selectors_path),
            "--output-report",
            str(report_path),
            "--allow-partial",
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert selectors_path.is_file()
    assert report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["counts"]["matched_selectors"] == 1
    assert report["counts"]["unmatched_clubs"] == 1


def test_export_observed_selector_map_without_world_state(tmp_path: Path) -> None:
    observations = _write_json(
        tmp_path / "observations.json",
        {
            "schema": selector_discovery.DISCOVERY_SCHEMA_ID,
            "divisions": [
                {
                    "division_key": "eng_d2",
                    "division_select_x": 559,
                    "division_select_y": 302,
                    "teams": [
                        {
                            "text": "Stoke C.",
                            "team_select_x": 330,
                            "team_select_y": 360,
                            "selected_team_select_x": 332,
                            "selected_team_select_y": 360,
                        }
                    ],
                }
            ],
        },
    )

    selector_map, report = selector_discovery.build_observed_selector_map(observations_path=observations)

    assert report["ok"] is True
    assert report["counts"]["exported_selectors"] == 1
    assert selector_map["selectors"][0]["club_key"] == "stoke_c"
    assert selector_map["selectors"][0]["team_select_x"] == 332


def test_export_observed_selector_map_cli(tmp_path: Path) -> None:
    observations = _write_json(
        tmp_path / "observations.json",
        {
            "schema": selector_discovery.DISCOVERY_SCHEMA_ID,
            "observations": [
                {
                    "text": "Stoke C.",
                    "division_select_x": 559,
                    "division_select_y": 302,
                    "team_select_x": 332,
                    "team_select_y": 360,
                }
            ],
        },
    )
    selectors_path = tmp_path / "selectors.observed.json"
    report_path = tmp_path / "selector_export_report.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER_SCRIPT_DIR / "selector_discovery.py"),
            "export-observed-selector-map",
            "--observations",
            str(observations),
            "--output-selectors",
            str(selectors_path),
            "--output-report",
            str(report_path),
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert selectors_path.is_file()
    assert report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["counts"]["exported_selectors"] == 1


def test_capture_grid_helpers_emit_expected_coordinates() -> None:
    args = selector_discovery_capture.build_parser().parse_args(
        [
            "--game-dir",
            "/tmp/game",
            "--artifacts-dir",
            "/tmp/artifacts",
            "--division-count",
            "3",
            "--division-grid-x",
            "559",
            "--division-grid-y0",
            "224",
            "--division-grid-y-pitch",
            "39",
            "--team-grid-x0",
            "178",
            "--team-grid-y0",
            "322",
            "--team-grid-cols",
            "3",
            "--team-grid-rows",
            "2",
            "--team-grid-x-pitch",
            "30",
            "--team-grid-y-pitch",
            "38",
        ]
    )

    assert selector_discovery_capture.build_division_points(args) == [(559, 224), (559, 263), (559, 302)]
    assert selector_discovery_capture.build_team_grid_points(args) == [
        (178, 322),
        (208, 322),
        (238, 322),
        (178, 360),
        (208, 360),
        (238, 360),
    ]


def test_capture_explicit_team_points_override_grid() -> None:
    args = selector_discovery_capture.build_parser().parse_args(
        [
            "--game-dir",
            "/tmp/game",
            "--artifacts-dir",
            "/tmp/artifacts",
            "--team-grid-x0",
            "1",
            "--team-grid-y0",
            "2",
            "--team-grid-cols",
            "2",
            "--team-grid-rows",
            "2",
            "--team-point",
            "180,322",
            "--team-point",
            "220,322",
        ]
    )

    assert selector_discovery_capture.build_team_grid_points(args) == [(180, 322), (220, 322)]


def test_capture_explicit_division_points_override_grid() -> None:
    args = selector_discovery_capture.build_parser().parse_args(
        [
            "--game-dir",
            "/tmp/game",
            "--artifacts-dir",
            "/tmp/artifacts",
            "--division-count",
            "3",
            "--division-grid-x",
            "1",
            "--division-grid-y0",
            "2",
            "--division-grid-y-pitch",
            "3",
            "--division-point",
            "78,302",
            "--division-point",
            "562,302",
        ]
    )

    assert selector_discovery_capture.build_division_points(args) == [(78, 302), (562, 302)]


def test_capture_payload_uses_discovery_schema() -> None:
    args = selector_discovery_capture.build_parser().parse_args(
        ["--game-dir", "/tmp/game", "--artifacts-dir", "/tmp/artifacts", "--skip-ocr"]
    )

    payload = selector_discovery_capture.build_discovery_payload(
        args=args,
        division_records=[
            {
                "division_key": "division_01",
                "division_select_x": 559,
                "division_select_y": 224,
                "teams": [
                    {
                        "text": "Stoke C",
                        "team_select_x": 327,
                        "team_select_y": 356,
                    }
                ],
            }
        ],
        setup_records=[],
        initial_screen={"screen": "title_screen"},
    )

    assert payload["schema"] == selector_discovery.DISCOVERY_SCHEMA_ID
    assert payload["capture"]["mode"] == "runner_ocr_grid_probe"
    assert payload["divisions"][0]["teams"][0]["text"] == "Stoke C"


def test_capture_cleanup_handles_prelaunch_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    closed: list[object] = []

    def raise_missing_wmctrl() -> list[dict]:
        raise FileNotFoundError("wmctrl")

    monkeypatch.setattr(selector_discovery_capture, "get_windows", raise_missing_wmctrl)
    monkeypatch.setattr(selector_discovery_capture, "close_launch_log", lambda process: closed.append(process))

    args = selector_discovery_capture.build_parser().parse_args(
        [
            "--game-dir",
            str(tmp_path / "game"),
            "--artifacts-dir",
            str(tmp_path / "artifacts"),
        ]
    )

    with pytest.raises(FileNotFoundError):
        selector_discovery_capture.run_capture(args)

    assert closed == [None]
