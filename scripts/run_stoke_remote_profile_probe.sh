#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PM99_RUNNER_NAMESPACE="${PM99_RUNNER_NAMESPACE:-pm99-research-main}"
export PM99_RUNNER_REMOTE_ROOT="${PM99_RUNNER_REMOTE_ROOT:-/home/joe/pm99-runner/namespaces/${PM99_RUNNER_NAMESPACE}}"
export PM99_RUNNER_REMOTE_ASSET_ROOT="${PM99_RUNNER_REMOTE_ASSET_ROOT:-/home/joe/pm99-runner/shared}"
export PM99_RUNNER_REMOTE_REPO_DIR="${PM99_RUNNER_REMOTE_REPO_DIR:-${PM99_RUNNER_REMOTE_ROOT}/workspace/repo}"
export PM99_RUNNER_REMOTE_EDITOR_REPO_DIR="${PM99_RUNNER_REMOTE_EDITOR_REPO_DIR:-${PM99_RUNNER_REMOTE_ROOT}/workspace/editor}"
export PM99_RUNNER_REMOTE_IMAGE="${PM99_RUNNER_REMOTE_IMAGE:-pm99-runner-${PM99_RUNNER_NAMESPACE}:latest}"
export PM99_RUNNER_HOST_LOCK_NAME="${PM99_RUNNER_HOST_LOCK_NAME:-runner-host}"
source "${REPO_ROOT}/upstream/pm99-runner/scripts/pm99_runner/common.sh"

RUN_TAG="stoke_remote_profile_probe_$(date -u +%Y%m%dT%H%M%SZ)"
LOCAL_GAME_DIR=""
LOCAL_OVERLAY_DIR=""
LOCAL_ARTIFACT_DIR="${REPO_ROOT}/artifacts/stoke_remote_profile_probe"
PROFILE_COUNT=0
WORKER_NAME="${PM99_RUNNER_WORKER_NAME:-}"
SKIP_SETUP=0
SKIP_SYNC=0
SKIP_PREPARE=0
MODE="vanilla_profile"
SQUAD_DIFF_THRESHOLD=50
REFERENCE_SCREENSHOT=""
SKIP_IMAGE_EVAL=0
KEEP_REMOTE_RUN=0
KEEP_REMOTE_ARTIFACTS=0
CLEANUP_ON_FAILURE=0

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
  cat <<'EOF'
Usage: scripts/run_stoke_remote_profile_probe.sh [options]

Upload a local PM99 game tree to the isolated remote runner host, execute the
vanilla Stoke profile driver in the remote Docker image, and mirror artifacts
back locally. By default the probe starts from the remote prepared source
install, then optionally overlays a local directory on top.

Options:
  --run-tag <id>            Override the remote/local artifact tag
  --mode <id>               Probe mode: vanilla_profile or static_squad (default: vanilla_profile)
  --worker <name>           Select a configured PM99 worker lane
  --local-game-dir <path>   Local full game directory to upload instead of remote source install
  --local-overlay-dir <p>   Local overlay tree rsynced on top of the remote source install
  --local-artifact-dir <p>  Local artifact root (default: artifacts/stoke_remote_profile_probe)
  --profile-count <n>       Driver profile count (default: 0)
  --skip-setup              Skip remote host bootstrap for the namespaced runner root
  --squad-diff-threshold <n>
                            Image-diff threshold for static_squad success (default: 50)
  --reference-screenshot <p>
                            Override the static_squad reference screenshot path
  --skip-image-eval         Skip static_squad image comparison and trust runner status only
  --keep-remote-run         Preserve the remote per-run game/home/prefix directory
  --keep-remote-artifacts   Preserve the remote artifact directory after local mirroring
  --cleanup-on-failure      Clean remote run/artifact state after a failed run once mirroring succeeds
  --skip-sync               Skip repo/editor rsync before remote execution
  --skip-prepare            Skip remote source-install preparation
  -h, --help                Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-tag) RUN_TAG="$2"; shift 2 ;;
    --mode) MODE="$2"; shift 2 ;;
    --worker) WORKER_NAME="$2"; shift 2 ;;
    --local-game-dir) LOCAL_GAME_DIR="$2"; shift 2 ;;
    --local-overlay-dir) LOCAL_OVERLAY_DIR="$2"; shift 2 ;;
    --local-artifact-dir) LOCAL_ARTIFACT_DIR="$2"; shift 2 ;;
    --profile-count) PROFILE_COUNT="$2"; shift 2 ;;
    --skip-setup) SKIP_SETUP=1; shift ;;
    --squad-diff-threshold) SQUAD_DIFF_THRESHOLD="$2"; shift 2 ;;
    --reference-screenshot) REFERENCE_SCREENSHOT="$2"; shift 2 ;;
    --skip-image-eval) SKIP_IMAGE_EVAL=1; shift ;;
    --keep-remote-run) KEEP_REMOTE_RUN=1; shift ;;
    --keep-remote-artifacts) KEEP_REMOTE_ARTIFACTS=1; shift ;;
    --cleanup-on-failure) CLEANUP_ON_FAILURE=1; shift ;;
    --skip-sync) SKIP_SYNC=1; shift ;;
    --skip-prepare) SKIP_PREPARE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
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
if [[ "${MODE}" != "vanilla_profile" && "${MODE}" != "static_squad" ]]; then
  echo "Unsupported mode: ${MODE}" >&2
  exit 2
