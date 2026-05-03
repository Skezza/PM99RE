#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}" || exit 2

BUILD_DIR=""
BATCH_COUNT="${PM99_ENGLISH80_VARNAME_BATCH_COUNT:-8}"
RUN_TAG=""
SCROLL_PAGES="${PM99_ENGLISH80_VARNAME_SCROLL_PAGES:-1}"
SCROLL_CLICKS="${PM99_ENGLISH80_VARNAME_SCROLL_CLICKS:-8}"
CAPTURE_TRANSFERS=0

usage() {
  cat <<'EOF'
Usage: ./scripts/run_english80_variable_name_runner_matrix.sh [options]

Run pm99-runner visual squad proof across all 80 English variable-name clubs.

Options:
  --build-dir <path>       Variable-name build dir. Defaults to latest pointer.
  --batch-count <n>        Parallel wrapper count. Default: 8.
  --run-tag <id>           Matrix tag suffix. Default generated from UTC time.
  --scroll-pages <n>       Additional squad scroll proof pages per club. Default: 1.
  --scroll-clicks <n>      Down clicks per scroll proof page. Default: 8.
  --capture-transfers      Also capture transfers route. Default: squad only.
  -h, --help               Show help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --build-dir) BUILD_DIR="$2"; shift 2 ;;
    --batch-count) BATCH_COUNT="$2"; shift 2 ;;
    --run-tag) RUN_TAG="$2"; shift 2 ;;
    --scroll-pages) SCROLL_PAGES="$2"; shift 2 ;;
    --scroll-clicks) SCROLL_CLICKS="$2"; shift 2 ;;
    --capture-transfers) CAPTURE_TRANSFERS=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "${BUILD_DIR}" ]]; then
  if [[ ! -f .local/latest_english80_2026_variable_names_dir.txt ]]; then
    echo "Missing latest variable-name build pointer" >&2
    exit 2
  fi
  BUILD_DIR="$(cat .local/latest_english80_2026_variable_names_dir.txt)"
fi
BUILD_DIR="$(cd "${BUILD_DIR}" && pwd)"
GAME_ROOT="${BUILD_DIR}/game"
WORLD_STATE="${BUILD_DIR}/world_english80_2026_variable_names.json"
SELECTOR_MAP="${ROOT_DIR}/.local/selector_maps/pm99_vanilla_english_80_selector_map.json"

if [[ -z "${RUN_TAG}" ]]; then
  RUN_TAG="english80_varnames_80club_squad_$(date -u +%Y%m%dT%H%M%SZ)"
fi

if [[ ! -d "${GAME_ROOT}" || ! -f "${WORLD_STATE}" || ! -f "${SELECTOR_MAP}" ]]; then
  echo "Missing game/world/selector input for build: ${BUILD_DIR}" >&2
  exit 2
fi

MATRIX="${BUILD_DIR}/runner_80club_squad_matrix_${RUN_TAG}"
mkdir -p "${MATRIX}/logs" "${MATRIX}/artifacts"
printf '%s\n' "${MATRIX}" > "${BUILD_DIR}/latest_80club_squad_matrix_dir.txt"

python3 - "${WORLD_STATE}" "${MATRIX}" "${BATCH_COUNT}" <<'PY'
from __future__ import annotations
import json
import sys
from pathlib import Path

world = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
matrix = Path(sys.argv[2])
batch_count = int(sys.argv[3])
clubs = [
    str(row["club_key"])
    for row in world.get("clubs", [])
    if isinstance(row, dict) and str(row.get("club_key") or "").strip()
]
if len(clubs) != 80:
    raise SystemExit(f"Expected 80 clubs in world state, got {len(clubs)}")
if batch_count < 1:
    raise SystemExit("batch-count must be >= 1")
batches = [[] for _ in range(batch_count)]
for index, club in enumerate(clubs):
    batches[index % batch_count].append(club)
(matrix / "clubs_all.txt").write_text("\n".join(clubs) + "\n", encoding="utf-8")
for index, batch in enumerate(batches):
    (matrix / f"batch_{index:02d}_clubs.txt").write_text("\n".join(batch) + "\n", encoding="utf-8")
