#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER_ROOT="${ROOT_DIR}/upstream/pm99-runner"
export PM99_RUNNER_HOST_LOCK_NAME="${PM99_RUNNER_HOST_LOCK_NAME:-runner-host}"
source "${RUNNER_ROOT}/scripts/pm99_runner/common.sh"

RUN_TAG="stoke_2015_faces_capture_$(pm99_runner_timestamp_utc)"
GAME_ROOT=""
DBDAT_DIR=""
PROFILE_COUNT=20
ROW_X=40
ROW_START_Y=127
ROW_PITCH=15
OVERRIDE_ENT=0
EXE_OVERRIDE=""
LATE_DBDAT_DIR=""
LATE_DBDAT_FILES="JUG98030.FDI,EQ98030.FDI,MINIFOTO.PKF"
ALLOW_LEGACY_LATE_INJECTION=0
FULL_GAME_ROOT_MODE=0
SKIP_SETUP=0
SKIP_BUILD=0
SKIP_PREPARE=0
KEEP_REMOTE_RUN=0
KEEP_REMOTE_ARTIFACTS=0
CLEANUP_ON_FAILURE=0

usage() {
  cat <<'EOF'
Usage: ./scripts/run_stoke_profile_capture_with_dbdat_overrides.sh (--game-root <path> | --dbdat-dir <path>) [options]

Run the Stoke vanilla profile capture lane while injecting local DBDAT overrides
(JUG/EQ/ENT/MINIFOTO) into a disposable remote PM99 game copy.

Options:
  --game-root <path>          Isolated PM99 game root containing MANAGPRE.EXE + DBDAT/
  --dbdat-dir <path>          Local directory with override DBDAT files
  --run-tag <id>              Override run tag
  --profile-count <n>         Number of squad profile rows to capture (default: 20)
  --row-x <pixels>            Squad row click X coordinate (default: 40)
  --row-start-y <pixels>      Squad row 1 click Y coordinate (default: 127)
  --row-pitch <pixels>        Squad row vertical spacing (default: 15)
  --override-ent              Also override ENT98030.FDI from --dbdat-dir
  --exe-override <path>       Optional MANAGPRE.EXE override to copy into the run
  --allow-legacy-late-injection
                              Permit debug-only late DBDAT injection
  --late-dbdat-dir <path>     Debug-only DBDAT dir injected after dashboard is reached
  --late-dbdat-files <csv>    Debug-only late-inject file list (default: JUG98030.FDI,EQ98030.FDI,MINIFOTO.PKF)
  --skip-setup                Skip remote host bootstrap/sync prerequisites
  --skip-build                Skip docker image build
  --skip-prepare              Skip clean source extraction
  --keep-remote-run           Preserve remote per-run workspace
  --keep-remote-artifacts     Preserve remote artifacts after mirroring
  --cleanup-on-failure        Clean remote state after failed run once mirrored
  -h, --help                  Show this help
EOF
  echo
  pm99_runner_usage_common
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --game-root) GAME_ROOT="$2"; shift 2 ;;
    --dbdat-dir) DBDAT_DIR="$2"; shift 2 ;;
    --run-tag) RUN_TAG="$2"; shift 2 ;;
    --profile-count) PROFILE_COUNT="$2"; shift 2 ;;
    --row-x) ROW_X="$2"; shift 2 ;;
    --row-start-y) ROW_START_Y="$2"; shift 2 ;;
    --row-pitch) ROW_PITCH="$2"; shift 2 ;;
    --override-ent) OVERRIDE_ENT=1; shift ;;
    --exe-override) EXE_OVERRIDE="$2"; shift 2 ;;
    --allow-legacy-late-injection) ALLOW_LEGACY_LATE_INJECTION=1; shift ;;
    --late-dbdat-dir) LATE_DBDAT_DIR="$2"; shift 2 ;;
    --late-dbdat-files) LATE_DBDAT_FILES="$2"; shift 2 ;;
    --skip-setup) SKIP_SETUP=1; shift ;;
    --skip-build) SKIP_BUILD=1; shift ;;
    --skip-prepare) SKIP_PREPARE=1; shift ;;
    --keep-remote-run) KEEP_REMOTE_RUN=1; shift ;;
    --keep-remote-artifacts) KEEP_REMOTE_ARTIFACTS=1; shift ;;
    --cleanup-on-failure) CLEANUP_ON_FAILURE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "${GAME_ROOT}" && -z "${DBDAT_DIR}" ]]; then
  echo "Provide --game-root or --dbdat-dir" >&2
  usage >&2
  exit 2
fi
if [[ -n "${GAME_ROOT}" && -n "${DBDAT_DIR}" ]]; then
  echo "--game-root and --dbdat-dir are mutually exclusive" >&2
  exit 2
fi

