#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PM99_RUNNER_NAMESPACE="${PM99_RUNNER_NAMESPACE:-pm99-research-main}"
export PM99_RUNNER_REMOTE_ROOT="${PM99_RUNNER_REMOTE_ROOT:-/home/joe/pm99-runner/namespaces/${PM99_RUNNER_NAMESPACE}}"
export PM99_RUNNER_REMOTE_ASSET_ROOT="${PM99_RUNNER_REMOTE_ASSET_ROOT:-/home/joe/pm99-runner/shared}"
export PM99_RUNNER_REMOTE_REPO_DIR="${PM99_RUNNER_REMOTE_REPO_DIR:-${PM99_RUNNER_REMOTE_ROOT}/workspace/repo}"
export PM99_RUNNER_REMOTE_EDITOR_REPO_DIR="${PM99_RUNNER_REMOTE_EDITOR_REPO_DIR:-${PM99_RUNNER_REMOTE_ROOT}/workspace/editor}"
export PM99_RUNNER_REMOTE_IMAGE="${PM99_RUNNER_REMOTE_IMAGE:-pm99-runner:latest}"
export PM99_RUNNER_HOST_LOCK_NAME="${PM99_RUNNER_HOST_LOCK_NAME:-runner-host}"

source "${REPO_ROOT}/upstream/pm99-runner/scripts/pm99_runner/common.sh"

RUN_TAG="stoke_runtime_probe_direct_$(date -u +%Y%m%dT%H%M%SZ)"
LOCAL_GAME_DIR=""
LOCAL_OVERLAY_DIR=""
LOCAL_ARTIFACT_DIR="${REPO_ROOT}/artifacts/stoke_remote_profile_probe"
DO_SETUP=0
DO_PREPARE=0
DO_SYNC=0
KEEP_REMOTE=0
DOCKER_TIMEOUT_SECONDS="${PM99_RUNNER_DOCKER_TIMEOUT_SECONDS:-900}"
USE_DEFAULT_STEPS=1
declare -a CUSTOM_STEPS=()

STATIC_SQUAD_STEPS=(
  "manager_league|click|460,263|4.0"
  "manager_double|native_double_click|338,63,1|4.0"
  "continue_visible|native_input_click|494,459,1|5.0"
  "focus_name|native_input_click|389,82,1|0.5"
  "J|native_key|J|0.1"
  "O|native_key|O|0.1"
  "E|native_key|E|0.1"
  "space|native_key|Space|0.1"
  "B|native_key|B|0.1"
  "L|native_key|L|0.1"
  "O2|native_key|O|0.1"
  "G1|native_key|G|0.1"
  "G2|native_key|G|0.1"
  "S|native_key|S|0.3"
  "second_division|native_input_click|559,302,1|0.8"
  "pick_stoke|native_input_click|327,356,1|1.0"
  "continue_team|native_input_click|561,440,1|5.0"
  "pick_rival1|native_input_click|173,390,1|0.8"
  "assign_rival1|native_input_click|490,92,1|0.8"
  "pick_rival2|native_input_click|173,390,1|0.8"
  "assign_rival2|native_input_click|490,176,1|0.8"
  "pick_rival3|native_input_click|173,390,1|0.8"
  "assign_rival3|native_input_click|490,258,1|0.8"
  "pick_rival4|native_input_click|173,390,1|0.8"
  "assign_rival4|native_input_click|490,341,1|0.8"
  "continue_after_rivals|native_input_click|561,442,1|6.0"
  "preseason_continue_retry|native_input_click|561,442,1|8.0"
  "preseason_continue_retry|native_input_click|561,442,1|8.0"
  "dashboard_select_squad|native_input_click|214,395,1|1.0"
  "dashboard_enter_selected|native_input_click|571,459,1|6.0"
)

