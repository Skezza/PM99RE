#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER_ROOT="${ROOT_DIR}/upstream/pm99-runner"
export PM99_RUNNER_HOST_LOCK_NAME="${PM99_RUNNER_HOST_LOCK_NAME:-runner-host}"
source "${RUNNER_ROOT}/scripts/pm99_runner/common.sh"

RUN_TAG="full_db_world_proof_$(pm99_runner_timestamp_utc)"
WORLD_STATE=""
SELECTOR_MAP=""
ALLOW_BLOCKED=0
PROFILE_COUNT=20
MIN_FULL_TIME_MATCHES=8
MAX_STEPS=1200
SKIP_SETUP=0
SKIP_BUILD=0
SKIP_PREPARE=0
KEEP_REMOTE_RUN=0
KEEP_REMOTE_ARTIFACTS=0
CLEANUP_ON_FAILURE=0
DRY_RUN=0

usage() {
  cat <<'USAGE'
Usage: ./scripts/run_full_db_world_proof_matrix.sh --world-state <path> [options]

Compile/apply a canonical full-DB world-state into a cached remote PM99 baseline,
then execute the initial runtime proof matrix against that rewritten full game.

Current runtime proofs:
  - global route capture: squad, line_up, tactics, results, league_tables, fixtures
  - global season sentinel: season progression on the rewritten world

Options:
  --world-state <path>       Canonical world-state JSON input (required)
  --selector-map <path>      Optional club selector map JSON
  --run-tag <id>             Override run tag
  --profile-count <n>        Squad profile captures in route mode (default: 20)
  --min-full-time-matches <n>
                             Minimum full-time matches for sentinel (default: 8)
  --max-steps <n>            Sentinel max driver steps (default: 1200)
  --allow-blocked            Apply even when compile blockers exist
  --skip-setup               Skip remote host bootstrap/sync prerequisites
  --skip-build               Skip docker image build
  --skip-prepare             Skip clean source extraction
  --keep-remote-run          Preserve remote per-run workspace
  --keep-remote-artifacts    Preserve remote artifacts after mirroring
  --cleanup-on-failure       Clean remote state after failed run once mirrored
  --dry-run                  Write control manifest only; skip remote execution
  -h, --help                 Show this help
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

world_sha256() {
  python3 - "$1" <<'PY'
from pathlib import Path
import hashlib
import sys
print(hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest())
PY
}

write_control_manifest() {
  local output_path="$1"
  python3 - "${WORLD_STATE}" "${SELECTOR_MAP}" "${RUN_TAG}" "${PROFILE_COUNT}" "${MIN_FULL_TIME_MATCHES}" "${MAX_STEPS}" "${ALLOW_BLOCKED}" "${output_path}" <<'PY'
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys

world_state_path = Path(sys.argv[1]).resolve()
selector_map_path = Path(sys.argv[2]).resolve() if sys.argv[2] else None
run_tag = sys.argv[3]
profile_count = int(sys.argv[4])
min_full_time_matches = int(sys.argv[5])
max_steps = int(sys.argv[6])
allow_blocked = sys.argv[7] == "1"
output_path = Path(sys.argv[8]).resolve()
payload = json.loads(world_state_path.read_text(encoding="utf-8"))

selector_rows = {}
selector_query_rows = {}
if selector_map_path is not None:
    selector_payload = json.loads(selector_map_path.read_text(encoding="utf-8"))
    for row in selector_payload.get("selectors") or []:
        if not isinstance(row, dict):
            continue
        club_key = str(row.get("club_key") or "").strip()
        team_query = str(row.get("team_query") or row.get("team_name") or row.get("set_name") or "").strip().casefold()
        if club_key:
            selector_rows[club_key] = row
        if team_query:
            selector_query_rows[team_query] = row

clubs = list(payload.get("clubs") or [])
divisions = list(payload.get("divisions") or [])

def proof_selector(item):
    club_key = str(item.get("club_key") or "").strip()
    team_query = str(item.get("team_query") or item.get("team_name") or item.get("set_name") or "").strip().casefold()
    mapped = selector_rows.get(club_key) or selector_query_rows.get(team_query) or {}
    nested = item.get("proof_selector") or item.get("runtime_selector") or {}
    if not isinstance(nested, dict):
        nested = {}
    mapped_nested = mapped.get("proof_selector") or mapped.get("runtime_selector") or {}
    if not isinstance(mapped_nested, dict):
        mapped_nested = {}
    merged = {**mapped_nested, **{key: mapped[key] for key in ("team_select_x", "team_select_y", "division_select_x", "division_select_y") if key in mapped}, **nested}
    for key in ("team_select_x", "team_select_y", "division_select_x", "division_select_y"):
        if key in item:
            merged[key] = item[key]
    selector = {}
    for key in ("team_select_x", "team_select_y", "division_select_x", "division_select_y"):
        value = merged.get(key)
        selector[key] = None if value in (None, "") else int(value)
    return selector

def runtime_routes(item):
    club_key = str(item.get("club_key") or "").strip()
    team_query = str(item.get("team_query") or item.get("team_name") or item.get("set_name") or "").strip().casefold()
    mapped = selector_rows.get(club_key) or selector_query_rows.get(team_query) or {}
    routes = item.get("runtime_routes")
    if routes is None:
        routes = mapped.get("runtime_routes")
    if routes is None:
        return ["squad", "line_up", "tactics", "results", "league_tables", "fixtures"]
    return [str(route).strip() for route in routes if str(route).strip()]

club_cases = []
for item in clubs:
    club_key = str(item.get("club_key") or "").strip()
    selector = proof_selector(item)
    missing = [key for key, value in selector.items() if value is None]
    club_cases.append(
        {
            "case_id": f"club_smoke::{club_key}",
            "club_key": club_key,
            "team_query": str(item.get("team_query") or item.get("team_name") or item.get("set_name") or "").strip(),
            "proof_mode": "generic_club_route_capture",
            "routes": runtime_routes(item),
            "selector": selector,
            "status": "blocked_missing_selector" if missing else "ready",
            "blockers": [f"missing_{key}" for key in missing],
        }
    )
division_cases = []
for item in divisions:
    club_key = str(item.get("club_key") or "").strip()
    club_case = next((case for case in club_cases if case["club_key"] == club_key), None)
    division_cases.append(
        {
            "case_id": f"division_season::{club_key}",
            "club_key": club_key,
            "division": str(item.get("division") or "").strip(),
            "country": str(item.get("country") or "").strip(),
            "proof_mode": "generic_club_season_sentinel",
            "selector": dict(club_case.get("selector") or {}) if club_case is not None else {},
            "status": "ready" if club_case is not None and club_case["status"] == "ready" else "blocked_missing_selector",
            "blockers": [] if club_case is not None and club_case["status"] == "ready" else ["club_selector_not_ready"],
        }
    )

control = {
    "scope": "full_db_world_proof_matrix",
    "schema": str(payload.get("schema") or ""),
    "run_tag": run_tag,
    "world_state": {
        "path": str(world_state_path),
        "sha256": hashlib.sha256(world_state_path.read_bytes()).hexdigest(),
    },
    "selector_map": {
        "path": str(selector_map_path),
        "sha256": hashlib.sha256(selector_map_path.read_bytes()).hexdigest(),
    } if selector_map_path is not None else None,
    "counts": {
        "clubs": len(clubs),
        "players": len(list(payload.get("players") or [])),
        "squad_memberships": len(list(payload.get("squad_memberships") or [])),
        "divisions": len(divisions),
    },
    "settings": {
        "profile_count": profile_count,
        "min_full_time_matches": min_full_time_matches,
        "max_steps": max_steps,
        "allow_blocked": allow_blocked,
    },
    "planned_cases": {
        "club_smoke": club_cases,
        "division_season": division_cases,
        "global_runtime": [
            {
                "case_id": "global_route_capture",
                "routes": ["squad", "line_up", "tactics", "results", "league_tables", "fixtures"],
            },
            {
                "case_id": "global_season_sentinel",
                "min_full_time_matches": min_full_time_matches,
                "max_steps": max_steps,
            },
        ],
    },
    "notes": [
        "This first implementation executes global runtime proofs on the rewritten world.",
        "Per-club route proofs execute when team/division selector coordinates are provided.",
        "Division placement remains fail-closed when it differs from baseline because the editor write surface is unreleased.",
    ],
}
output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_text(json.dumps(control, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(control, indent=2, sort_keys=True))
PY
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --world-state) WORLD_STATE="$2"; shift 2 ;;
    --selector-map) SELECTOR_MAP="$2"; shift 2 ;;
    --run-tag) RUN_TAG="$2"; shift 2 ;;
    --profile-count) PROFILE_COUNT="$2"; shift 2 ;;
    --min-full-time-matches) MIN_FULL_TIME_MATCHES="$2"; shift 2 ;;
    --max-steps) MAX_STEPS="$2"; shift 2 ;;
    --allow-blocked) ALLOW_BLOCKED=1; shift ;;
    --skip-setup) SKIP_SETUP=1; shift ;;
    --skip-build) SKIP_BUILD=1; shift ;;
    --skip-prepare) SKIP_PREPARE=1; shift ;;
    --keep-remote-run) KEEP_REMOTE_RUN=1; shift ;;
    --keep-remote-artifacts) KEEP_REMOTE_ARTIFACTS=1; shift ;;
    --cleanup-on-failure) CLEANUP_ON_FAILURE=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "${WORLD_STATE}" ]]; then
  echo "--world-state is required" >&2
  usage >&2
  exit 2
