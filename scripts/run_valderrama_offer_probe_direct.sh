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

RUN_TAG="valderrama_offer_probe_$(date -u +%Y%m%dT%H%M%SZ)"
WORKER_NAME="${PM99_RUNNER_WORKER_NAME:-}"
LOCAL_GAME_DIR=""
LOCAL_OVERLAY_DIR=""
LOCAL_ARTIFACT_DIR="${REPO_ROOT}/artifacts/valderrama_offer_probe"
TEAM_SLOT="1"
WINDOW_TIMEOUT="120"
DOCKER_TIMEOUT_SECONDS="${PM99_RUNNER_DOCKER_TIMEOUT_SECONDS:-900}"
KEEP_REMOTE_RUN=0
KEEP_REMOTE_ARTIFACTS=0
CLEANUP_ON_FAILURE=0
OFFER_BATCH_COUNT="${PM99_VALDERRAMA_OFFER_BATCH_COUNT:-0}"
WAGE_BATCH_COUNT="${PM99_VALDERRAMA_WAGE_BATCH_COUNT:-0}"
SUBMIT_OFFER_ACTION="${PM99_VALDERRAMA_SUBMIT_OFFER_ACTION:-native_double_click}"
SUBMIT_OFFER_SPEC="${PM99_VALDERRAMA_SUBMIT_OFFER_SPEC:-427,437,1}"
SUBMIT_OFFER_DELAY="${PM99_VALDERRAMA_SUBMIT_OFFER_DELAY:-3.0}"
CONTINUE_COUNT="${PM99_VALDERRAMA_CONTINUE_COUNT:-4}"
FINAL_INSPECT_MODE="${PM99_VALDERRAMA_FINAL_INSPECT_MODE:-briefcase_and_current_offers}"
CURRENT_OFFER_CLICK_ACTION="${PM99_VALDERRAMA_CURRENT_OFFER_CLICK_ACTION:-native_input_click}"
CURRENT_OFFER_CLICK_SPEC="${PM99_VALDERRAMA_CURRENT_OFFER_CLICK_SPEC:-606,113,1}"
CURRENT_OFFER_CLICK_DELAY="${PM99_VALDERRAMA_CURRENT_OFFER_CLICK_DELAY:-1.5}"
CURRENT_OFFER_POST_ACTION="${PM99_VALDERRAMA_CURRENT_OFFER_POST_ACTION:-}"
CURRENT_OFFER_POST_SPEC="${PM99_VALDERRAMA_CURRENT_OFFER_POST_SPEC:-}"
CURRENT_OFFER_POST_DELAY="${PM99_VALDERRAMA_CURRENT_OFFER_POST_DELAY:-0.8}"
CURRENT_OFFER_INSPECT_DELAYS="${PM99_VALDERRAMA_CURRENT_OFFER_INSPECT_DELAYS:-}"
NEWS_CURRENT_POST_ACTION="${PM99_VALDERRAMA_NEWS_CURRENT_POST_ACTION:-}"
NEWS_CURRENT_POST_SPEC="${PM99_VALDERRAMA_NEWS_CURRENT_POST_SPEC:-}"
NEWS_CURRENT_POST_DELAY="${PM99_VALDERRAMA_NEWS_CURRENT_POST_DELAY:-0.8}"
NEWS_RETURN_POST_ACTION="${PM99_VALDERRAMA_NEWS_RETURN_POST_ACTION:-}"
NEWS_RETURN_POST_SPEC="${PM99_VALDERRAMA_NEWS_RETURN_POST_SPEC:-}"
NEWS_RETURN_POST_DELAY="${PM99_VALDERRAMA_NEWS_RETURN_POST_DELAY:-0.8}"
NEWS_POPUP_POST_ACTION="${PM99_VALDERRAMA_NEWS_POPUP_POST_ACTION:-}"
NEWS_POPUP_POST_SPEC="${PM99_VALDERRAMA_NEWS_POPUP_POST_SPEC:-}"
NEWS_POPUP_POST_DELAY="${PM99_VALDERRAMA_NEWS_POPUP_POST_DELAY:-0.8}"
NEWS_POPUP_CLOSE_POST_ACTION="${PM99_VALDERRAMA_NEWS_POPUP_CLOSE_POST_ACTION:-}"
NEWS_POPUP_CLOSE_POST_SPEC="${PM99_VALDERRAMA_NEWS_POPUP_CLOSE_POST_SPEC:-}"
NEWS_POPUP_CLOSE_POST_DELAY="${PM99_VALDERRAMA_NEWS_POPUP_CLOSE_POST_DELAY:-0.8}"
NEWS_POPUP_CLOSE_INSPECT_DELAYS="${PM99_VALDERRAMA_NEWS_POPUP_CLOSE_INSPECT_DELAYS:-}"
FINAL_PREFLIGHT_ACTION="${PM99_VALDERRAMA_FINAL_PREFLIGHT_ACTION:-}"
FINAL_PREFLIGHT_SPEC="${PM99_VALDERRAMA_FINAL_PREFLIGHT_SPEC:-}"
FINAL_PREFLIGHT_DELAY="${PM99_VALDERRAMA_FINAL_PREFLIGHT_DELAY:-1.0}"
FINAL_PREFLIGHT_INSPECT_DELAY="${PM99_VALDERRAMA_FINAL_PREFLIGHT_INSPECT_DELAY:-0.5}"
AUTO_CONTINUE_CYCLES="${PM99_VALDERRAMA_AUTO_CONTINUE_CYCLES:-0}"
AUTO_DASHBOARD_PROBE_COUNT="${PM99_VALDERRAMA_AUTO_DASHBOARD_PROBE_COUNT:-0}"
AUTO_DASHBOARD_PROBE_DELAY="${PM99_VALDERRAMA_AUTO_DASHBOARD_PROBE_DELAY:-1.0}"
declare -a TICKER_TARGETS=()
declare -a POST_AUTO_STEPS=()
PRE_SUBMIT_STEPS=()