fi
if [[ -n "${REFERENCE_SCREENSHOT}" && ! -f "${REFERENCE_SCREENSHOT}" ]]; then
  echo "Missing reference screenshot: ${REFERENCE_SCREENSHOT}" >&2
  exit 2
fi

reject_legacy_shared_state() {
  local target_path="$1"
  local label="$2"
  python3 - "${REPO_ROOT}" "${target_path}" "${label}" <<'PY'
from pathlib import Path
import sys

repo_root = Path(sys.argv[1])
sys.path.insert(0, str(repo_root / "scripts"))
from assert_pm99_isolated_input import ensure_not_legacy_path  # noqa: E402

ensure_not_legacy_path(sys.argv[2], label=sys.argv[3])
PY
}

pm99_runner_select_remote_worker "${WORKER_NAME:-}"
PM99_RUNNER_HOST_LOCK_CONCURRENCY="${PM99_RUNNER_WORKER_LANE_COUNT}"

pm99_runner_require_cmd "${PM99_RUNNER_SSH_BIN}"
pm99_runner_require_cmd "${PM99_RUNNER_RSYNC_BIN}"
pm99_runner_require_editor_root
pm99_runner_acquire_remote_host_lock "run_stoke_remote_profile_probe:${RUN_TAG}"
trap 'pm99_runner_release_remote_host_lock' EXIT


if [[ -n "${LOCAL_GAME_DIR}" ]]; then
  reject_legacy_shared_state "${LOCAL_GAME_DIR}" "local game dir"
  python3 "${REPO_ROOT}/scripts/assert_pm99_isolated_input.py" --game-root "${LOCAL_GAME_DIR}" >/dev/null
fi
if [[ -n "${LOCAL_OVERLAY_DIR}" ]]; then
  reject_legacy_shared_state "${LOCAL_OVERLAY_DIR}" "local overlay dir"
fi
if [[ ${SKIP_SETUP} -eq 0 ]]; then
  "${REPO_ROOT}/upstream/pm99-runner/scripts/pm99_runner/setup_remote_host.sh" --skip-repo-sync
fi
if [[ ${SKIP_PREPARE} -eq 0 ]]; then
  "${REPO_ROOT}/upstream/pm99-runner/scripts/pm99_runner/prepare_game_source.sh"
fi

if [[ ${SKIP_SYNC} -eq 0 ]]; then
  pm99_runner_sync_repo
fi

REMOTE_IMAGE_PRESENT="$(pm99_runner_ssh "
set -euo pipefail
if docker image inspect '${PM99_RUNNER_REMOTE_IMAGE}' >/dev/null 2>&1; then
  echo 1
else
  echo 0
fi
")"
if [[ "${REMOTE_IMAGE_PRESENT}" != "1" ]]; then
  "${REPO_ROOT}/upstream/pm99-runner/scripts/pm99_runner/build_runner_image.sh" --skip-repo-sync