fi
WORLD_STATE="$(abs_path "${WORLD_STATE}")"
if [[ ! -f "${WORLD_STATE}" ]]; then
  echo "Missing world-state file: ${WORLD_STATE}" >&2
  exit 2
fi
COMPILE_SELECTOR_ARGS=()
if [[ -n "${SELECTOR_MAP}" ]]; then
  SELECTOR_MAP="$(abs_path "${SELECTOR_MAP}")"
  if [[ ! -f "${SELECTOR_MAP}" ]]; then
    echo "Missing selector-map file: ${SELECTOR_MAP}" >&2
    exit 2
  fi
  COMPILE_SELECTOR_ARGS=(--selector-map "${SELECTOR_MAP}")
fi

pm99_runner_ensure_local_artifact_root
LOCAL_ARTIFACT_DIR="${PM99_RUNNER_LOCAL_ARTIFACT_ROOT}/${RUN_TAG}"
mkdir -p "${LOCAL_ARTIFACT_DIR}"
CONTROL_MANIFEST="${LOCAL_ARTIFACT_DIR}/control_manifest.json"
write_control_manifest "${CONTROL_MANIFEST}" >/dev/null

if [[ ${DRY_RUN} -eq 1 ]]; then
  python3 - "${CONTROL_MANIFEST}" "${LOCAL_ARTIFACT_DIR}" <<'PY'
