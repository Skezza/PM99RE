#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER_ROOT="${ROOT_DIR}/upstream/pm99-runner"
export PM99_RUNNER_HOST_LOCK_NAME="${PM99_RUNNER_HOST_LOCK_NAME:-runner-host}"
source "${RUNNER_ROOT}/scripts/pm99_runner/common.sh"

RUN_TAG="pm99_2025_roster_visual_sample_$(pm99_runner_timestamp_utc)"
GAME_ROOT="${ROOT_DIR}/work/pm99/codex_2025_roster/pm99_2025_roster_top80_world_ready_20260424T230207Z/game"
WORLD_STATE="${ROOT_DIR}/.local/pm99_2025_roster_world/world_2025_top80.json"
SELECTOR_MAP="${ROOT_DIR}/.local/selector_maps/pm99_vanilla_english_80_selector_map.json"
PROFILE_COUNT=2
SKIP_SETUP=0
SKIP_BUILD=0
KEEP_REMOTE_RUN=0
KEEP_REMOTE_ARTIFACTS=0
CLEANUP_ON_FAILURE=0
SQUAD_ENABLE_STATUS_FILTERS=0
SQUAD_SCROLL_PROOF_PAGES=0
SQUAD_SCROLL_CLICKS=6
SQUAD_CAPTURE_YOUTH_TEAM=0
declare -a CLUB_KEYS=(
  arsenal
  liverpool
  manchester_city
  manchester_united
  stoke_city
  queens_park_rangers
  cardiff_city
  port_vale
  wycombe_wanderers
)
declare -a CAPTURE_ROUTES=(squad line_up)

usage() {
  cat <<'EOF'
Usage: ./scripts/run_2025_roster_visual_sample.sh [options]

Copy the final isolated 2025 roster game to the PM99 runner, open selected
clubs through the new-game selector, and capture visual squad/line-up evidence.

Options:
  --game-root <path>       Isolated patched PM99 game root
  --world-state <path>     World-state JSON used to resolve club rows
  --selector-map <path>    Selector map JSON used to resolve click coordinates
  --run-tag <id>           Override artifact tag
  --club-key <key>         Repeatable club key; replaces the default sample list
  --capture-route <route>  Repeatable route; replaces default squad,line_up
  --profile-count <n>      Player profile captures per squad route (default: 2)
  --skip-setup             Skip remote host bootstrap/sync prerequisites
  --skip-build             Skip docker image build
  --keep-remote-run        Preserve remote per-run workspace
  --keep-remote-artifacts  Preserve remote artifacts after mirroring
  --cleanup-on-failure     Clean remote state after failed run once mirrored
  --squad-enable-status-filters
                           Tick squad status filters before squad proof screenshots
  --squad-scroll-proof-pages <n>
                           Capture additional squad screenshots after scrolling down
  --squad-scroll-clicks <n> Number of down-arrow clicks per scroll proof page
  --squad-capture-youth-team
                           Click and capture the squad screen's Youth Team view
  -h, --help               Show this help
EOF
  echo
  pm99_runner_usage_common
}

CUSTOM_CLUBS=0
CUSTOM_ROUTES=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --game-root) GAME_ROOT="$2"; shift 2 ;;
    --world-state) WORLD_STATE="$2"; shift 2 ;;
    --selector-map) SELECTOR_MAP="$2"; shift 2 ;;
    --run-tag) RUN_TAG="$2"; shift 2 ;;
    --club-key)
      if [[ ${CUSTOM_CLUBS} -eq 0 ]]; then
        CLUB_KEYS=()
        CUSTOM_CLUBS=1
      fi
      CLUB_KEYS+=("$2")
      shift 2
      ;;
    --capture-route)
      if [[ ${CUSTOM_ROUTES} -eq 0 ]]; then
        CAPTURE_ROUTES=()
        CUSTOM_ROUTES=1
      fi
      CAPTURE_ROUTES+=("$2")
      shift 2
      ;;
    --profile-count) PROFILE_COUNT="$2"; shift 2 ;;
    --skip-setup) SKIP_SETUP=1; shift ;;
    --skip-build) SKIP_BUILD=1; shift ;;
    --keep-remote-run) KEEP_REMOTE_RUN=1; shift ;;
    --keep-remote-artifacts) KEEP_REMOTE_ARTIFACTS=1; shift ;;
    --cleanup-on-failure) CLEANUP_ON_FAILURE=1; shift ;;
    --squad-enable-status-filters) SQUAD_ENABLE_STATUS_FILTERS=1; shift ;;
    --squad-scroll-proof-pages) SQUAD_SCROLL_PROOF_PAGES="$2"; shift 2 ;;
    --squad-scroll-clicks) SQUAD_SCROLL_CLICKS="$2"; shift 2 ;;
    --squad-capture-youth-team) SQUAD_CAPTURE_YOUTH_TEAM=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

