#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUNNER_ROOT="${REPO_ROOT}/upstream/pm99-runner"
DEFAULT_ARTIFACT_ROOT="${REPO_ROOT}/.local/runlogs/pm99_runner"

export PM99_RUNNER_LOCAL_ARTIFACT_ROOT="${PM99_RUNNER_LOCAL_ARTIFACT_ROOT:-${DEFAULT_ARTIFACT_ROOT}}"

source "${RUNNER_ROOT}/scripts/pm99_runner/common.sh"

EXPERIMENT=""
WORKER_NAME=""
RUN_TAG=""
ARTIFACT_ROOT="${PM99_RUNNER_LOCAL_ARTIFACT_ROOT}"
DRY_RUN=0
ALLOW_DIRTY_RUNNER=0
ALLOW_RUNNER_CWD=0
declare -a EXTRA_ARGS=()

action_usage() {
  cat <<'USAGE'
Usage: ./scripts/run_pm99_experiment.sh <experiment> --worker <name> [options] [-- <extra args...>]

Run a PM99 experiment through the protected runner wrappers from outside the
runner checkout. This is the recommended front door for day-to-day launches.

Experiments:
  smoke
  new-game
  guided-squad
  route-capture
  exploration
  season-experiment
  staff-extract
  staff-determinism
  vanilla-profile-capture
  premier-offer-capture

Options:
  --worker <name>           Required PM99 worker lane
  --run-tag <id>            Override the experiment tag
  --artifact-root <path>    Local artifact root (default: .local/runlogs/pm99_runner)
  --dry-run                 Validate and write control_launch.json only
  --allow-dirty-runner      Bypass the dirty runner checkout hard block
  --allow-runner-cwd        Bypass the inside-runner-cwd hard block
  --                        Pass the remaining arguments through to the runner wrapper
  -h, --help                Show this help
USAGE
  echo
  pm99_runner_usage_common
}

abs_path() {
  python3 - "$1" <<'PY'
from pathlib import Path
import sys

print(Path(sys.argv[1]).expanduser().resolve())
PY
}

json_array() {
  python3 - "$@" <<'PY'
import json
import sys

print(json.dumps(sys.argv[1:]))
PY
}

warn_override() {
  printf 'WARNING: %s\n' "$1" >&2
}

require_worker() {
  if [[ -z "${WORKER_NAME}" ]]; then
    echo "--worker is required" >&2
    action_usage >&2
    exit 2
  fi
}

build_child_command() {
  local wrapper_path="$1"
  shift
  CHILD_COMMAND=("${wrapper_path}" "$@")
}

