#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER_ROOT="${ROOT_DIR}/upstream/pm99-runner"
export PM99_RUNNER_HOST_LOCK_NAME="${PM99_RUNNER_HOST_LOCK_NAME:-runner-host}"
source "${RUNNER_ROOT}/scripts/pm99_runner/common.sh"
RUN_TAG="pm99_setup_smoke_$(pm99_runner_timestamp_utc)"
GAME_ROOT=""
SKIP_SETUP=0
SKIP_BUILD=0
KEEP_REMOTE_RUN=0
KEEP_REMOTE_ARTIFACTS=0
CLEANUP_ON_FAILURE=0
usage(){ echo "Usage: $0 --game-root PATH [--run-tag TAG] [--skip-setup] [--skip-build]" >&2; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --game-root) GAME_ROOT="$2"; shift 2 ;;
    --run-tag) RUN_TAG="$2"; shift 2 ;;
    --skip-setup) SKIP_SETUP=1; shift ;;
    --skip-build) SKIP_BUILD=1; shift ;;
    --keep-remote-run) KEEP_REMOTE_RUN=1; shift ;;
    --keep-remote-artifacts) KEEP_REMOTE_ARTIFACTS=1; shift ;;
    --cleanup-on-failure) CLEANUP_ON_FAILURE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done
if [[ -z "$GAME_ROOT" ]]; then usage; exit 2; fi
GAME_ROOT="$(cd "$GAME_ROOT" && pwd)"
python3 "${ROOT_DIR}/scripts/assert_pm99_isolated_input.py" --game-root "$GAME_ROOT" >/dev/null
pm99_runner_require_cmd "${PM99_RUNNER_SSH_BIN}"
pm99_runner_require_cmd "${PM99_RUNNER_RSYNC_BIN}"
pm99_runner_require_editor_root
pm99_runner_select_remote_worker "${PM99_RUNNER_WORKER_NAME:-default}"
pm99_runner_acquire_remote_host_lock "run_pm99_manager_league_smoke:${RUN_TAG}"
trap 'pm99_runner_release_remote_host_lock' EXIT
if [[ $SKIP_SETUP -eq 0 ]]; then "${RUNNER_ROOT}/scripts/pm99_runner/setup_remote_host.sh"; fi
if [[ $SKIP_BUILD -eq 0 ]]; then "${RUNNER_ROOT}/scripts/pm99_runner/build_runner_image.sh"; fi
pm99_runner_sync_repo
pm99_runner_ensure_local_artifact_root
REMOTE_RUN_ROOT="${PM99_RUNNER_REMOTE_ROOT}/workspace/runs/${RUN_TAG}"
REMOTE_ARTIFACT_DIR="${PM99_RUNNER_REMOTE_ROOT}/artifacts/${RUN_TAG}"
REMOTE_GAME_DIR="${REMOTE_RUN_ROOT}/premier-manager-ninety-nine"
REMOTE_HOME_DIR="${REMOTE_RUN_ROOT}/home"
REMOTE_WINE_PREFIX_DIR="${REMOTE_RUN_ROOT}/wine-prefix"
LOCAL_ARTIFACT_DIR="${PM99_RUNNER_LOCAL_ARTIFACT_ROOT}/${RUN_TAG}"
pm99_runner_ssh "set -euo pipefail; rm -rf '${REMOTE_RUN_ROOT}' '${REMOTE_ARTIFACT_DIR}'; mkdir -p '${REMOTE_GAME_DIR}' '${REMOTE_HOME_DIR}' '${REMOTE_WINE_PREFIX_DIR}' '${REMOTE_ARTIFACT_DIR}'"
"${PM99_RUNNER_RSYNC_BIN}" -az --delete --exclude='DBDAT/*.backup*' --exclude='DBDAT/*backup*' "${GAME_ROOT}/" "$(pm99_runner_remote_spec):${REMOTE_GAME_DIR}/"
mkdir -p "${LOCAL_ARTIFACT_DIR}"
RUN_STATUS=0
set +e
pm99_runner_remote_one_shot_container_with_timeout \
  "${PM99_RUNNER_DOCKER_TIMEOUT_SECONDS:-180}" \
  "${RUN_TAG}" \
  "run_pm99_manager_league_smoke.sh" \
  "pm99-agent-${RUN_TAG}" \
  "${REMOTE_ARTIFACT_DIR}" \
  --image "${PM99_RUNNER_REMOTE_IMAGE}" \
  --user CURRENT_USER \
  --workdir /workspace/repo \
  --shm-size 2g \
  --env HOME=/workspace/home \
  --env PM99_EDITOR_ROOT=/workspace/editor \
  --env PM99_RUNNER_FAST_OCR=1 \
  --env PM99_RUNNER_TRACE_MODE=lean \
  --env PYTHONPATH=/workspace/repo:/workspace/editor \
  --env WINEPREFIX=/workspace/wine-prefix \
  --volume "${PM99_RUNNER_REMOTE_REPO_DIR}:/workspace/repo" \
  --volume "${PM99_RUNNER_REMOTE_EDITOR_REPO_DIR}:/workspace/editor" \
  --volume "${REMOTE_WINE_PREFIX_DIR}:/workspace/wine-prefix" \
  --volume "${REMOTE_HOME_DIR}:/workspace/home" \
  --volume "${REMOTE_GAME_DIR}:/workspace/game" \
  --volume "${REMOTE_ARTIFACT_DIR}:/workspace/artifacts" \
  -- python3 /workspace/repo/scripts/pm99_runner/native_runner.py new-game \
    --game-dir /workspace/game \
    --artifacts-dir /workspace/artifacts \
    --expect-initial-screen title_screen \
    --expect-final-screen name_team_screen \
    --step 'manager_league|click|460,263|4.0' \
    --step 'manager_double|native_double_click|338,63,1|4.0' \
    --step 'continue_visible|native_input_click|494,459,1|5.0'