(matrix / "driver_progress.json").write_text(
    json.dumps(
        {
            "state": "started",
            "club_count": len(clubs),
            "batch_count": batch_count,
            "batch_sizes": [len(batch) for batch in batches],
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
print(json.dumps({"club_count": len(clubs), "batch_sizes": [len(batch) for batch in batches]}, indent=2))
PY

pids=()
for index in $(seq 0 $((BATCH_COUNT - 1))); do
  (
    set -euo pipefail
    CLUB_ARGS=()
    while IFS= read -r club; do
      [[ -n "${club}" ]] && CLUB_ARGS+=(--club-key "${club}")
    done < "${MATRIX}/batch_$(printf '%02d' "${index}")_clubs.txt"

    ROUTE_ARGS=(--capture-route squad)
    if [[ "${CAPTURE_TRANSFERS}" -eq 1 ]]; then
      ROUTE_ARGS+=(--capture-route transfers)
    fi

    export PM99_RUNNER_LOCAL_ARTIFACT_ROOT="${MATRIX}/artifacts"
    export PM99_RUNNER_WORKER_LANE_COUNT="${PM99_RUNNER_WORKER_LANE_COUNT:-8}"
    export PM99_RUNNER_HOST_LOCK_CONCURRENCY="${PM99_RUNNER_HOST_LOCK_CONCURRENCY:-8}"
    export PM99_RUNNER_DOCKER_TIMEOUT_SECONDS="${PM99_RUNNER_DOCKER_TIMEOUT_SECONDS:-900}"
    export PM99_RUNNER_RUN_ROOT_BUDGET_ENFORCE="${PM99_RUNNER_RUN_ROOT_BUDGET_ENFORCE:-0}"
    export PM99_RUNNER_SKIP_CLASSIFICATION="${PM99_RUNNER_SKIP_CLASSIFICATION:-1}"
    unset PM99_RUNNER_FAST_OCR

    ./scripts/run_2025_roster_visual_sample.sh \
      --game-root "${GAME_ROOT}" \
      --world-state "${WORLD_STATE}" \
      --selector-map "${SELECTOR_MAP}" \
      --run-tag "${RUN_TAG}_batch_$(printf '%02d' "${index}")" \
      "${CLUB_ARGS[@]}" \
      "${ROUTE_ARGS[@]}" \
      --profile-count 0 \
      --squad-scroll-proof-pages "${SCROLL_PAGES}" \
      --squad-scroll-clicks "${SCROLL_CLICKS}" \
      --skip-setup \
      --skip-build \
      --cleanup-on-failure
  ) > "${MATRIX}/logs/batch_$(printf '%02d' "${index}").stdout" 2> "${MATRIX}/logs/batch_$(printf '%02d' "${index}").stderr" &
  pids+=("$!")
  echo "$!" > "${MATRIX}/logs/batch_$(printf '%02d' "${index}").pid"
done

status=0
for pid in "${pids[@]}"; do
  if ! wait "${pid}"; then
    status=1
  fi
done

python3 - "${MATRIX}" "${status}" <<'PY'
from __future__ import annotations
import json
import sys
from pathlib import Path

matrix = Path(sys.argv[1])
status = int(sys.argv[2])
artifact_root = matrix / "artifacts"
all_clubs = [line.strip() for line in (matrix / "clubs_all.txt").read_text(encoding="utf-8").splitlines() if line.strip()]
seen: list[str] = []
failed: list[dict[str, object]] = []
batches: list[dict[str, object]] = []
for summary_path in sorted(artifact_root.glob("*/summary.json")):
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    cases = [case for case in payload.get("cases") or [] if isinstance(case, dict)]
    for case in cases:
        club = str(case.get("club_key") or "")
        if club:
            seen.append(club)
        if not case.get("ok"):
            failed.append(case)
    batches.append(
        {
            "summary_path": str(summary_path),
            "success": bool(payload.get("success")),
            "case_count": len(cases),
            "cases": cases,
        }
    )
missing = [club for club in all_clubs if club not in seen]
summary = {
    "success": status == 0 and not failed and not missing,
    "status": status,
    "artifact_root": str(artifact_root.resolve()),
    "batch_count": len(batches),
    "all_club_count": len(all_clubs),
    "seen_club_count": len(set(seen)),
    "ok_club_count": len({club for club in seen}) - len({str(case.get("club_key") or "") for case in failed}),
    "failed_case_count": len(failed),
    "missing_club_count": len(missing),
    "missing_clubs": missing,
    "failed_cases": failed,
    "batches": batches,
}
(matrix / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
(matrix / "summary.html").write_text(
    "<!doctype html><meta charset='utf-8'><title>English80 Variable Names Matrix</title>"
    "<body><h1>English80 Variable Names Matrix</h1><pre>"
    + json.dumps({key: value for key, value in summary.items() if key != "batches"}, indent=2, sort_keys=True)
    + "</pre></body>",
    encoding="utf-8",
)
(matrix / "driver_progress.json").write_text(
    json.dumps({"state": "finished", **{key: value for key, value in summary.items() if key != "batches"}}, indent=2, sort_keys=True)
    + "\n",
    encoding="utf-8",
)
print(json.dumps({key: value for key, value in summary.items() if key != "batches"}, indent=2, sort_keys=True))
raise SystemExit(0 if summary["success"] else 1)
PY