import json
from pathlib import Path
import sys

control_manifest = Path(sys.argv[1]).resolve()
artifact_dir = Path(sys.argv[2]).resolve()
print(json.dumps({
    "success": True,
    "dry_run": True,
    "control_manifest_path": str(control_manifest),
    "local_artifact_dir": str(artifact_dir),
}, indent=2, sort_keys=True))
PY
  exit 0
fi

pm99_runner_require_cmd "${PM99_RUNNER_SSH_BIN}"
pm99_runner_require_cmd "${PM99_RUNNER_RSYNC_BIN}"
pm99_runner_require_editor_root
pm99_runner_select_remote_worker "${PM99_RUNNER_WORKER_NAME:-default}"
PM99_RUNNER_HOST_LOCK_CONCURRENCY="${PM99_RUNNER_WORKER_LANE_COUNT}"
pm99_runner_acquire_remote_host_lock "run_full_db_world_proof_matrix:${RUN_TAG}"
trap 'pm99_runner_release_remote_host_lock' EXIT

if [[ ${SKIP_SETUP} -eq 0 ]]; then
  "${RUNNER_ROOT}/scripts/pm99_runner/setup_remote_host.sh"
fi
if [[ ${SKIP_PREPARE} -eq 0 ]]; then
  "${RUNNER_ROOT}/scripts/pm99_runner/prepare_game_source.sh" --skip-zip-upload