usage() {
  cat <<'USAGE'
Usage: scripts/run_valderrama_offer_probe_direct.sh [options]

Compliant Valderrama offer-path probe using PM99 worker leases and the remote
runner entrypoint.

Options:
  --run-tag <id>              Override the artifact/run tag
  --worker <name>             Select a configured PM99 worker lane
  --local-game-dir <path>     Upload a full local game dir into the remote run root
  --local-overlay-dir <path>  Rsync a local overlay on top of the remote source install
  --local-artifact-dir <path> Local artifact root (default: artifacts/valderrama_offer_probe)
  --team-slot <n>             Premier team slot for the new game (default: 1)
  --window-timeout <sec>      Driver window timeout seconds (default: 120)
  --docker-timeout <sec>      Hard timeout for the container (default: 900)
  --auto-continue-cycles <n>  Let the driver advance dynamically after submit
  --auto-dashboard-probe-count <n> Extra dashboard screenshots per auto-continue visit
  --auto-dashboard-probe-delay <sec> Delay before each extra dashboard probe
  --ticker-target <token>     Normalized token that must appear in ticker OCR
  --post-autocontinue-step <spec>  LABEL|ACTION|VALUE|DELAY step after auto-continue
  --pre-submit-step <spec>        LABEL|ACTION|VALUE|DELAY step before offer submit
  --keep-remote-run           Preserve the remote per-run game/home/prefix directory
  --keep-remote-artifacts     Preserve the remote artifact directory after local mirroring
  --cleanup-on-failure        Clean remote run/artifact state after a failed run once mirroring succeeds
  -h, --help                  Show this help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-tag) RUN_TAG="$2"; shift 2 ;;
    --worker) WORKER_NAME="$2"; shift 2 ;;
    --local-game-dir) LOCAL_GAME_DIR="$2"; shift 2 ;;
    --local-overlay-dir) LOCAL_OVERLAY_DIR="$2"; shift 2 ;;
    --local-artifact-dir) LOCAL_ARTIFACT_DIR="$2"; shift 2 ;;
    --team-slot) TEAM_SLOT="$2"; shift 2 ;;
    --window-timeout) WINDOW_TIMEOUT="$2"; shift 2 ;;
    --docker-timeout) DOCKER_TIMEOUT_SECONDS="$2"; shift 2 ;;
    --auto-continue-cycles) AUTO_CONTINUE_CYCLES="$2"; shift 2 ;;
    --auto-dashboard-probe-count) AUTO_DASHBOARD_PROBE_COUNT="$2"; shift 2 ;;
    --auto-dashboard-probe-delay) AUTO_DASHBOARD_PROBE_DELAY="$2"; shift 2 ;;
    --ticker-target) TICKER_TARGETS+=("$2"); shift 2 ;;
    --post-autocontinue-step) POST_AUTO_STEPS+=("$2"); shift 2 ;;
    --pre-submit-step) PRE_SUBMIT_STEPS+=("$2"); shift 2 ;;
    --keep-remote-run) KEEP_REMOTE_RUN=1; shift ;;
    --keep-remote-artifacts) KEEP_REMOTE_ARTIFACTS=1; shift ;;
    --cleanup-on-failure) CLEANUP_ON_FAILURE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "${LOCAL_GAME_DIR}" && -z "${LOCAL_OVERLAY_DIR}" ]]; then
  echo "One of --local-game-dir or --local-overlay-dir is required" >&2
  exit 2