RUN_STATUS=$?
set -e
set +e
pm99_runner_sync_remote_artifacts "${REMOTE_ARTIFACT_DIR}" "${LOCAL_ARTIFACT_DIR}"
SYNC_STATUS=$?
pm99_runner_cleanup_remote_state "$RUN_STATUS" "$SYNC_STATUS" "$REMOTE_RUN_ROOT" "$REMOTE_ARTIFACT_DIR" "$KEEP_REMOTE_RUN" "$KEEP_REMOTE_ARTIFACTS" "$CLEANUP_ON_FAILURE" 0
CLEANUP_STATUS=$?
set -e
python3 - "${LOCAL_ARTIFACT_DIR}" "$RUN_STATUS" "$SYNC_STATUS" "$CLEANUP_STATUS" <<'PY'
import json, sys
from pathlib import Path
root=Path(sys.argv[1])
summary_path=root/'summary.json'
runner={}
if summary_path.is_file():
    try: runner=json.loads(summary_path.read_text())
    except Exception: runner={}
out={'success': int(sys.argv[2])==0 and int(sys.argv[3])==0 and int(sys.argv[4])==0, 'run_status': int(sys.argv[2]), 'sync_status': int(sys.argv[3]), 'cleanup_status': int(sys.argv[4]), 'artifact_dir': str(root), 'runner_summary': runner}
(root/'manager_smoke_summary.json').write_text(json.dumps(out, indent=2, sort_keys=True)+'\n')
print(json.dumps(out, indent=2, sort_keys=True))
PY
if [[ $SYNC_STATUS -ne 0 ]]; then exit "$SYNC_STATUS"; fi
if [[ $CLEANUP_STATUS -ne 0 && $RUN_STATUS -eq 0 ]]; then exit "$CLEANUP_STATUS"; fi
exit "$RUN_STATUS"