fi
if [[ ${SKIP_BUILD} -eq 0 ]]; then
  "${RUNNER_ROOT}/scripts/pm99_runner/build_runner_image.sh"
fi

pm99_runner_sync_repo
pm99_runner_ensure_local_artifact_root

REMOTE_RUN_ROOT="${PM99_RUNNER_REMOTE_ROOT}/workspace/runs/${RUN_TAG}"
REMOTE_ARTIFACT_DIR="${PM99_RUNNER_REMOTE_ROOT}/artifacts/${RUN_TAG}"
REMOTE_WORLD_STATE_DIR="${PM99_RUNNER_REMOTE_ROOT}/workspace/world_state_inputs"
WORLD_STATE_SHA="$(world_sha256 "${WORLD_STATE}")"
REMOTE_WORLD_STATE_PATH="${REMOTE_WORLD_STATE_DIR}/${WORLD_STATE_SHA}.json"
REMOTE_SELECTOR_MAP_PATH=""

pm99_runner_ssh "mkdir -p $(printf '%q' "${REMOTE_WORLD_STATE_DIR}") $(printf '%q' "${REMOTE_ARTIFACT_DIR}")"
pm99_runner_scp_to_remote "${WORLD_STATE}" "${REMOTE_WORLD_STATE_PATH}"
if [[ -n "${SELECTOR_MAP}" ]]; then
  SELECTOR_MAP_SHA="$(world_sha256 "${SELECTOR_MAP}")"
  REMOTE_SELECTOR_MAP_PATH="${REMOTE_WORLD_STATE_DIR}/${SELECTOR_MAP_SHA}.selectors.json"
  pm99_runner_scp_to_remote "${SELECTOR_MAP}" "${REMOTE_SELECTOR_MAP_PATH}"
fi

BASELINE_KIND="full_db_world_apply"
BASELINE_MANIFEST_JSON="$(
  python3 - "${WORLD_STATE}" "${WORLD_STATE_SHA}" "${SELECTOR_MAP}" "${ALLOW_BLOCKED}" "${ROOT_DIR}" "${RUNNER_ROOT}" "${ROOT_DIR}/upstream/pm99-skezmod-db-editor" <<'PY'
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess
import sys

world_state, world_sha, selector_map, allow_blocked, repo_root, runner_root, editor_root = sys.argv[1:]

def git_rev(path: str) -> str:
    completed = subprocess.run(["git", "-C", path, "rev-parse", "HEAD"], text=True, capture_output=True, check=False)
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"

payload = {
    "baseline_kind": "full_db_world_apply",
    "world_state": {
        "path": str(Path(world_state).resolve()),
        "sha256": world_sha,
    },
    "selector_map": (
        {
            "path": str(Path(selector_map).resolve()),
            "sha256": hashlib.sha256(Path(selector_map).read_bytes()).hexdigest(),
        }
        if selector_map
        else None
    ),
    "allow_blocked": allow_blocked == "1",
    "repo_fingerprints": {
        "pm99_research": git_rev(repo_root),
        "pm99_runner": git_rev(runner_root),
        "pm99_editor": git_rev(editor_root),
    },
    "recipe": {
        "compile_command": "pm99_world_state.py world-compile-plan",
        "apply_command": "pm99_world_state.py world-apply-plan",
        "runtime_cases": ["global_route_capture", "global_season_sentinel"],
    },
}
print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
PY
)"
BASELINE_MANIFEST_HASH="$(
  python3 - "${BASELINE_MANIFEST_JSON}" <<'PY'
import hashlib
import sys
print(hashlib.sha256(sys.argv[1].encode("utf-8")).hexdigest())
PY
)"

ALLOW_BLOCKED_FLAG=""
if [[ ${ALLOW_BLOCKED} -eq 1 ]]; then
  ALLOW_BLOCKED_FLAG="--allow-blocked"
