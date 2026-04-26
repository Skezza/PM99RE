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

RUN_TAG="pm99_ddraw_trace_probe_$(date -u +%Y%m%dT%H%M%SZ)"
WORKER_NAME="${PM99_RUNNER_WORKER_NAME:-tiny-m73}"
LOCAL_OVERLAY_DIR="${REPO_ROOT}/.local/runner-overlays/ddraw-trace"
LOCAL_ARTIFACT_DIR="${REPO_ROOT}/artifacts/pm99_ddraw_trace_probe"
SCREEN_GEOMETRY="${PM99_RUNNER_SCREEN_GEOMETRY:-640x480x16}"
DOCKER_TIMEOUT_SECONDS="${PM99_RUNNER_DOCKER_TIMEOUT_SECONDS:-900}"
WINE_DEBUG="${WINEDEBUG:--all}"
NORMALIZE_DISPLAY_MODE=0
KEEP_REMOTE=0

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
Usage: scripts/run_pm99_ddraw_trace_probe.sh [options]

Run the static PM99/Stoke flow with a log-only ddraw.dll overlay and collect
DirectDraw trace artifacts. This wrapper exists so the trace env is passed to
the container without editing protected runner internals.

Options:
  --worker <name>           Remote worker name (default: tiny-m73)
  --run-tag <id>            Override artifact/run tag
  --local-overlay-dir <p>   Overlay containing ddraw.dll (default: .local/runner-overlays/ddraw-trace)
  --local-artifact-dir <p>  Local artifact root (default: artifacts/pm99_ddraw_trace_probe)
  --screen-geometry <geom>  Xvfb geometry (default: PM99_RUNNER_SCREEN_GEOMETRY or 640x480x16)
  --wine-debug <channels>   WINEDEBUG value (default: -all)
  --normalize-display-mode  Make shim report 640x480x16 from GetDisplayMode
  --docker-timeout <sec>    Hard timeout for the container (default: 900)
  --keep-remote             Do not clean remote run/artifacts after success
  -h, --help                Show this help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --worker) WORKER_NAME="$2"; shift 2 ;;
    --run-tag) RUN_TAG="$2"; shift 2 ;;
    --local-overlay-dir) LOCAL_OVERLAY_DIR="$2"; shift 2 ;;
    --local-artifact-dir) LOCAL_ARTIFACT_DIR="$2"; shift 2 ;;
    --screen-geometry) SCREEN_GEOMETRY="$2"; shift 2 ;;
    --wine-debug) WINE_DEBUG="$2"; shift 2 ;;
    --normalize-display-mode) NORMALIZE_DISPLAY_MODE=1; shift ;;
    --docker-timeout) DOCKER_TIMEOUT_SECONDS="$2"; shift 2 ;;
    --keep-remote) KEEP_REMOTE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ ! -d "${LOCAL_OVERLAY_DIR}" ]]; then
  echo "Missing local overlay dir: ${LOCAL_OVERLAY_DIR}" >&2
  exit 2
fi
if [[ ! -f "${LOCAL_OVERLAY_DIR}/ddraw.dll" ]]; then
  echo "Missing ddraw.dll in overlay dir: ${LOCAL_OVERLAY_DIR}" >&2
  exit 2
fi

pm99_runner_require_cmd "${PM99_RUNNER_SSH_BIN}"
pm99_runner_require_cmd "${PM99_RUNNER_RSYNC_BIN}"
pm99_runner_require_editor_root
pm99_runner_select_remote_worker "${WORKER_NAME}"
PM99_RUNNER_HOST_LOCK_CONCURRENCY="${PM99_RUNNER_WORKER_LANE_COUNT}"

pm99_runner_acquire_remote_host_lock "run_pm99_ddraw_trace_probe:${RUN_TAG}"
trap 'pm99_runner_release_remote_host_lock' EXIT

