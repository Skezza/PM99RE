from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "scripts" / "run_pm99_experiment.sh"
RUNNER_ROOT = REPO_ROOT / "upstream" / "pm99-runner"
DEFAULT_ARTIFACT_ROOT = REPO_ROOT / ".local" / "runlogs" / "pm99_runner"

BOGUS_ENV = {
    "PM99_RUNNER_REMOTE_HOST": "invalid.example.invalid",
    "PM99_RUNNER_REMOTE_USER": "nobody",
    "PM99_RUNNER_SSH_BIN": "/bin/false",
    "PM99_RUNNER_RSYNC_BIN": "/bin/false",
}

GENERIC_EXPERIMENTS = [
    ("smoke", "run_stoke_smoke.sh"),
    ("new-game", "run_stoke_new_game.sh"),
    ("guided-squad", "run_stoke_guided_squad.sh"),
    ("route-capture", "run_stoke_route_capture.sh"),
    ("exploration", "run_stoke_exploration.sh"),
    ("season-experiment", "run_stoke_season_experiment.sh"),
    ("staff-determinism", "run_stoke_staff_determinism.sh"),
    ("vanilla-profile-capture", "run_stoke_vanilla_profile_capture.sh"),
    ("premier-offer-capture", "run_premier_offer_capture.sh"),
    ("selector-discovery-capture", "run_selector_discovery_capture.sh"),
]


def run_launcher(
    args: list[str],
    *,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(BOGUS_ENV)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(LAUNCHER), *args],
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def read_manifest(manifest_path: Path) -> dict[str, object]:
    return json.loads(manifest_path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("experiment, wrapper_name", GENERIC_EXPERIMENTS)
def test_launcher_dry_run_maps_wrappers_and_writes_manifest(
    tmp_path: Path,
    experiment: str,
    wrapper_name: str,
) -> None:
    artifact_root = tmp_path / "artifacts"
    run_tag = f"launcher_{experiment.replace('-', '_')}"
    result = run_launcher(
        [
            experiment,
            "--worker",
            "lane-a",
            "--run-tag",
            run_tag,
            "--artifact-root",
            str(artifact_root),
            "--dry-run",
            "--",
            "--skip-setup",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    manifest_path = artifact_root / run_tag / "control_launch.json"
    manifest = read_manifest(manifest_path)
    expected_wrapper = RUNNER_ROOT / "scripts" / "pm99_runner" / wrapper_name

    assert manifest_path == artifact_root / run_tag / "control_launch.json"
    assert manifest["experiment"] == experiment
    assert manifest["run_tag"] == run_tag
    assert manifest["worker"] == "lane-a"
    assert manifest["dry_run"] is True
    assert manifest["artifact_root"] == str(artifact_root.resolve())
    assert manifest["artifact_dir"] == str((artifact_root / run_tag).resolve())
    assert manifest["launcher"]["path"] == str(LAUNCHER)
    assert manifest["runner"]["path"] == str(RUNNER_ROOT)
    assert manifest["wrapper_path"] == str(expected_wrapper)
    assert manifest["child_command"][0] == str(expected_wrapper)
    assert manifest["child_extra_args"] == ["--skip-setup"]
    assert manifest["child_command"][-1] == "--skip-setup"

    if experiment == "staff-determinism":
        assert manifest["child_command"][1:3] == ["--run-tag-prefix", run_tag]
        assert "--worker" not in manifest["child_command"]
    else:
        assert manifest["child_command"][1:5] == ["--run-tag", run_tag, "--worker", "lane-a"]

    shutil.rmtree(manifest_path.parent)


def test_launcher_requires_worker(tmp_path: Path) -> None:
    result = run_launcher(["smoke", "--dry-run"], cwd=tmp_path)

    assert result.returncode == 2
    assert "--worker is required" in result.stderr


def test_launcher_default_root_and_generated_tag(tmp_path: Path) -> None:
    before = set(DEFAULT_ARTIFACT_ROOT.glob("*/control_launch.json"))
    result = run_launcher(["smoke", "--worker", "lane-a", "--dry-run"], cwd=tmp_path)
    after = set(DEFAULT_ARTIFACT_ROOT.glob("*/control_launch.json"))
    new_paths = sorted(after - before)

    assert result.returncode == 0, result.stderr
    assert len(new_paths) == 1

    manifest_path = new_paths[0]
    manifest = read_manifest(manifest_path)
    assert manifest["run_tag"].startswith("pm99_smoke_")
    assert manifest["artifact_root"] == str(DEFAULT_ARTIFACT_ROOT.resolve())
    assert manifest["artifact_dir"] == str(manifest_path.parent.resolve())
    assert manifest_path.parent.parent == DEFAULT_ARTIFACT_ROOT.resolve()

    shutil.rmtree(manifest_path.parent)


def test_launcher_blocks_running_from_inside_runner_checkout(tmp_path: Path) -> None:
    result = run_launcher(["smoke", "--worker", "lane-a", "--dry-run"], cwd=RUNNER_ROOT)

    assert result.returncode == 2
    assert "Refusing to launch from inside the protected runner checkout" in result.stderr


def test_launcher_allow_runner_cwd_bypasses_guard(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    run_tag = "allow_runner_cwd"
    result = run_launcher(
        [
            "smoke",
            "--worker",
            "lane-a",
            "--run-tag",
            run_tag,
            "--artifact-root",
            str(artifact_root),
            "--allow-runner-cwd",
            "--dry-run",
            "--",
            "--skip-setup",
        ],
        cwd=RUNNER_ROOT,
    )

    assert result.returncode == 0, result.stderr
    manifest = read_manifest(artifact_root / run_tag / "control_launch.json")
    assert manifest["cwd_inside_runner"] is True
    assert manifest["allow_runner_cwd"] is True
    shutil.rmtree(artifact_root / run_tag)


def test_launcher_blocks_dirty_runner_checkout(tmp_path: Path) -> None:
    dirty_file = RUNNER_ROOT / ".pm99_launcher_dirty_sentinel"
    dirty_file.write_text("dirty\n", encoding="utf-8")
    try:
        result = run_launcher(["smoke", "--worker", "lane-a", "--dry-run"], cwd=tmp_path)
        assert result.returncode == 2
        assert "Refusing to launch from a dirty runner checkout" in result.stderr
    finally:
        dirty_file.unlink(missing_ok=True)


def test_launcher_allow_dirty_runner_bypasses_guard(tmp_path: Path) -> None:
    dirty_file = RUNNER_ROOT / ".pm99_launcher_dirty_sentinel"
    dirty_file.write_text("dirty\n", encoding="utf-8")
    artifact_root = tmp_path / "artifacts"
    run_tag = "allow_dirty_runner"
    try:
        result = run_launcher(
            [
                "smoke",
                "--worker",
                "lane-a",
                "--run-tag",
                run_tag,
                "--artifact-root",
                str(artifact_root),
                "--allow-dirty-runner",
                "--dry-run",
                "--",
                "--skip-setup",
            ],
            cwd=tmp_path,
        )
        assert result.returncode == 0, result.stderr
        manifest = read_manifest(artifact_root / run_tag / "control_launch.json")
        assert manifest["runner"]["dirty"] is True
        assert manifest["allow_dirty_runner"] is True
    finally:
        dirty_file.unlink(missing_ok=True)
        shutil.rmtree(artifact_root / run_tag, ignore_errors=True)