fi
REMOTE_SELECTOR_MAP_ARGS=""
if [[ -n "${REMOTE_SELECTOR_MAP_PATH}" ]]; then
  REMOTE_SELECTOR_MAP_ARGS="--selector-map $(printf '%q' "${REMOTE_SELECTOR_MAP_PATH}")"
fi
BASELINE_BUILD_REMOTE_COMMAND_TEMPLATE=$(cat <<EOF2
set -euo pipefail
mkdir -p "__PM99_REMOTE_ARTIFACT_DIR__/compile" "__PM99_REMOTE_ARTIFACT_DIR__/apply"
python3 /workspace/repo/scripts/pm99_world_state.py world-compile-plan $(printf '%q' "${REMOTE_WORLD_STATE_PATH}") --game-root "__PM99_REMOTE_GAME_DIR__" --output-dir "__PM99_REMOTE_ARTIFACT_DIR__/compile" ${REMOTE_SELECTOR_MAP_ARGS} --json > "__PM99_REMOTE_ARTIFACT_DIR__/compile_result.json"
python3 /workspace/repo/scripts/pm99_world_state.py world-apply-plan "__PM99_REMOTE_ARTIFACT_DIR__/compile/world_plan.json" --game-root "__PM99_REMOTE_GAME_DIR__" --output-dir "__PM99_REMOTE_ARTIFACT_DIR__/apply" --json ${ALLOW_BLOCKED_FLAG} > "__PM99_REMOTE_ARTIFACT_DIR__/apply_stdout.json"
EOF2
)

pm99_runner_prepare_cached_remote_run_root \
  "${REMOTE_RUN_ROOT}" \
  "${REMOTE_ARTIFACT_DIR}" \
  "${BASELINE_KIND}" \
  "${BASELINE_MANIFEST_HASH}" \
  "${BASELINE_MANIFEST_JSON}" \
  "${BASELINE_BUILD_REMOTE_COMMAND_TEMPLATE}" \
  club_smoke \
  route_capture \
  season

BASELINE_METADATA_JSON="$(pm99_runner_build_baseline_metadata_json "${PM99_RUNNER_BASELINE_USED}" "${PM99_RUNNER_BASELINE_STATUS}" "${PM99_RUNNER_BASELINE_KIND}" "${PM99_RUNNER_BASELINE_MANIFEST_HASH}" "${PM99_RUNNER_BASELINE_ROOT}" "${PM99_RUNNER_BASELINE_REASON}")"
pm99_runner_write_local_baseline_metadata "${LOCAL_ARTIFACT_DIR}" "${BASELINE_METADATA_JSON}"

REMOTE_GAME_DIR="$(pm99_runner_remote_game_dir "${REMOTE_RUN_ROOT}")"
REMOTE_HOME_DIR="$(pm99_runner_remote_home_dir "${REMOTE_RUN_ROOT}")"
REMOTE_WINE_PREFIX_DIR="$(pm99_runner_remote_wine_prefix_dir "${REMOTE_RUN_ROOT}")"