select_wrapper() {
  local experiment_name="$1"
  local wrapper_path=""

  case "${experiment_name}" in
    smoke)
      wrapper_path="${RUNNER_REPO_ROOT}/scripts/pm99_runner/run_stoke_smoke.sh"
      build_child_command "${wrapper_path}" --run-tag "${RUN_TAG}" --worker "${PM99_RUNNER_WORKER_NAME}" "${EXTRA_ARGS[@]}"
      ;;
    new-game)
      wrapper_path="${RUNNER_REPO_ROOT}/scripts/pm99_runner/run_stoke_new_game.sh"
      build_child_command "${wrapper_path}" --run-tag "${RUN_TAG}" --worker "${PM99_RUNNER_WORKER_NAME}" "${EXTRA_ARGS[@]}"
      ;;
    guided-squad)
      wrapper_path="${RUNNER_REPO_ROOT}/scripts/pm99_runner/run_stoke_guided_squad.sh"
      build_child_command "${wrapper_path}" --run-tag "${RUN_TAG}" --worker "${PM99_RUNNER_WORKER_NAME}" "${EXTRA_ARGS[@]}"
      ;;
    route-capture)
      wrapper_path="${RUNNER_REPO_ROOT}/scripts/pm99_runner/run_stoke_route_capture.sh"
      build_child_command "${wrapper_path}" --run-tag "${RUN_TAG}" --worker "${PM99_RUNNER_WORKER_NAME}" "${EXTRA_ARGS[@]}"
      ;;
    exploration)
      wrapper_path="${RUNNER_REPO_ROOT}/scripts/pm99_runner/run_stoke_exploration.sh"
      build_child_command "${wrapper_path}" --run-tag "${RUN_TAG}" --worker "${PM99_RUNNER_WORKER_NAME}" "${EXTRA_ARGS[@]}"
      ;;
    season-experiment)
      wrapper_path="${RUNNER_REPO_ROOT}/scripts/pm99_runner/run_stoke_season_experiment.sh"
      build_child_command "${wrapper_path}" --run-tag "${RUN_TAG}" --worker "${PM99_RUNNER_WORKER_NAME}" "${EXTRA_ARGS[@]}"
      ;;
    staff-extract)
      wrapper_path="${RUNNER_REPO_ROOT}/scripts/pm99_runner/run_stoke_staff_extract.sh"
      build_child_command "${wrapper_path}" --run-tag "${RUN_TAG}" --worker "${PM99_RUNNER_WORKER_NAME}" "${EXTRA_ARGS[@]}"
      ;;
    staff-determinism)
      wrapper_path="${RUNNER_REPO_ROOT}/scripts/pm99_runner/run_stoke_staff_determinism.sh"
      build_child_command "${wrapper_path}" --run-tag-prefix "${RUN_TAG}" "${EXTRA_ARGS[@]}"
      ;;
    vanilla-profile-capture)
      wrapper_path="${RUNNER_REPO_ROOT}/scripts/pm99_runner/run_stoke_vanilla_profile_capture.sh"
      build_child_command "${wrapper_path}" --run-tag "${RUN_TAG}" --worker "${PM99_RUNNER_WORKER_NAME}" "${EXTRA_ARGS[@]}"
      ;;
    premier-offer-capture)
      wrapper_path="${RUNNER_REPO_ROOT}/scripts/pm99_runner/run_premier_offer_capture.sh"
      build_child_command "${wrapper_path}" --run-tag "${RUN_TAG}" --worker "${PM99_RUNNER_WORKER_NAME}" "${EXTRA_ARGS[@]}"
      ;;
    *)
      echo "Unsupported experiment: ${experiment_name}" >&2
      action_usage >&2
      exit 2
      ;;
  esac

  if [[ ! -x "${wrapper_path}" ]]; then
    echo "Missing runner wrapper: ${wrapper_path}" >&2
    exit 2
  fi

  WRAPPER_PATH="${wrapper_path}"
}

if [[ $# -eq 0 ]]; then
  action_usage >&2
  exit 2
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --)
      shift
      while [[ $# -gt 0 ]]; do
        EXTRA_ARGS+=("$1")
        shift
      done
      break
      ;;
    -h|--help)
      action_usage
      exit 0
      ;;
    --worker)
      WORKER_NAME="${2:-}"
      shift 2
      ;;
    --run-tag)
      RUN_TAG="${2:-}"
      shift 2
      ;;
    --artifact-root)
      ARTIFACT_ROOT="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --allow-dirty-runner)
      ALLOW_DIRTY_RUNNER=1
      shift
      ;;
    --allow-runner-cwd)
      ALLOW_RUNNER_CWD=1
      shift
      ;;
    --*)
      echo "Unknown option: $1" >&2
      action_usage >&2
      exit 2
      ;;
    *)
      if [[ -z "${EXPERIMENT}" ]]; then
        EXPERIMENT="$1"
        shift
      else
        echo "Unexpected positional argument: $1" >&2
        action_usage >&2
        exit 2
      fi
      ;;
  esac
done

if [[ -z "${EXPERIMENT}" ]]; then
  echo "An experiment name is required" >&2
  action_usage >&2
  exit 2
fi

require_worker