fi
if [[ -n "${LOCAL_GAME_DIR}" && ! -d "${LOCAL_GAME_DIR}" ]]; then
  echo "Missing local game dir: ${LOCAL_GAME_DIR}" >&2
  exit 2
fi
if [[ -n "${LOCAL_OVERLAY_DIR}" && ! -d "${LOCAL_OVERLAY_DIR}" ]]; then
  echo "Missing local overlay dir: ${LOCAL_OVERLAY_DIR}" >&2
  exit 2
fi

pm99_runner_select_remote_worker "${WORKER_NAME:-}"
PM99_RUNNER_HOST_LOCK_CONCURRENCY="${PM99_RUNNER_WORKER_LANE_COUNT}"
pm99_runner_require_cmd "${PM99_RUNNER_SSH_BIN}"
pm99_runner_require_cmd "${PM99_RUNNER_RSYNC_BIN}"
pm99_runner_require_editor_root
pm99_runner_ensure_local_artifact_root

pm99_runner_acquire_remote_host_lock "run_valderrama_offer_probe_direct:${RUN_TAG}"
trap 'pm99_runner_release_remote_host_lock' EXIT

pm99_runner_sync_repo

REMOTE_RUN_ROOT="$(pm99_runner_remote_run_root "${RUN_TAG}")"
REMOTE_ARTIFACT_DIR="${PM99_RUNNER_REMOTE_ROOT}/artifacts/${RUN_TAG}"
LOCAL_FINAL_ARTIFACT_DIR="${LOCAL_ARTIFACT_DIR}/${RUN_TAG}"
REMOTE_GAME_DIR="$(pm99_runner_remote_game_dir "${REMOTE_RUN_ROOT}")"
REMOTE_HOME_DIR="$(pm99_runner_remote_home_dir "${REMOTE_RUN_ROOT}")"
REMOTE_WINE_PREFIX_DIR="$(pm99_runner_remote_wine_prefix_dir "${REMOTE_RUN_ROOT}")"

pm99_runner_prepare_remote_run_root "${REMOTE_RUN_ROOT}" "${REMOTE_ARTIFACT_DIR}"

if [[ -n "${LOCAL_GAME_DIR}" ]]; then
  "${PM99_RUNNER_RSYNC_BIN}" -az --delete \
    "${LOCAL_GAME_DIR}/" "$(pm99_runner_remote_spec):${REMOTE_GAME_DIR}/"
fi

if [[ -n "${LOCAL_OVERLAY_DIR}" ]]; then
  "${PM99_RUNNER_RSYNC_BIN}" -az \
    "${LOCAL_OVERLAY_DIR}/" "$(pm99_runner_remote_spec):${REMOTE_GAME_DIR}/"
fi

driver_args=(
  python3
  /workspace/repo/scripts/pm99_runner/premier_offer_capture_driver.py
  --game-dir /workspace/game
  --artifacts-dir /workspace/artifacts
  --window-timeout "${WINDOW_TIMEOUT}"
  --team-slot "${TEAM_SLOT}"
  --skip-team-probe-ocr
  --success-mode final_step
  --post-step 'continue_retry|native_input_click|561,442,1|8.0'
  --post-step 'select_transfers|native_input_click|223,318,1|1.0'
  --post-step 'open_transfers|native_double_click|223,318,1|6.0'
  --post-step 'return_to_transfers|native_input_click|573,466,1|2.5'
  --post-step 'open_offers_button|native_double_click|564,372,1|2.5'
  --post-step 'open_player_name_search|native_input_click|565,360,1|2.5'
  --post-step 'focus_search_name_field|native_input_click|238,141,1|0.8'
  --post-step 'name_V|native_key|V|0.1'
  --post-step 'name_A1|native_key|A|0.1'
  --post-step 'name_L|native_key|L|0.1'
  --post-step 'name_D|native_key|D|0.1'
  --post-step 'name_E|native_key|E|0.1'
  --post-step 'name_R1|native_key|R|0.1'
  --post-step 'name_R2|native_key|R|0.1'
  --post-step 'name_A2|native_key|A|0.1'
  --post-step 'name_M|native_key|M|0.1'
  --post-step 'name_A3|native_key|A|0.4'
  --post-step 'submit_valderrama_search|native_double_click|486,142,1|3.5'
  --post-step 'select_valderrama_row|native_input_click|120,166,1|1.0'
  --post-step 'open_valderrama_row|native_input_key|Return|5.0'
  --post-step 'inspect_valderrama_profile|native_inspect|ignored|0.5'
  --post-step 'click_contract_header|native_input_click|520,42,1|2.0'
)