if [[ -n "${GAME_ROOT}" ]]; then
  GAME_ROOT="$(cd "${GAME_ROOT}" && pwd)"
  python3 "${ROOT_DIR}/scripts/assert_pm99_isolated_input.py" --game-root "${GAME_ROOT}" >/dev/null
  DBDAT_DIR="${GAME_ROOT}/DBDAT"
  FULL_GAME_ROOT_MODE=1
  if [[ -z "${EXE_OVERRIDE}" && -f "${GAME_ROOT}/MANAGPRE.EXE" ]]; then
    EXE_OVERRIDE="${GAME_ROOT}/MANAGPRE.EXE"
  fi
fi

DBDAT_DIR="$(cd "${DBDAT_DIR}" && pwd)"
python3 "${ROOT_DIR}/scripts/assert_pm99_isolated_input.py" \
  --dbdat-dir "${DBDAT_DIR}" \
  --required-dbdat-file JUG98030.FDI \
  --required-dbdat-file EQ98030.FDI \
  --required-dbdat-file MINIFOTO.PKF >/dev/null
for required in JUG98030.FDI EQ98030.FDI MINIFOTO.PKF; do
  if [[ ! -f "${DBDAT_DIR}/${required}" ]]; then
    echo "Missing override file: ${DBDAT_DIR}/${required}" >&2
    exit 2
  fi
done
if [[ ${OVERRIDE_ENT} -eq 1 && ! -f "${DBDAT_DIR}/ENT98030.FDI" ]]; then
  echo "Missing override file: ${DBDAT_DIR}/ENT98030.FDI" >&2
  exit 2
fi
if [[ -n "${EXE_OVERRIDE}" && ! -f "${EXE_OVERRIDE}" ]]; then
  echo "Missing MANAGPRE.EXE override: ${EXE_OVERRIDE}" >&2
  exit 2