REMOTE_RUN_ROOT="$(pm99_runner_remote_run_root "${RUN_TAG}")"
REMOTE_GAME_DIR="$(pm99_runner_remote_game_dir "${REMOTE_RUN_ROOT}")"
REMOTE_HOME_DIR="$(pm99_runner_remote_home_dir "${REMOTE_RUN_ROOT}")"
REMOTE_WINE_PREFIX_DIR="$(pm99_runner_remote_wine_prefix_dir "${REMOTE_RUN_ROOT}")"
REMOTE_ARTIFACT_DIR="${PM99_RUNNER_REMOTE_ROOT}/artifacts/${RUN_TAG}"
FINAL_LOCAL_ARTIFACT_DIR="${LOCAL_ARTIFACT_DIR}/${RUN_TAG}"

pm99_runner_prepare_remote_run_root "${REMOTE_RUN_ROOT}" "${REMOTE_ARTIFACT_DIR}"
"${PM99_RUNNER_RSYNC_BIN}" -az \
  "${LOCAL_OVERLAY_DIR}/" "$(pm99_runner_remote_spec):${REMOTE_GAME_DIR}/"

DRIVER_COMMAND=(
  python3 /workspace/repo/scripts/pm99_runner/native_runner.py
  new-game
  --game-dir /workspace/game
  --artifacts-dir /workspace/artifacts
)
for step in "${STATIC_SQUAD_STEPS[@]}"; do
  DRIVER_COMMAND+=(--step "${step}")
done

set +e
pm99_runner_remote_one_shot_container_with_timeout \
  "${DOCKER_TIMEOUT_SECONDS}" \
  "${RUN_TAG}" \
  "run_pm99_ddraw_trace_probe.sh" \
  "pm99-agent-${RUN_TAG}" \
  "${REMOTE_ARTIFACT_DIR}" \
  --image "${PM99_RUNNER_REMOTE_IMAGE}" \
  --user CURRENT_USER \
  --workdir /workspace/repo \
  --shm-size 2g \
  --env HOME=/workspace/home \
  --env PM99_EDITOR_ROOT=/workspace/editor \
  --env PM99_SCREEN_GEOMETRY="${SCREEN_GEOMETRY}" \
  --env PM99_DDRAW_TRACE_LOG=/workspace/artifacts/pm99-ddraw.log \
  --env PM99_DDRAW_NORMALIZE_DISPLAY_MODE="${NORMALIZE_DISPLAY_MODE}" \
  --env WINEDLLOVERRIDES=ddraw=n,b \
  --env WINEDEBUG="${WINE_DEBUG}" \
  --env PYTHONPATH=/workspace/home:/workspace/repo:/workspace/editor \
  --env WINEPREFIX=/workspace/wine-prefix \
  --volume "${PM99_RUNNER_REMOTE_REPO_DIR}:/workspace/repo" \
  --volume "${PM99_RUNNER_REMOTE_EDITOR_REPO_DIR}:/workspace/editor" \
  --volume "${REMOTE_WINE_PREFIX_DIR}:/workspace/wine-prefix" \
  --volume "${REMOTE_HOME_DIR}:/workspace/home" \
  --volume "${REMOTE_GAME_DIR}:/workspace/game" \
  --volume "${REMOTE_ARTIFACT_DIR}:/workspace/artifacts" \
  -- "${DRIVER_COMMAND[@]}"
RUN_STATUS=$?
set -e

SYNC_STATUS=0
pm99_runner_sync_remote_artifacts "${REMOTE_ARTIFACT_DIR}" "${FINAL_LOCAL_ARTIFACT_DIR}" || SYNC_STATUS=$?

if [[ ${SYNC_STATUS} -eq 0 ]]; then
  python3 "${REPO_ROOT}/scripts/summarize_pm99_ddraw_trace.py" "${FINAL_LOCAL_ARTIFACT_DIR}" \
    --output "${FINAL_LOCAL_ARTIFACT_DIR}/pm99-ddraw-summary.json" || true
fi

if [[ ${KEEP_REMOTE} -eq 0 ]]; then
  set +e
  pm99_runner_cleanup_remote_state \
    "${RUN_STATUS}" \
    "${SYNC_STATUS}" \
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
echo "sync_status=${SYNC_STATUS}"

if [[ ${SYNC_STATUS} -ne 0 ]]; then
  exit "${SYNC_STATUS}"
fi
if [[ ${CLEANUP_STATUS} -ne 0 && ${RUN_STATUS} -eq 0 ]]; then
  exit "${CLEANUP_STATUS}"
fi
exit "${RUN_STATUS}"