if [[ -z "${RUN_TAG}" ]]; then
  EXPERIMENT_SLUG="${EXPERIMENT//-/_}"
  RUN_TAG="pm99_${EXPERIMENT_SLUG}_$(pm99_runner_timestamp_utc)"
fi

ARTIFACT_ROOT="$(abs_path "${ARTIFACT_ROOT}")"
export PM99_RUNNER_LOCAL_ARTIFACT_ROOT="${ARTIFACT_ROOT}"

RUNNER_REPO_ROOT="$(git -C "${RUNNER_ROOT}" rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${RUNNER_REPO_ROOT}" ]]; then
  echo "Missing runner checkout: ${RUNNER_ROOT}" >&2
  exit 2
fi
RUNNER_BRANCH="$(git -C "${RUNNER_REPO_ROOT}" rev-parse --abbrev-ref HEAD)"
RUNNER_COMMIT="$(git -C "${RUNNER_REPO_ROOT}" rev-parse HEAD)"
RUNNER_STATUS="$(git -C "${RUNNER_REPO_ROOT}" status --porcelain --untracked-files=all)"
RUNNER_DIRTY=0
if [[ -n "${RUNNER_STATUS}" ]]; then
  RUNNER_DIRTY=1
fi

CWD="$(pwd -P)"
CWD_INSIDE_RUNNER=0
case "${CWD}" in
  "${RUNNER_REPO_ROOT}"|"${RUNNER_REPO_ROOT}"/*)
    CWD_INSIDE_RUNNER=1
    ;;
esac

if [[ ${CWD_INSIDE_RUNNER} -eq 1 && ${ALLOW_RUNNER_CWD} -eq 0 ]]; then
  echo "Refusing to launch from inside the protected runner checkout: ${CWD}" >&2
  echo "Run this from the research repo or pass --allow-runner-cwd only if you really mean it." >&2
  exit 2
fi

if [[ ${RUNNER_DIRTY} -eq 1 && ${ALLOW_DIRTY_RUNNER} -eq 0 ]]; then
  echo "Refusing to launch from a dirty runner checkout: ${RUNNER_REPO_ROOT}" >&2
  echo "Clean the runner repo or pass --allow-dirty-runner only if you really mean it." >&2
  printf '%s\n' "${RUNNER_STATUS}" >&2
  exit 2
fi

if [[ ${CWD_INSIDE_RUNNER} -eq 1 && ${ALLOW_RUNNER_CWD} -eq 1 ]]; then
  warn_override "launching from inside the protected runner checkout because --allow-runner-cwd was set"
fi
if [[ ${RUNNER_DIRTY} -eq 1 && ${ALLOW_DIRTY_RUNNER} -eq 1 ]]; then
  warn_override "launching from a dirty runner checkout because --allow-dirty-runner was set"
fi

pm99_runner_select_remote_worker "${WORKER_NAME}"
WORKER_NAME="${PM99_RUNNER_WORKER_NAME}"

select_wrapper "${EXPERIMENT}"
ARTIFACT_DIR="${ARTIFACT_ROOT}/${RUN_TAG}"
MANIFEST_PATH="${ARTIFACT_DIR}/control_launch.json"

pm99_runner_ensure_local_artifact_root
mkdir -p "${ARTIFACT_DIR}"

COMMAND_LINE="$(printf '%q ' "${CHILD_COMMAND[@]}")"
COMMAND_LINE="${COMMAND_LINE% }"
EXTRA_ARGS_JSON="$(json_array "${EXTRA_ARGS[@]}")"
COMMAND_JSON="$(json_array "${CHILD_COMMAND[@]}")"

LAUNCHER_TIMESTAMP_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
export LAUNCHER_TIMESTAMP_UTC
export LAUNCHER_COMMAND_JSON="${COMMAND_JSON}"
export LAUNCHER_COMMAND_LINE="${COMMAND_LINE}"
export LAUNCHER_EXTRA_ARGS_JSON="${EXTRA_ARGS_JSON}"
export LAUNCHER_RUN_TAG="${RUN_TAG}"
export LAUNCHER_EXPERIMENT="${EXPERIMENT}"
export LAUNCHER_WORKER_NAME="${WORKER_NAME}"
export LAUNCHER_ARTIFACT_ROOT="${ARTIFACT_ROOT}"
export LAUNCHER_ARTIFACT_DIR="${ARTIFACT_DIR}"
export LAUNCHER_CWD="${CWD}"
export LAUNCHER_REPO_ROOT="${REPO_ROOT}"
export LAUNCHER_RUNNER_ROOT="${RUNNER_REPO_ROOT}"
export LAUNCHER_RUNNER_BRANCH="${RUNNER_BRANCH}"
export LAUNCHER_RUNNER_COMMIT="${RUNNER_COMMIT}"
export LAUNCHER_RUNNER_DIRTY="${RUNNER_DIRTY}"
export LAUNCHER_CWD_INSIDE_RUNNER="${CWD_INSIDE_RUNNER}"
export LAUNCHER_ALLOW_DIRTY_RUNNER="${ALLOW_DIRTY_RUNNER}"
export LAUNCHER_ALLOW_RUNNER_CWD="${ALLOW_RUNNER_CWD}"
export LAUNCHER_DRY_RUN="${DRY_RUN}"
export LAUNCHER_WRAPPER_PATH="${WRAPPER_PATH}"

python3 - "${MANIFEST_PATH}" <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

manifest_path = Path(sys.argv[1])
manifest = {
    "artifact_dir": os.environ["LAUNCHER_ARTIFACT_DIR"],
    "artifact_root": os.environ["LAUNCHER_ARTIFACT_ROOT"],
    "allow_dirty_runner": os.environ["LAUNCHER_ALLOW_DIRTY_RUNNER"] == "1",
    "allow_runner_cwd": os.environ["LAUNCHER_ALLOW_RUNNER_CWD"] == "1",
    "child_command": json.loads(os.environ["LAUNCHER_COMMAND_JSON"]),
    "child_command_line": os.environ["LAUNCHER_COMMAND_LINE"],
    "child_extra_args": json.loads(os.environ["LAUNCHER_EXTRA_ARGS_JSON"]),
    "cwd": os.environ["LAUNCHER_CWD"],
    "cwd_inside_runner": os.environ["LAUNCHER_CWD_INSIDE_RUNNER"] == "1",
    "dry_run": os.environ["LAUNCHER_DRY_RUN"] == "1",
    "experiment": os.environ["LAUNCHER_EXPERIMENT"],
    "launcher": {
        "name": "run_pm99_experiment.sh",
        "path": os.environ["LAUNCHER_REPO_ROOT"] + "/scripts/run_pm99_experiment.sh",
    },
    "run_tag": os.environ["LAUNCHER_RUN_TAG"],
    "runner": {
        "branch": os.environ["LAUNCHER_RUNNER_BRANCH"],
        "commit": os.environ["LAUNCHER_RUNNER_COMMIT"],
        "dirty": os.environ["LAUNCHER_RUNNER_DIRTY"] == "1",
        "path": os.environ["LAUNCHER_RUNNER_ROOT"],
    },
    "timestamp_utc": os.environ["LAUNCHER_TIMESTAMP_UTC"],
    "worker": os.environ["LAUNCHER_WORKER_NAME"],
    "wrapper_path": os.environ["LAUNCHER_WRAPPER_PATH"],
}
manifest_path.parent.mkdir(parents=True, exist_ok=True)
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

echo "control_launch_manifest=${MANIFEST_PATH}" >&2
echo "control_launch_command=${COMMAND_LINE}" >&2

if [[ ${DRY_RUN} -eq 1 ]]; then
  echo "dry_run=1" >&2
  exit 0
fi

exec "${CHILD_COMMAND[@]}"