for i in $(seq 1 "${OFFER_BATCH_COUNT}"); do
  driver_args+=(--post-step "offer_batch_$(printf '%02d' "${i}")|native_input_click_repeat|221,279,1,10|1.0")
done

driver_args+=(--post-step 'inspect_offer_target|native_inspect|ignored|0.5')

for i in $(seq 1 "${WAGE_BATCH_COUNT}"); do
  driver_args+=(--post-step "wage_batch_$(printf '%02d' "${i}")|native_input_click_repeat|213,337,1,10|1.0")
done

for pre_submit_step in "${PRE_SUBMIT_STEPS[@]}"; do
  driver_args+=(--post-step "${pre_submit_step}")
done

driver_args+=(
  --post-step 'inspect_ready_to_submit|native_inspect|ignored|0.5'
  --post-step "submit_offer|${SUBMIT_OFFER_ACTION}|${SUBMIT_OFFER_SPEC}|${SUBMIT_OFFER_DELAY}"
  --post-step 'inspect_post_submit|native_inspect|ignored|0.5'
  --post-step 'close_contract_offer_pane|native_input_click|573,460,1|1.2'
  --post-step 'inspect_after_close_contract_offer_pane|native_inspect|ignored|0.5'
  --post-step 'close_contract_offer_pane_retry|native_input_click|573,460,1|1.2'
  --post-step 'inspect_offers_after_submit|native_inspect|ignored|0.5'
  --post-step 'return_from_offers_to_dashboard_primary|native_input_click|561,442,1|1.8'
  --post-step 'inspect_after_return_from_offers_to_dashboard_primary|native_inspect|ignored|0.5'
  --post-step 'return_from_offers_to_dashboard_secondary|native_input_click|573,460,1|1.2'
  --post-step 'inspect_after_return_from_offers_to_dashboard_secondary|native_inspect|ignored|0.5'
  --post-step 'return_from_offers_to_dashboard_return_key|native_key|Return|1.0'
  --post-step 'leave_transfer_market_to_dashboard_primary|native_input_click|573,460,1|1.2'
  --post-step 'inspect_after_leave_transfer_market_to_dashboard_primary|native_inspect|ignored|0.5'
  --post-step 'leave_transfer_market_to_dashboard_secondary|native_input_click|573,460,1|1.2'
  --post-step 'inspect_after_leave_transfer_market_to_dashboard_secondary|native_inspect|ignored|0.5'
  --post-step 'leave_transfer_market_to_dashboard_text|native_input_click|598,455,1|1.2'
  --post-step 'inspect_after_leave_transfer_market_to_dashboard_text|native_inspect|ignored|0.5'
  --post-step 'inspect_dashboard_before_continue|native_inspect|ignored|0.5'
)

if [[ "${AUTO_CONTINUE_CYCLES}" != "0" ]]; then
  driver_args+=(--auto-continue-cycles "${AUTO_CONTINUE_CYCLES}")
fi
if [[ "${AUTO_DASHBOARD_PROBE_COUNT}" != "0" ]]; then
  driver_args+=(--auto-dashboard-probe-count "${AUTO_DASHBOARD_PROBE_COUNT}")
  driver_args+=(--auto-dashboard-probe-delay "${AUTO_DASHBOARD_PROBE_DELAY}")
fi
for ticker_target in "${TICKER_TARGETS[@]}"; do
  driver_args+=(--ticker-target "${ticker_target}")
