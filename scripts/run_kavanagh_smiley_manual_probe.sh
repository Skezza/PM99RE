#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER_ROOT="${ROOT_DIR}/upstream/pm99-runner"
export PM99_RUNNER_HOST_LOCK_NAME="${PM99_RUNNER_HOST_LOCK_NAME:-runner-host}"
source "${RUNNER_ROOT}/scripts/pm99_runner/common.sh"

RUN_TAG=""
MINIFOTO_OVERRIDE=""
ROW_Y=297
KEEP_REMOTE_RUN=0
KEEP_REMOTE_ARTIFACTS=0

usage() {
  cat <<'EOF'
Usage: ./scripts/run_kavanagh_smiley_manual_probe.sh --run-tag <id> [options]

Run a deterministic vanilla new-game input script through native_runner.py and
capture Stoke slot-11 profile evidence (Graham Kavanagh lane target).

Options:
  --run-tag <id>              Required run tag for remote/local artifacts.
  --minifoto-override <path>  Optional patched MINIFOTO.PKF to inject before launch.
  --row-y <pixels>            Squad row Y coordinate (default: 297 for slot 11).
  --keep-remote-run           Keep remote workspace run root after sync.
  --keep-remote-artifacts     Keep remote artifact dir after sync.
  -h, --help                  Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-tag) RUN_TAG="$2"; shift 2 ;;
    --minifoto-override) MINIFOTO_OVERRIDE="$2"; shift 2 ;;
    --row-y) ROW_Y="$2"; shift 2 ;;
    --keep-remote-run) KEEP_REMOTE_RUN=1; shift ;;
    --keep-remote-artifacts) KEEP_REMOTE_ARTIFACTS=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "${RUN_TAG}" ]]; then
  echo "--run-tag is required" >&2
  usage >&2
  exit 2
fi

if [[ -n "${MINIFOTO_OVERRIDE}" && ! -f "${MINIFOTO_OVERRIDE}" ]]; then
  echo "MINIFOTO override file not found: ${MINIFOTO_OVERRIDE}" >&2
  exit 2
fi

pm99_runner_require_cmd "${PM99_RUNNER_SSH_BIN}"
pm99_runner_require_cmd "${PM99_RUNNER_RSYNC_BIN}"
pm99_runner_require_editor_root
pm99_runner_select_remote_worker "${PM99_RUNNER_WORKER_NAME:-default}"
PM99_RUNNER_HOST_LOCK_CONCURRENCY="${PM99_RUNNER_WORKER_LANE_COUNT}"
pm99_runner_acquire_remote_host_lock "run_kavanagh_smiley_manual_probe:${RUN_TAG}"
trap 'pm99_runner_release_remote_host_lock' EXIT

pm99_runner_sync_repo
pm99_runner_ensure_local_artifact_root

REMOTE_RUN_ROOT="${PM99_RUNNER_REMOTE_ROOT}/workspace/runs/${RUN_TAG}"
REMOTE_ARTIFACT_DIR="${PM99_RUNNER_REMOTE_ROOT}/artifacts/${RUN_TAG}"
LOCAL_ARTIFACT_DIR="${PM99_RUNNER_LOCAL_ARTIFACT_ROOT}/${RUN_TAG}"
REMOTE_GAME_DIR="${REMOTE_RUN_ROOT}/premier-manager-ninety-nine"
REMOTE_HOME_DIR="${REMOTE_RUN_ROOT}/home"
REMOTE_WINE_PREFIX_DIR="${REMOTE_RUN_ROOT}/wine-prefix"
pm99_runner_ssh "
set -euo pipefail
rm -rf '${REMOTE_RUN_ROOT}' '${REMOTE_ARTIFACT_DIR}'
mkdir -p '${REMOTE_RUN_ROOT}' '${REMOTE_HOME_DIR}' '${REMOTE_WINE_PREFIX_DIR}' '${REMOTE_ARTIFACT_DIR}'
cp -a '$(pm99_runner_remote_source_install_dir)' '${REMOTE_GAME_DIR}'
"