usage() {
  cat <<'USAGE'
Usage: scripts/run_stoke_runtime_probe_direct.sh [options]

Direct native Stoke runtime probe against the remote runner host.
This script deliberately defaults to the already-built stable image
`pm99-runner:latest` and skips setup/sync/prepare unless explicitly enabled.

Options:
  --run-tag <id>            Override the artifact/run tag
  --local-game-dir <path>   Upload a full local game dir into the remote run root
  --local-overlay-dir <p>   Rsync a local overlay on top of the remote source install
  --local-artifact-dir <p>  Local artifact root (default: artifacts/stoke_remote_profile_probe)
  --with-setup              Run remote host bootstrap first
  --with-prepare            Run remote source-install preparation first
  --with-sync               Sync repo/editor to the remote namespace first
  --docker-timeout <sec>    Hard timeout for the container (default: 900)
  --keep-remote             Do not clean remote run/artifacts after success
  --no-default-steps        Do not run the built-in Stoke squad navigation steps
  --step <spec>             Append a native_runner step: LABEL|ACTION|VALUE|DELAY
  -h, --help                Show this help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-tag) RUN_TAG="$2"; shift 2 ;;
    --local-game-dir) LOCAL_GAME_DIR="$2"; shift 2 ;;
    --local-overlay-dir) LOCAL_OVERLAY_DIR="$2"; shift 2 ;;
    --local-artifact-dir) LOCAL_ARTIFACT_DIR="$2"; shift 2 ;;
    --with-setup) DO_SETUP=1; shift ;;
    --with-prepare) DO_PREPARE=1; shift ;;
    --with-sync) DO_SYNC=1; shift ;;
    --docker-timeout) DOCKER_TIMEOUT_SECONDS="$2"; shift 2 ;;
    --keep-remote) KEEP_REMOTE=1; shift ;;
    --no-default-steps) USE_DEFAULT_STEPS=0; shift ;;
    --step) CUSTOM_STEPS+=("$2"); shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -n "${LOCAL_GAME_DIR}" && ! -d "${LOCAL_GAME_DIR}" ]]; then
  echo "Missing local game dir: ${LOCAL_GAME_DIR}" >&2
  exit 2
fi
if [[ -n "${LOCAL_OVERLAY_DIR}" && ! -d "${LOCAL_OVERLAY_DIR}" ]]; then
  echo "Missing local overlay dir: ${LOCAL_OVERLAY_DIR}" >&2
  exit 2
fi

pm99_runner_require_cmd "${PM99_RUNNER_SSH_BIN}"
pm99_runner_require_cmd "${PM99_RUNNER_RSYNC_BIN}"
pm99_runner_require_editor_root
pm99_runner_select_remote_worker "${PM99_RUNNER_WORKER_NAME:-default}"
PM99_RUNNER_HOST_LOCK_CONCURRENCY="${PM99_RUNNER_WORKER_LANE_COUNT}"

pm99_runner_acquire_remote_host_lock "run_stoke_runtime_probe_direct:${RUN_TAG}"
trap 'pm99_runner_release_remote_host_lock' EXIT

if [[ ${DO_SETUP} -eq 1 ]]; then
  "${REPO_ROOT}/upstream/pm99-runner/scripts/pm99_runner/setup_remote_host.sh" --skip-repo-sync
fi
if [[ ${DO_PREPARE} -eq 1 ]]; then
  "${REPO_ROOT}/upstream/pm99-runner/scripts/pm99_runner/prepare_game_source.sh"
fi
if [[ ${DO_SYNC} -eq 1 ]]; then
  pm99_runner_sync_repo
fi

REMOTE_RUN_ROOT="$(pm99_runner_remote_run_root "${RUN_TAG}")"
REMOTE_GAME_DIR="$(pm99_runner_remote_game_dir "${REMOTE_RUN_ROOT}")"
REMOTE_HOME_DIR="$(pm99_runner_remote_home_dir "${REMOTE_RUN_ROOT}")"
REMOTE_WINE_PREFIX_DIR="$(pm99_runner_remote_wine_prefix_dir "${REMOTE_RUN_ROOT}")"
REMOTE_ARTIFACT_DIR="${PM99_RUNNER_REMOTE_ROOT}/artifacts/${RUN_TAG}"
FINAL_LOCAL_ARTIFACT_DIR="${LOCAL_ARTIFACT_DIR}/${RUN_TAG}"