fi
LATE_FILE_LIST=()
if [[ -n "${LATE_DBDAT_DIR}" ]]; then
  if [[ ${ALLOW_LEGACY_LATE_INJECTION} -ne 1 ]]; then
    echo "Late injection is debug-only. Re-run with --allow-legacy-late-injection to permit it." >&2
    exit 2
  fi
  LATE_DBDAT_DIR="$(cd "${LATE_DBDAT_DIR}" && pwd)"
  if [[ ! -d "${LATE_DBDAT_DIR}" ]]; then
    echo "Missing late DBDAT directory: ${LATE_DBDAT_DIR}" >&2
    exit 2
  fi
  IFS=',' read -r -a _late_files_raw <<< "${LATE_DBDAT_FILES}"
  for raw_name in "${_late_files_raw[@]}"; do
    file_name="${raw_name//[[:space:]]/}"
    if [[ -z "${file_name}" ]]; then
      continue
    fi
    if [[ ! -f "${LATE_DBDAT_DIR}/${file_name}" ]]; then
      echo "Missing late override file: ${LATE_DBDAT_DIR}/${file_name}" >&2
      exit 2
    fi
    LATE_FILE_LIST+=("${file_name}")
  done
  if [[ ${#LATE_FILE_LIST[@]} -eq 0 ]]; then
    echo "No valid --late-dbdat-files entries were provided" >&2
    exit 2
  fi
fi

pm99_runner_require_cmd "${PM99_RUNNER_SSH_BIN}"
pm99_runner_require_cmd "${PM99_RUNNER_RSYNC_BIN}"
pm99_runner_require_editor_root
pm99_runner_select_remote_worker "${PM99_RUNNER_WORKER_NAME:-default}"
PM99_RUNNER_HOST_LOCK_CONCURRENCY="${PM99_RUNNER_WORKER_LANE_COUNT}"
pm99_runner_acquire_remote_host_lock "run_stoke_profile_capture_with_dbdat_overrides:${RUN_TAG}"
trap 'pm99_runner_release_remote_host_lock' EXIT

if [[ ${SKIP_SETUP} -eq 0 ]]; then
  "${RUNNER_ROOT}/scripts/pm99_runner/setup_remote_host.sh"
fi
if [[ ${SKIP_PREPARE} -eq 0 && ${FULL_GAME_ROOT_MODE} -eq 0 ]]; then
  "${RUNNER_ROOT}/scripts/pm99_runner/prepare_game_source.sh" --skip-zip-upload
fi
if [[ ${SKIP_BUILD} -eq 0 ]]; then
  "${RUNNER_ROOT}/scripts/pm99_runner/build_runner_image.sh"
fi

pm99_runner_sync_repo
pm99_runner_ensure_local_artifact_root

REMOTE_RUN_ROOT="${PM99_RUNNER_REMOTE_ROOT}/workspace/runs/${RUN_TAG}"
REMOTE_ARTIFACT_DIR="${PM99_RUNNER_REMOTE_ROOT}/artifacts/${RUN_TAG}"
REMOTE_GAME_DIR="${REMOTE_RUN_ROOT}/premier-manager-ninety-nine"
REMOTE_HOME_DIR="${REMOTE_RUN_ROOT}/home"
REMOTE_WINE_PREFIX_DIR="${REMOTE_RUN_ROOT}/wine-prefix"
REMOTE_LATE_DBDAT_DIR="${REMOTE_RUN_ROOT}/late_dbdat"
LOCAL_ARTIFACT_DIR="${PM99_RUNNER_LOCAL_ARTIFACT_ROOT}/${RUN_TAG}"
pm99_runner_ssh "
set -euo pipefail
rm -rf '${REMOTE_RUN_ROOT}' '${REMOTE_ARTIFACT_DIR}'
mkdir -p '${REMOTE_RUN_ROOT}' '${REMOTE_HOME_DIR}' '${REMOTE_WINE_PREFIX_DIR}' '${REMOTE_ARTIFACT_DIR}' '${REMOTE_LATE_DBDAT_DIR}'
mkdir -p '${REMOTE_GAME_DIR}'
"

if [[ ${FULL_GAME_ROOT_MODE} -eq 1 ]]; then
  "${PM99_RUNNER_RSYNC_BIN}" -az --delete \
    "${GAME_ROOT}/" \
    "$(pm99_runner_remote_spec):${REMOTE_GAME_DIR}/"
else
  pm99_runner_ssh "cp -a '$(pm99_runner_remote_source_install_dir)/.' '${REMOTE_GAME_DIR}/'"
  for file_name in JUG98030.FDI EQ98030.FDI MINIFOTO.PKF; do
    pm99_runner_scp_to_remote \
      "${DBDAT_DIR}/${file_name}" \
      "${REMOTE_GAME_DIR}/DBDAT/${file_name}"
  done
  if [[ ${OVERRIDE_ENT} -eq 1 ]]; then
    pm99_runner_scp_to_remote \
      "${DBDAT_DIR}/ENT98030.FDI" \
      "${REMOTE_GAME_DIR}/DBDAT/ENT98030.FDI"
  fi
  if [[ -n "${EXE_OVERRIDE}" ]]; then
    pm99_runner_scp_to_remote \
      "${EXE_OVERRIDE}" \
      "${REMOTE_GAME_DIR}/MANAGPRE.EXE"
  fi
fi
if [[ -n "${LATE_DBDAT_DIR}" ]]; then
  for file_name in "${LATE_FILE_LIST[@]}"; do
    pm99_runner_scp_to_remote \
      "${LATE_DBDAT_DIR}/${file_name}" \
      "${REMOTE_LATE_DBDAT_DIR}/${file_name}"
  done
fi

DOCKER_LATE_MOUNT_ARGS=()
DRIVER_LATE_ARGS=""
if [[ -n "${LATE_DBDAT_DIR}" ]]; then
  DOCKER_LATE_MOUNT_ARGS=(--volume "${REMOTE_LATE_DBDAT_DIR}:/workspace/late_dbdat")
  DRIVER_LATE_ARGS="--late-dbdat-override-dir /workspace/late_dbdat --late-dbdat-files $(printf '%q' "${LATE_DBDAT_FILES}")"
fi

set +e
pm99_runner_remote_one_shot_container_with_timeout \
  "${PM99_RUNNER_DOCKER_TIMEOUT_SECONDS:-900}" \
  "${RUN_TAG}" \
  "run_stoke_profile_capture_with_dbdat_overrides.sh" \
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
  ${DOCKER_LATE_MOUNT_ARGS[@]} \
  -- python3 /workspace/repo/scripts/pm99_runner/stoke_vanilla_profile_capture_driver.py \
    --game-dir /workspace/game \
    --artifacts-dir /workspace/artifacts \
    --profile-count "${PROFILE_COUNT}" \
    --row-x "${ROW_X}" \
    --row-start-y "${ROW_START_Y}" \
    --row-pitch "${ROW_PITCH}" \
    ${DRIVER_LATE_ARGS}
RUN_STATUS=$?
set -e

set +e
pm99_runner_sync_remote_artifacts "${REMOTE_ARTIFACT_DIR}" "${LOCAL_ARTIFACT_DIR}"
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

if [[ ${SYNC_STATUS} -ne 0 ]]; then
  RUN_STATUS="${SYNC_STATUS}"
elif [[ ${CLEANUP_STATUS} -ne 0 && ${RUN_STATUS} -eq 0 ]]; then
  RUN_STATUS="${CLEANUP_STATUS}"
fi

echo "RUN_TAG=${RUN_TAG}"
echo "RUN_STATUS=${RUN_STATUS}"
echo "LOCAL_ARTIFACT_DIR=${LOCAL_ARTIFACT_DIR}"

exit "${RUN_STATUS}"
