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

RUN_TAG="pm99_ddraw_trace_build_$(date -u +%Y%m%dT%H%M%SZ)"
WORKER_NAME="${PM99_RUNNER_WORKER_NAME:-tiny-m73}"
OUTPUT_DIR="${REPO_ROOT}/.local/runner-overlays/ddraw-trace"
LOCAL_ARTIFACT_DIR="${REPO_ROOT}/artifacts/pm99_ddraw_trace_build"
DOCKER_TIMEOUT_SECONDS="${PM99_RUNNER_DOCKER_TIMEOUT_SECONDS:-300}"
KEEP_REMOTE=0

usage() {
  cat <<'USAGE'
Usage: scripts/build_pm99_ddraw_trace_overlay.sh [options]

Build the PM99 log-only ddraw.dll proxy using the existing runner image and
place it into a local source-relative overlay directory.

Options:
  --worker <name>          Remote worker name (default: tiny-m73)
  --run-tag <id>           Override artifact/run tag
  --output-dir <path>      Local overlay output dir (default: .local/runner-overlays/ddraw-trace)
  --local-artifact-dir <p> Local artifact root (default: artifacts/pm99_ddraw_trace_build)
  --docker-timeout <sec>   Hard timeout for the build container (default: 300)
  --keep-remote            Do not clean remote run/artifacts after success
  -h, --help               Show this help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --worker) WORKER_NAME="$2"; shift 2 ;;
    --run-tag) RUN_TAG="$2"; shift 2 ;;
    --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
    --local-artifact-dir) LOCAL_ARTIFACT_DIR="$2"; shift 2 ;;
    --docker-timeout) DOCKER_TIMEOUT_SECONDS="$2"; shift 2 ;;
    --keep-remote) KEEP_REMOTE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

SOURCE_C="${REPO_ROOT}/scripts/pm99_ddraw_trace_proxy.c"
SOURCE_DEF="${REPO_ROOT}/scripts/pm99_ddraw_trace_proxy.def"
if [[ ! -f "${SOURCE_C}" || ! -f "${SOURCE_DEF}" ]]; then
  echo "Missing DirectDraw trace proxy source files" >&2
  exit 2
fi

pm99_runner_require_cmd "${PM99_RUNNER_SSH_BIN}"
pm99_runner_require_cmd "${PM99_RUNNER_RSYNC_BIN}"
pm99_runner_select_remote_worker "${WORKER_NAME}"
PM99_RUNNER_HOST_LOCK_CONCURRENCY="${PM99_RUNNER_WORKER_LANE_COUNT}"

pm99_runner_acquire_remote_host_lock "build_pm99_ddraw_trace_overlay:${RUN_TAG}"
trap 'pm99_runner_release_remote_host_lock' EXIT

REMOTE_RUN_ROOT="$(pm99_runner_remote_run_root "${RUN_TAG}")"
REMOTE_ARTIFACT_DIR="${PM99_RUNNER_REMOTE_ROOT}/artifacts/${RUN_TAG}"
REMOTE_BUILD_DIR="${REMOTE_RUN_ROOT}/ddraw-trace-build"
REMOTE_HOME_DIR="$(pm99_runner_remote_home_dir "${REMOTE_RUN_ROOT}")"
REMOTE_WINE_PREFIX_DIR="$(pm99_runner_remote_wine_prefix_dir "${REMOTE_RUN_ROOT}")"
FINAL_LOCAL_ARTIFACT_DIR="${LOCAL_ARTIFACT_DIR}/${RUN_TAG}"

pm99_runner_prepare_remote_run_root "${REMOTE_RUN_ROOT}" "${REMOTE_ARTIFACT_DIR}"
pm99_runner_ssh "mkdir -p $(printf '%q' "${REMOTE_BUILD_DIR}")"
"${PM99_RUNNER_RSYNC_BIN}" -az \
  "${SOURCE_C}" "${SOURCE_DEF}" \
  "$(pm99_runner_remote_spec):${REMOTE_BUILD_DIR}/"

BUILD_COMMAND=(
  i686-w64-mingw32-gcc
  -std=c99
  -Wall
  -Wextra
  -Werror
  -O2
  -s
  -shared
  -o /workspace/artifacts/ddraw.dll
  /workspace/build/pm99_ddraw_trace_proxy.c
  /workspace/build/pm99_ddraw_trace_proxy.def
)

set +e
pm99_runner_remote_one_shot_container_with_timeout \
  "${DOCKER_TIMEOUT_SECONDS}" \
  "${RUN_TAG}" \
  "build_pm99_ddraw_trace_overlay.sh" \
  "pm99-agent-${RUN_TAG}" \
  "${REMOTE_ARTIFACT_DIR}" \
  --image "${PM99_RUNNER_REMOTE_IMAGE}" \
  --user CURRENT_USER \
  --workdir /workspace/build \
  --env HOME=/workspace/home \
  --env WINEPREFIX=/workspace/wine-prefix \
  --env PM99_RUNNER_STARTUP_LOG=/workspace/artifacts/remote_agent_startup.log \
  --volume "${REMOTE_HOME_DIR}:/workspace/home" \
  --volume "${REMOTE_WINE_PREFIX_DIR}:/workspace/wine-prefix" \
  --volume "${REMOTE_BUILD_DIR}:/workspace/build" \
  --volume "${REMOTE_ARTIFACT_DIR}:/workspace/artifacts" \
  -- "${BUILD_COMMAND[@]}"
RUN_STATUS=$?
set -e

SYNC_STATUS=0
pm99_runner_sync_remote_artifacts "${REMOTE_ARTIFACT_DIR}" "${FINAL_LOCAL_ARTIFACT_DIR}" || SYNC_STATUS=$?

if [[ ${RUN_STATUS} -eq 0 && ${SYNC_STATUS} -eq 0 ]]; then
  mkdir -p "${OUTPUT_DIR}"
  cp "${FINAL_LOCAL_ARTIFACT_DIR}/ddraw.dll" "${OUTPUT_DIR}/ddraw.dll"
  cat > "${OUTPUT_DIR}/README.txt" <<'EOF'
PM99 DirectDraw trace overlay.

Use with WINEDLLOVERRIDES=ddraw=n,b and PM99_DDRAW_TRACE_LOG pointing at an
artifact path. The proxy is log-only: it forwards DirectDraw calls and records
startup/mode HRESULTs without forcing windowed mode or scaling.
EOF
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
echo "overlay_dir=${OUTPUT_DIR}"
echo "run_status=${RUN_STATUS}"
echo "sync_status=${SYNC_STATUS}"

if [[ ${RUN_STATUS} -ne 0 ]]; then
  exit "${RUN_STATUS}"
fi
if [[ ${SYNC_STATUS} -ne 0 ]]; then
  exit "${SYNC_STATUS}"
fi
if [[ ${CLEANUP_STATUS} -ne 0 ]]; then
  exit "${CLEANUP_STATUS}"
fi
