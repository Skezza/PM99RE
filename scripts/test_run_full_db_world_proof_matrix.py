from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def test_run_full_db_world_proof_matrix_dry_run(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    world_state = tmp_path / "world.json"
    world_state.write_text(
        json.dumps(
            {
                "schema": "pm99-world-state-v1",
                "clubs": [
                    {
                        "club_key": "stoke",
                        "team_query": "Stoke C.",
                        "team_select_x": 327,
                        "team_select_y": 356,
                        "division_select_x": 559,
                        "division_select_y": 302,
                    }
                ],
                "players": [{"player_key": "butland", "name": "Jack Butland"}],
                "squad_memberships": [{"club_key": "stoke", "player_key": "butland", "slot": 1, "source": "linked"}],
                "divisions": [{"club_key": "stoke", "division": "premier", "country": "england"}],
            }
        ),
        encoding="utf-8",
    )
    artifact_root = tmp_path / "artifacts"
    env = os.environ.copy()
    env["PM99_RUNNER_LOCAL_ARTIFACT_ROOT"] = str(artifact_root)

    completed = subprocess.run(
        [
            "bash",
            str(repo_root / "scripts" / "run_full_db_world_proof_matrix.sh"),
            "--world-state",
            str(world_state),
            "--run-tag",
            "dry_run_case",
            "--dry-run",
        ],
        cwd=str(repo_root),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["dry_run"] is True
    control_manifest = artifact_root / "dry_run_case" / "control_manifest.json"
    assert control_manifest.is_file()
    manifest = json.loads(control_manifest.read_text(encoding="utf-8"))
    assert manifest["counts"]["clubs"] == 1
    assert manifest["planned_cases"]["club_smoke"][0]["club_key"] == "stoke"
    assert manifest["planned_cases"]["club_smoke"][0]["status"] == "ready"
    assert manifest["planned_cases"]["club_smoke"][0]["selector"]["team_select_y"] == 356
    assert manifest["planned_cases"]["division_season"][0]["division"] == "premier"
    assert manifest["planned_cases"]["global_runtime"][0]["case_id"] == "global_route_capture"


def test_run_full_db_world_proof_matrix_dry_run_uses_selector_map(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    world_state = tmp_path / "world.json"
    world_state.write_text(
        json.dumps(
            {
                "schema": "pm99-world-state-v1",
                "clubs": [{"club_key": "stoke", "team_query": "Stoke C."}],
                "players": [{"player_key": "butland", "name": "Jack Butland"}],
                "squad_memberships": [{"club_key": "stoke", "player_key": "butland", "slot": 1, "source": "linked"}],
                "divisions": [{"club_key": "stoke", "division": "premier", "country": "england"}],
            }
        ),
        encoding="utf-8",
    )
    selector_map = tmp_path / "selectors.json"
    selector_map.write_text(
        json.dumps(
            {
                "schema": "pm99-club-selector-map-v1",
                "selectors": [
                    {
                        "club_key": "stoke",
                        "team_select_x": 327,
                        "team_select_y": 356,
                        "division_select_x": 559,
                        "division_select_y": 302,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    artifact_root = tmp_path / "artifacts"
    env = os.environ.copy()
    env["PM99_RUNNER_LOCAL_ARTIFACT_ROOT"] = str(artifact_root)

    completed = subprocess.run(
        [
            "bash",
            str(repo_root / "scripts" / "run_full_db_world_proof_matrix.sh"),
            "--world-state",
            str(world_state),
            "--selector-map",
            str(selector_map),
            "--run-tag",
            "dry_run_map_case",
            "--dry-run",
        ],
        cwd=str(repo_root),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    control_manifest = artifact_root / "dry_run_map_case" / "control_manifest.json"
    manifest = json.loads(control_manifest.read_text(encoding="utf-8"))
    assert manifest["selector_map"] is not None
    assert manifest["planned_cases"]["club_smoke"][0]["status"] == "ready"
    assert manifest["planned_cases"]["club_smoke"][0]["selector"]["team_select_y"] == 356