done
for post_auto_step in "${POST_AUTO_STEPS[@]}"; do
  driver_args+=(--post-autocontinue-step "${post_auto_step}")
done

for i in $(seq 1 "${CONTINUE_COUNT}"); do
  cycle="$(printf '%02d' "${i}")"
  driver_args+=(--post-step "advance_${cycle}_startseason|native_input_click|594,427,1|1.2")
  driver_args+=(--post-step "inspect_advance_${cycle}_startseason|native_inspect|ignored|0.5")
  driver_args+=(--post-step "advance_${cycle}_pmshield_ok|native_input_click|95,355,1|1.0")
  driver_args+=(--post-step "inspect_advance_${cycle}_pmshield_ok|native_inspect|ignored|0.5")
  driver_args+=(--post-step "advance_${cycle}_lineup_warning_ok|native_input_click|401,269,1|1.0")
  driver_args+=(--post-step "inspect_advance_${cycle}_lineup_warning_ok|native_inspect|ignored|0.5")
  driver_args+=(--post-step "advance_${cycle}_match_options|native_input_click|512,453,1|1.2")
  driver_args+=(--post-step "inspect_advance_${cycle}_match_options|native_inspect|ignored|0.5")
  driver_args+=(--post-step "advance_${cycle}_match_intro|native_input_click|552,452,1|1.2")
  driver_args+=(--post-step "inspect_advance_${cycle}_match_intro|native_inspect|ignored|0.5")
  driver_args+=(--post-step "advance_${cycle}_dashboard|native_input_click|582,459,1|1.4")
  driver_args+=(--post-step "inspect_advance_${cycle}_dashboard|native_inspect|ignored|0.5")
  driver_args+=(--post-step "advance_${cycle}_return|native_key|Return|1.0")
  driver_args+=(--post-step "inspect_continue_${cycle}|native_inspect|ignored|0.5")
done

if [[ -n "${FINAL_PREFLIGHT_ACTION}" && -n "${FINAL_PREFLIGHT_SPEC}" ]]; then
  driver_args+=(--post-step "post_continue_final_preflight|${FINAL_PREFLIGHT_ACTION}|${FINAL_PREFLIGHT_SPEC}|${FINAL_PREFLIGHT_DELAY}")
  driver_args+=(--post-step "post_continue_inspect_final_preflight|native_inspect|ignored|${FINAL_PREFLIGHT_INSPECT_DELAY}")
fi