pm99_runner_prepare_remote_run_root "${REMOTE_RUN_ROOT}" "${REMOTE_ARTIFACT_DIR}"

if [[ -n "${LOCAL_GAME_DIR}" ]]; then
  "${PM99_RUNNER_RSYNC_BIN}" -az --delete \
    "${LOCAL_GAME_DIR}/" "$(pm99_runner_remote_spec):${REMOTE_GAME_DIR}/"
fi

if [[ -n "${LOCAL_OVERLAY_DIR}" ]]; then
  "${PM99_RUNNER_RSYNC_BIN}" -az \
    "${LOCAL_OVERLAY_DIR}/" "$(pm99_runner_remote_spec):${REMOTE_GAME_DIR}/"
fi

DRIVER_COMMAND=(
  python3 /workspace/repo/scripts/pm99_runner/native_runner.py
  new-game
  --game-dir /workspace/game
  --artifacts-dir /workspace/artifacts
)
if [[ ${USE_DEFAULT_STEPS} -eq 1 ]]; then
  for step in "${STATIC_SQUAD_STEPS[@]}"; do
    DRIVER_COMMAND+=(--step "${step}")
  done
fi
for step in "${CUSTOM_STEPS[@]}"; do
  DRIVER_COMMAND+=(--step "${step}")
done

set +e
pm99_runner_remote_one_shot_container_with_timeout \
  "${DOCKER_TIMEOUT_SECONDS}" \
  "${RUN_TAG}" \
  "run_stoke_runtime_probe_direct.sh" \
  "pm99-agent-${RUN_TAG}" \
  "${REMOTE_ARTIFACT_DIR}" \
  --image "${PM99_RUNNER_REMOTE_IMAGE}" \
  --user CURRENT_USER \
  --workdir /workspace/repo \
  --shm-size 2g \
  --env HOME=/workspace/home \
  --env PM99_EDITOR_ROOT=/workspace/editor \
  --env PM99_SCREEN_GEOMETRY=${PM99_RUNNER_SCREEN_GEOMETRY:-640x480x16} \
  --env PYTHONPATH=/workspace/home:/workspace/repo:/workspace/editor \
  --env WINEPREFIX=/workspace/wine-prefix \
  --env WINEDLLOVERRIDES=${PM99_RUNNER_WINEDLLOVERRIDES:-} \
  --volume "${PM99_RUNNER_REMOTE_REPO_DIR}:/workspace/repo" \
  --volume "${PM99_RUNNER_REMOTE_EDITOR_REPO_DIR}:/workspace/editor" \
  --volume "${REMOTE_WINE_PREFIX_DIR}:/workspace/wine-prefix" \
  --volume "${REMOTE_HOME_DIR}:/workspace/home" \
  --volume "${REMOTE_GAME_DIR}:/workspace/game" \
  --volume "${REMOTE_ARTIFACT_DIR}:/workspace/artifacts" \
  -- "${DRIVER_COMMAND[@]}"
RUN_STATUS=$?
set -e

pm99_runner_sync_remote_artifacts "${REMOTE_ARTIFACT_DIR}" "${FINAL_LOCAL_ARTIFACT_DIR}"

if [[ ${KEEP_REMOTE} -eq 0 ]]; then
  set +e
  pm99_runner_cleanup_remote_state \
    "${RUN_STATUS}" \
    0 \
    "${REMOTE_RUN_ROOT}" \
    "${REMOTE_ARTIFACT_DIR}" \
    0 \
    0 \
    1 \
    0
  CLEANUP_STATUS=$?
  set -e
else
  CLEANUP_STATUS=0
fi

echo "remote_run_root=${REMOTE_RUN_ROOT}"
echo "remote_artifacts=${REMOTE_ARTIFACT_DIR}"
echo "local_artifacts=${FINAL_LOCAL_ARTIFACT_DIR}"
echo "run_status=${RUN_STATUS}"

if [[ ${CLEANUP_STATUS} -ne 0 && ${RUN_STATUS} -eq 0 ]]; then
  exit "${CLEANUP_STATUS}"
fi
exit "${RUN_STATUS}"