if [[ -n "${MINIFOTO_OVERRIDE}" ]]; then
  REMOTE_OVERRIDE_PATH="${REMOTE_RUN_ROOT}/MINIFOTO.override.PKF"
  pm99_runner_scp_to_remote "${MINIFOTO_OVERRIDE}" "${REMOTE_OVERRIDE_PATH}"
  pm99_runner_ssh "
set -euo pipefail
cp '${REMOTE_OVERRIDE_PATH}' '${REMOTE_GAME_DIR}/DBDAT/MINIFOTO.PKF'
"
fi

declare -a STEPS=(
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
  "dashboard_select_squad|native_input_click|214,395,1|1.0"
  "dashboard_enter_selected|native_input_click|571,459,1|6.0"
  "dashboard_activate_squad|native_input_click|214,395,1|3.0"
  "dashboard_enter_selected_retry|native_input_click|571,459,1|6.0"
  "dashboard_squad_retry|native_double_click|214,395,1|5.0"
  "profile_select_target|native_input_click|40,${ROW_Y},1|0.35"
  "profile_open_target|native_double_click|40,${ROW_Y},1|3.5"
  "profile_open_fallback|native_input_key|Return|1.8"
  "profile_hold|sleep|noop|1.0"
)

STEP_ARGS=""
for step in "${STEPS[@]}"; do
  STEP_ARGS+=" --step $(printf '%q' "${step}")"
done

set +e
pm99_runner_remote_one_shot_container_with_timeout \
  "${PM99_RUNNER_DOCKER_TIMEOUT_SECONDS:-900}" \
  "${RUN_TAG}" \
  "run_kavanagh_smiley_manual_probe.sh" \
  "pm99-agent-${RUN_TAG}" \
  "${REMOTE_ARTIFACT_DIR}" \
  --image "${PM99_RUNNER_REMOTE_IMAGE}" \
  --user CURRENT_USER \
  --workdir /workspace/repo \
  --shm-size 2g \
  --env HOME=/workspace/home \
  --env PM99_EDITOR_ROOT=/workspace/editor \
  --env PYTHONPATH=/workspace/home:/workspace/repo:/workspace/editor \
  --env WINEPREFIX=/workspace/wine-prefix \
  --volume "${PM99_RUNNER_REMOTE_REPO_DIR}:/workspace/repo" \
  --volume "${PM99_RUNNER_REMOTE_EDITOR_REPO_DIR}:/workspace/editor" \
  --volume "${REMOTE_WINE_PREFIX_DIR}:/workspace/wine-prefix" \
  --volume "${REMOTE_HOME_DIR}:/workspace/home" \
  --volume "${REMOTE_GAME_DIR}:/workspace/game" \
  --volume "${REMOTE_ARTIFACT_DIR}:/workspace/artifacts" \
  -- python3 /workspace/repo/scripts/pm99_runner/native_runner.py \
    new-game \
    --game-dir /workspace/game \
    --artifacts-dir /workspace/artifacts \
    ${STEP_ARGS}
RUN_STATUS=$?
set -e

pm99_runner_sync_remote_artifacts "${REMOTE_ARTIFACT_DIR}" "${LOCAL_ARTIFACT_DIR}"

if [[ ${KEEP_REMOTE_ARTIFACTS} -eq 0 ]]; then
  pm99_runner_ssh "rm -rf '${REMOTE_ARTIFACT_DIR}'"
fi
if [[ ${KEEP_REMOTE_RUN} -eq 0 ]]; then
  pm99_runner_ssh "rm -rf '${REMOTE_RUN_ROOT}'"
fi

echo "RUN_TAG=${RUN_TAG}"
echo "RUN_STATUS=${RUN_STATUS}"
echo "LOCAL_ARTIFACT_DIR=${LOCAL_ARTIFACT_DIR}"

exit "${RUN_STATUS}"