case "${FINAL_INSPECT_MODE}" in
  none)
    ;;
  briefcase_and_current_offers)
    driver_args+=(
      --post-step 'prefinal_startseason_continue|native_input_click|594,427,1|1.2'
      --post-step 'prefinal_inspect_startseason_continue|native_inspect|ignored|0.5'
      --post-step 'prefinal_pmshield_ok|native_input_click|95,355,1|1.0'
      --post-step 'prefinal_inspect_pmshield_ok|native_inspect|ignored|0.5'
      --post-step 'prefinal_lineup_warning_ok|native_input_click|401,299,1|1.0'
      --post-step 'prefinal_inspect_lineup_warning_ok|native_inspect|ignored|0.5'
      --post-step 'prefinal_match_options_continue|native_input_click|512,453,1|1.2'
      --post-step 'prefinal_inspect_match_options_continue|native_inspect|ignored|0.5'
      --post-step 'prefinal_match_intro_continue|native_input_click|552,452,1|1.2'
      --post-step 'prefinal_inspect_match_intro_continue|native_inspect|ignored|0.5'
      --post-step 'prefinal_dashboard_continue|native_input_click|582,459,1|1.4'
      --post-step 'prefinal_inspect_dashboard_continue|native_inspect|ignored|0.5'
      --post-step 'prefinal_return_key|native_key|Return|1.0'
      --post-step 'prefinal_inspect_return_key|native_inspect|ignored|0.5'
      --post-step 'post_continue_lineup_warning_ok|native_input_click|401,299,1|1.0'
      --post-step 'post_continue_inspect_lineup_warning_ok|native_inspect|ignored|0.5'
      --post-step 'post_continue_open_briefcase|native_input_click|564,260,1|2.5'
      --post-step 'post_continue_inspect_briefcase|native_inspect|ignored|0.5'
      --post-step 'post_continue_return_from_briefcase|native_input_click|573,460,1|1.0'
      --post-step 'post_continue_open_current_offers|native_input_click|564,296,1|2.5'
      --post-step 'post_continue_inspect_current_offers|native_inspect|ignored|0.5'
      --post-step "post_continue_click_current_offer_top|${CURRENT_OFFER_CLICK_ACTION}|${CURRENT_OFFER_CLICK_SPEC}|${CURRENT_OFFER_CLICK_DELAY}"
      --post-step 'post_continue_inspect_current_offer_top|native_inspect|ignored|0.5'
    )
    if [[ -n "${CURRENT_OFFER_POST_ACTION}" && -n "${CURRENT_OFFER_POST_SPEC}" ]]; then
      driver_args+=(--post-step "post_continue_current_offer_followup|${CURRENT_OFFER_POST_ACTION}|${CURRENT_OFFER_POST_SPEC}|${CURRENT_OFFER_POST_DELAY}")
    fi
    if [[ -n "${CURRENT_OFFER_INSPECT_DELAYS}" ]]; then
      IFS=',' read -r -a current_offer_inspect_delays <<< "${CURRENT_OFFER_INSPECT_DELAYS}"
      for index in "${!current_offer_inspect_delays[@]}"; do
        inspect_delay="${current_offer_inspect_delays[$index]}"
        driver_args+=(--post-step "post_continue_current_offer_inspect_$(printf '%02d' $((index + 1)))|native_inspect|ignored|${inspect_delay}")
      done
    fi
    ;;
  news_surface)
    driver_args+=(
      --post-step 'post_continue_open_news|native_input_click|442,459,1|2.5'
      --post-step 'post_continue_inspect_news|native_inspect|ignored|0.5'
      --post-step 'post_continue_open_news_second_div|native_input_click|509,248,1|1.2'
      --post-step 'post_continue_inspect_news_second_div|native_inspect|ignored|0.5'
      --post-step 'post_continue_open_news_last|native_input_click|171,447,1|1.0'
      --post-step 'post_continue_inspect_news_last|native_inspect|ignored|0.5'
      --post-step 'post_continue_open_news_current|native_input_click|221,447,1|1.0'
      --post-step 'post_continue_inspect_news_current|native_inspect|ignored|0.5'
    )
    if [[ -n "${NEWS_CURRENT_POST_ACTION}" && -n "${NEWS_CURRENT_POST_SPEC}" ]]; then
      driver_args+=(--post-step "post_continue_news_current_followup|${NEWS_CURRENT_POST_ACTION}|${NEWS_CURRENT_POST_SPEC}|${NEWS_CURRENT_POST_DELAY}")
    fi
    if [[ -n "${NEWS_RETURN_POST_ACTION}" && -n "${NEWS_RETURN_POST_SPEC}" ]]; then
      driver_args+=(--post-step "post_continue_news_return_followup|${NEWS_RETURN_POST_ACTION}|${NEWS_RETURN_POST_SPEC}|${NEWS_RETURN_POST_DELAY}")
    fi
    if [[ -n "${NEWS_POPUP_POST_ACTION}" && -n "${NEWS_POPUP_POST_SPEC}" ]]; then
      driver_args+=(--post-step "post_continue_news_popup_followup|${NEWS_POPUP_POST_ACTION}|${NEWS_POPUP_POST_SPEC}|${NEWS_POPUP_POST_DELAY}")
    fi
    if [[ -n "${NEWS_POPUP_CLOSE_POST_ACTION}" && -n "${NEWS_POPUP_CLOSE_POST_SPEC}" ]]; then
      driver_args+=(--post-step "post_continue_news_popup_close|${NEWS_POPUP_CLOSE_POST_ACTION}|${NEWS_POPUP_CLOSE_POST_SPEC}|${NEWS_POPUP_CLOSE_POST_DELAY}")
    fi
    if [[ -n "${NEWS_POPUP_CLOSE_INSPECT_DELAYS}" ]]; then
      IFS=',' read -r -a news_popup_close_inspect_delays <<< "${NEWS_POPUP_CLOSE_INSPECT_DELAYS}"
      for index in "${!news_popup_close_inspect_delays[@]}"; do
        inspect_delay="${news_popup_close_inspect_delays[$index]}"
        driver_args+=(--post-step "post_continue_news_popup_close_inspect_$(printf '%02d' $((index + 1)))|native_inspect|ignored|${inspect_delay}")
      done
    fi
    ;;
  *)
    echo "Unsupported FINAL_INSPECT_MODE=${FINAL_INSPECT_MODE}" >&2
    exit 2
    ;;
