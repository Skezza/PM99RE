#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_WORKER_ID="${USER:-worker}"
DEFAULT_RUN_ID="full_db_world_$(date -u +%Y%m%dT%H%M%SZ)"

WORKER_ID="${DEFAULT_WORKER_ID}"
RUN_ID="${DEFAULT_RUN_ID}"
RUN_ROOT=""
WORLD_STATE=""
SELECTOR_MAP=""
PRINT_JSON=0
ALLOW_BLOCKED=0
SKIP_PLAYER_ROUNDTRIP_SAFETY=0

usage() {
  cat <<EOF
Usage: ./scripts/build_full_db_world_isolated_game.sh [options]

Create or reuse an isolated PM99 run root, compile a canonical full-DB world-state
plan against that game copy, apply the released editor surfaces, and append the
result to the isolated run manifest.

Options:
  --world-state <path>   Canonical world-state JSON input (required)
  --selector-map <path>  Optional club selector map JSON
  --worker-id <id>       Worker label for a newly created run
  --run-id <id>          Run identifier for a newly created run
  --run-root <path>      Reuse an existing isolated run root instead of creating one
  --allow-blocked        Apply even when compile blockers exist
  --skip-player-roundtrip-safety
                         Opt into full-roster player writes that rely on
                         post-write validation instead of per-record prechecks
  --json                 Print a JSON summary at the end
  -h, --help             Show this help
EOF
}

abs_path() {
  python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY
}

append_mutation() {
  local manifest_path="$1"
  local game_root="$2"
  local step_name="$3"
  local summary_path="$4"

  PYTHONPATH="${ROOT_DIR}/scripts${PYTHONPATH:+:${PYTHONPATH}}" \
    python3 - "${manifest_path}" "${game_root}" "${step_name}" "${summary_path}" <<'PY'
from __future__ import annotations
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from assert_pm99_isolated_input import core_file_hashes
manifest_path = Path(sys.argv[1]).resolve()
game_root = Path(sys.argv[2]).resolve()
step_name = sys.argv[3]
summary_path = Path(sys.argv[4]).resolve()
payload = json.loads(manifest_path.read_text(encoding='utf-8'))
mutations = list(payload.get('mutations') or [])
mutations.append({
    'step': step_name,
    'timestamp_utc': datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'summary_path': str(summary_path),
    'core_files': core_file_hashes(game_root),
})
payload['mutations'] = mutations
manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')
PY
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --world-state) WORLD_STATE="$2"; shift 2 ;;
    --selector-map) SELECTOR_MAP="$2"; shift 2 ;;
    --worker-id) WORKER_ID="$2"; shift 2 ;;
    --run-id) RUN_ID="$2"; shift 2 ;;
    --run-root) RUN_ROOT="$2"; shift 2 ;;
    --allow-blocked) ALLOW_BLOCKED=1; shift ;;
    --skip-player-roundtrip-safety) SKIP_PLAYER_ROUNDTRIP_SAFETY=1; shift ;;
    --json) PRINT_JSON=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "${WORLD_STATE}" ]]; then
  echo "--world-state is required" >&2
  usage >&2
  exit 2
fi
WORLD_STATE="$(abs_path "${WORLD_STATE}")"
COMPILE_SELECTOR_ARGS=()
if [[ -n "${SELECTOR_MAP}" ]]; then
  SELECTOR_MAP="$(abs_path "${SELECTOR_MAP}")"
  COMPILE_SELECTOR_ARGS=(--selector-map "${SELECTOR_MAP}")
fi

if [[ -z "${RUN_ROOT}" ]]; then
  create_payload="$(${ROOT_DIR}/scripts/create_pm99_isolated_run.sh --worker-id "${WORKER_ID}" --run-id "${RUN_ID}" --json)"
  RUN_ROOT="$(python3 - "${create_payload}" <<'PY'
import json, sys
print(json.loads(sys.argv[1])['run_root'])
PY
)"
else
  RUN_ROOT="$(abs_path "${RUN_ROOT}")"
fi

GAME_ROOT="${RUN_ROOT}/game"
RUN_MANIFEST="${RUN_ROOT}/run_manifest.json"
if [[ ! -f "${RUN_MANIFEST}" ]]; then
  echo "Missing run manifest: ${RUN_MANIFEST}" >&2
  exit 2
fi
python3 "${ROOT_DIR}/scripts/assert_pm99_isolated_input.py" --game-root "${GAME_ROOT}" --require-writable >/dev/null

OUTPUT_DIR="${RUN_ROOT}/patches/full_db_world"
mkdir -p "${OUTPUT_DIR}"

set +e
python3 "${ROOT_DIR}/scripts/pm99_world_state.py" world-compile-plan \
  "${WORLD_STATE}" \
  --game-root "${GAME_ROOT}" \
  --output-dir "${OUTPUT_DIR}/compile" \
  "${COMPILE_SELECTOR_ARGS[@]}" \
  --json > "${OUTPUT_DIR}/compile_result.json"