mkdir -p "${LOCAL_ARTIFACT_DIR}/club_status"
CLUB_STATUS=0
CLUB_CASE_INDEX=0
while IFS=$'\t' read -r CASE_ID CLUB_KEY TEAM_QUERY TEAM_SELECT_X TEAM_SELECT_Y DIVISION_SELECT_X DIVISION_SELECT_Y ROUTES_CSV; do
  if [[ -z "${CASE_ID}" ]]; then
    continue
  fi
  CLUB_CASE_INDEX=$((CLUB_CASE_INDEX + 1))
  SAFE_CLUB_KEY="$(printf '%s' "${CLUB_KEY}" | tr -c 'A-Za-z0-9_' '_')"
  CHILD_TAG="${RUN_TAG}_club_${CLUB_CASE_INDEX}_${SAFE_CLUB_KEY}"
  CHILD_REMOTE_ARTIFACT_DIR="${REMOTE_ARTIFACT_DIR}/club_smoke/${SAFE_CLUB_KEY}"
  ROUTE_ARGS=()
  IFS=',' read -r -a ROUTES_ARRAY <<< "${ROUTES_CSV}"
  for ROUTE_NAME in "${ROUTES_ARRAY[@]}"; do
    if [[ -n "${ROUTE_NAME}" ]]; then
      ROUTE_ARGS+=(--capture-route "${ROUTE_NAME}")
    fi
  done
  if [[ ${#ROUTE_ARGS[@]} -eq 0 ]]; then
    ROUTE_ARGS=(--capture-route squad --capture-route line_up --capture-route tactics)
  fi
  set +e
  pm99_runner_remote_one_shot_container_with_timeout \
    "${PM99_RUNNER_DOCKER_TIMEOUT_SECONDS:-900}" \
    "${CHILD_TAG}" \
    "run_full_db_world_proof_matrix.sh" \
    "pm99-agent-${CHILD_TAG}" \
    "${CHILD_REMOTE_ARTIFACT_DIR}" \
    --image "${PM99_RUNNER_REMOTE_IMAGE}" \
    --user CURRENT_USER \
    --workdir /workspace/repo \
    --shm-size 2g \
    --env HOME=/workspace/home \
    --env PM99_EDITOR_ROOT=/workspace/editor \
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
      --artifacts-dir "/workspace/artifacts/club_smoke/${SAFE_CLUB_KEY}" \
      --proof-mode generic_club_route_capture \
      --team-name "${TEAM_QUERY}" \
      --team-select-x "${TEAM_SELECT_X}" \
      --team-select-y "${TEAM_SELECT_Y}" \
      --division-select-x "${DIVISION_SELECT_X}" \
      --division-select-y "${DIVISION_SELECT_Y}" \
      --capture-routes-only \
      "${ROUTE_ARGS[@]}" \
      --profile-count "${PROFILE_COUNT}" \
      --row-pitch 15
  CHILD_STATUS=$?
  set -e
  printf '%s\n' "${CHILD_STATUS}" > "${LOCAL_ARTIFACT_DIR}/club_status/${SAFE_CLUB_KEY}.status"
  if [[ ${CHILD_STATUS} -ne 0 ]]; then
    CLUB_STATUS=1
  fi
done < <(
  python3 - "${CONTROL_MANIFEST}" <<'PY'
from __future__ import annotations
import json
import sys
from pathlib import Path

control = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for case in control.get("planned_cases", {}).get("club_smoke", []):
    if case.get("status") != "ready":
        continue
    selector = case.get("selector") or {}
    routes = ",".join(str(route) for route in case.get("routes", []) if str(route))
    print(
        "\t".join(
            [
                str(case.get("case_id") or ""),
                str(case.get("club_key") or ""),
                str(case.get("team_query") or ""),
                str(selector.get("team_select_x") or ""),
                str(selector.get("team_select_y") or ""),
                str(selector.get("division_select_x") or ""),
                str(selector.get("division_select_y") or ""),
                routes,
            ]
        )
    )
PY
)

set +e
pm99_runner_remote_one_shot_container_with_timeout \
  "${PM99_RUNNER_DOCKER_TIMEOUT_SECONDS:-900}" \
  "${RUN_TAG}_routes" \
  "run_full_db_world_proof_matrix.sh" \
  "pm99-agent-${RUN_TAG}-routes" \
  "${REMOTE_ARTIFACT_DIR}/route_capture" \
  --image "${PM99_RUNNER_REMOTE_IMAGE}" \
  --user CURRENT_USER \
  --workdir /workspace/repo \
  --shm-size 2g \
  --env HOME=/workspace/home \
  --env PM99_EDITOR_ROOT=/workspace/editor \
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
    --artifacts-dir /workspace/artifacts/route_capture \
    --proof-mode generic_club_route_capture \
    --capture-routes-only \
    --capture-route squad \
    --capture-route line_up \
    --capture-route tactics \
    --capture-route results \
    --capture-route league_tables \
    --capture-route fixtures \
    --profile-count "${PROFILE_COUNT}" \
    --row-pitch 15
ROUTE_STATUS=$?

pm99_runner_remote_one_shot_container_with_timeout \
  "${PM99_RUNNER_DOCKER_TIMEOUT_SECONDS:-900}" \
  "${RUN_TAG}_season" \
  "run_full_db_world_proof_matrix.sh" \
  "pm99-agent-${RUN_TAG}-season" \
  "${REMOTE_ARTIFACT_DIR}/season" \
  --image "${PM99_RUNNER_REMOTE_IMAGE}" \
  --user CURRENT_USER \
  --workdir /workspace/repo \
  --shm-size 2g \
  --env HOME=/workspace/home \
  --env PM99_EDITOR_ROOT=/workspace/editor \
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
    --artifacts-dir /workspace/artifacts/season \
    --proof-mode generic_club_season_sentinel \
    --strategy win \
    --min-full-time-matches "${MIN_FULL_TIME_MATCHES}" \
    --max-steps "${MAX_STEPS}"
SEASON_STATUS=$?
set -e

set +e
pm99_runner_sync_remote_artifacts "${REMOTE_ARTIFACT_DIR}" "${LOCAL_ARTIFACT_DIR}"
SYNC_STATUS=$?
pm99_runner_cleanup_remote_state \
  $(( CLUB_STATUS != 0 || ROUTE_STATUS != 0 || SEASON_STATUS != 0 ? 1 : 0 )) \
  "${SYNC_STATUS}" \
  "${REMOTE_RUN_ROOT}" \
  "${REMOTE_ARTIFACT_DIR}" \
  "${KEEP_REMOTE_RUN}" \
  "${KEEP_REMOTE_ARTIFACTS}" \
  "${CLEANUP_ON_FAILURE}" \
  0
CLEANUP_STATUS=$?
set -e

pm99_runner_annotate_local_summary_with_baseline "${LOCAL_ARTIFACT_DIR}/route_capture/summary.json" "${BASELINE_METADATA_JSON}"
pm99_runner_annotate_local_summary_with_baseline "${LOCAL_ARTIFACT_DIR}/season/summary.json" "${BASELINE_METADATA_JSON}"

FINAL_SUMMARY="${LOCAL_ARTIFACT_DIR}/summary.json"
FINAL_REPORT="${LOCAL_ARTIFACT_DIR}/summary.html"
python3 - "${CONTROL_MANIFEST}" "${FINAL_SUMMARY}" "${FINAL_REPORT}" "${LOCAL_ARTIFACT_DIR}" "${CLUB_STATUS}" "${ROUTE_STATUS}" "${SEASON_STATUS}" "${SYNC_STATUS}" "${CLEANUP_STATUS}" "${BASELINE_METADATA_JSON}" <<'PY'
from __future__ import annotations
import json
from pathlib import Path
import sys

control_manifest_path = Path(sys.argv[1]).resolve()
summary_path = Path(sys.argv[2]).resolve()
report_path = Path(sys.argv[3]).resolve()
artifact_dir = Path(sys.argv[4]).resolve()
club_status = int(sys.argv[5])
route_status = int(sys.argv[6])
season_status = int(sys.argv[7])
sync_status = int(sys.argv[8])
cleanup_status = int(sys.argv[9])
baseline_metadata = json.loads(sys.argv[10])
control = json.loads(control_manifest_path.read_text(encoding="utf-8"))

def load_json(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))

route_summary = load_json(artifact_dir / "route_capture" / "summary.json")
season_summary = load_json(artifact_dir / "season" / "summary.json")
club_cases = list((control.get("planned_cases") or {}).get("club_smoke") or [])
blocked_club_cases = [case for case in club_cases if case.get("status") != "ready"]
executed_club_cases = []
for case in club_cases:
    if case.get("status") != "ready":
        continue
    club_key = str(case.get("club_key") or "")
    safe_key = "".join(char if char.isalnum() or char == "_" else "_" for char in club_key)
    status_path = artifact_dir / "club_status" / f"{safe_key}.status"
    status = int(status_path.read_text(encoding="utf-8").strip()) if status_path.is_file() else 99
    executed_club_cases.append(
        {
            "case_id": case.get("case_id"),
            "club_key": club_key,
            "status": status,
            "ok": status == 0,
            "summary_path": str((artifact_dir / "club_smoke" / safe_key / "summary.json").resolve()),
        }
    )
success = (
    club_status == 0
    and route_status == 0
    and season_status == 0
    and sync_status == 0
    and cleanup_status == 0
    and not blocked_club_cases
)

payload = {
    "success": success,
    "scope": "full_db_world_proof_matrix",
    "control_manifest_path": str(control_manifest_path),
    "local_artifact_dir": str(artifact_dir),
    "baseline_cache": baseline_metadata,
    "planned_cases": control.get("planned_cases", {}),
    "executed_cases": {
        "club_smoke": {
            "status": club_status,
            "ok": club_status == 0 and not blocked_club_cases,
            "executed": executed_club_cases,
            "blocked": blocked_club_cases,
        },
        "global_route_capture": {
            "status": route_status,
            "summary_path": str((artifact_dir / "route_capture" / "summary.json").resolve()),
            "ok": route_status == 0,
        },
        "global_season_sentinel": {
            "status": season_status,
            "summary_path": str((artifact_dir / "season" / "summary.json").resolve()),
            "ok": season_status == 0,
        },
    },
    "transport": {
        "sync_status": sync_status,
        "cleanup_status": cleanup_status,
    },
    "route_capture": route_summary,
    "season_sentinel": season_summary,
}
summary_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
report_path.write_text(
    """<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\" />
<title>PM99 Full-DB World Proof Matrix</title>
<style>
body { font-family: sans-serif; margin: 2rem; }
table { border-collapse: collapse; width: 100%; margin-bottom: 2rem; }
th, td { border: 1px solid #ccc; padding: 0.5rem; text-align: left; }
th { background: #f5f5f5; }
.ok { color: #0a7a20; }
.bad { color: #8a1111; }
</style></head><body>
<h1>PM99 Full-DB World Proof Matrix</h1>
<p>Status: <strong class=\"%s\">%s</strong></p>
<table>
<thead><tr><th>Case</th><th>Status</th><th>Summary</th></tr></thead>
<tbody>
<tr><td>club_smoke</td><td>%s</td><td>%s executed, %s blocked</td></tr>
<tr><td>global_route_capture</td><td>%s</td><td>%s</td></tr>
<tr><td>global_season_sentinel</td><td>%s</td><td>%s</td></tr>
</tbody></table>
<pre>%s</pre>
</body></html>
"""
    % (
        "ok" if success else "bad",
        "OK" if success else "FAILED",
        club_status,
        len(executed_club_cases),
        len(blocked_club_cases),
        route_status,
        str((artifact_dir / "route_capture" / "summary.json").resolve()),
        season_status,
        str((artifact_dir / "season" / "summary.json").resolve()),
        json.dumps(control.get("counts", {}), indent=2, sort_keys=True),
    ),
    encoding="utf-8",
)
print(json.dumps(payload, indent=2, sort_keys=True))
PY

if [[ ${ROUTE_STATUS} -ne 0 ]]; then
  exit ${ROUTE_STATUS}
fi
if [[ ${CLUB_STATUS} -ne 0 ]]; then
  exit ${CLUB_STATUS}
fi
if [[ ${SEASON_STATUS} -ne 0 ]]; then
  exit ${SEASON_STATUS}
fi
if [[ ${SYNC_STATUS} -ne 0 ]]; then
  exit ${SYNC_STATUS}
fi
if [[ ${CLEANUP_STATUS} -ne 0 ]]; then
  exit ${CLEANUP_STATUS}
fi
if [[ "$(python3 - "${FINAL_SUMMARY}" <<'PY'
import json
import sys
from pathlib import Path

print("1" if json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")).get("success") else "0")
PY
)" != "1" ]]; then
  exit 1
fi
exit ${CLEANUP_STATUS}
