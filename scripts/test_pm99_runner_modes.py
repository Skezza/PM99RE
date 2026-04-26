from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_SCRIPT_DIR = REPO_ROOT / "upstream" / "pm99-runner" / "scripts" / "pm99_runner"
if str(RUNNER_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(RUNNER_SCRIPT_DIR))

import stoke_season_driver as driver


def test_build_new_game_prefix_steps_accepts_generic_selectors() -> None:
    steps = driver.build_new_game_prefix_steps(
        manager_name="AI",
        team_select_x=321,
        team_select_y=222,
        division_select_x=555,
        division_select_y=111,
        team_step_label="pick_team",
    )

    by_label = {step.label: step for step in steps}
    assert by_label["select_division"].value == "555,111,1"
    assert by_label["pick_team"].value == "321,222,1"


def test_generic_route_mode_forces_route_capture() -> None:
    args = argparse.Namespace(
        proof_mode="generic_club_route_capture",
        capture_routes_only=False,
        exploration_scenario=None,
    )

    mode, capture_routes_only, exploration_mode, proof_mode = driver.resolve_driver_mode(args)

    assert mode == "generic-club-route-capture"
    assert proof_mode == "generic_club_route_capture"
    assert capture_routes_only is True
    assert args.capture_routes_only is True
    assert exploration_mode is False


def test_generic_modes_reject_exploration() -> None:
    args = argparse.Namespace(
        proof_mode="generic_club_season_sentinel",
        capture_routes_only=False,
        exploration_scenario="bootstrap",
    )

    with pytest.raises(SystemExit, match="exploration-scenario"):
        driver.resolve_driver_mode(args)