fi

REMOTE_RUN_ROOT="$(pm99_runner_remote_run_root "${RUN_TAG}")"
REMOTE_GAME_DIR="$(pm99_runner_remote_game_dir "${REMOTE_RUN_ROOT}")"
REMOTE_HOME_DIR="$(pm99_runner_remote_home_dir "${REMOTE_RUN_ROOT}")"
REMOTE_WINE_PREFIX_DIR="$(pm99_runner_remote_wine_prefix_dir "${REMOTE_RUN_ROOT}")"
REMOTE_ARTIFACT_DIR="${PM99_RUNNER_REMOTE_ROOT}/artifacts/${RUN_TAG}"
FINAL_LOCAL_ARTIFACT_DIR="${LOCAL_ARTIFACT_DIR}/${RUN_TAG}"
LOCAL_RUNNER_PACKAGE_DIR="${REPO_ROOT}/upstream/pm99-runner/scripts/pm99_runner"
REMOTE_RUNNER_PACKAGE_DIR="${REMOTE_HOME_DIR}/pm99_runner"

pm99_runner_prepare_remote_run_root "${REMOTE_RUN_ROOT}" "${REMOTE_ARTIFACT_DIR}"
pm99_runner_ssh "mkdir -p '${REMOTE_RUNNER_PACKAGE_DIR}'"
"${PM99_RUNNER_RSYNC_BIN}" -az --delete \
  "${LOCAL_RUNNER_PACKAGE_DIR}/" "$(pm99_runner_remote_spec):${REMOTE_RUNNER_PACKAGE_DIR}/"

if [[ -n "${LOCAL_GAME_DIR}" ]]; then
  "${PM99_RUNNER_RSYNC_BIN}" -az --delete \
    "${LOCAL_GAME_DIR}/" "$(pm99_runner_remote_spec):${REMOTE_GAME_DIR}/"
fi

if [[ -n "${LOCAL_OVERLAY_DIR}" ]]; then
  "${PM99_RUNNER_RSYNC_BIN}" -az \
    "${LOCAL_OVERLAY_DIR}/" "$(pm99_runner_remote_spec):${REMOTE_GAME_DIR}/"
fi

declare -a DRIVER_ARGS=(
  python3
  /workspace/home/pm99_runner/stoke_vanilla_profile_capture_driver.py
  --game-dir
  /workspace/game
  --artifacts-dir
  /workspace/artifacts
  --profile-count
  "${PROFILE_COUNT}"
)
if [[ "${MODE}" == "static_squad" ]]; then
  DRIVER_ARGS=(
    python3
    /workspace/home/pm99_runner/native_runner.py
    new-game
    --game-dir
    /workspace/game
    --artifacts-dir
    /workspace/artifacts
  )
  for step in "${STATIC_SQUAD_STEPS[@]}"; do
    DRIVER_ARGS+=(--step "${step}")
  done
fi

set +e
pm99_runner_remote_one_shot_container   "${RUN_TAG}"   "run_stoke_remote_profile_probe.sh"   "pm99-agent-${RUN_TAG}"   "${REMOTE_ARTIFACT_DIR}"   --image "${PM99_RUNNER_REMOTE_IMAGE}"   --user CURRENT_USER   --workdir /workspace/repo   --shm-size 2g   --env HOME=/workspace/home   --env PM99_EDITOR_ROOT=/workspace/editor   --env PYTHONPATH=/workspace/home:/workspace/repo:/workspace/editor   --env WINEPREFIX=/workspace/wine-prefix   --volume "${PM99_RUNNER_REMOTE_REPO_DIR}:/workspace/repo"   --volume "${PM99_RUNNER_REMOTE_EDITOR_REPO_DIR}:/workspace/editor"   --volume "${REMOTE_WINE_PREFIX_DIR}:/workspace/wine-prefix"   --volume "${REMOTE_HOME_DIR}:/workspace/home"   --volume "${REMOTE_GAME_DIR}:/workspace/game"   --volume "${REMOTE_ARTIFACT_DIR}:/workspace/artifacts"   --   "${DRIVER_ARGS[@]}"
RUN_STATUS=$?
set -e