COMPILE_STATUS=$?
set -e
append_mutation "${RUN_MANIFEST}" "${GAME_ROOT}" "compile_full_db_world_plan" "${OUTPUT_DIR}/compile_result.json"

PLAN_PATH="${OUTPUT_DIR}/compile/world_plan.json"
if [[ ! -f "${PLAN_PATH}" ]]; then
  echo "Missing compiled world plan: ${PLAN_PATH}" >&2
  exit 1
fi

APPLY_ARGS=(python3 "${ROOT_DIR}/scripts/pm99_world_state.py" world-apply-plan "${PLAN_PATH}" --game-root "${GAME_ROOT}" --output-dir "${OUTPUT_DIR}/apply" --json)
if [[ ${ALLOW_BLOCKED} -eq 1 ]]; then
  APPLY_ARGS+=(--allow-blocked)
fi
if [[ ${SKIP_PLAYER_ROUNDTRIP_SAFETY} -eq 1 ]]; then
  APPLY_ARGS+=(--skip-player-roundtrip-safety)
fi
set +e
"${APPLY_ARGS[@]}" > "${OUTPUT_DIR}/apply_result_stdout.json"
APPLY_STATUS=$?
set -e

SUMMARY_PATH="${OUTPUT_DIR}/apply/apply_result.json"
if [[ ! -f "${SUMMARY_PATH}" ]]; then
  SUMMARY_PATH="${OUTPUT_DIR}/apply_result_stdout.json"
fi
append_mutation "${RUN_MANIFEST}" "${GAME_ROOT}" "apply_full_db_world_plan" "${SUMMARY_PATH}"

python3 "${ROOT_DIR}/scripts/pm99_world_state.py" world-render-report \
  "${PLAN_PATH}" \
  --output-html "${OUTPUT_DIR}/world_plan.html" >/dev/null

BUILD_MANIFEST="${RUN_ROOT}/patches/full_db_world_build_manifest.json"
python3 - "${BUILD_MANIFEST}" "${RUN_ROOT}" "${GAME_ROOT}" "${RUN_MANIFEST}" "${WORLD_STATE}" "${SELECTOR_MAP}" "${OUTPUT_DIR}" "${COMPILE_STATUS}" "${APPLY_STATUS}" "${SKIP_PLAYER_ROUNDTRIP_SAFETY}" <<'PY'
from __future__ import annotations
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
build_manifest = Path(sys.argv[1]).resolve()
run_root = Path(sys.argv[2]).resolve()
game_root = Path(sys.argv[3]).resolve()
run_manifest = Path(sys.argv[4]).resolve()
world_state = Path(sys.argv[5]).resolve()
selector_map = sys.argv[6]
output_dir = Path(sys.argv[7]).resolve()
compile_status = int(sys.argv[8])
apply_status = int(sys.argv[9])
skip_player_roundtrip_safety = sys.argv[10] == "1"
payload = {
    'scope': 'full_db_world_isolated_build',
    'timestamp_utc': datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'run_root': str(run_root),
    'game_root': str(game_root),
    'run_manifest_path': str(run_manifest),
    'world_state_path': str(world_state),
    'selector_map_path': str(Path(selector_map).resolve()) if selector_map else None,
    'compile_status': compile_status,
    'apply_status': apply_status,
    'skip_player_roundtrip_safety': skip_player_roundtrip_safety,
    'output_dir': str(output_dir),
    'steps': {
        'compile_result': str(output_dir / 'compile_result.json'),
        'world_plan': str(output_dir / 'compile' / 'world_plan.json'),
        'apply_result': str(output_dir / 'apply' / 'apply_result.json'),
        'report_html': str(output_dir / 'world_plan.html'),
    },
}
build_manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')
print(json.dumps(payload, indent=2, sort_keys=True))
PY

if [[ ${PRINT_JSON} -eq 1 ]]; then
  python3 - "${RUN_ROOT}" "${GAME_ROOT}" "${RUN_MANIFEST}" "${BUILD_MANIFEST}" "${COMPILE_STATUS}" "${APPLY_STATUS}" <<'PY'
from __future__ import annotations
import json
from pathlib import Path
import sys
print(json.dumps({
    'success': int(sys.argv[5]) == 0 and int(sys.argv[6]) == 0,
    'run_root': str(Path(sys.argv[1]).resolve()),
    'game_root': str(Path(sys.argv[2]).resolve()),
    'run_manifest_path': str(Path(sys.argv[3]).resolve()),
    'build_manifest_path': str(Path(sys.argv[4]).resolve()),
    'compile_status': int(sys.argv[5]),
    'apply_status': int(sys.argv[6]),
}, indent=2, sort_keys=True))
PY
else
  echo "Built full-DB world isolated game:"
  echo "  run_root: ${RUN_ROOT}"
  echo "  game_root: ${GAME_ROOT}"
  echo "  output_dir: ${OUTPUT_DIR}"
  echo "  compile_status: ${COMPILE_STATUS}"
  echo "  apply_status: ${APPLY_STATUS}"
fi

if [[ ${COMPILE_STATUS} -ne 0 ]]; then
  exit ${COMPILE_STATUS}
fi
exit ${APPLY_STATUS}