esac

set +e
pm99_runner_remote_one_shot_container_with_timeout \
  "${DOCKER_TIMEOUT_SECONDS}" \
  "${RUN_TAG}" \
  "run_valderrama_offer_probe_direct.sh" \
  "pm99-agent-${RUN_TAG}" \
  "${REMOTE_ARTIFACT_DIR}" \
  --image "${PM99_RUNNER_REMOTE_IMAGE}" \
  --user CURRENT_USER \
  --workdir /workspace/repo \
  --shm-size 2g \
  --env HOME=/workspace/home \
  --env PM99_EDITOR_ROOT=/workspace/editor \
  --env PYTHONPATH=/workspace/repo:/workspace/editor \
  --env WINEPREFIX=/workspace/wine-prefix \
  --env CURRENT_OFFER_CLICK_ACTION=${CURRENT_OFFER_CLICK_ACTION:-} \
  --env CURRENT_OFFER_CLICK_SPEC=${CURRENT_OFFER_CLICK_SPEC:-} \
  --env CURRENT_OFFER_CLICK_DELAY=${CURRENT_OFFER_CLICK_DELAY:-} \
  --env CURRENT_OFFER_POST_ACTION=${CURRENT_OFFER_POST_ACTION:-} \
  --env CURRENT_OFFER_POST_SPEC=${CURRENT_OFFER_POST_SPEC:-} \
  --env CURRENT_OFFER_POST_DELAY=${CURRENT_OFFER_POST_DELAY:-} \
  --env CURRENT_OFFER_INSPECT_DELAYS=${CURRENT_OFFER_INSPECT_DELAYS:-} \
  --env NEWS_POPUP_CLOSE_INSPECT_DELAYS=${NEWS_POPUP_CLOSE_INSPECT_DELAYS:-} \
  --env FINAL_PREFLIGHT_ACTION=${FINAL_PREFLIGHT_ACTION:-} \
  --env FINAL_PREFLIGHT_SPEC=${FINAL_PREFLIGHT_SPEC:-} \
  --env FINAL_PREFLIGHT_DELAY=${FINAL_PREFLIGHT_DELAY:-} \
  --env FINAL_PREFLIGHT_INSPECT_DELAY=${FINAL_PREFLIGHT_INSPECT_DELAY:-} \
  --env PM99_RUNNER_SKIP_CLASSIFICATION=${PM99_RUNNER_SKIP_CLASSIFICATION:-} \
  --env PM99_OCR_TIMEOUT_SECONDS=${PM99_OCR_TIMEOUT_SECONDS:-} \
  --env PM99_RUNNER_SKIP_WINDOW_DEBUG=${PM99_RUNNER_SKIP_WINDOW_DEBUG:-} \
  --volume "${PM99_RUNNER_REMOTE_REPO_DIR}:/workspace/repo" \
  --volume "${PM99_RUNNER_REMOTE_EDITOR_REPO_DIR}:/workspace/editor" \
  --volume "${REMOTE_WINE_PREFIX_DIR}:/workspace/wine-prefix" \
  --volume "${REMOTE_HOME_DIR}:/workspace/home" \
  --volume "${REMOTE_GAME_DIR}:/workspace/game" \
  --volume "${REMOTE_ARTIFACT_DIR}:/workspace/artifacts" \
  -- "${driver_args[@]}"
RUN_STATUS=$?
set -e

set +e
pm99_runner_sync_remote_artifacts "${REMOTE_ARTIFACT_DIR}" "${LOCAL_FINAL_ARTIFACT_DIR}"
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

echo
echo "Valderrama offer probe artifacts:"
echo "  remote: ${REMOTE_ARTIFACT_DIR}"
echo "  local:  ${LOCAL_FINAL_ARTIFACT_DIR}"
echo "  run_status=${RUN_STATUS}"
echo "  sync_status=${SYNC_STATUS}"
echo "  cleanup_status=${CLEANUP_STATUS}"

if [[ ${SYNC_STATUS} -ne 0 ]]; then
  exit "${SYNC_STATUS}"
fi
if [[ ${CLEANUP_STATUS} -ne 0 && ${RUN_STATUS} -eq 0 ]]; then
  exit "${CLEANUP_STATUS}"
fi
exit "${RUN_STATUS}"