mkdir -p "${FINAL_LOCAL_ARTIFACT_DIR}"
set +e
pm99_runner_sync_remote_artifacts "${REMOTE_ARTIFACT_DIR}" "${FINAL_LOCAL_ARTIFACT_DIR}"
SYNC_STATUS=$?
pm99_runner_cleanup_remote_state \
  "${RUN_STATUS}" \
  "${SYNC_STATUS}" \
  "${REMOTE_RUN_ROOT}" \
  "${REMOTE_ARTIFACT_DIR}" \
  "${KEEP_REMOTE_RUN}" \
  "${KEEP_REMOTE_ARTIFACTS}" \
  "${CLEANUP_ON_FAILURE}" \
  0
CLEANUP_STATUS=$?
set -e

if [[ "${MODE}" == "static_squad" ]]; then
  STATIC_STATUS=0
  python3 - <<'PY' "${FINAL_LOCAL_ARTIFACT_DIR}" "${SQUAD_DIFF_THRESHOLD}" "${REPO_ROOT}" "${REFERENCE_SCREENSHOT}" "${SKIP_IMAGE_EVAL}"
from __future__ import annotations
import json
import sys
from pathlib import Path
from PIL import Image, ImageChops, ImageStat

artifact_dir = Path(sys.argv[1])
threshold = float(sys.argv[2])
repo_root = Path(sys.argv[3])
reference_override = Path(sys.argv[4]).resolve() if sys.argv[4] else None
skip_image_eval = bool(int(sys.argv[5]))
reference = reference_override or (
    repo_root / "upstream/pm99-runner/docs/artifacts/pm99_runner/stoke_vanilla_guided_20260408T220842Z/screens/29_dashboard_activate_squad.png"
)
screens = sorted((artifact_dir / "screens").glob("*.png"))
payload = {
    "mode": "static_squad",
    "reference_screenshot": str(reference),
    "diff_threshold": threshold,
    "screen_count": len(screens),
    "last_screenshot": str(screens[-1]) if screens else None,
    "best_screenshot": None,
    "squad_like": False,
    "image_eval_skipped": skip_image_eval,
}
if skip_image_eval:
    payload["success"] = True
elif screens and reference.is_file():
    ref_image = Image.open(reference).convert("RGB")
    best_avg = None
    best_mean = None
    best_path = None
    for screen_path in screens:
        screen_image = Image.open(screen_path).convert("RGB")
        diff = ImageChops.difference(ref_image, screen_image)
        mean = ImageStat.Stat(diff).mean
        avg = sum(mean) / len(mean)
        if best_avg is None or avg < best_avg:
            best_avg = avg
            best_mean = mean
            best_path = screen_path
    payload["best_screenshot"] = str(best_path) if best_path else None
    payload["diff_mean"] = best_mean
    payload["diff_average"] = best_avg
    payload["squad_like"] = best_avg is not None and best_avg <= threshold
    payload["success"] = payload["squad_like"]
else:
    payload["success"] = False
output_path = artifact_dir / "static_squad_evaluation.json"
output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
print(json.dumps(payload, indent=2))
raise SystemExit(0 if payload["success"] else 1)
PY
  STATIC_STATUS=$?
  if [[ ${RUN_STATUS} -eq 0 ]]; then
    RUN_STATUS=${STATIC_STATUS}
  fi
fi

if [[ ${SYNC_STATUS} -ne 0 ]]; then
  RUN_STATUS=${SYNC_STATUS}
elif [[ ${CLEANUP_STATUS} -ne 0 && ${RUN_STATUS} -eq 0 ]]; then
  RUN_STATUS=${CLEANUP_STATUS}
fi

echo "runner_namespace=${PM99_RUNNER_NAMESPACE}"
echo "remote_run_root=${REMOTE_RUN_ROOT}"
echo "remote_artifacts=${REMOTE_ARTIFACT_DIR}"
echo "local_artifacts=${FINAL_LOCAL_ARTIFACT_DIR}"
echo "run_status=${RUN_STATUS}"

exit "${RUN_STATUS}"