GAME_ROOT="$(cd "${GAME_ROOT}" && pwd)"
WORLD_STATE="$(cd "$(dirname "${WORLD_STATE}")" && pwd)/$(basename "${WORLD_STATE}")"
SELECTOR_MAP="$(cd "$(dirname "${SELECTOR_MAP}")" && pwd)/$(basename "${SELECTOR_MAP}")"

python3 "${ROOT_DIR}/scripts/assert_pm99_isolated_input.py" --game-root "${GAME_ROOT}" >/dev/null
if [[ ! -f "${WORLD_STATE}" ]]; then
  echo "Missing world-state: ${WORLD_STATE}" >&2
  exit 2
fi
if [[ ! -f "${SELECTOR_MAP}" ]]; then
  echo "Missing selector-map: ${SELECTOR_MAP}" >&2
  exit 2
fi
if [[ ${#CLUB_KEYS[@]} -eq 0 ]]; then
  echo "At least one --club-key is required" >&2
  exit 2
fi
if [[ ${#CAPTURE_ROUTES[@]} -eq 0 ]]; then
  echo "At least one --capture-route is required" >&2
  exit 2
fi

pm99_runner_require_cmd "${PM99_RUNNER_SSH_BIN}"
pm99_runner_require_cmd "${PM99_RUNNER_RSYNC_BIN}"
pm99_runner_require_editor_root
pm99_runner_select_remote_worker "${PM99_RUNNER_WORKER_NAME:-default}"
if [[ -z "${PM99_RUNNER_HOST_LOCK_CONCURRENCY_CONFIGURED}" ]]; then
  PM99_RUNNER_HOST_LOCK_CONCURRENCY="${PM99_RUNNER_WORKER_LANE_COUNT}"
fi
pm99_runner_acquire_remote_host_lock "run_2025_roster_visual_sample:${RUN_TAG}"
trap 'pm99_runner_release_remote_host_lock' EXIT

if [[ ${SKIP_SETUP} -eq 0 ]]; then
  "${RUNNER_ROOT}/scripts/pm99_runner/setup_remote_host.sh"
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
LOCAL_ARTIFACT_DIR="${PM99_RUNNER_LOCAL_ARTIFACT_ROOT}/${RUN_TAG}"

pm99_runner_ssh "
set -euo pipefail
rm -rf '${REMOTE_RUN_ROOT}' '${REMOTE_ARTIFACT_DIR}'
mkdir -p '${REMOTE_GAME_DIR}' '${REMOTE_HOME_DIR}' '${REMOTE_WINE_PREFIX_DIR}' '${REMOTE_ARTIFACT_DIR}'
"
"${PM99_RUNNER_RSYNC_BIN}" -az --delete \
  --exclude='DBDAT/*.backup*' \
  --exclude='DBDAT/*backup*' \
  "${GAME_ROOT}/" \
  "$(pm99_runner_remote_spec):${REMOTE_GAME_DIR}/"

rm -rf "${LOCAL_ARTIFACT_DIR}"
mkdir -p "${LOCAL_ARTIFACT_DIR}"
printf '%s\n' "${CLUB_KEYS[@]}" > "${LOCAL_ARTIFACT_DIR}/requested_clubs.txt"
printf '%s\n' "${CAPTURE_ROUTES[@]}" > "${LOCAL_ARTIFACT_DIR}/requested_routes.txt"

CASE_TSV="${LOCAL_ARTIFACT_DIR}/visual_cases.tsv"
python3 - "${WORLD_STATE}" "${SELECTOR_MAP}" "${CASE_TSV}" "${CLUB_KEYS[@]}" <<'PY'
from __future__ import annotations
import json
import sys
from pathlib import Path

world_path = Path(sys.argv[1])
selector_path = Path(sys.argv[2])
output_path = Path(sys.argv[3])
requested = list(sys.argv[4:])

world = json.loads(world_path.read_text(encoding="utf-8"))
selector_payload = json.loads(selector_path.read_text(encoding="utf-8"))
selectors = {
    str(item.get("club_key") or "").strip(): item
    for item in selector_payload.get("selectors", [])
    if isinstance(item, dict) and str(item.get("club_key") or "").strip()
}
clubs = {
    str(item.get("club_key") or "").strip(): item
    for item in world.get("clubs", [])
    if isinstance(item, dict) and str(item.get("club_key") or "").strip()
}

rows: list[str] = []
missing: list[str] = []
for key in requested:
    club = clubs.get(key)
    selector = selectors.get(key) or club
    if club is None:
        missing.append(key)
        continue
    values = {
        "team_select_x": selector.get("team_select_x"),
        "team_select_y": selector.get("team_select_y"),
        "division_select_x": selector.get("division_select_x"),
        "division_select_y": selector.get("division_select_y"),
    }
    if any(value in (None, "") for value in values.values()):
        missing.append(key)
        continue
    rows.append(
        "\t".join(
            [
                key,
                str(club.get("target_display_name") or club.get("set_name") or club.get("team_name") or key),
                str(club.get("team_query") or club.get("team_name") or club.get("set_name") or key),
                str(int(values["team_select_x"])),
                str(int(values["team_select_y"])),
                str(int(values["division_select_x"])),
                str(int(values["division_select_y"])),
            ]
        )
    )
if missing:
    raise SystemExit("Missing visual selectors for: " + ", ".join(missing))
output_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
print(json.dumps({"cases": len(rows), "output": str(output_path)}, indent=2))
PY

RUN_STATUS=0
mkdir -p "${LOCAL_ARTIFACT_DIR}/club_status"
while IFS=$'\t' read -r -u 3 CLUB_KEY SET_NAME TEAM_QUERY TEAM_SELECT_X TEAM_SELECT_Y DIVISION_SELECT_X DIVISION_SELECT_Y; do
  [[ -n "${CLUB_KEY}" ]] || continue
  SAFE_CLUB_KEY="$(printf '%s' "${CLUB_KEY}" | tr -c 'A-Za-z0-9_' '_')"
  CHILD_TAG="${RUN_TAG}_${SAFE_CLUB_KEY}"
  CHILD_REMOTE_ARTIFACT_DIR="${REMOTE_ARTIFACT_DIR}/clubs/${SAFE_CLUB_KEY}"
  ROUTE_ARGS=()
  for route_name in "${CAPTURE_ROUTES[@]}"; do
    ROUTE_ARGS+=(--capture-route "${route_name}")
  done
  SQUAD_FILTER_ARGS=()
  if [[ ${SQUAD_ENABLE_STATUS_FILTERS} -eq 1 ]]; then
    SQUAD_FILTER_ARGS+=(--squad-enable-status-filters)
  fi
  if [[ ${SQUAD_SCROLL_PROOF_PAGES} -gt 0 ]]; then
    SQUAD_FILTER_ARGS+=(--squad-scroll-proof-pages "${SQUAD_SCROLL_PROOF_PAGES}" --squad-scroll-clicks "${SQUAD_SCROLL_CLICKS}")
  fi
  if [[ ${SQUAD_CAPTURE_YOUTH_TEAM} -eq 1 ]]; then
    SQUAD_FILTER_ARGS+=(--squad-capture-youth-team)
  fi
  set +e
  pm99_runner_remote_one_shot_container_with_timeout \
    "${PM99_RUNNER_DOCKER_TIMEOUT_SECONDS:-900}" \
    "${CHILD_TAG}" \
    "run_2025_roster_visual_sample.sh" \
    "pm99-agent-${CHILD_TAG}" \
    "${CHILD_REMOTE_ARTIFACT_DIR}" \
    --image "${PM99_RUNNER_REMOTE_IMAGE}" \
    --user CURRENT_USER \
    --workdir /workspace/repo \
    --shm-size 2g \
    --env HOME=/workspace/home \
    --env PM99_EDITOR_ROOT=/workspace/editor \
    --env PM99_RUNNER_FAST_OCR="${PM99_RUNNER_FAST_OCR:-}" \
    --env PM99_RUNNER_SKIP_CLASSIFICATION="${PM99_RUNNER_SKIP_CLASSIFICATION:-}" \
    --env PYTHONPATH=/workspace/repo:/workspace/editor \
    --env WINEPREFIX=/workspace/wine-prefix \
    --volume "${PM99_RUNNER_REMOTE_REPO_DIR}:/workspace/repo" \
    --volume "${PM99_RUNNER_REMOTE_EDITOR_REPO_DIR}:/workspace/editor" \
    --volume "${REMOTE_WINE_PREFIX_DIR}:/workspace/wine-prefix" \
    --volume "${REMOTE_HOME_DIR}:/workspace/home" \
    --volume "${REMOTE_GAME_DIR}:/workspace/game" \
    --volume "${REMOTE_ARTIFACT_DIR}:/workspace/artifacts" \
    -- python3 /workspace/repo/scripts/pm99_runner/stoke_season_driver.py \
      --game-dir /workspace/game \
      --artifacts-dir "/workspace/artifacts/clubs/${SAFE_CLUB_KEY}" \
      --proof-mode generic_club_route_capture \
      --manager-name "AI" \
      --team-name "${TEAM_QUERY}" \
      --team-select-x "${TEAM_SELECT_X}" \
      --team-select-y "${TEAM_SELECT_Y}" \
      --division-select-x "${DIVISION_SELECT_X}" \
      --division-select-y "${DIVISION_SELECT_Y}" \
      --capture-routes-only \
      "${ROUTE_ARGS[@]}" \
      "${SQUAD_FILTER_ARGS[@]}" \
      --profile-count "${PROFILE_COUNT}" \
      --row-pitch 15
  CHILD_STATUS=$?
  set -e
  printf '%s\n' "${CHILD_STATUS}" > "${LOCAL_ARTIFACT_DIR}/club_status/${SAFE_CLUB_KEY}.status"
  if [[ ${CHILD_STATUS} -ne 0 ]]; then
    RUN_STATUS=1
  fi
done 3< "${CASE_TSV}"

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

python3 - "${LOCAL_ARTIFACT_DIR}" "${RUN_STATUS}" "${SYNC_STATUS}" "${CLEANUP_STATUS}" <<'PY'
from __future__ import annotations
import json
import sys
from pathlib import Path

try:
    from PIL import Image, ImageStat
except Exception:  # pragma: no cover - optional runtime evidence hardening
    Image = None  # type: ignore[assignment]
    ImageStat = None  # type: ignore[assignment]


def _ratio(pixels, predicate):
    return sum(1 for pixel in pixels if predicate(pixel)) / max(1, len(pixels))


def _looks_like_application_cannot_continue(path: Path) -> bool:
    if Image is None or ImageStat is None or not path.is_file():
        return False
    try:
        image = Image.open(path).convert("RGB")
    except Exception:
        return False
    if image.width < 445 or image.height < 290:
        return False
    title = list(image.crop((202, 179, 438, 204)).getdata())
    icon = list(image.crop((214, 210, 250, 246)).getdata())
    panel = image.crop((203, 205, 437, 284))
    text = list(image.crop((255, 215, 425, 235)).getdata())

    title_dark = _ratio(title, lambda rgb: rgb[0] < 80 and rgb[1] < 80 and rgb[2] < 80)
    warning_orange = _ratio(icon, lambda rgb: rgb[0] > 180 and 80 < rgb[1] < 180 and rgb[2] < 90)
    panel_mean = sum(ImageStat.Stat(panel).mean) / 3
    text_dark = _ratio(text, lambda rgb: rgb[0] < 80 and rgb[1] < 80 and rgb[2] < 80)
    return title_dark > 0.45 and warning_orange > 0.03 and panel_mean > 150 and text_dark > 0.01


def _looks_like_squad_management(path: Path) -> bool:
    if Image is None or ImageStat is None or not path.is_file():
        return False
    try:
        image = Image.open(path).convert("RGB")
    except Exception:
        return False
    if image.width < 640 or image.height < 460:
        return False
    header = list(image.crop((150, 5, 450, 55)).getdata())
    table = image.crop((5, 95, 535, 462))
    table_pixels = list(table.getdata())
    header_white = _ratio(header, lambda rgb: rgb[0] > 200 and rgb[1] > 200 and rgb[2] > 200)
    table_light = _ratio(table_pixels, lambda rgb: rgb[0] > 150 and rgb[1] > 150 and rgb[2] > 150)
    table_mean = sum(ImageStat.Stat(table).mean) / 3
    return header_white > 0.04 and table_light > 0.45 and table_mean > 160


def _pick_squad_screenshot(screenshots: list[str]) -> str:
    preferences = [
        "squad_inspect_scroll",
        "squad_inspect_filters_enabled",
        "squad_inspect_retry",
        "squad_inspect",
    ]
    for token in preferences:
        for shot in reversed(screenshots):
            if token in shot:
                return shot
    return screenshots[-1] if screenshots else ""


artifact_dir = Path(sys.argv[1]).resolve()
run_status = int(sys.argv[2])
sync_status = int(sys.argv[3])
cleanup_status = int(sys.argv[4])
cases = []
for line in (artifact_dir / "visual_cases.tsv").read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    club_key, set_name, team_query, *_ = line.split("\t")
    safe_key = "".join(char if char.isalnum() or char == "_" else "_" for char in club_key)
    summary_path = artifact_dir / "clubs" / safe_key / "summary.json"
    status_path = artifact_dir / "club_status" / f"{safe_key}.status"
    status = int(status_path.read_text(encoding="utf-8").strip()) if status_path.is_file() else 99
    screenshots = sorted(str(path.relative_to(artifact_dir)) for path in (artifact_dir / "clubs" / safe_key / "screens").glob("*.png"))
    selected_screenshot = _pick_squad_screenshot(screenshots)
    crash_dialog = _looks_like_application_cannot_continue(artifact_dir / selected_screenshot) if selected_screenshot else False
    squad_screen = _looks_like_squad_management(artifact_dir / selected_screenshot) if selected_screenshot else False
    visual_ok = status == 0 and bool(selected_screenshot) and not crash_dialog and squad_screen
    cases.append(
        {
            "club_key": club_key,
            "set_name": set_name,
            "team_query": team_query,
            "status": status,
            "ok": visual_ok,
            "process_ok": status == 0,
            "visual_ok": visual_ok,
            "application_cannot_continue": crash_dialog,
            "squad_management_screen": squad_screen,
            "selected_screenshot": selected_screenshot,
            "summary_path": str(summary_path),
            "screenshots": screenshots,
        }
    )
payload = {
    "success": run_status == 0 and sync_status == 0 and cleanup_status == 0 and all(case["ok"] for case in cases),
    "scope": "pm99_2025_roster_visual_sample",
    "artifact_dir": str(artifact_dir),
    "cases": cases,
    "transport": {"sync_status": sync_status, "cleanup_status": cleanup_status},
}
(artifact_dir / "summary.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(payload, indent=2, sort_keys=True))
PY

if [[ ${SYNC_STATUS} -ne 0 ]]; then
  exit "${SYNC_STATUS}"
fi
if [[ ${CLEANUP_STATUS} -ne 0 && ${RUN_STATUS} -eq 0 ]]; then
  exit "${CLEANUP_STATUS}"
fi
exit "${RUN_STATUS}"
